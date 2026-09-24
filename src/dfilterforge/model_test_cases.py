"""Ready evaluator cases of the test split, in model item order.

Each case pairs two independently worded requests with a canonical typed
target, its reference filter, an authored near-wrong mutation filter and
recipe and witness memberships authored apart from both filters.
scripts/probe_adequacy.py checks the memberships with tshark.
"""

from __future__ import annotations

from dfilterforge.benchmark import ACK_RECIPES
from dfilterforge.benchmark import HIGH_UDP_PORT_RECIPES
from dfilterforge.benchmark import RECIPES
from dfilterforge.benchmark import SYN_RECIPES
from dfilterforge.benchmark import TCP_RECIPES
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
from dfilterforge.witnesses import CLIENT_WITNESSES
from dfilterforge.witnesses import HIGH_PORT_WITNESSES
from dfilterforge.witnesses import HTTPS_WITNESSES
from dfilterforge.witnesses import PRIVATE_WITNESSES
from dfilterforge.witnesses import SOURCE_53_WITNESSES
from dfilterforge.witnesses import SYN_WITNESSES
from dfilterforge.witnesses import TCP_WITNESSES
from dfilterforge.witnesses import TTL_BELOW_64_WITNESSES
from dfilterforge.witnesses import UDP_WITNESSES


def ready_test_cases() -> tuple[ModelSemanticCase, ...]:
    """Returns the ready test compositions."""
    responses = frozenset({"udp-response", "udp-nxdomain"})
    source_testnet = frozenset(RECIPES) - {"udp-private", "tcp-reverse"}
    ttl_normal = predicate("ip.ttl", Operator.GE, 64)
    source_test = predicate("ip.src", Operator.IN_SUBNET, "192.0.2.0/24")
    source_private = predicate("ip.src", Operator.IN_SUBNET, "10.0.0.0/8")
    destination_private = predicate("ip.dst", Operator.IN_SUBNET, "10.0.0.0/8")
    syn_bit = predicate("tcp.flags.syn", Operator.EQ, True)
    ack_bit = predicate("tcp.flags.ack", Operator.EQ, True)
    reset_bit = predicate("tcp.flags.reset", Operator.EQ, True)
    qtype_a = predicate("dns.qry.type", Operator.EQ, 1)
    qtype_aaaa = predicate("dns.qry.type", Operator.EQ, 28)
    udp_high = predicate("udp.dstport", Operator.GT, 5353)

    return (
        ModelSemanticCase(
            "tcp-source-testnet",
            "test",
            (
                "Show TCP packets sourced from TEST-NET-1, 192.0.2.0/24.",
                "Find TCP traffic whose IPv4 source belongs to the "
                "192.0.2.0/24 documentation subnet.",
            ),
            All(children=(predicate("tcp"), source_test)),
            "tcp && ip.src == 192.0.2.0/24",
            "tcp && ip",
            oracle(
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
            All(children=(predicate("udp"), source_test)),
            "udp && ip.src == 192.0.2.0/24",
            "udp && ip",
            oracle(
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
            oracle(
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
            oracle(
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
            oracle(
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
            oracle(
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
            oracle(
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
            oracle(
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
                    predicate("udp.dstport", Operator.LT, 5353),
                    qtype_a,
                )
            ),
            "udp.dstport < 5353 && dns.qry.type == 1",
            "udp && udp.dstport < 5353",
            oracle(
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
                    predicate("udp.dstport", Operator.EQ, 53),
                    predicate("udp.srcport", Operator.NE, 53),
                )
            ),
            "udp.dstport == 53 && udp.srcport != 53",
            "udp && udp.dstport == 53",
            oracle(
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
                    predicate("udp.srcport", Operator.EQ, 53),
                    predicate("udp.dstport", Operator.NE, 53),
                    predicate("dns.flags.rcode", Operator.EQ, 0),
                )
            ),
            "udp.srcport == 53 && udp.dstport != 53 && dns.flags.rcode == 0",
            "udp && udp.srcport == 53 && udp.dstport != 53",
            oracle(
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
            AnyOf(
                children=(qtype_aaaa, predicate("udp.srcport", Operator.EQ, 53))
            ),
            "dns.qry.type == 28 || udp.srcport == 53",
            "dns && udp.srcport == 53",
            oracle(
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
                    predicate("tcp.dstport", Operator.EQ, 443),
                    predicate("tcp.flags.syn", Operator.EQ, False),
                )
            ),
            "tcp.dstport == 443 && tcp.flags.syn == 0",
            "tcp && tcp.flags.syn == 0",
            oracle(
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
                    predicate("tcp.dstport", Operator.EQ, 443),
                    syn_bit,
                    predicate("tcp.flags.ack", Operator.EQ, False),
                )
            ),
            "tcp.dstport == 443 && tcp.flags.syn == 1 && tcp.flags.ack == 0",
            "tcp && tcp.flags.syn == 1 && tcp.flags.ack == 0",
            oracle(
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
                    predicate("tcp.dstport", Operator.EQ, 443),
                    AnyOf(children=(syn_bit, reset_bit)),
                )
            ),
            "tcp.dstport == 443 && "
            "(tcp.flags.syn == 1 || tcp.flags.reset == 1)",
            "(tcp && tcp.flags.syn == 1) || tcp.flags.reset == 1",
            oracle(
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
            predicate("tcp.dstport", Operator.NE, 443),
            "tcp.dstport != 443",
            "tcp.dstport == 53",
            oracle(
                {"tcp-query", "tcp-http"},
                {"tcp-query"},
                witnesses=(TCP_WITNESSES - HTTPS_WITNESSES, set()),
            ),
        ),
    )
