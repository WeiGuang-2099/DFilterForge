"""Evaluator cases of the model split and their gold records.

Each case holds two independently worded requests. A ready case pairs them
with a canonical typed target, its reference filter, an authored near-wrong
mutation filter and recipe and witness memberships authored apart from both
filters; its tables live in :mod:`dfilterforge.model_dev_cases` and
:mod:`dfilterforge.model_test_cases`. A non-ready case's gold is a status
and, for needs_clarification, the slots the request leaves open; no filter
answers it, and its table is here. All of them live apart from
:mod:`dfilterforge.model_split`, which turns every case into model inputs
and evaluator gold, so the case lists can grow without the contracts module
growing with them.
"""

from __future__ import annotations

from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal, TypeAlias

from pydantic import Field
from pydantic import model_validator

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue

CaseSplit: TypeAlias = Literal["dev", "test"]
NonReadyStatus: TypeAlias = Literal["needs_clarification", "not_expressible"]


@dataclass(frozen=True)
class RecipeOracle:
    """Independent canonical and mutation recipe and witness memberships."""

    canonical: frozenset[str]
    mutation: frozenset[str]


@dataclass(frozen=True)
class ModelSemanticCase:
    """One evaluator case with two independently worded model requests."""

    case_id: str
    split: CaseSplit
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


def predicate(
    field: str,
    operator: Operator = Operator.EXISTS,
    value: ScalarValue | tuple[ScalarValue, ...] | None = None,
) -> Predicate:
    """Builds one typed predicate; the operator defaults to existence."""
    return Predicate(field=field, operator=operator, value=value)


def oracle(
    canonical: AbstractSet[str],
    mutation: AbstractSet[str],
    *,
    witnesses: tuple[AbstractSet[str], AbstractSet[str]],
) -> RecipeOracle:
    """Joins recipe memberships with the canonical and mutation witnesses."""
    return RecipeOracle(
        frozenset(canonical) | witnesses[0], frozenset(mutation) | witnesses[1]
    )


class ModelNonReadyCaseV1(FrozenModel):
    """Evaluator-only gold for a request no single filter should answer.

    A needs_clarification case names the slots its request leaves open, one
    or more from the closed list; a not_expressible case names none.
    """

    case_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    split: CaseSplit
    status: NonReadyStatus
    missing_slots: tuple[MissingSlot, ...] = ()
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_slots(self) -> "ModelNonReadyCaseV1":
        """Keeps the gold slots consistent with the gold status."""
        if len(set(self.missing_slots)) != len(self.missing_slots):
            raise ValueError("gold missing_slots must be unique")
        needs_slots = self.status == GenerationStatus.NEEDS_CLARIFICATION
        if needs_slots != bool(self.missing_slots):
            raise ValueError(
                "needs_clarification gold needs slots; not_expressible none"
            )
        return self


@dataclass(frozen=True)
class ModelNonReadyCase:
    """One non-ready evaluator case with two independently worded requests.

    Attributes:
        case_id: Stable evaluator identifier, never shown to a model.
        split: The split the case belongs to.
        status: The status the gold expects.
        paraphrases: The two model-visible requests.
        missing_slots: The slots a needs_clarification request leaves open;
            empty for not_expressible.
        rationale: Why no single-packet filter answers the request.
    """

    case_id: str
    split: CaseSplit
    status: NonReadyStatus
    paraphrases: tuple[str, str]
    missing_slots: tuple[MissingSlot, ...]
    rationale: str

    def gold(self) -> ModelNonReadyCaseV1:
        """Returns the evaluator-only gold record of this case."""
        return ModelNonReadyCaseV1(
            case_id=self.case_id,
            split=self.split,
            status=self.status,
            missing_slots=self.missing_slots,
            rationale=self.rationale,
        )


def model_non_ready_cases() -> tuple[ModelNonReadyCase, ...]:
    """Returns the needs_clarification and not_expressible compositions."""
    return (
        ModelNonReadyCase(
            "nc-new-file-server",
            "dev",
            "needs_clarification",
            (
                "Can you pull all the traffic headed to the new file server? "
                "Any protocol or port is fine.",
                "I want to see everything sent to the new file server, "
                "regardless of protocol or port.",
            ),
            (MissingSlot.ADDRESS,),
            "Every packet whose destination is the new file server, any "
            "protocol or port; the server's address is never given.",
        ),
        ModelNonReadyCase(
            "nc-billing-port",
            "dev",
            "needs_clarification",
            (
                "I'd like to see whatever traffic is going to the port the "
                "billing service listens on — any host, and both TCP and UDP "
                "should count.",
                "Which packets are headed to the billing service's listening "
                "port? Count both TCP and UDP, and don't restrict it to any "
                "particular host.",
            ),
            (MissingSlot.PORT,),
            "Traffic to the destination port the in-house billing service "
            "listens on, any host, TCP or UDP; the port number is never given.",
        ),
        ModelNonReadyCase(
            "nc-ttl-cutoff",
            "dev",
            "needs_clarification",
            (
                "Could you get me the IPv4 packets with a TTL below the "
                "threshold we agreed on earlier? Any protocol, either "
                "direction is fine.",
                "Which IPv4 packets have a TTL under the cutoff we settled on "
                "before, not including the cutoff itself? Protocol and "
                "direction don't matter.",
            ),
            (MissingSlot.VALUE,),
            "IPv4 packets whose TTL is strictly below a previously agreed "
            "cutoff; the cutoff number is never given.",
        ),
        ModelNonReadyCase(
            "nc-one-direction",
            "dev",
            "needs_clarification",
            (
                "Only pull one direction of the traffic between 192.0.2.0/24 "
                "and 10.0.0.0/8 — not both ways, just get me that one side.",
                "Give me the conversation between 192.0.2.0/24 and 10/8, but "
                "one-way only rather than both directions.",
            ),
            (MissingSlot.DIRECTION,),
            "Only one direction of the traffic between 192.0.2.0/24 and "
            "10.0.0.0/8; which direction is never stated.",
        ),
        ModelNonReadyCase(
            "ne-after-syn",
            "dev",
            "not_expressible",
            (
                "For every TCP packet that has the SYN flag set, I want the "
                "very next frame in the capture right after it — whatever "
                "protocol it is, whatever connection it belongs to.",
                "I want to see the packet immediately following each TCP SYN "
                "in the capture file, in capture order, no matter its protocol "
                "or connection.",
            ),
            (),
            "The frame that immediately follows each TCP SYN in capture order, "
            "whatever it is; a display filter judges one packet at a time and "
            "cannot refer to the previous frame.",
        ),
        ModelNonReadyCase(
            "ne-five-largest",
            "dev",
            "not_expressible",
            (
                "I want the five largest packets in the whole capture, ranked "
                "by frame length.",
                "Which 5 frames in this capture are the biggest by frame "
                "length? Filter down to just those.",
            ),
            (),
            "The five largest packets in the capture; a ranking across "
            "packets, not a per-packet predicate.",
        ),
        ModelNonReadyCase(
            "ne-chrome-process",
            "dev",
            "not_expressible",
            (
                "Can you get me the packets that the Chrome browser process "
                "sent? Just so you know, this is a plain Ethernet capture with "
                "no process information included.",
                "Can you filter for just the packets the Chrome browser "
                "process sent? It's an ordinary Ethernet capture, and nothing "
                "about processes was recorded.",
            ),
            (),
            "Packets sent by the Chrome browser process, in a plain Ethernet "
            "capture with no process metadata; process identity is not in the "
            "packets.",
        ),
        ModelNonReadyCase(
            "ne-rewrite-ttl",
            "dev",
            "not_expressible",
            (
                "Change the TTL on every packet in this capture to 64.",
                "Can you set the TTL to 64 on all of the packets in this "
                "capture?",
            ),
            (),
            "Set the TTL of every packet to 64; an edit, not a selection.",
        ),
        ModelNonReadyCase(
            "nc-compromised-laptop",
            "test",
            "needs_clarification",
            (
                "That compromised laptop we found - I need to see the DNS "
                "traffic it's sending out.",
                "I want every DNS packet where the laptop that got compromised "
                "is the source.",
            ),
            (MissingSlot.ADDRESS,),
            "DNS traffic sent from the compromised laptop; the laptop's "
            "address is never given.",
        ),
        ModelNonReadyCase(
            "nc-game-server-port",
            "test",
            "needs_clarification",
            (
                "Grab the UDP traffic headed to whatever port our game server "
                "listens on, regardless of host.",
                "I need the UDP packets whose destination port is the one our "
                "game server uses, with no restriction on host.",
            ),
            (MissingSlot.PORT,),
            "UDP packets sent to the destination port the in-house game server "
            "uses, any host; the port number is never given.",
        ),
        ModelNonReadyCase(
            "nc-that-flag",
            "test",
            "needs_clarification",
            (
                "There's a particular flag we talked about - can you pull the "
                "TCP segments that have it set?",
                "Can you filter for TCP segments with the flag we were talking "
                "about turned on?",
            ),
            (MissingSlot.FIELD,),
            "TCP segments with one particular flag set; which flag is never "
            "named.",
        ),
        ModelNonReadyCase(
            "nc-streaming-transport",
            "test",
            "needs_clarification",
            (
                "I want to see the traffic headed to destination port 5000, "
                "but only in whichever single transport protocol our streaming "
                "app actually uses there, not both.",
                "Can you filter for traffic headed for destination port 5000 "
                "using just the transport protocol our streaming app runs on? "
                "I don't want the other transport included.",
            ),
            (MissingSlot.PROTOCOL,),
            "Packets to destination port 5000 over the single transport (TCP "
            "or UDP) the streaming app uses; which transport is never stated.",
        ),
        ModelNonReadyCase(
            "nc-record-type",
            "test",
            "needs_clarification",
            (
                "Filter DNS queries for that record type we were discussing - "
                "just the queries, skip the responses.",
                "Can you pull out the DNS query packets asking for that record "
                "type we talked about before? Leave out the responses.",
            ),
            (MissingSlot.VALUE,),
            "DNS queries (not responses) for a previously discussed record "
            "type; the record type is never named.",
        ),
        ModelNonReadyCase(
            "nc-os-default-ttl",
            "test",
            "needs_clarification",
            (
                "Our server's OS isn't confirmed yet, but I need all IPv4 "
                "packets with a TTL at or above whatever that OS's default TTL "
                "turns out to be - same threshold across the board, any "
                "protocol or direction.",
                "Can you filter IPv4 traffic for TTL values at or above the "
                "default TTL of whatever OS our server has installed? Apply "
                "the same cutoff to every packet regardless of protocol or "
                "direction; nobody has confirmed yet which OS is on that box.",
            ),
            (MissingSlot.VALUE,),
            "IPv4 packets whose TTL is at least (inclusive) the "
            "operating-system default, with the OS unknown; the threshold is "
            "never given. Contestable.",
        ),
        ModelNonReadyCase(
            "nc-5353-one-direction",
            "test",
            "needs_clarification",
            (
                "I only need the UDP port 5353 traffic that's going one "
                "direction, not both ways together.",
                "Can you filter UDP traffic on port 5353 for a single "
                "direction only? I don't want both directions mixed together.",
            ),
            (MissingSlot.DIRECTION,),
            "UDP packets on port 5353 in one direction only (source port or "
            "destination port); which side is never stated.",
        ),
        ModelNonReadyCase(
            "nc-printer",
            "test",
            "needs_clarification",
            (
                "That printer in the office - can you get me everything it "
                "sends out, any protocol or port?",
                "I want all packets with the office printer as the source, "
                "with no restriction on protocol or port.",
            ),
            (MissingSlot.ADDRESS,),
            "Every packet sent from the office printer, any protocol or port; "
            "the printer's address is never given.",
        ),
        ModelNonReadyCase(
            "ne-https-login-url",
            "test",
            "not_expressible",
            (
                "Need the HTTPS requests hitting /login - heads up, it's all "
                "encrypted and we don't have the decryption keys.",
                "Show the HTTPS requests for the /login page. The traffic is "
                "encrypted and we don't have the keys to decrypt it.",
            ),
            (),
            "HTTPS requests for the /login page when the traffic is encrypted "
            "and no decryption keys are available; the URL path is inside TLS.",
        ),
        ModelNonReadyCase(
            "ne-busy-sources",
            "test",
            "not_expressible",
            (
                "Any source address that sent more than 100 packets total in "
                "this capture - I want all their packets.",
                "Filter down to every packet sent by source addresses whose "
                "total packet count in the whole capture is above 100.",
            ),
            (),
            "All packets from any source that sent more than 100 packets in "
            "total; needs a per-source count across packets.",
        ),
        ModelNonReadyCase(
            "ne-lost-packets",
            "test",
            "not_expressible",
            (
                "Looking for the packets that got lost before they ever "
                "reached the capture point.",
                "Can you pull up the actual packets that got dropped before "
                "arriving at the capture point?",
            ),
            (),
            "The lost packets themselves, which never reached the capture; "
            "they are absent from the capture file.",
        ),
        ModelNonReadyCase(
            "ne-average-ttl",
            "test",
            "not_expressible",
            (
                "Work out the average IPv4 TTL per destination address for me.",
                "Group the IPv4 packets by the IP they're sent to and give me "
                "the mean TTL for each group.",
            ),
            (),
            "The average IPv4 TTL for each destination address; an aggregate "
            "statistic, not a packet set.",
        ),
        ModelNonReadyCase(
            "ne-port-scan",
            "test",
            "not_expressible",
            (
                "Whoever's running a port scan - same source hitting a ton of "
                "different ports in a short burst - I want every probe packet "
                "they sent.",
                "Filter for all probe packets sent by any scanner, where a "
                "scanner is a single source that probes many different ports "
                "over a short period.",
            ),
            (),
            "Packets that belong to a port scan, defined as one source probing "
            "many ports; behaviour across packets with no per-packet field. "
            "Contestable against single-packet heuristics.",
        ),
        ModelNonReadyCase(
            "ne-block-private",
            "test",
            "not_expressible",
            (
                "Block all traffic coming from 10.0.0.0/8 at the firewall.",
                "Can you set up the firewall to block everything sourced from "
                "10.0.0.0/8?",
            ),
            (),
            "Block every packet from 10.0.0.0/8 at the firewall; an "
            "enforcement action, not a selection.",
        ),
        ModelNonReadyCase(
            "ne-sort-port",
            "test",
            "not_expressible",
            (
                "Sort these packets by destination port, highest to lowest.",
                "Can you order the capture's packets by destination port in "
                "descending order?",
            ),
            (),
            "Sort the packets by destination port, highest first; ordering, "
            "not selection.",
        ),
        ModelNonReadyCase(
            "ne-finance-user",
            "test",
            "not_expressible",
            (
                "Finance team's traffic, all of it, from any of them - just "
                "know they don't have fixed IPs or their own subnet since they "
                "rotate shared machines, and this is a plain capture with no "
                "process or login info, so it has to be tied to the actual "
                "person.",
                "I need every packet that any member of the finance group "
                "generated. They share and rotate computers so there's no "
                "fixed IP or subnet, and this ordinary capture carries no "
                "process or logged-in user information; we can only pick them "
                "out by who they are.",
            ),
            (),
            "Packets generated by someone on the finance team, who have no "
            "fixed addresses; user identity is not in the packets.",
        ),
    )
