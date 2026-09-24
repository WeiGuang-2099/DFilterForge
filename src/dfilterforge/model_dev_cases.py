"""Ready evaluator cases of the dev split, in model item order.

Each case pairs two independently worded requests with a canonical typed
target, its reference filter, an authored near-wrong mutation filter and
recipe and witness memberships authored apart from both filters.
scripts/probe_adequacy.py checks the memberships with tshark.
"""

from __future__ import annotations

from dfilterforge.benchmark import ACK_RECIPES
from dfilterforge.benchmark import DNS_RECIPES
from dfilterforge.benchmark import UDP_RECIPES
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.model_cases import ModelSemanticCase
from dfilterforge.model_cases import oracle
from dfilterforge.model_cases import predicate
from dfilterforge.witnesses import A_QUERY_WITNESSES
from dfilterforge.witnesses import ACK_WITNESSES
from dfilterforge.witnesses import DNS_WITNESSES
from dfilterforge.witnesses import FIN_WITNESSES
from dfilterforge.witnesses import HTTPS_WITNESSES
from dfilterforge.witnesses import PRIVATE_WITNESSES
from dfilterforge.witnesses import RESPONSE_WITNESSES
from dfilterforge.witnesses import TTL_BELOW_64_WITNESSES
from dfilterforge.witnesses import UDP_WITNESSES

_RESPONSE_RECIPES = frozenset({"udp-response", "udp-nxdomain"})

_TTL_AT_MOST_1 = predicate("ip.ttl", Operator.LE, 1)
_TTL_AT_LEAST_64 = predicate("ip.ttl", Operator.GE, 64)
_TO_PRIVATE = predicate("ip.dst", Operator.IN_SUBNET, "10.0.0.0/8")
_SYN = predicate("tcp.flags.syn", Operator.EQ, True)
_ACK = predicate("tcp.flags.ack", Operator.EQ, True)
_RST = predicate("tcp.flags.reset", Operator.EQ, True)
_FIN = predicate("tcp.flags.fin", Operator.EQ, True)
_QUERY = predicate("dns.flags.response", Operator.EQ, False)
_RESPONSE = predicate("dns.flags.response", Operator.EQ, True)
_QTYPE_A = predicate("dns.qry.type", Operator.EQ, 1)
_QTYPE_AAAA = predicate("dns.qry.type", Operator.EQ, 28)


def ready_dev_cases() -> tuple[ModelSemanticCase, ...]:
    """Returns the ready dev compositions."""
    return (
        ModelSemanticCase(
            "tcp-expiring-ttl",
            "dev",
            (
                "Keep only TCP packets whose IPv4 TTL is 1 or lower.",
                "Find expiring IPv4 traffic carried by TCP, using TTL at "
                "most one.",
            ),
            All(children=(predicate("tcp"), _TTL_AT_MOST_1)),
            "tcp && ip.ttl <= 1",
            "ip.ttl <= 1 && (tcp || udp)",
            oracle(
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
            All(children=(predicate("udp"), _TTL_AT_MOST_1)),
            "udp && ip.ttl <= 1",
            "ip.ttl <= 1 && (udp || tcp)",
            oracle(
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
            All(children=(_ACK, predicate("tcp.dstport", Operator.EQ, 443))),
            "tcp.flags.ack == 1 && tcp.dstport == 443",
            "tcp.flags.ack == 1 && tcp",
            oracle(
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
            All(children=(_QUERY, _QTYPE_A)),
            "dns.flags.response == 0 && dns.qry.type == 1",
            "dns.flags.response == 0 && dns",
            oracle(
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
            AnyOf(
                children=(
                    predicate("tcp.flags.fin", Operator.EQ, True),
                    _RESPONSE,
                )
            ),
            "tcp.flags.fin == 1 || dns.flags.response == 1",
            "dns && dns.flags.response == 1",
            oracle(
                {"fin", *_RESPONSE_RECIPES},
                _RESPONSE_RECIPES,
                witnesses=(
                    RESPONSE_WITNESSES | FIN_WITNESSES,
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
                    predicate("udp"),
                    Not(child=predicate("dns")),
                    _TO_PRIVATE,
                )
            ),
            "udp && !dns && ip.dst == 10.0.0.0/8",
            "udp && !dns && ip",
            oracle(
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
                            _SYN,
                            predicate("tcp.flags.ece", Operator.EQ, True),
                        )
                    ),
                    _TTL_AT_MOST_1,
                )
            ),
            "(tcp.flags.syn == 1 && tcp.flags.ece == 1) || ip.ttl <= 1",
            "tcp && tcp.flags.syn == 1 && tcp.flags.ece == 1",
            oracle(
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
            AnyOf(
                children=(
                    _QTYPE_AAAA,
                    predicate("dns.flags.rcode", Operator.EQ, 3),
                )
            ),
            "dns.qry.type == 28 || dns.flags.rcode == 3",
            "dns && dns.qry.type == 28",
            oracle(
                {"udp-aaaa", "udp-nxdomain"},
                {"udp-aaaa"},
                witnesses=(set(), set()),
            ),
        ),
        ModelSemanticCase(
            "reset-or-fin",
            "dev",
            (
                "I need every TCP segment that has the RST flag or the FIN "
                "flag set - either one qualifies. It doesn't matter if ACK, "
                "ECE, or other flags are on at the same time, like RST+ACK or "
                "FIN+ACK, and there's no restriction on port or direction.",
                "I need all TCP segments where RST is set, FIN is set, or "
                "both, on any port and in any direction. Don't drop ones that "
                "also carry ACK, ECE or other flags.",
            ),
            AnyOf(children=(_RST, _FIN)),
            "tcp.flags.reset == 1 || tcp.flags.fin == 1",
            "tcp.flags == 4 || tcp.flags == 1",
            # Only the bare FIN has a whole flag byte of 1 or 4.
            oracle(
                {"reset", "fin"},
                {"fin"},
                witnesses=(FIN_WITNESSES | {"ece-syn-reset"}, set()),
            ),
        ),
        ModelSemanticCase(
            "udp-normal-ttl",
            "dev",
            (
                "Pull all UDP packets with an IPv4 TTL of 64 or higher, any "
                "port, any upper-layer protocol - DNS and mDNS packets count "
                "too. Anything at TTL 63 or below should be left out.",
                "Can you find all UDP traffic with an IPv4 TTL of at least 64? "
                "Include DNS and mDNS too, don't narrow it by port or "
                "upper-layer protocol, and drop anything at TTL 63 or below.",
            ),
            All(children=(predicate("udp"), _TTL_AT_LEAST_64)),
            "udp && ip.ttl >= 64",
            "udp && ip.ttl > 64",
            oracle(
                UDP_RECIPES - {"udp-lowttl"},
                set(),
                witnesses=(
                    UDP_WITNESSES - TTL_BELOW_64_WITNESSES,
                    {"udp-ttl-128"},
                ),
            ),
        ),
        ModelSemanticCase(
            "private-destination",
            "dev",
            (
                "Grab everything headed to an address inside 10.0.0.0/8, no "
                "matter the protocol - TCP, UDP, DNS all count. If only the "
                "source address falls in that range but the destination "
                "doesn't, leave it out.",
                "I need all traffic going to destination addresses in "
                "10.0.0.0/8, any protocol. A packet sourced from 10.0.0.0/8 "
                "but sent to an address outside that range doesn't qualify.",
            ),
            _TO_PRIVATE,
            "ip.dst == 10.0.0.0/8",
            "ip.addr == 10.0.0.0/8",
            oracle(
                {"udp-private-destination"},
                {"udp-private-destination", "udp-private"},
                witnesses=(
                    PRIVATE_WITNESSES - {"udp-from-far-private"},
                    PRIVATE_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "dns-error-responses",
            "dev",
            (
                "I want DNS responses that came back with anything other than "
                "a successful result - NXDOMAIN, SERVFAIL, any error code "
                "counts, but only responses, not queries. Include mDNS "
                "responses too, regardless of transport.",
                "Pull all failed DNS responses: any response code except "
                "NOERROR, including NXDOMAIN and SERVFAIL. Responses only, not "
                "queries, with mDNS responses included and no restriction on "
                "transport.",
            ),
            All(
                children=(
                    _RESPONSE,
                    Not(child=predicate("dns.flags.rcode", Operator.EQ, 0)),
                )
            ),
            "dns.flags.response == 1 && !(dns.flags.rcode == 0)",
            "dns.flags.rcode == 3",
            oracle(
                {"udp-nxdomain"},
                {"udp-nxdomain"},
                witnesses=({"dns-servfail"}, set()),
            ),
        ),
    )
