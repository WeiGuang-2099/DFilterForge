"""Shortcut policy: filters that match the probes without stating the intent.

A filter can select exactly the labelled frames of every probe and still say
nothing about the request: it can count frames, read the capture clock, name
a stream index or copy a constant the capture generator happened to use.
Such an answer would select the wrong packets in any other capture, so the
protocol scores it as ``shortcut`` and never as strong exact.

The rules, pre-registered in ``docs/protocol.md``:

- capture-position: a field the frozen catalog types as a frame number or a
  time, any ``frame.`` field other than frame.len, frame.cap_len and
  frame.protocols, any ``_ws.`` field, and any conversation index (a name
  component ``stream``).
- generator-identifier: the IPv4 identification, the DNS transaction ID,
  checksums and raw sequence numbers, which the generator derives from seeds
  and frame positions.
- capture-constant: a literal the request does not state that only the
  generator could have supplied: a single host address, a network touching
  the server pool 198.51.100.0/24, a number at or above the ephemeral port
  base, a MAC address or a generated DNS name.

Detection is static. Field names and literals come from the typed IR, or,
for a display filter, from a lexical scan that sets quoted strings aside. The
scan implements no filter semantics; tshark alone decides what a filter
means, and a name the catalog does not register can only match by name.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
import ipaddress
import re

from pydantic import Field

from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import walk_predicates


class ShortcutRule(StrEnum):
    """The rule a shortcut breaks."""

    CAPTURE_POSITION = "capture-position"
    GENERATOR_IDENTIFIER = "generator-identifier"
    CAPTURE_CONSTANT = "capture-constant"


# tshark types whose values count frames or time rather than describe a
# packet: dns.response_in, tcp.time_delta, frame.time_epoch and so on.
POSITION_TYPES = frozenset(
    {"FT_FRAMENUM", "FT_ABSOLUTE_TIME", "FT_RELATIVE_TIME"}
)
# The frame fields that describe the packet itself.
_PACKET_FRAME_FIELDS = frozenset(
    {"frame.len", "frame.cap_len", "frame.protocols"}
)
_GENERATOR_FIELDS = frozenset({"ip.id", "dns.id", "tcp.seq_raw", "tcp.ack_raw"})
# The generator's server hosts, 198.51.100.<ordinal>.
SERVER_POOL = ipaddress.IPv4Network("198.51.100.0/24")
# fixtures and witnesses number ephemeral ports from 41000 + seed + ordinal.
EPHEMERAL_BASE = 41000
# Question names the generator writes: probe-<seed>-<ordinal>.example and
# witness-<seed>-<ordinal>.example.
_GENERATED_NAME = re.compile(r"(?:probe|witness)-\d+-\d+")
_MAX_TOKEN_CHARS = 64

_STRING = re.compile(r"""r?"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'""", re.DOTALL)
_WORD = re.compile(r"[A-Za-z0-9_.:/-]+")
_IPV4 = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?")
_MAC = re.compile(r"[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(?:\1[0-9A-Fa-f]{2}){4}")
_INTEGER = re.compile(r"0[xX][0-9A-Fa-f]+|\d+")
_FIELD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
_LETTER = re.compile(r"[A-Za-z_]")
_KEYWORDS = frozenset(
    {
        "all",
        "and",
        "any",
        "contains",
        "eq",
        "false",
        "ge",
        "gt",
        "in",
        "le",
        "lt",
        "matches",
        "ne",
        "not",
        "or",
        "true",
        "xor",
    }
)


class ShortcutHitV1(FrozenModel):
    """One rule a candidate breaks, with the name or literal that breaks it."""

    rule: ShortcutRule
    token: str = Field(min_length=1, max_length=_MAX_TOKEN_CHARS)


@dataclass(frozen=True, slots=True)
class FilterReferences:
    """The field names and literals one candidate filter mentions.

    Attributes:
        fields: Field names, in first-mention order.
        addresses: IPv4 literals as written, with their parsed network.
        numbers: Integer literals as written, with their value.
        macs: MAC address literals as written.
        strings: Quoted or typed string literals.
        disjunctions: Binary OR operations; a typed any of n children counts
            n - 1, so both contracts count the same thing.
    """

    fields: tuple[str, ...]
    addresses: tuple[tuple[str, ipaddress.IPv4Network], ...]
    numbers: tuple[tuple[str, int], ...]
    macs: tuple[str, ...]
    strings: tuple[str, ...]
    disjunctions: int


@dataclass
class _Collected:
    fields: list[str]
    addresses: list[tuple[str, ipaddress.IPv4Network]]
    numbers: list[tuple[str, int]]
    macs: list[str]
    strings: list[str]

    def add_literal(self, text: str) -> bool:
        """Records ``text`` as an address, MAC or integer if it is one."""
        if _IPV4.fullmatch(text):
            try:
                network = ipaddress.IPv4Network(text, strict=False)
            except ValueError:
                return False
            self.addresses.append((text, network))
            return True
        if _MAC.fullmatch(text):
            self.macs.append(text)
            return True
        if _INTEGER.fullmatch(text):
            self.numbers.append((text, int(text, 0)))
            return True
        return False

    def references(self, disjunctions: int) -> FilterReferences:
        """Freezes what was collected, each field name once."""
        return FilterReferences(
            tuple(dict.fromkeys(self.fields)),
            tuple(self.addresses),
            tuple(self.numbers),
            tuple(self.macs),
            tuple(self.strings),
            disjunctions,
        )


def _scan_words(text: str, collected: _Collected) -> None:
    for word in _WORD.findall(text):
        # A set range such as 41000..41100 holds two literals.
        for part in word.split(".."):
            if not part or collected.add_literal(part):
                continue
            if (
                _FIELD.fullmatch(part)
                and _LETTER.search(part)
                and part.lower() not in _KEYWORDS
            ):
                collected.fields.append(part)


def _filter_references(text: str) -> FilterReferences:
    collected = _Collected([], [], [], [], [])
    outside: list[str] = []
    position = 0
    for match in _STRING.finditer(text):
        outside.append(text[position : match.start()])
        literal = match.group()
        collected.strings.append(literal[2 if literal[0] == "r" else 1 : -1])
        position = match.end()
    outside.append(text[position:])
    bare = " ".join(outside)
    _scan_words(bare, collected)
    disjunctions = bare.count("||") + sum(
        word.lower() == "or" for word in _WORD.findall(bare)
    )
    return collected.references(disjunctions)


def _any_nodes(expression: Expression) -> Iterator[AnyOf]:
    if isinstance(expression, Predicate):
        return
    if isinstance(expression, Not):
        yield from _any_nodes(expression.child)
        return
    if isinstance(expression, AnyOf):
        yield expression
    for child in expression.children:
        yield from _any_nodes(child)


def _typed_references(intent: IntentIrV1) -> FilterReferences:
    collected = _Collected([], [], [], [], [])
    for _, predicate in walk_predicates(intent.expression):
        collected.fields.append(predicate.field)
        values = (
            predicate.value
            if isinstance(predicate.value, tuple)
            else (predicate.value,)
        )
        for value in values:
            if isinstance(value, bool) or value is None:
                continue
            if isinstance(value, int):
                collected.numbers.append((str(value), value))
            elif isinstance(value, str) and not collected.add_literal(value):
                collected.strings.append(value)
    disjunctions = sum(
        len(node.children) - 1 for node in _any_nodes(intent.expression)
    )
    return collected.references(disjunctions)


def references(candidate: IntentIrV1 | str) -> FilterReferences:
    """Returns the field names and literals a candidate mentions.

    Args:
        candidate: A typed IR, or a display filter exactly as the model
            wrote it.

    Returns:
        The references, in the order the candidate mentions them.
    """
    if isinstance(candidate, str):
        return _filter_references(candidate)
    return _typed_references(candidate)


def _hit(rule: ShortcutRule, token: str) -> ShortcutHitV1:
    return ShortcutHitV1(rule=rule, token=token[:_MAX_TOKEN_CHARS])


def _position_field(name: str, tshark_type: str | None) -> bool:
    if tshark_type in POSITION_TYPES or name.startswith("_ws."):
        return True
    if name.startswith("frame.") and name not in _PACKET_FRAME_FIELDS:
        return True
    return "stream" in name.split(".")


def _generator_field(name: str) -> bool:
    return name in _GENERATOR_FIELDS or any(
        part.startswith("checksum") for part in name.split(".")
    )


def _constant_hits(
    found: FilterReferences, request: str
) -> Iterator[ShortcutHitV1]:
    stated = request.lower()

    def unstated(token: str) -> bool:
        return token.lower() not in stated

    for text, network in found.addresses:
        address = str(network.network_address)
        if not (unstated(text) and unstated(address)):
            continue
        if network.prefixlen == 32 or (
            network.prefixlen >= 8
            and network.overlaps(SERVER_POOL)
            and unstated("TEST-NET-2")
        ):
            yield _hit(ShortcutRule.CAPTURE_CONSTANT, text)
    for text, value in found.numbers:
        if value >= EPHEMERAL_BASE and unstated(str(value)) and unstated(text):
            yield _hit(ShortcutRule.CAPTURE_CONSTANT, text)
    for text in found.macs:
        if unstated(text):
            yield _hit(ShortcutRule.CAPTURE_CONSTANT, text)
    for text in found.strings:
        for name in _GENERATED_NAME.findall(text):
            if unstated(name):
                yield _hit(ShortcutRule.CAPTURE_CONSTANT, name)


def find_shortcuts(
    found: FilterReferences,
    request: str,
    tshark_types: Mapping[str, str],
) -> tuple[ShortcutHitV1, ...]:
    """Returns every shortcut rule a candidate breaks, each token once.

    Args:
        found: What the candidate mentions, from :func:`references`.
        request: The request text the model saw; a literal it states is
            never a capture constant.
        tshark_types: The frozen catalog's raw tshark type for each field
            name it registers.

    Returns:
        The hits in rule order, then in mention order.
    """
    hits: list[ShortcutHitV1] = []
    for name in found.fields:
        if _position_field(name, tshark_types.get(name)):
            hits.append(_hit(ShortcutRule.CAPTURE_POSITION, name))
        elif _generator_field(name):
            hits.append(_hit(ShortcutRule.GENERATOR_IDENTIFIER, name))
    hits.extend(_constant_hits(found, request))
    order = list(ShortcutRule)
    unique = dict.fromkeys(hits)
    return tuple(sorted(unique, key=lambda hit: order.index(hit.rule)))
