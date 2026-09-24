"""Single-site mutants of a typed intent, for probe adequacy checks.

A mutant changes exactly one site of a canonical expression: one predicate's
field, operator or value, or one logical node. Each operator family encodes
a near miss that a probe set must tell apart from the gold, so a mutant that
matches the gold's labels on every probe exposes a gap in the probes rather
than a fault in the gold. Generation is pure and deterministic; callers
compile and execute the mutants.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
import ipaddress
import itertools
from types import MappingProxyType
from typing import Literal, TypeAlias

from pydantic import Field
from pydantic import ValidationError

from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue


class MutantCategory(StrEnum):
    """The operator family that produced a mutant."""

    FIELD_SWAP = "field-swap"
    PROTOCOL_AS_PORT = "protocol-as-port"
    FLAG_AS_NUMBER = "flag-as-number"
    FLAG_AS_BYTE = "flag-as-byte"
    VALUE_DOMAIN = "value-domain"
    BOUNDARY = "boundary"
    SUBNET = "subnet"
    DROP_CONJUNCT = "drop-conjunct"
    DROP_DISJUNCT = "drop-disjunct"
    DROP_NOT = "drop-not"


_Value: TypeAlias = ScalarValue | tuple[ScalarValue, ...] | None
# (category, change label, field, operator, value) before IR validation.
_Candidate: TypeAlias = tuple[MutantCategory, str, str, Operator, _Value]
# (path of the edited node, category, change label, mutated subtree).
_Edit: TypeAlias = tuple[tuple[int, ...], MutantCategory, str, Expression]

# Direction and scope slips: a one-sided port or address written for either
# side or the other side, and the two ECN flags exchanged for each other.
FIELD_SWAPS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "tcp.dstport": ("tcp.port", "tcp.srcport"),
        "tcp.srcport": ("tcp.port", "tcp.dstport"),
        "udp.dstport": ("udp.port", "udp.srcport"),
        "udp.srcport": ("udp.port", "udp.dstport"),
        "ip.src": ("ip.addr", "ip.dst"),
        "ip.dst": ("ip.addr", "ip.src"),
        "tcp.flags.ece": ("tcp.flags.cwr",),
        "tcp.flags.cwr": ("tcp.flags.ece",),
    }
)

# A protocol test written as the port the protocol usually runs on, on either
# side. tshark decodes by dissector: DNS can run off port 53, where its UDP
# heuristic still finds it, and a port can carry another payload.
PROTOCOL_AS_PORT: Mapping[str, tuple[tuple[str, int], ...]] = MappingProxyType(
    {
        "dns": (("udp.port", 53), ("tcp.port", 53)),
        "mdns": (("udp.port", 5353),),
        "http": (("tcp.port", 80),),
    }
)

# A TCP flag written as the number field with a similar name. Relative
# numbering shows ack 1 on the first ACK of a stream and seq 0 on its SYN,
# so these agree with the flag on ordinary traffic.
FLAG_AS_NUMBER: Mapping[tuple[str, bool], tuple[str, Operator, int]] = (
    MappingProxyType(
        {
            ("tcp.flags.ack", True): ("tcp.ack", Operator.EQ, 1),
            ("tcp.flags.ack", False): ("tcp.ack", Operator.EQ, 0),
            ("tcp.flags.syn", True): ("tcp.seq", Operator.EQ, 0),
            ("tcp.flags.syn", False): ("tcp.seq", Operator.NE, 0),
        }
    )
)

# A set TCP flag written as the whole flag field equal to that bit alone,
# as the pilot suite's tcp.flags == 2 mutations read SYN. It misses every
# segment that carries another flag as well, such as FIN with ACK.
FLAG_AS_BYTE: Mapping[str, int] = MappingProxyType(
    {
        "tcp.flags.fin": 0x01,
        "tcp.flags.syn": 0x02,
        "tcp.flags.reset": 0x04,
        "tcp.flags.push": 0x08,
        "tcp.flags.ack": 0x10,
        "tcp.flags.urg": 0x20,
        "tcp.flags.ece": 0x40,
        "tcp.flags.cwr": 0x80,
    }
)

# One DNS code rewritten as "not the other common code" or as a range: A (1)
# against AAAA (28) question types, NOERROR (0) against NXDOMAIN (3) response
# codes. Applies to equality predicates only.
VALUE_DOMAIN: Mapping[tuple[str, int], tuple[tuple[Operator, int], ...]] = (
    MappingProxyType(
        {
            ("dns.qry.type", 1): ((Operator.NE, 28),),
            ("dns.qry.type", 28): ((Operator.NE, 1),),
            ("dns.flags.rcode", 0): ((Operator.NE, 3), (Operator.LT, 3)),
            ("dns.flags.rcode", 3): ((Operator.NE, 0), (Operator.GT, 0)),
        }
    )
)

# Off-by-one and strictness slips on an integer comparison: the strict or
# inclusive twin, equality with the bound, and the bound moved by one. Each
# edit is (new operator, offset added to the original value).
BOUNDARY_EDITS: Mapping[Operator, tuple[tuple[Operator, int], ...]] = (
    MappingProxyType(
        {
            Operator.LE: (
                (Operator.LT, 0),
                (Operator.EQ, 0),
                (Operator.LE, 1),
                (Operator.LE, -1),
            ),
            Operator.GE: (
                (Operator.GT, 0),
                (Operator.EQ, 0),
                (Operator.GE, 1),
                (Operator.GE, -1),
            ),
            Operator.GT: (
                (Operator.GE, 0),
                (Operator.GT, 1),
                (Operator.GT, -1),
            ),
            Operator.LT: (
                (Operator.LE, 0),
                (Operator.LT, 1),
                (Operator.LT, -1),
            ),
            Operator.NE: ((Operator.LT, 0), (Operator.GT, 0)),
        }
    )
)

# Network size slips, as (prefix length change, largest original prefix
# length it applies to, index of the chosen block). A widening needs an
# original prefix at least that long. The eight-bit narrowing takes the
# second block (10.0.0.0/8 becomes 10.1.0.0/16), so it does not start at the
# original network address as the one-bit narrowing does.
SUBNET_EDITS: tuple[tuple[int, int, int], ...] = (
    (-8, 128, 0),
    (1, 24, 0),
    (8, 16, 1),
)


@dataclass(frozen=True, slots=True)
class Mutant:
    """One single-site edit of a canonical intent.

    Attributes:
        category: The operator family that produced the edit.
        edit: Stable label, unique within one source expression. It starts
            with the edited node's path (``root`` or dotted child indexes,
            as in ``intent_ir.walk_predicates``) followed by the change.
        intent: The mutated intent, validated as IR.
    """

    category: MutantCategory
    edit: str
    intent: IntentIrV1


WaiverKind: TypeAlias = Literal["equivalent", "not_separable"]


class MutantWaiver(FrozenModel):
    """A reasoned exception for one surviving mutant of one gold case.

    ``equivalent`` means the mutant selects the same packets as the gold
    under the specification's assumptions. ``not_separable`` means no clean
    packet in the pinned tshark tells the two apart.

    An edit label names a node path, not the predicate at it, so a reordered
    gold expression can give the label to another mutant. The compiled
    filter the reason was written for pins the waiver to its mutant: a
    label whose filter changed no longer matches, and the waiver goes stale.
    """

    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    edit: str = Field(min_length=1)
    display_filter: str = Field(min_length=1)
    kind: WaiverKind
    reason: str = Field(min_length=1)


def _subnet_alternatives(value: str) -> Iterator[str]:
    network = ipaddress.ip_network(value, strict=False)
    for change, largest, index in SUBNET_EDITS:
        prefix = network.prefixlen + change
        if network.prefixlen > largest or prefix < 0:
            continue
        if change < 0:
            yield str(network.supernet(new_prefix=prefix))
        else:
            blocks = network.subnets(new_prefix=prefix)
            yield from map(str, itertools.islice(blocks, index, index + 1))


def _integer_candidates(
    field: str, operator: Operator, value: int
) -> Iterator[_Candidate]:
    if operator == Operator.EQ:
        for new_operator, new_value in VALUE_DOMAIN.get((field, value), ()):
            yield (
                MutantCategory.VALUE_DOMAIN,
                f"{field} eq {value} -> {new_operator.value} {new_value}",
                field,
                new_operator,
                new_value,
            )
    for new_operator, offset in BOUNDARY_EDITS.get(operator, ()):
        yield (
            MutantCategory.BOUNDARY,
            f"{field} {operator.value} {value} -> "
            f"{new_operator.value} {value + offset}",
            field,
            new_operator,
            value + offset,
        )


def _predicate_candidates(predicate: Predicate) -> Iterator[_Candidate]:
    """Yields unvalidated single-site predicate edits in a fixed order."""
    field, operator, value = (
        predicate.field,
        predicate.operator,
        predicate.value,
    )
    for other in FIELD_SWAPS.get(field, ()):
        yield (
            MutantCategory.FIELD_SWAP,
            f"{field} -> {other}",
            other,
            operator,
            value,
        )
    if operator == Operator.EXISTS:
        for port_field, port in PROTOCOL_AS_PORT.get(field, ()):
            yield (
                MutantCategory.PROTOCOL_AS_PORT,
                f"{field} -> {port_field} eq {port}",
                port_field,
                Operator.EQ,
                port,
            )
    if operator == Operator.EQ and isinstance(value, bool):
        number = FLAG_AS_NUMBER.get((field, value))
        if number is not None:
            other, new_operator, new_value = number
            yield (
                MutantCategory.FLAG_AS_NUMBER,
                f"{field} eq {str(value).lower()} -> "
                f"{other} {new_operator.value} {new_value}",
                other,
                new_operator,
                new_value,
            )
        bit = FLAG_AS_BYTE.get(field)
        if value and bit is not None:
            yield (
                MutantCategory.FLAG_AS_BYTE,
                f"{field} eq true -> tcp.flags eq {bit}",
                "tcp.flags",
                Operator.EQ,
                bit,
            )
    if isinstance(value, int) and not isinstance(value, bool):
        yield from _integer_candidates(field, operator, value)
    if operator == Operator.IN_SUBNET and isinstance(value, str):
        for alternative in _subnet_alternatives(value):
            yield (
                MutantCategory.SUBNET,
                f"{field} {value} -> {alternative}",
                field,
                operator,
                alternative,
            )


def _predicate_edits(
    predicate: Predicate, path: tuple[int, ...]
) -> Iterator[_Edit]:
    """Yields the predicate edits that still validate as IR."""
    for category, change, field, operator, value in _predicate_candidates(
        predicate
    ):
        try:
            mutated = Predicate(field=field, operator=operator, value=value)
        except ValidationError:
            continue
        yield path, category, change, mutated


def _group(node: All | AnyOf, children: tuple[Expression, ...]) -> Expression:
    if isinstance(node, All):
        return All(children=children)
    return AnyOf(children=children)


def _edits(node: Expression, path: tuple[int, ...]) -> Iterator[_Edit]:
    """Yields every single-site edit of ``node`` in a fixed preorder."""
    if isinstance(node, Predicate):
        yield from _predicate_edits(node, path)
        return
    if isinstance(node, Not):
        yield path, MutantCategory.DROP_NOT, "drop not", node.child
        for inner, category, change, child in _edits(node.child, path + (0,)):
            yield inner, category, change, Not(child=child)
        return
    drop = (
        MutantCategory.DROP_CONJUNCT
        if isinstance(node, All)
        else MutantCategory.DROP_DISJUNCT
    )
    children = node.children
    for index, child in enumerate(children):
        rest = children[:index] + children[index + 1 :]
        remaining = rest[0] if len(rest) == 1 else _group(node, rest)
        yield path, drop, f"drop child {index}", remaining
        for inner, category, change, mutated in _edits(child, path + (index,)):
            replaced = children[:index] + (mutated,) + children[index + 1 :]
            yield inner, category, change, _group(node, replaced)


def single_site_mutants(intent: IntentIrV1) -> tuple[Mutant, ...]:
    """Returns every single-site mutant of an intent in a stable order.

    Children come in index order, and each group's drop edit for a child
    precedes the edits inside that child. A predicate yields field swap,
    protocol as port, flag as number, flag as byte, value domain, boundary
    and subnet edits, in that order.
    An edit that does not validate as IR is skipped. Distinct mutants can
    compile to the same filter text; deduplication is the caller's choice.

    Args:
        intent: The canonical intent to mutate.

    Returns:
        The mutants, each differing from ``intent`` at exactly one site.
    """
    return tuple(
        Mutant(
            category,
            f"{'.'.join(map(str, path)) or 'root'}: {change}",
            IntentIrV1(expression=expression),
        )
        for path, category, change, expression in _edits(intent.expression, ())
    )
