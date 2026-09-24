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
                "Dig up every TCP packet sourced from 192.0.2.0/24 "
                "(TEST-NET-1), regardless of port or which flags are set -- "
                "DNS running over TCP counts too. Base it purely on the source "
                "address; if only the destination lands in that range, it "
                "doesn't count.",
                "Pull all TCP traffic originating from 192.0.2.0/24 "
                "(TEST-NET-1) regardless of port or flags, TCP-based DNS "
                "included; ignore packets where only the destination is in "
                "that range.",
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
                "Track down the UDP packets coming from 192.0.2.0/24 "
                "(TEST-NET-1) as the source -- DNS, mDNS, plain UDP, all of it "
                "counts, any port or TTL. Base this on source address alone; "
                "packets that only have the destination in that range don't "
                "count.",
                "Give me every UDP packet sent from 192.0.2.0/24 (TEST-NET-1), "
                "whatever the port, TTL, or application (DNS, mDNS, or "
                "otherwise); packets merely addressed to that range should be "
                "left out.",
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
                "Can you get me IPv4 packets where either end -- source or "
                "destination -- falls inside 10.0.0.0/8? TCP, UDP, DNS, any "
                "port, all count.",
                "Pull all IPv4 traffic to or from 10.0.0.0/8, with TCP, UDP, "
                "and DNS all included and any port number allowed.",
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
                "Surface IPv4 packets whose source sits in either 192.0.2.0/24 "
                "(TEST-NET-1) or 10.0.0.0/8 -- any protocol works. Both ranges "
                "are source-only checks, so packets that only have the "
                "destination in one of those blocks don't count.",
                "Give me all IPv4 traffic originating from 192.0.2.0/24 or "
                "10.0.0.0/8, whatever the protocol; ignore packets that are "
                "merely destined for either range.",
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
                "Let's see the TCP segments with the ACK flag set -- it's fine "
                "if SYN, FIN, RST or other flags are also set -- but leave out "
                "anything sourced from 192.0.2.0/24 (TEST-NET-1). As long as "
                "the source isn't in that range it's in; destination and port "
                "don't matter.",
                "Which TCP packets have ACK set but don't come from TEST-NET-1 "
                "(192.0.2.0/24)? Packets carrying SYN, FIN, RST or other flags "
                "together with ACK still count, and I don't care about "
                "destination or port.",
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
                "Pull up the UDP packets whose destination port is above 5353 "
                "and whose source address is in 192.0.2.0/24 (TEST-NET-1) -- "
                "doesn't matter if it's DNS or what the TTL is.",
                "Which UDP packets sourced from TEST-NET-1 (192.0.2.0/24) are "
                "going to a destination port above 5353, not counting 5353 "
                "itself? Whether they're DNS and what the TTL is are both "
                "irrelevant.",
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
                "Pull the UDP packets where the destination port is above 5353 "
                "and the TTL is at least 64 — don't filter by source address, "
                "and it doesn't matter whether it's DNS traffic or not.",
                "Find UDP packets whose destination port is above 5353 and "
                "whose TTL is at least 64, from any source, whether or not "
                "they are DNS.",
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
                "I need UDP packets that satisfy all three of these at once: "
                "destination port above 5353, source address inside "
                "192.0.2.0/24, and a TTL of at least 64. Whether it's DNS "
                "doesn't matter.",
                "I'm looking for UDP coming from the TEST-NET-1 block "
                "(192.0.2.0/24) to destination ports above 5353, only where "
                "the TTL is at least 64, DNS or otherwise.",
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
                "Show me the UDP traffic headed to a destination port below "
                "5353 where the DNS question section is asking for an A record "
                "- that covers A queries as well as any response whose "
                "question was A. Judge it as DNS by what's actually in the "
                "packet rather than insisting on port 53, and don't carve mDNS "
                "out separately, since it still just needs to clear that same "
                "port limit.",
                "Find UDP packets going to a destination port below 5353 that "
                "carry a DNS question for an A record, whether they are "
                "queries or responses. Recognize DNS by the packet content "
                "rather than by port 53, and don't exclude mDNS separately.",
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
                "Grab the UDP packets going to port 53 where the source port "
                "isn't 53 as well — exclude the ones where both ends use port "
                "53. Destination address and content don't matter.",
                "Give me UDP traffic sent to destination port 53 where the "
                "source port is not 53, leaving out packets that have 53 on "
                "both ends, regardless of destination address or what's "
                "inside.",
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
                "Show me only the UDP DNS responses with a NOERROR response "
                "code that go from source port 53 to a destination port other "
                "than 53. Leave out NXDOMAIN, SERVFAIL, and any other error "
                "responses, skip packets where both ports are 53, and skip DNS "
                "queries that happen to go out from port 53 too.",
                "Which UDP packets from source port 53 to a non-53 destination "
                "port are DNS responses with a NOERROR response code? Error "
                "answers like NXDOMAIN and SERVFAIL don't count, nor do "
                "packets where both ports are 53, nor queries originating from "
                "port 53.",
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
                "Give me everything that meets either condition: DNS traffic "
                "where the question asks about an AAAA record — query or "
                "response, any port, any transport, mDNS included — or any UDP "
                "packet at all coming from port 53, whether it's a query, a "
                "successful answer, or an error answer, regardless of the "
                "destination port.",
                "Which packets are either DNS messages asking about an AAAA "
                "record, queries or responses on any port or transport and "
                "including mDNS, or UDP packets from source port 53 of any "
                "sort (queries, successful responses and error responses "
                "alike) going to any destination port?",
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
                "Filter down to the TCP traffic heading to port 443 where the "
                "SYN flag isn't set — ACK, FIN, RST, ECE, whatever else can be "
                "anything. Don't include traffic coming from port 443 itself.",
                "Which TCP packets headed to destination port 443 have the SYN "
                "flag cleared? Flags such as ACK, FIN, RST and ECE may be set "
                "or not, and packets coming from port 443 should not be "
                "included.",
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
                "Pull the TCP packets headed to port 443 that have the SYN "
                "flag set but not the ACK flag — it's fine if ECE or CWR is "
                "set too. Exclude SYNs that come from port 443.",
                "Pull out TCP packets toward destination port 443 where SYN is "
                "on and ACK is off, even when ECE, CWR or other flags are also "
                "set; SYNs sent from port 443 should be left out.",
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
                "Get me the TCP packets going to port 443 where either the SYN "
                "flag or the RST flag is set, or both — having ACK or ECE set "
                "too is fine. Skip anything originating from port 443.",
                "Which TCP packets headed to destination port 443 carry at "
                "least one of the SYN or RST flags? Other flags such as ACK "
                "and ECE may also be set, and packets coming from port 443 "
                "should be excluded.",
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
                "I want the TCP packets whose destination port isn't 443 — "
                "that includes the return traffic coming back from port 443 to "
                "somewhere else. Leave UDP out of it.",
                "Find TCP packets whose destination port is anything other "
                "than 443, including replies sent from port 443 to other "
                "ports; no UDP.",
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
