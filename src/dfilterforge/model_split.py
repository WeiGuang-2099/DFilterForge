"""Held-out model evaluation compositions and model-safe artifacts.

The split deliberately reuses the benchmark's packet recipes and protocols.
It holds out predicate compositions and capture instances, not recipe or
protocol families. Each probe copy ends in a tail of witness packets that
separate near-miss filters the recipes alone cannot. Evaluator gold is
written separately from model inputs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import Field
from pydantic import model_validator

from dfilterforge.benchmark import ACK_RECIPES
from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.benchmark import DNS_RECIPES
from dfilterforge.benchmark import generate_benchmark
from dfilterforge.benchmark import HIGH_UDP_PORT_RECIPES
from dfilterforge.benchmark import RECIPES
from dfilterforge.benchmark import SYN_RECIPES
from dfilterforge.benchmark import TCP_RECIPES
from dfilterforge.benchmark import UDP_RECIPES
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue
from dfilterforge.mutants import MutantWaiver
from dfilterforge.witnesses import A_QUERY_WITNESSES
from dfilterforge.witnesses import ACK_WITNESSES
from dfilterforge.witnesses import append_witnesses
from dfilterforge.witnesses import CLIENT_WITNESSES
from dfilterforge.witnesses import DNS_WITNESSES
from dfilterforge.witnesses import HIGH_PORT_WITNESSES
from dfilterforge.witnesses import HTTPS_WITNESSES
from dfilterforge.witnesses import PRIVATE_WITNESSES
from dfilterforge.witnesses import RESPONSE_WITNESSES
from dfilterforge.witnesses import SOURCE_53_WITNESSES
from dfilterforge.witnesses import SYN_WITNESSES
from dfilterforge.witnesses import TCP_WITNESSES
from dfilterforge.witnesses import TTL_BELOW_64_WITNESSES
from dfilterforge.witnesses import UDP_WITNESSES
from dfilterforge.witnesses import WITNESS_NAMES

ModelSplit = Literal["dev", "test"]

_CAPTURE_IDS: dict[ModelSplit, tuple[str, ...]] = {
    "dev": ("semantic-11", "semantic-17", "semantic-23"),
    "test": ("semantic-31", "semantic-37", "semantic-43"),
}
_USER_ASSUMPTIONS = (
    "Interpret the request at packet scope over complete Ethernet/IPv4 "
    "packets.",
    "Treat source and destination constraints as directional.",
)
_SPEC_ASSUMPTIONS = (
    "Complete synthetic Ethernet/IPv4 TCP and UDP packets only.",
    "mDNS exposes shared dns.* fields but remains a distinct protocol.",
    "Equivalence applies only to the selected probes and pinned environment.",
)
# Evaluator-only readings of one case's wording, added to the shared
# specification assumptions; the model never sees them.
_CASE_ASSUMPTIONS: dict[str, tuple[str, ...]] = {
    "fin-or-dns-response": (
        "All DNS responses include mDNS responses, which carry the same "
        "dns.* response flag.",
    ),
}
_PROVENANCE = (
    "Model evaluation cases authored as held-out compositions over the same "
    "packet recipes and protocol families as dfilterforge.benchmark/v1. Dev "
    "uses copies of semantic-11/17/23 and test copies of semantic-31/37/43, "
    "rather than the original semantic-suite probes semantic-01/02/03; each "
    "copy keeps the benchmark frames byte for byte and appends the 31 "
    "witness packets of dfilterforge.witnesses. This is strictly an "
    "unseen-composition plus unseen-capture-instance split; it is not an "
    "unseen-recipe or unseen-protocol split. Labels are authored from recipe "
    "and witness membership rather than inferred from display filters, and "
    "scripts/probe_adequacy.py checks them with tshark on all six probes."
)


class ModelInputItemV1(FrozenModel):
    """The complete model-visible contract for one paraphrased request."""

    item_id: str = Field(pattern=r"^mei-[0-9]{4}$")
    intent: str = Field(min_length=1)
    user_assumptions: tuple[str, ...] = Field(min_length=1)
    split: ModelSplit


class ModelGoldCaseV1(FrozenModel):
    """Evaluator-only canonical target and its authored near-wrong filter."""

    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    spec: SemanticSpecV1
    mutation_filter: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_case_identity(self) -> "ModelGoldCaseV1":
        """Keeps the evaluator case identity aligned with its specification."""
        if self.spec.task_id != self.case_id:
            raise ValueError("gold case_id must match spec.task_id")
        if self.spec.split not in _CAPTURE_IDS:
            raise ValueError("gold specifications must use dev or test split")
        expected_probe_ids = _CAPTURE_IDS[self.spec.split]
        if tuple(probe.probe_id for probe in self.spec.probes) != (
            expected_probe_ids
        ):
            raise ValueError("gold probes do not match the declared split")
        return self


class ModelGoldV1(FrozenModel):
    """Evaluator-only targets and opaque model-item routing."""

    schema_version: Literal["model-gold/1.0"] = "model-gold/1.0"
    cases: tuple[ModelGoldCaseV1, ...] = Field(min_length=1)
    item_to_case: dict[str, str]

    @model_validator(mode="after")
    def validate_item_routing(self) -> "ModelGoldV1":
        """Requires unique cases and exactly two items routed to each case."""
        case_ids = tuple(case.case_id for case in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("gold case IDs must be unique")
        if not self.item_to_case:
            raise ValueError("gold item routing cannot be empty")
        if any(not item_id.startswith("mei-") for item_id in self.item_to_case):
            raise ValueError("gold routing requires opaque model item IDs")
        unknown = set(self.item_to_case.values()) - set(case_ids)
        if unknown:
            raise ValueError("gold routing references an unknown case")
        counts = Counter(self.item_to_case.values())
        if any(counts[case_id] != 2 for case_id in case_ids):
            raise ValueError("every gold case requires exactly two model items")
        return self


@dataclass(frozen=True)
class RecipeOracle:
    """Independent canonical and mutation recipe and witness memberships."""

    canonical: frozenset[str]
    mutation: frozenset[str]


@dataclass(frozen=True)
class ModelSemanticCase:
    """One evaluator case with two independently worded model requests."""

    case_id: str
    split: ModelSplit
    paraphrases: tuple[str, str]
    expression: Expression
    reference_filter: str
    mutation_filter: str
    recipe_oracle: RecipeOracle

    @property
    def canonical_ir(self) -> IntentIrV1:
        """Returns the canonical typed target for this case."""
        return IntentIrV1(expression=self.expression)

    def labels(
        self, probe: BenchmarkProbe, *, mutation: bool = False
    ) -> tuple[int, ...]:
        """Maps the independently authored recipe oracle to frame numbers."""
        memberships = (
            self.recipe_oracle.mutation
            if mutation
            else self.recipe_oracle.canonical
        )
        return tuple(
            index
            for index, recipe in enumerate(probe.recipes, 1)
            if recipe in memberships
        )


@dataclass(frozen=True)
class ModelSplitArtifacts:
    """In-memory contracts and paths emitted by split generation."""

    inputs: tuple[ModelInputItemV1, ...]
    gold: ModelGoldV1
    inputs_path: Path
    gold_path: Path
    capture_paths: tuple[Path, ...]
    # The same captures with their recipe and witness order, for labels on
    # any probe.
    probes: tuple[BenchmarkProbe, ...]


def _p(
    field: str,
    operator: Operator = Operator.EXISTS,
    value: ScalarValue | tuple[ScalarValue, ...] | None = None,
) -> Predicate:
    return Predicate(field=field, operator=operator, value=value)


def _oracle(
    canonical: AbstractSet[str],
    mutation: AbstractSet[str],
    *,
    witnesses: tuple[AbstractSet[str], AbstractSet[str]],
) -> RecipeOracle:
    """Joins recipe memberships with the canonical and mutation witnesses."""
    return RecipeOracle(
        frozenset(canonical) | witnesses[0], frozenset(mutation) | witnesses[1]
    )


def model_semantic_cases() -> tuple[ModelSemanticCase, ...]:
    """Returns eight dev and sixteen test held-out compositions."""
    responses = frozenset({"udp-response", "udp-nxdomain"})
    source_testnet = frozenset(RECIPES) - {"udp-private", "tcp-reverse"}
    ttl_low = _p("ip.ttl", Operator.LE, 1)
    ttl_normal = _p("ip.ttl", Operator.GE, 64)
    source_test = _p("ip.src", Operator.IN_SUBNET, "192.0.2.0/24")
    source_private = _p("ip.src", Operator.IN_SUBNET, "10.0.0.0/8")
    destination_private = _p("ip.dst", Operator.IN_SUBNET, "10.0.0.0/8")
    syn_bit = _p("tcp.flags.syn", Operator.EQ, True)
    ack_bit = _p("tcp.flags.ack", Operator.EQ, True)
    reset_bit = _p("tcp.flags.reset", Operator.EQ, True)
    query = _p("dns.flags.response", Operator.EQ, False)
    response = _p("dns.flags.response", Operator.EQ, True)
    qtype_a = _p("dns.qry.type", Operator.EQ, 1)
    qtype_aaaa = _p("dns.qry.type", Operator.EQ, 28)
    udp_high = _p("udp.dstport", Operator.GT, 5353)

    return (
        ModelSemanticCase(
            "tcp-expiring-ttl",
            "dev",
            (
                "Keep only TCP packets whose IPv4 TTL is 1 or lower.",
                "Find expiring IPv4 traffic carried by TCP, using TTL at "
                "most one.",
            ),
            All(children=(_p("tcp"), ttl_low)),
            "tcp && ip.ttl <= 1",
            "ip.ttl <= 1 && (tcp || udp)",
            _oracle(
                {"tcp-lowttl"},
                {"tcp-lowttl", "udp-lowttl"},
                witnesses=({"tcp-ttl-0"}, {"tcp-ttl-0", "udp-ttl-0"}),
            ),
        ),
        ModelSemanticCase(
            "udp-expiring-ttl",
            "dev",
            (
                "Keep only UDP packets whose IPv4 TTL is at most one.",
                "Find expiring IPv4 datagrams carried by UDP, with TTL no "
                "greater than 1.",
            ),
            All(children=(_p("udp"), ttl_low)),
            "udp && ip.ttl <= 1",
            "ip.ttl <= 1 && (udp || tcp)",
            _oracle(
                {"udp-lowttl"},
                {"tcp-lowttl", "udp-lowttl"},
                witnesses=({"udp-ttl-0"}, {"tcp-ttl-0", "udp-ttl-0"}),
            ),
        ),
        ModelSemanticCase(
            "ack-to-https",
            "dev",
            (
                "Show TCP packets sent to port 443 with the ACK flag set.",
                "Find acknowledged TCP segments whose destination service "
                "port is 443.",
            ),
            All(children=(ack_bit, _p("tcp.dstport", Operator.EQ, 443))),
            "tcp.flags.ack == 1 && tcp.dstport == 443",
            "tcp.flags.ack == 1 && tcp",
            _oracle(
                {"syn-ack", "ack", "reset", "tcp-lowttl", "tcp-reverse"},
                ACK_RECIPES,
                witnesses=(ACK_WITNESSES & HTTPS_WITNESSES, ACK_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "dns-a-queries",
            "dev",
            (
                "Show DNS queries for A records over any transport, "
                "including mDNS.",
                "Find request-side DNS messages asking for IPv4 address "
                "records without limiting transport.",
            ),
            All(children=(query, qtype_a)),
            "dns.flags.response == 0 && dns.qry.type == 1",
            "dns.flags.response == 0 && dns",
            _oracle(
                {"tcp-query", "udp-query", "udp-both-53", "udp-mdns"},
                # The dns protocol test in the mutation never matches mDNS.
                {"tcp-query", "udp-query", "udp-both-53", "udp-aaaa"},
                witnesses=(
                    A_QUERY_WITNESSES,
                    A_QUERY_WITNESSES | {"dns-mx-query"},
                ),
            ),
        ),
        ModelSemanticCase(
            "fin-or-dns-response",
            "dev",
            (
                "Show TCP FIN packets together with all DNS responses.",
                "Match either a TCP close segment carrying FIN or a "
                "response-side DNS message.",
            ),
            AnyOf(children=(_p("tcp.flags.fin", Operator.EQ, True), response)),
            "tcp.flags.fin == 1 || dns.flags.response == 1",
            "dns && dns.flags.response == 1",
            _oracle(
                {"fin", *responses},
                responses,
                witnesses=(
                    RESPONSE_WITNESSES,
                    RESPONSE_WITNESSES & DNS_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "udp-nondns-private-destination",
            "dev",
            (
                "Show non-DNS UDP packets whose IPv4 destination is inside "
                "10.0.0.0/8.",
                "Find UDP traffic not decoded as DNS when it is headed to a "
                "private 10/8 address.",
            ),
            All(
                children=(
                    _p("udp"),
                    Not(child=_p("dns")),
                    destination_private,
                )
            ),
            "udp && !dns && ip.dst == 10.0.0.0/8",
            "udp && !dns && ip",
            _oracle(
                {"udp-private-destination"},
                UDP_RECIPES - DNS_RECIPES,
                witnesses=(
                    {"udp-to-far-private"},
                    UDP_WITNESSES - DNS_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "ecn-syn-or-expiring",
            "dev",
            (
                "Show either ECN-enabled TCP SYN packets or IPv4 packets "
                "with TTL at most one.",
                "Match TCP connection starts carrying ECE, plus expiring "
                "IPv4 traffic at TTL 1 or below.",
            ),
            AnyOf(
                children=(
                    All(
                        children=(
                            syn_bit,
                            _p("tcp.flags.ece", Operator.EQ, True),
                        )
                    ),
                    ttl_low,
                )
            ),
            "(tcp.flags.syn == 1 && tcp.flags.ece == 1) || ip.ttl <= 1",
            "tcp && tcp.flags.syn == 1 && tcp.flags.ece == 1",
            _oracle(
                {"ecn-syn", "tcp-lowttl", "udp-lowttl"},
                {"ecn-syn"},
                # cwr-syn has no ECE and ece-syn-reset no SYN.
                witnesses=({"tcp-ttl-0", "udp-ttl-0"}, set()),
            ),
        ),
        ModelSemanticCase(
            "aaaa-or-nxdomain",
            "dev",
            (
                "Show DNS AAAA questions or DNS NXDOMAIN messages.",
                "Find DNS traffic that either asks for IPv6 addresses or "
                "reports a name error.",
            ),
            AnyOf(children=(qtype_aaaa, _p("dns.flags.rcode", Operator.EQ, 3))),
            "dns.qry.type == 28 || dns.flags.rcode == 3",
            "dns && dns.qry.type == 28",
            _oracle(
                {"udp-aaaa", "udp-nxdomain"},
                {"udp-aaaa"},
                witnesses=(set(), set()),
            ),
        ),
        ModelSemanticCase(
            "tcp-source-testnet",
            "test",
            (
                "Show TCP packets sourced from TEST-NET-1, 192.0.2.0/24.",
                "Find TCP traffic whose IPv4 source belongs to the "
                "192.0.2.0/24 documentation subnet.",
            ),
            All(children=(_p("tcp"), source_test)),
            "tcp && ip.src == 192.0.2.0/24",
            "tcp && ip",
            _oracle(
                TCP_RECIPES - {"tcp-reverse"},
                TCP_RECIPES,
                witnesses=(TCP_WITNESSES & CLIENT_WITNESSES, TCP_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "udp-source-testnet",
            "test",
            (
                "Show UDP packets sourced from TEST-NET-1, 192.0.2.0/24.",
                "Find UDP datagrams whose IPv4 source belongs to the "
                "192.0.2.0/24 documentation subnet.",
            ),
            All(children=(_p("udp"), source_test)),
            "udp && ip.src == 192.0.2.0/24",
            "udp && ip",
            _oracle(
                UDP_RECIPES - {"udp-private"},
                UDP_RECIPES,
                witnesses=(UDP_WITNESSES & CLIENT_WITNESSES, UDP_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "private-either-endpoint",
            "test",
            (
                "Show IPv4 packets with either endpoint inside 10.0.0.0/8.",
                "Find traffic where the source or destination address is in "
                "the private 10/8 network.",
            ),
            AnyOf(children=(source_private, destination_private)),
            "ip.src == 10.0.0.0/8 || ip.dst == 10.0.0.0/8",
            "ip && ip.src == 10.0.0.0/8",
            _oracle(
                {"udp-private", "udp-private-destination"},
                {"udp-private"},
                witnesses=(PRIVATE_WITNESSES, {"udp-from-far-private"}),
            ),
        ),
        ModelSemanticCase(
            "source-testnet-or-private",
            "test",
            (
                "Show packets sourced from either 192.0.2.0/24 or "
                "10.0.0.0/8.",
                "Find IPv4 traffic whose source is in TEST-NET-1 or the "
                "private 10/8 range.",
            ),
            AnyOf(children=(source_test, source_private)),
            "ip.src == 192.0.2.0/24 || ip.src == 10.0.0.0/8",
            "ip && ip.src == 192.0.2.0/24",
            _oracle(
                frozenset(RECIPES) - {"tcp-reverse"},
                source_testnet,
                witnesses=(
                    CLIENT_WITNESSES | {"udp-from-far-private"},
                    CLIENT_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "ack-outside-testnet",
            "test",
            (
                "Show ACK-bearing TCP packets whose source is outside "
                "192.0.2.0/24.",
                "Find TCP segments with ACK set, excluding sources in "
                "TEST-NET-1.",
            ),
            All(children=(ack_bit, Not(child=source_test))),
            "tcp.flags.ack == 1 && !(ip.src == 192.0.2.0/24)",
            "tcp && tcp.flags.ack == 1",
            _oracle(
                {"tcp-reverse"},
                ACK_RECIPES,
                witnesses=(ACK_WITNESSES - CLIENT_WITNESSES, ACK_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "high-udp-source-testnet",
            "test",
            (
                "Show UDP packets sent above port 5353 when sourced from "
                "192.0.2.0/24.",
                "Find TEST-NET-1-sourced UDP datagrams whose destination "
                "port is greater than 5353.",
            ),
            All(children=(udp_high, source_test)),
            "udp.dstport > 5353 && ip.src == 192.0.2.0/24",
            "udp && udp.dstport > 5353",
            _oracle(
                HIGH_UDP_PORT_RECIPES - {"udp-private"},
                HIGH_UDP_PORT_RECIPES,
                witnesses=(
                    HIGH_PORT_WITNESSES & CLIENT_WITNESSES,
                    HIGH_PORT_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "high-udp-normal-ttl",
            "test",
            (
                "Show UDP packets sent above port 5353 with IPv4 TTL at "
                "least 64.",
                "Find high-destination-port UDP datagrams whose TTL is 64 "
                "or greater.",
            ),
            All(children=(udp_high, ttl_normal)),
            "udp.dstport > 5353 && ip.ttl >= 64",
            "ip && udp.dstport > 5353",
            _oracle(
                HIGH_UDP_PORT_RECIPES - {"udp-lowttl"},
                HIGH_UDP_PORT_RECIPES,
                witnesses=(
                    HIGH_PORT_WITNESSES - TTL_BELOW_64_WITNESSES,
                    HIGH_PORT_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "high-udp-testnet-normal-ttl",
            "test",
            (
                "Show UDP packets above destination port 5353 with source "
                "in 192.0.2.0/24 and TTL at least 64.",
                "Find normal-TTL, high-port UDP datagrams sent by a "
                "TEST-NET-1 source.",
            ),
            All(children=(udp_high, source_test, ttl_normal)),
            "udp.dstport > 5353 && ip.src == 192.0.2.0/24 && ip.ttl >= 64",
            "udp && udp.dstport > 5353 && ip.src == 192.0.2.0/24",
            _oracle(
                HIGH_UDP_PORT_RECIPES - {"udp-private", "udp-lowttl"},
                HIGH_UDP_PORT_RECIPES - {"udp-private"},
                witnesses=(
                    (HIGH_PORT_WITNESSES & CLIENT_WITNESSES)
                    - TTL_BELOW_64_WITNESSES,
                    HIGH_PORT_WITNESSES & CLIENT_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "low-port-dns-a",
            "test",
            (
                "Show UDP packets below destination port 5353 that carry a "
                "DNS A question.",
                "Find IPv4-address DNS questions in UDP datagrams whose "
                "destination port is under 5353.",
            ),
            All(
                children=(
                    _p("udp.dstport", Operator.LT, 5353),
                    qtype_a,
                )
            ),
            "udp.dstport < 5353 && dns.qry.type == 1",
            "udp && udp.dstport < 5353",
            _oracle(
                {"udp-query", "udp-both-53"},
                {"udp-query", "udp-both-53", "udp-aaaa"},
                witnesses=(
                    A_QUERY_WITNESSES
                    | {"dns-response-53-to-53", "dns-response-to-low-port"},
                    A_QUERY_WITNESSES
                    | {
                        "dns-response-53-to-53",
                        "dns-response-to-low-port",
                        "dns-mx-query",
                    },
                ),
            ),
        ),
        ModelSemanticCase(
            "dns-destination-not-source",
            "test",
            (
                "Show UDP packets sent to port 53 whose source port is not "
                "also 53.",
                "Find UDP destination-53 traffic excluding packets that use "
                "port 53 at both endpoints.",
            ),
            All(
                children=(
                    _p("udp.dstport", Operator.EQ, 53),
                    _p("udp.srcport", Operator.NE, 53),
                )
            ),
            "udp.dstport == 53 && udp.srcport != 53",
            "udp && udp.dstport == 53",
            _oracle(
                {"udp-query", "udp-aaaa"},
                {"udp-query", "udp-both-53", "udp-aaaa"},
                witnesses=(
                    {
                        "dns-mx-query",
                        "dns-query-from-low-port",
                        "dns-to-private",
                    },
                    {
                        "dns-mx-query",
                        "dns-query-from-low-port",
                        "dns-to-private",
                        "dns-response-53-to-53",
                    },
                ),
            ),
        ),
        ModelSemanticCase(
            "successful-source-dns",
            "test",
            (
                "Show successful DNS messages in UDP from source port 53 to "
                "a different destination port.",
                "Find UDP source-53 DNS responses with response code zero, "
                "excluding port 53 at the destination.",
            ),
            All(
                children=(
                    _p("udp.srcport", Operator.EQ, 53),
                    _p("udp.dstport", Operator.NE, 53),
                    _p("dns.flags.rcode", Operator.EQ, 0),
                )
            ),
            "udp.srcport == 53 && udp.dstport != 53 && dns.flags.rcode == 0",
            "udp && udp.srcport == 53 && udp.dstport != 53",
            _oracle(
                {"udp-response"},
                responses,
                witnesses=(
                    {"dns-response-to-low-port"},
                    SOURCE_53_WITNESSES - {"dns-response-53-to-53"},
                ),
            ),
        ),
        ModelSemanticCase(
            "aaaa-or-udp-source-dns",
            "test",
            (
                "Show packets that are DNS AAAA questions or UDP packets "
                "sourced from port 53.",
                "Find either IPv6-address DNS questions or datagrams whose "
                "UDP source port is 53.",
            ),
            AnyOf(children=(qtype_aaaa, _p("udp.srcport", Operator.EQ, 53))),
            "dns.qry.type == 28 || udp.srcport == 53",
            "dns && udp.srcport == 53",
            _oracle(
                {
                    "udp-aaaa",
                    "udp-response",
                    "udp-nxdomain",
                    "udp-both-53",
                },
                {"udp-response", "udp-nxdomain", "udp-both-53"},
                witnesses=(SOURCE_53_WITNESSES, SOURCE_53_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "https-without-syn",
            "test",
            (
                "Show TCP packets to port 443 with the SYN flag clear.",
                "Find non-SYN TCP segments whose destination port is 443.",
            ),
            All(
                children=(
                    _p("tcp.dstport", Operator.EQ, 443),
                    _p("tcp.flags.syn", Operator.EQ, False),
                )
            ),
            "tcp.dstport == 443 && tcp.flags.syn == 0",
            "tcp && tcp.flags.syn == 0",
            _oracle(
                (TCP_RECIPES - SYN_RECIPES) - {"tcp-query"},
                TCP_RECIPES - SYN_RECIPES,
                witnesses=(
                    HTTPS_WITNESSES - SYN_WITNESSES,
                    TCP_WITNESSES - SYN_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "https-syn-no-ack",
            "test",
            (
                "Show TCP packets to port 443 with SYN set and ACK clear.",
                "Find port-443 TCP connection starts that do not carry ACK.",
            ),
            All(
                children=(
                    _p("tcp.dstport", Operator.EQ, 443),
                    syn_bit,
                    _p("tcp.flags.ack", Operator.EQ, False),
                )
            ),
            "tcp.dstport == 443 && tcp.flags.syn == 1 && tcp.flags.ack == 0",
            "tcp && tcp.flags.syn == 1 && tcp.flags.ack == 0",
            _oracle(
                {"syn", "ecn-syn"},
                SYN_RECIPES - {"syn-ack"},
                witnesses=(HTTPS_WITNESSES & SYN_WITNESSES, SYN_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "https-syn-or-reset",
            "test",
            (
                "Show TCP packets to port 443 carrying either SYN or RST.",
                "Find destination-443 TCP segments when the SYN or reset bit "
                "is set.",
            ),
            All(
                children=(
                    _p("tcp.dstport", Operator.EQ, 443),
                    AnyOf(children=(syn_bit, reset_bit)),
                )
            ),
            "tcp.dstport == 443 && "
            "(tcp.flags.syn == 1 || tcp.flags.reset == 1)",
            "(tcp && tcp.flags.syn == 1) || tcp.flags.reset == 1",
            _oracle(
                (SYN_RECIPES - {"tcp-http"}) | {"reset"},
                SYN_RECIPES | {"reset"},
                witnesses=(
                    (HTTPS_WITNESSES & SYN_WITNESSES) | {"ece-syn-reset"},
                    SYN_WITNESSES | {"ece-syn-reset"},
                ),
            ),
        ),
        ModelSemanticCase(
            "tcp-destination-not-https",
            "test",
            (
                "Show TCP packets whose destination port is not 443.",
                "Find TCP traffic addressed to any destination service other "
                "than port 443.",
            ),
            _p("tcp.dstport", Operator.NE, 443),
            "tcp.dstport != 443",
            "tcp.dstport == 53",
            _oracle(
                {"tcp-query", "tcp-http"},
                {"tcp-query"},
                witnesses=(TCP_WITNESSES - HTTPS_WITNESSES, set()),
            ),
        ),
    )


# Single-site mutants of the cases above that the probes may leave alive,
# each with a reason. scripts/probe_adequacy.py fails on any other survivor
# and on any waiver that no longer matches a survivor.
MUTANT_WAIVERS: tuple[MutantWaiver, ...] = (
    MutantWaiver(
        case_id="private-either-endpoint",
        edit="0: ip.src -> ip.addr",
        display_filter="(ip.addr == 10.0.0.0/8 || ip.dst == 10.0.0.0/8)",
        kind="equivalent",
        reason=(
            "ip.addr matches exactly where ip.src or ip.dst does, and the "
            "other branch already tests ip.dst."
        ),
    ),
    MutantWaiver(
        case_id="private-either-endpoint",
        edit="1: ip.dst -> ip.addr",
        display_filter="(ip.src == 10.0.0.0/8 || ip.addr == 10.0.0.0/8)",
        kind="equivalent",
        reason=(
            "ip.addr matches exactly where ip.src or ip.dst does, and the "
            "other branch already tests ip.src."
        ),
    ),
    MutantWaiver(
        case_id="dns-destination-not-source",
        edit="0: udp.dstport -> udp.port",
        display_filter="(udp.port == 53 && udp.srcport != 53)",
        kind="equivalent",
        reason=(
            "With the source port required not to be 53, udp.port == 53 can "
            "only match the destination port."
        ),
    ),
    MutantWaiver(
        case_id="successful-source-dns",
        edit="0: udp.srcport -> udp.port",
        display_filter=(
            "(udp.port == 53 && udp.dstport != 53 && dns.flags.rcode == 0)"
        ),
        kind="equivalent",
        reason=(
            "With the destination port required not to be 53, udp.port == 53 "
            "can only match the source port."
        ),
    ),
)


def _copy_selected_probes(output_dir: Path) -> tuple[BenchmarkProbe, ...]:
    """Copies the six selected benchmark captures and appends witnesses."""
    capture_dir = output_dir / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    selected_ids = {
        probe_id
        for probe_ids in _CAPTURE_IDS.values()
        for probe_id in probe_ids
    }
    selected: list[BenchmarkProbe] = []
    with TemporaryDirectory(prefix="dfilterforge-model-split-") as staging:
        generated = generate_benchmark(Path(staging))
        # generate_benchmark builds capture i with seed 100 + i.
        for seed, probe in enumerate(generated, 100):
            if probe.probe_id not in selected_ids:
                continue
            target = capture_dir / probe.capture_path.name
            target.write_bytes(
                append_witnesses(
                    probe.capture_path.read_bytes(), seed, len(probe.recipes)
                )
            )
            selected.append(
                BenchmarkProbe(
                    probe.probe_id, target, probe.recipes + WITNESS_NAMES
                )
            )
    order = {
        probe_id: index
        for index, probe_id in enumerate(
            probe_id
            for split in ("dev", "test")
            for probe_id in _CAPTURE_IDS[split]
        )
    }
    return tuple(sorted(selected, key=lambda probe: order[probe.probe_id]))


def _build_gold_case(
    case: ModelSemanticCase, probes: dict[str, BenchmarkProbe]
) -> ModelGoldCaseV1:
    expectations: list[ProbeExpectationV1] = []
    for probe_id in _CAPTURE_IDS[case.split]:
        probe = probes[probe_id]
        capture = probe.capture_path.read_bytes()
        expectations.append(
            ProbeExpectationV1(
                probe_id=probe_id,
                capture_sha256=hashlib.sha256(capture).hexdigest(),
                expected_frames=case.labels(probe),
            )
        )
    spec = SemanticSpecV1(
        task_id=case.case_id,
        intent=case.paraphrases[0],
        assumptions=_SPEC_ASSUMPTIONS + _CASE_ASSUMPTIONS.get(case.case_id, ()),
        canonical_ir=case.canonical_ir,
        reference_filter=case.reference_filter,
        probes=tuple(expectations),
        split=case.split,
        provenance=_PROVENANCE,
        license="MIT",
        review_status="reviewed",
    )
    return ModelGoldCaseV1(
        case_id=case.case_id,
        spec=spec,
        mutation_filter=case.mutation_filter,
    )


def generate_model_split(output_dir: Path) -> ModelSplitArtifacts:
    """Writes model-safe inputs, evaluator-only gold, and six captures.

    Existing generated files with the same names are replaced. No descriptive
    case identity, typed IR, filter, probe, frame, or capture metadata enters
    ``model_inputs.jsonl``.

    Args:
        output_dir: Destination for the two contracts and selected captures.

    Returns:
        The validated in-memory contracts and their generated filesystem paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    capture_probes = _copy_selected_probes(output_dir)
    probes_by_id = {probe.probe_id: probe for probe in capture_probes}
    cases = model_semantic_cases()
    inputs: list[ModelInputItemV1] = []
    routes: dict[str, str] = {}
    next_item_id = 1
    for case in cases:
        for intent in case.paraphrases:
            item_id = f"mei-{next_item_id:04d}"
            next_item_id += 1
            inputs.append(
                ModelInputItemV1(
                    item_id=item_id,
                    intent=intent,
                    user_assumptions=_USER_ASSUMPTIONS,
                    split=case.split,
                )
            )
            routes[item_id] = case.case_id
    gold = ModelGoldV1(
        cases=tuple(_build_gold_case(case, probes_by_id) for case in cases),
        item_to_case=routes,
    )
    inputs_path = output_dir / "model_inputs.jsonl"
    encoded_inputs = "".join(
        json.dumps(item.model_dump(mode="json"), sort_keys=True) + "\n"
        for item in inputs
    )
    inputs_path.write_text(encoded_inputs, encoding="utf-8")
    gold_path = output_dir / "evaluator_gold.json"
    gold_path.write_text(
        gold.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return ModelSplitArtifacts(
        inputs=tuple(inputs),
        gold=gold,
        inputs_path=inputs_path,
        gold_path=gold_path,
        capture_paths=tuple(probe.capture_path for probe in capture_probes),
        probes=capture_probes,
    )
