"""Reviewed packet semantics and reproducible synthetic benchmark captures.

Labels name packet recipes explicitly; they never interpret display filters or
compiled IR. This curated pilot suite is not a training or held-out test split.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct

from dfilterforge import fixtures
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue

RECIPES = (
    "syn",
    "syn-ack",
    "ack",
    "ecn-syn",
    "reset",
    "fin",
    "tcp-query",
    "udp-query",
    "udp-response",
    "udp-other",
    "udp-both-53",
    "tcp-http",
    "udp-mdns",
    "udp-aaaa",
    "udp-nxdomain",
    "udp-lowttl",
    "tcp-lowttl",
    "udp-private",
    "udp-private-destination",
    "tcp-reverse",
)
_TCP = frozenset(
    (
        "syn",
        "syn-ack",
        "ack",
        "ecn-syn",
        "reset",
        "fin",
        "tcp-query",
        "tcp-http",
        "tcp-lowttl",
        "tcp-reverse",
    )
)
_UDP = frozenset(RECIPES) - _TCP
_DNS = frozenset(
    (
        "tcp-query",
        "udp-query",
        "udp-response",
        "udp-both-53",
        "udp-aaaa",
        "udp-nxdomain",
    )
)
_QUERY = (_DNS | {"udp-mdns"}) - {"udp-response", "udp-nxdomain"}
_SYN = frozenset(("syn", "syn-ack", "ecn-syn", "tcp-http"))
_ACK = frozenset(
    (
        "syn-ack",
        "ack",
        "reset",
        "tcp-query",
        "tcp-lowttl",
        "tcp-reverse",
    )
)
_PROVENANCE = (
    "Synthetic packet recipes and recipe memberships authored directly in "
    "src/dfilterforge/benchmark.py; independently reviewed by Codex agent "
    "semantic_independent_review on 2026-09-09. Wireshark 4.6.8 Docker "
    "execution verified 36 cases across three probes: reference 108/108, "
    "typed candidate 108/108, and mutation kills 36/36. The scope is limited "
    "to recorded synthetic probes; it is not a held-out split or global "
    "semantic proof."
)
_REVIEW_STATUS = "reviewed"


@dataclass(frozen=True)
class SemanticCase:
    """An independently labeled intent and an authored near-wrong filter."""

    task_id: str
    intent: str
    expression: Expression
    reference_filter: str
    mutation_filter: str
    matching_recipes: frozenset[str]

    @property
    def canonical_ir(self) -> IntentIrV1:
        """Returns the compiler input for this semantic case."""
        return IntentIrV1(expression=self.expression)


@dataclass(frozen=True)
class BenchmarkProbe:
    """One capture and its packet recipe ordering."""

    probe_id: str
    capture_path: Path
    recipes: tuple[str, ...]

    def labels(self, case: SemanticCase) -> tuple[int, ...]:
        """Maps authored recipe memberships to packet numbers."""
        return tuple(
            index
            for index, recipe in enumerate(self.recipes, 1)
            if recipe in case.matching_recipes
        )


def _p(
    field: str,
    operator: Operator = Operator.EXISTS,
    value: ScalarValue | tuple[ScalarValue, ...] | None = None,
) -> Predicate:
    return Predicate(field=field, operator=operator, value=value)


def semantic_cases() -> tuple[SemanticCase, ...]:
    """Returns 36 reviewed specifications covering distinct semantic traps."""
    eq = Operator.EQ
    tcp = _p("tcp")
    udp = _p("udp")
    syn = _p("tcp.flags.syn", eq, True)
    ack = _p("tcp.flags.ack", eq, True)
    query = _p("dns.flags.response", eq, False)
    rows: tuple[tuple[str, str, Expression, str, str, frozenset[str]], ...] = (
        (
            "tcp-presence",
            "TCP packets, including DNS over TCP.",
            tcp,
            "tcp",
            "tcp && !dns",
            _TCP,
        ),
        (
            "udp-presence",
            "UDP packets, including non-DNS traffic.",
            udp,
            "udp",
            "udp && dns",
            _UDP,
        ),
        (
            "dns-presence",
            "Unicast DNS over either TCP or UDP; mDNS is a separate protocol.",
            _p("dns"),
            "dns",
            "udp && dns",
            _DNS,
        ),
        (
            "tcp-absence",
            "Packets without a TCP layer.",
            Not(child=tcp),
            "!tcp",
            "dns",
            _UDP,
        ),
        (
            "syn-bit",
            "TCP SYN bit set, even with ACK or ECN.",
            syn,
            "tcp.flags.syn == 1",
            "tcp.flags == 2",
            _SYN,
        ),
        (
            "ack-bit",
            "TCP ACK bit set, including resets.",
            ack,
            "tcp.flags.ack == 1",
            "tcp.flags == 16",
            _ACK,
        ),
        (
            "syn-no-ack",
            "SYN set and ACK clear, including ECN SYN.",
            All(children=(syn, _p("tcp.flags.ack", eq, False))),
            "tcp.flags.syn == 1 && tcp.flags.ack == 0",
            "tcp.flags.syn == 1",
            _SYN - {"syn-ack"},
        ),
        (
            "syn-and-ack",
            "SYN and ACK both set.",
            All(children=(syn, ack)),
            "tcp.flags.syn == 1 && tcp.flags.ack == 1",
            "tcp.flags.syn == 1 || tcp.flags.ack == 1",
            frozenset(("syn-ack",)),
        ),
        (
            "syn-or-fin",
            "Either SYN or FIN set.",
            AnyOf(children=(syn, _p("tcp.flags.fin", eq, True))),
            "tcp.flags.syn == 1 || tcp.flags.fin == 1",
            "tcp.flags.syn == 1 && tcp.flags.fin == 1",
            _SYN | {"fin"},
        ),
        (
            "tcp-no-syn",
            "TCP packets with SYN clear; UDP is excluded.",
            _p("tcp.flags.syn", eq, False),
            "tcp.flags.syn == 0",
            "!(tcp.flags.syn == 1)",
            _TCP - _SYN,
        ),
        (
            "reset-bit",
            "TCP resets, including ACK resets.",
            _p("tcp.flags.reset", eq, True),
            "tcp.flags.reset == 1",
            "tcp.flags == 4",
            frozenset(("reset",)),
        ),
        (
            "fin-bit",
            "TCP connection-close FIN packets.",
            _p("tcp.flags.fin", eq, True),
            "tcp.flags.fin == 1",
            "tcp.flags.reset == 1",
            frozenset(("fin",)),
        ),
        (
            "ecn-syn",
            "SYN with ECN echo enabled.",
            All(children=(syn, _p("tcp.flags.ece", eq, True))),
            "tcp.flags.syn == 1 && tcp.flags.ece == 1",
            "tcp.flags.syn == 1",
            frozenset(("ecn-syn",)),
        ),
        (
            "udp-dns-query",
            "DNS queries over UDP only.",
            All(children=(udp, query)),
            "udp && dns.flags.response == 0",
            "dns.flags.response == 0",
            _QUERY - {"tcp-query"},
        ),
        (
            "dns-query",
            "DNS queries over any transport.",
            query,
            "dns.flags.response == 0",
            "udp && dns.flags.response == 0",
            _QUERY,
        ),
        (
            "dns-response",
            "DNS responses including NXDOMAIN.",
            _p("dns.flags.response", eq, True),
            "dns.flags.response == 1",
            "dns.flags.response == 1 && dns.flags.rcode == 0",
            frozenset(("udp-response", "udp-nxdomain")),
        ),
        (
            "dns-tcp",
            "DNS transported over TCP.",
            All(children=(tcp, _p("dns"))),
            "tcp && dns",
            "udp && dns",
            frozenset(("tcp-query",)),
        ),
        (
            "udp-destination-dns",
            "UDP destination port 53, independent of source.",
            _p("udp.dstport", eq, 53),
            "udp.dstport == 53",
            "udp.port == 53",
            frozenset(("udp-query", "udp-both-53", "udp-aaaa")),
        ),
        (
            "udp-source-dns",
            "UDP source port 53, independent of destination.",
            _p("udp.srcport", eq, 53),
            "udp.srcport == 53",
            "udp.dstport == 53",
            frozenset(("udp-response", "udp-both-53", "udp-nxdomain")),
        ),
        (
            "udp-either-dns",
            "UDP port 53 on either endpoint.",
            _p("udp.port", eq, 53),
            "udp.port == 53",
            "udp.dstport == 53",
            _DNS - {"tcp-query", "udp-mdns"},
        ),
        (
            "udp-both-dns",
            "UDP port 53 on both endpoints.",
            All(
                children=(_p("udp.srcport", eq, 53), _p("udp.dstport", eq, 53))
            ),
            "udp.srcport == 53 && udp.dstport == 53",
            "udp.port == 53",
            frozenset(("udp-both-53",)),
        ),
        (
            "tcp-web-ports",
            "TCP destined for HTTP or HTTPS ports.",
            _p("tcp.dstport", Operator.IN, (80, 443)),
            "tcp.dstport in {80,443}",
            "tcp.dstport == 443",
            _TCP - {"tcp-query"},
        ),
        (
            "tcp-http",
            "TCP destination HTTP port, not DNS or HTTPS.",
            _p("tcp.dstport", eq, 80),
            "tcp.dstport == 80",
            "tcp.dstport in {80,443}",
            frozenset(("tcp-http",)),
        ),
        (
            "udp-high-port",
            "UDP destination ports above 5353, excluding the boundary.",
            _p("udp.dstport", Operator.GT, 5353),
            "udp.dstport > 5353",
            "udp.dstport >= 5353",
            frozenset(
                (
                    "udp-response",
                    "udp-nxdomain",
                    "udp-other",
                    "udp-lowttl",
                    "udp-private",
                    "udp-private-destination",
                )
            ),
        ),
        (
            "udp-low-port",
            "UDP destination ports below 5353, excluding mDNS.",
            _p("udp.dstport", Operator.LT, 5353),
            "udp.dstport < 5353",
            "udp.dstport <= 5353",
            frozenset(("udp-query", "udp-both-53", "udp-aaaa")),
        ),
        (
            "udp-not-dns",
            "UDP without the unicast DNS protocol; mDNS remains included.",
            All(children=(udp, Not(child=_p("dns")))),
            "udp && !dns",
            "!dns",
            _UDP - _DNS,
        ),
        (
            "dns-aaaa",
            "DNS questions for IPv6 addresses.",
            _p("dns.qry.type", eq, 28),
            "dns.qry.type == 28",
            "dns.qry.type == 1",
            frozenset(("udp-aaaa",)),
        ),
        (
            "dns-a",
            "DNS A questions, including mDNS and response question sections.",
            _p("dns.qry.type", eq, 1),
            "dns.qry.type == 1",
            "dns.qry.type == 1 && dns.flags.response == 0",
            (_DNS | {"udp-mdns"}) - {"udp-aaaa"},
        ),
        (
            "dns-nxdomain",
            "DNS name-error responses.",
            _p("dns.flags.rcode", eq, 3),
            "dns.flags.rcode == 3",
            "dns.flags.response == 1",
            frozenset(("udp-nxdomain",)),
        ),
        (
            "dns-name-substring",
            "DNS or mDNS questions containing the example label.",
            _p("dns.qry.name", Operator.CONTAINS, "example"),
            'dns.qry.name contains "example"',
            'dns.qry.name == "example"',
            _DNS | {"udp-mdns"},
        ),
        (
            "ttl-expiring",
            "IPv4 packets with TTL at most one.",
            _p("ip.ttl", Operator.LE, 1),
            "ip.ttl <= 1",
            "ip.ttl < 1",
            frozenset(("udp-lowttl", "tcp-lowttl")),
        ),
        (
            "ttl-normal",
            "IPv4 TTL at least 64, including the boundary.",
            _p("ip.ttl", Operator.GE, 64),
            "ip.ttl >= 64",
            "ip.ttl > 64",
            frozenset(RECIPES) - {"udp-lowttl", "tcp-lowttl"},
        ),
        (
            "source-private",
            "IPv4 source in private 10/8 space.",
            _p("ip.src", Operator.IN_SUBNET, "10.0.0.0/8"),
            "ip.src == 10.0.0.0/8",
            "ip.dst == 10.0.0.0/8",
            frozenset(("udp-private",)),
        ),
        (
            "source-testnet",
            "IPv4 source in TEST-NET-1, not either endpoint.",
            _p("ip.src", Operator.IN_SUBNET, "192.0.2.0/24"),
            "ip.src == 192.0.2.0/24",
            "ip.addr == 192.0.2.0/24",
            frozenset(RECIPES) - {"udp-private", "tcp-reverse"},
        ),
        (
            "grouped-transport",
            "TCP SYN packets or DNS responses, with grouping.",
            AnyOf(
                children=(
                    All(children=(tcp, syn)),
                    _p("dns.flags.response", eq, True),
                )
            ),
            "(tcp && tcp.flags.syn == 1) || dns.flags.response == 1",
            "tcp && (tcp.flags.syn == 1 || dns.flags.response == 1)",
            _SYN | {"udp-response", "udp-nxdomain"},
        ),
        (
            "exclude-syn-reset",
            "TCP excluding both SYN and reset packets.",
            All(
                children=(
                    tcp,
                    Not(
                        child=AnyOf(
                            children=(syn, _p("tcp.flags.reset", eq, True))
                        )
                    ),
                )
            ),
            "tcp && !(tcp.flags.syn == 1 || tcp.flags.reset == 1)",
            "!(tcp.flags.syn == 1 || tcp.flags.reset == 1)",
            _TCP - _SYN - {"reset"},
        ),
    )
    return tuple(SemanticCase(*row) for row in rows)


def _packet(recipe: str, seed: int, ordinal: int) -> bytes:
    bases = {
        "tcp-http": "syn",
        "udp-mdns": "udp-query",
        "udp-aaaa": "udp-query",
        "udp-nxdomain": "udp-response",
        "udp-lowttl": "udp-other",
        "tcp-lowttl": "ack",
        "udp-private": "udp-other",
        "udp-private-destination": "udp-other",
        "tcp-reverse": "ack",
    }
    # Reuse the checked packet builder without changing its nine probes.
    packet = bytearray(
        fixtures.ethernet_packet(bases.get(recipe, recipe), seed, ordinal)
    )
    ip_end = 14 + int.from_bytes(packet[16:18], "big")
    if recipe in {"tcp-http", "udp-mdns"}:
        packet[36:38] = struct.pack("!H", 80 if recipe == "tcp-http" else 5353)
    if recipe == "udp-aaaa":
        packet[ip_end - 4 : ip_end - 2] = struct.pack("!H", 28)
    if recipe == "udp-nxdomain":
        packet[45] |= 3
    if recipe in {"udp-lowttl", "tcp-lowttl"}:
        packet[22] = 1
    if recipe == "udp-private":
        packet[26:30] = bytes((10, 1, 2, 3))
    if recipe == "udp-private-destination":
        packet[30:34] = bytes((10, 1, 2, 3))
    if recipe == "tcp-reverse":
        packet[26:30], packet[30:34] = packet[30:34], packet[26:30]
    packet[24:26] = b"\0\0"
    packet[24:26] = struct.pack(
        "!H", fixtures.internet_checksum(bytes(packet[14:34]))
    )
    checksum_offset = 50 if packet[23] == 6 else 40
    packet[checksum_offset : checksum_offset + 2] = b"\0\0"
    segment = bytes(packet[34:ip_end])
    pseudo = bytes(packet[26:34]) + struct.pack(
        "!BBH", 0, packet[23], len(segment)
    )
    checksum = fixtures.internet_checksum(pseudo + segment) or 0xFFFF
    packet[checksum_offset : checksum_offset + 2] = struct.pack("!H", checksum)
    return bytes(packet)


def capture_bytes(recipes: tuple[str, ...], seed: int) -> bytes:
    """Builds a deterministic complete Ethernet/IPv4 PCAP from named recipes."""
    if not recipes or any(recipe not in RECIPES for recipe in recipes):
        raise ValueError("Capture requires known packet recipes")
    if not 1 <= seed <= 10000 or len(recipes) > 200:
        raise ValueError(
            "Capture seed or packet count is outside benchmark bounds"
        )
    records = [struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)]
    for ordinal, recipe in enumerate(recipes, 1):
        packet = _packet(recipe, seed, ordinal)
        records.extend(
            (
                struct.pack(
                    "<IIII",
                    1700000000 + seed,
                    ordinal * 1000,
                    len(packet),
                    len(packet),
                ),
                packet,
            )
        )
    return b"".join(records)


def generate_benchmark(output_dir: Path) -> tuple[BenchmarkProbe, ...]:
    """Writes 50 distinct captures; the first three serve every semantic case.

    Probe one omits SYN-ACK, exposing the inadequacy of a single happy-path
    witness. Probe two restores it; probe three reverses and duplicates traffic.
    Remaining captures rotate, reverse, duplicate and vary deterministic seeds.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    probes: list[BenchmarkProbe] = []
    for index in range(50):
        offset = index % len(RECIPES)
        cycle = index // len(RECIPES)
        recipes = RECIPES[offset:] + RECIPES[:offset]
        if index == 0:
            recipes = tuple(recipe for recipe in recipes if recipe != "syn-ack")
        elif index % 2 == 0:
            duplicate_count = index % 5 + 1 + cycle * 5
            recipes = tuple(reversed(recipes)) + recipes[:duplicate_count]
        elif cycle:
            recipes += recipes[:cycle]
        probe_id = f"semantic-{index + 1:02}"
        path = output_dir / f"{probe_id}.pcap"
        path.write_bytes(capture_bytes(recipes, 100 + index))
        probes.append(BenchmarkProbe(probe_id, path, recipes))
    # Compute the three shared probe identities once, without hashing unrelated
    # files.
    capture_identities = {
        probe.probe_id: hashlib.sha256(
            probe.capture_path.read_bytes()
        ).hexdigest()
        for probe in probes[:3]
    }
    for directory in ("specs", "intents"):
        (output_dir / directory).mkdir(exist_ok=True)
    for case in semantic_cases():
        expectations = tuple(
            ProbeExpectationV1(
                probe_id=probe.probe_id,
                capture_sha256=capture_identities[probe.probe_id],
                expected_frames=probe.labels(case),
            )
            for probe in probes[:3]
        )
        spec = SemanticSpecV1(
            task_id=case.task_id,
            intent=case.intent,
            assumptions=(
                "Complete synthetic Ethernet/IPv4 TCP and UDP packets only.",
                "Includes mDNS with shared dns.* fields but a distinct "
                "protocol.",
                "Equivalence applies only to these probes and the pinned "
                "environment.",
            ),
            canonical_ir=case.canonical_ir,
            reference_filter=case.reference_filter,
            probes=expectations,
            split="pilot",
            provenance=_PROVENANCE,
            license="MIT",
            review_status=_REVIEW_STATUS,
        )
        (output_dir / "specs" / f"{case.task_id}.json").write_text(
            spec.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "intents" / f"{case.task_id}.json").write_text(
            case.canonical_ir.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    manifest = {
        "schema_version": "1.0",
        "generator": "dfilterforge.benchmark/v1",
        "status": "ready",
        "split": "pilot",
        "license": "MIT",
        "review_status": _REVIEW_STATUS,
        "provenance": _PROVENANCE,
        "probes": [
            {
                "probe_id": p.probe_id,
                "capture": p.capture_path.name,
                "seed": 100 + index,
                "recipes": p.recipes,
            }
            for index, p in enumerate(probes)
        ],
        "specs": [
            {
                "task_id": c.task_id,
                "spec_path": f"specs/{c.task_id}.json",
                "intent_path": f"intents/{c.task_id}.json",
                "intent": c.intent,
                "canonical_ir": c.canonical_ir.model_dump(mode="json"),
                "reference_filter": c.reference_filter,
                "mutation_filter": c.mutation_filter,
                "matching_recipes": sorted(c.matching_recipes),
                "probes": [
                    {"probe_id": p.probe_id, "expected_frames": p.labels(c)}
                    for p in probes[:3]
                ],
            }
            for c in semantic_cases()
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return tuple(probes)
