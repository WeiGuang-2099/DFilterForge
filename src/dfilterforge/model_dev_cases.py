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
from dfilterforge.witnesses import RESPONSE_WITNESSES
from dfilterforge.witnesses import UDP_WITNESSES


def ready_dev_cases() -> tuple[ModelSemanticCase, ...]:
    """Returns the ready dev compositions."""
    responses = frozenset({"udp-response", "udp-nxdomain"})
    ttl_low = predicate("ip.ttl", Operator.LE, 1)
    destination_private = predicate("ip.dst", Operator.IN_SUBNET, "10.0.0.0/8")
    syn_bit = predicate("tcp.flags.syn", Operator.EQ, True)
    ack_bit = predicate("tcp.flags.ack", Operator.EQ, True)
    query = predicate("dns.flags.response", Operator.EQ, False)
    response = predicate("dns.flags.response", Operator.EQ, True)
    qtype_a = predicate("dns.qry.type", Operator.EQ, 1)
    qtype_aaaa = predicate("dns.qry.type", Operator.EQ, 28)

    return (
        ModelSemanticCase(
            "tcp-expiring-ttl",
            "dev",
            (
                "Keep only TCP packets whose IPv4 TTL is 1 or lower.",
                "Find expiring IPv4 traffic carried by TCP, using TTL at "
                "most one.",
            ),
            All(children=(predicate("tcp"), ttl_low)),
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
            All(children=(predicate("udp"), ttl_low)),
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
            All(children=(ack_bit, predicate("tcp.dstport", Operator.EQ, 443))),
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
            All(children=(query, qtype_a)),
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
                    response,
                )
            ),
            "tcp.flags.fin == 1 || dns.flags.response == 1",
            "dns && dns.flags.response == 1",
            oracle(
                {"fin", *responses},
                responses,
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
                    destination_private,
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
                            syn_bit,
                            predicate("tcp.flags.ece", Operator.EQ, True),
                        )
                    ),
                    ttl_low,
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
                    qtype_aaaa,
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
    )
