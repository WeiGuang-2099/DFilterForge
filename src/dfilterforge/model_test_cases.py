"""Ready evaluator cases of the test split, in model item order.

Each case pairs two independently worded requests with a canonical typed
target, its reference filter, an authored near-wrong mutation filter and
recipe and witness memberships authored apart from both filters.
scripts/probe_adequacy.py checks the memberships with tshark.
"""

# A case table is data. Splitting it by line count would scatter one
# split's cases across modules, so the size check is off for this file.
# pylint: disable=too-many-lines

from __future__ import annotations

from dfilterforge.benchmark import ACK_RECIPES
from dfilterforge.benchmark import DNS_RECIPES
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
from dfilterforge.witnesses import DNS_WITNESSES
from dfilterforge.witnesses import FIN_WITNESSES
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

_RESPONSE_RECIPES = frozenset({"udp-response", "udp-nxdomain"})
_TESTNET_SOURCE_RECIPES = frozenset(RECIPES) - {"udp-private", "tcp-reverse"}
# TCP recipes that use port 443 at one end.
_HTTPS_RECIPES = TCP_RECIPES - {"tcp-query", "tcp-http"}
# Witnesses a server sends from port 443.
_FROM_HTTPS_WITNESSES = frozenset(
    {
        "server-ack",
        "server-ack-next",
        "keepalive-server-ack",
        "server-syn",
        "server-fin-ack",
    }
)
# UDP witnesses sent to destination port 53 or 5353.
_TO_DNS_PORT_WITNESSES = frozenset(
    {
        "dns-mx-query",
        "dns-response-53-to-53",
        "dns-query-from-low-port",
        "dns-to-private",
        "mdns-response",
    }
)
# Witnesses with neither endpoint in 192.0.2.0/24.
_OFF_TESTNET_WITNESSES = frozenset(
    {
        "udp-from-far-private",
        "tcp-to-private",
        "tcp-near-testnet",
        "udp-near-testnet",
    }
)

_TTL_AT_MOST_1 = predicate("ip.ttl", Operator.LE, 1)
_TTL_AT_LEAST_64 = predicate("ip.ttl", Operator.GE, 64)
_FROM_TESTNET = predicate("ip.src", Operator.IN_SUBNET, "192.0.2.0/24")
_FROM_PRIVATE = predicate("ip.src", Operator.IN_SUBNET, "10.0.0.0/8")
_TO_PRIVATE = predicate("ip.dst", Operator.IN_SUBNET, "10.0.0.0/8")
_TESTNET_ENDPOINT = predicate("ip.addr", Operator.IN_SUBNET, "192.0.2.0/24")
_SYN = predicate("tcp.flags.syn", Operator.EQ, True)
_ACK = predicate("tcp.flags.ack", Operator.EQ, True)
_RST = predicate("tcp.flags.reset", Operator.EQ, True)
_FIN = predicate("tcp.flags.fin", Operator.EQ, True)
_ECE = predicate("tcp.flags.ece", Operator.EQ, True)
_CWR = predicate("tcp.flags.cwr", Operator.EQ, True)
_QUERY = predicate("dns.flags.response", Operator.EQ, False)
_RESPONSE = predicate("dns.flags.response", Operator.EQ, True)
_NXDOMAIN = predicate("dns.flags.rcode", Operator.EQ, 3)
_QTYPE_A = predicate("dns.qry.type", Operator.EQ, 1)
_QTYPE_AAAA = predicate("dns.qry.type", Operator.EQ, 28)
_UDP_ABOVE_5353 = predicate("udp.dstport", Operator.GT, 5353)


def ready_test_cases() -> tuple[ModelSemanticCase, ...]:
    """Returns the ready test compositions."""
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
            All(children=(predicate("tcp"), _FROM_TESTNET)),
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
            All(children=(predicate("udp"), _FROM_TESTNET)),
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
            AnyOf(children=(_FROM_PRIVATE, _TO_PRIVATE)),
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
            AnyOf(children=(_FROM_TESTNET, _FROM_PRIVATE)),
            "ip.src == 192.0.2.0/24 || ip.src == 10.0.0.0/8",
            "ip && ip.src == 192.0.2.0/24",
            oracle(
                frozenset(RECIPES) - {"tcp-reverse"},
                _TESTNET_SOURCE_RECIPES,
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
            All(children=(_ACK, Not(child=_FROM_TESTNET))),
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
            All(children=(_UDP_ABOVE_5353, _FROM_TESTNET)),
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
            All(children=(_UDP_ABOVE_5353, _TTL_AT_LEAST_64)),
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
            All(children=(_UDP_ABOVE_5353, _FROM_TESTNET, _TTL_AT_LEAST_64)),
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
                    _QTYPE_A,
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
                _RESPONSE_RECIPES,
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
                children=(
                    _QTYPE_AAAA,
                    predicate("udp.srcport", Operator.EQ, 53),
                )
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
                    _SYN,
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
                    AnyOf(children=(_SYN, _RST)),
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
        ModelSemanticCase(
            "tcp-from-https-port",
            "test",
            (
                "Can you pull every TCP packet sent from port 443, whatever "
                "flags it's carrying? Judge it purely by source port, not by "
                "IP address - traffic going to port 443 from some other source "
                "port doesn't count.",
                "Which TCP packets have a source port of 443? Any flags are "
                "fine and IP addresses don't matter, but traffic whose "
                "destination port is 443 while the source port is something "
                "else should be left out.",
            ),
            predicate("tcp.srcport", Operator.EQ, 443),
            "tcp.srcport == 443",
            "tcp.port == 443",
            oracle(
                set(),
                _HTTPS_RECIPES,
                witnesses=(
                    _FROM_HTTPS_WITNESSES,
                    HTTPS_WITNESSES | _FROM_HTTPS_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "tcp-without-port-443",
            "test",
            (
                "Filter out anything touching port 443 on either end and give "
                "me the rest of the TCP traffic - if source or destination is "
                "443, it's excluded. UDP doesn't belong in this one.",
                "Give me the TCP packets where neither the source port nor the "
                "destination port is 443; if either end uses 443, drop it. No "
                "UDP.",
            ),
            All(
                children=(
                    predicate("tcp"),
                    Not(child=predicate("tcp.port", Operator.EQ, 443)),
                )
            ),
            "tcp && !(tcp.port == 443)",
            "tcp && tcp.dstport != 443",
            oracle(
                {"tcp-query", "tcp-http"},
                {"tcp-query", "tcp-http"},
                witnesses=(
                    {"tcp-to-private"},
                    _FROM_HTTPS_WITNESSES | {"tcp-to-private"},
                ),
            ),
        ),
        ModelSemanticCase(
            "fin-from-https-port",
            "test",
            (
                "Looking for FIN segments sent from source port 443 - FIN+ACK "
                "counts too. Go by source port only, not IP address; a FIN "
                "headed to port 443 from a different source port doesn't "
                "qualify.",
                "I want every TCP segment with FIN set whose source port is "
                "443, whether or not ACK is also set. Judge by the port alone; "
                "a FIN sent to destination port 443 from some other source "
                "port doesn't belong.",
            ),
            All(children=(_FIN, predicate("tcp.srcport", Operator.EQ, 443))),
            "tcp.flags.fin == 1 && tcp.srcport == 443",
            "tcp.flags.fin == 1",
            oracle(
                set(),
                {"fin"},
                witnesses=(FIN_WITNESSES, FIN_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "ece-any-segment",
            "test",
            (
                "Need every TCP segment with the ECE flag on, no matter what "
                "else rides along with it - SYN, ACK, RST, CWR, any "
                "combination is fine. A segment with only CWR and no ECE "
                "doesn't count, and there's no restriction on port or "
                "direction.",
                "Pull all TCP segments carrying the ECE flag, regardless of "
                "any other flags (SYN, ACK, RST, CWR) and regardless of port "
                "or direction. Leave out segments that have CWR without ECE.",
            ),
            _ECE,
            "tcp.flags.ece == 1",
            "tcp.flags.ece == 1 && tcp.flags.syn == 1",
            oracle(
                {"ecn-syn"},
                {"ecn-syn"},
                witnesses=({"ece-ack", "ece-syn-reset"}, set()),
            ),
        ),
        ModelSemanticCase(
            "cwr-any-segment",
            "test",
            (
                "Get me all TCP segments with the CWR flag set, whether or not "
                "SYN, ECE, or anything else is also on. One with ECE but no "
                "CWR shouldn't show up, and there's no port or direction "
                "limit.",
                "Which TCP segments have Congestion Window Reduced (CWR) set? "
                "Ignore any other flags such as SYN or ECE, and any port or "
                "direction; skip segments that have ECE without CWR.",
            ),
            _CWR,
            "tcp.flags.cwr == 1",
            "tcp.flags.ece == 1",
            oracle(
                {"ecn-syn"},
                {"ecn-syn"},
                witnesses=({"cwr-syn"}, {"ece-ack", "ece-syn-reset"}),
            ),
        ),
        ModelSemanticCase(
            "syn-without-ece",
            "test",
            (
                "I want SYN segments that don't have ECE set - SYN-ACK is "
                "included, and it's fine if CWR is also set as long as ECE "
                "isn't. Anything with both SYN and ECE together should be "
                "excluded; no port or direction restriction.",
                "List all TCP segments that have the SYN flag set but not the "
                "ECE flag, SYN-ACKs included, on any port and in either "
                "direction. A SYN with CWR but no ECE still counts; any SYN "
                "carrying ECE should be dropped.",
            ),
            All(
                children=(
                    _SYN,
                    predicate("tcp.flags.ece", Operator.EQ, False),
                )
            ),
            "tcp.flags.syn == 1 && tcp.flags.ece == 0",
            "tcp.flags.syn == 1 && tcp.flags.cwr == 0",
            oracle(
                SYN_RECIPES - {"ecn-syn"},
                SYN_RECIPES - {"ecn-syn"},
                witnesses=(SYN_WITNESSES, SYN_WITNESSES - {"cwr-syn"}),
            ),
        ),
        ModelSemanticCase(
            "control-segments",
            "test",
            (
                "I'm after TCP segments that have at least one of SYN, FIN, or "
                "RST set - any one of the three qualifies. It doesn't matter "
                "if ACK, ECE, or CWR is also present, and there's no port or "
                "direction limit.",
                "Which TCP segments carry SYN, FIN or RST (any one or more of "
                "them)? Other flags like ACK, ECE or CWR don't matter, and "
                "neither do port or direction.",
            ),
            AnyOf(children=(_SYN, _FIN, _RST)),
            "tcp.flags.syn == 1 || tcp.flags.fin == 1 || tcp.flags.reset == 1",
            "tcp.flags.syn == 1 || tcp.flags.fin == 1",
            oracle(
                SYN_RECIPES | {"reset", "fin"},
                SYN_RECIPES | {"fin"},
                witnesses=(
                    SYN_WITNESSES | FIN_WITNESSES | {"ece-syn-reset"},
                    SYN_WITNESSES | FIN_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "https-no-syn-no-reset",
            "test",
            (
                "For traffic headed to port 443, I only want the segments "
                "where neither SYN nor RST is set - ACK, FIN, ECE, whatever "
                "else, none of that matters. Judge it by destination port "
                "only, not IP; traffic coming from port 443 to somewhere else "
                "doesn't count.",
                "Which TCP segments sent to destination port 443 have both SYN "
                "and RST clear? I don't care about ACK, FIN, ECE or other "
                "flags, or about IP addresses; segments with source port 443 "
                "and a different destination port should be left out.",
            ),
            All(
                children=(
                    predicate("tcp.dstport", Operator.EQ, 443),
                    Not(child=AnyOf(children=(_SYN, _RST))),
                )
            ),
            "tcp.dstport == 443 && "
            "!(tcp.flags.syn == 1 || tcp.flags.reset == 1)",
            "tcp.port == 443 && !(tcp.flags.syn == 1 || tcp.flags.reset == 1)",
            oracle(
                _HTTPS_RECIPES - SYN_RECIPES - {"reset"},
                _HTTPS_RECIPES - SYN_RECIPES - {"reset"},
                witnesses=(
                    HTTPS_WITNESSES - SYN_WITNESSES - {"ece-syn-reset"},
                    (HTTPS_WITNESSES | _FROM_HTTPS_WITNESSES)
                    - SYN_WITNESSES
                    - {"ece-syn-reset"},
                ),
            ),
        ),
        ModelSemanticCase(
            "ack-without-syn",
            "test",
            (
                "Give me TCP segments with ACK set but SYN not set - RST, FIN, "
                "PSH, ECE, and whether there's a payload, none of that "
                "matters. Just leave out anything where SYN is also on, like "
                "SYN-ACK; no port or direction restriction.",
                "Give me all ACK segments that don't have SYN set, so no "
                "SYN-ACKs. Any other flags like RST, FIN, PSH or ECE are fine, "
                "with or without data, across every port and direction.",
            ),
            All(
                children=(
                    _ACK,
                    predicate("tcp.flags.syn", Operator.EQ, False),
                )
            ),
            "tcp.flags.ack == 1 && tcp.flags.syn == 0",
            "tcp.flags.ack == 1",
            oracle(
                ACK_RECIPES - {"syn-ack"},
                ACK_RECIPES,
                witnesses=(ACK_WITNESSES, ACK_WITNESSES),
            ),
        ),
        ModelSemanticCase(
            "ack-no-payload",
            "test",
            (
                "Track down TCP segments that have ACK set and carry zero "
                "bytes of payload - pure acknowledgments. SYN-ACK, RST+ACK, "
                "and FIN+ACK still qualify as long as there's no data riding "
                "along, but something like DNS over TCP with an actual payload "
                "should be excluded; no port or direction restriction.",
                "I need the data-less ACK segments: ACK set and 0 bytes of TCP "
                "payload, whether or not SYN, RST, FIN or ECE is also set "
                "(SYN-ACK, RST+ACK and FIN+ACK all qualify), across all ports "
                "and directions. Drop any segment that carries data, such as "
                "DNS over TCP.",
            ),
            All(children=(_ACK, predicate("tcp.len", Operator.EQ, 0))),
            "tcp.flags.ack == 1 && tcp.len == 0",
            "tcp.flags == 16",
            # A flag byte of exactly ACK drops the ACKs that also carry
            # RST, SYN, ECE or FIN.
            oracle(
                ACK_RECIPES - {"tcp-query"},
                {"ack", "tcp-lowttl", "tcp-reverse"},
                witnesses=(
                    ACK_WITNESSES,
                    ACK_WITNESSES - {"ece-ack", "server-fin-ack"},
                ),
            ),
        ),
        ModelSemanticCase(
            "udp-short-ttl",
            "test",
            (
                "Could you get UDP packets where the IPv4 TTL is below 64? TTL "
                "63 should show up, TTL 64 shouldn't, and TTL 0 still counts. "
                "Any port, any content.",
                "List UDP traffic whose IPv4 TTL is less than 64 (so 63 "
                "qualifies but 64 doesn't, and TTL 0 qualifies as well), "
                "regardless of port or content.",
            ),
            All(
                children=(
                    predicate("udp"),
                    predicate("ip.ttl", Operator.LT, 64),
                )
            ),
            "udp && ip.ttl < 64",
            "udp && ip.ttl < 63",
            oracle(
                {"udp-lowttl"},
                {"udp-lowttl"},
                witnesses=(
                    UDP_WITNESSES & TTL_BELOW_64_WITNESSES,
                    {"udp-ttl-0", "udp-ttl-2"},
                ),
            ),
        ),
        ModelSemanticCase(
            "ttl-between",
            "test",
            (
                "Pull packets with an IPv4 TTL strictly between 1 and 64 - 1 "
                "and 64 themselves are excluded, but 2 and 63 should be "
                "included. Any protocol, TCP and UDP both fine.",
                "Give me packets whose IPv4 TTL is above 1 and below 64, "
                "exclusive at both ends: TTL 1 and TTL 64 are out, TTL 2 and "
                "TTL 63 are in. Any protocol, TCP or UDP.",
            ),
            All(
                children=(
                    predicate("ip.ttl", Operator.GT, 1),
                    predicate("ip.ttl", Operator.LT, 64),
                )
            ),
            "ip.ttl > 1 && ip.ttl < 64",
            "ip.ttl >= 1 && ip.ttl < 64",
            oracle(
                set(),
                {"tcp-lowttl", "udp-lowttl"},
                witnesses=(
                    TTL_BELOW_64_WITNESSES - {"tcp-ttl-0", "udp-ttl-0"},
                    TTL_BELOW_64_WITNESSES - {"tcp-ttl-0", "udp-ttl-0"},
                ),
            ),
        ),
        ModelSemanticCase(
            "udp-to-dns-or-mdns-port",
            "test",
            (
                "Get me UDP traffic headed to port 53 or port 5353 - "
                "destination port only, source port doesn't matter. Just go by "
                "the port number, not the content; DNS or mDNS, queries or "
                "responses, all count.",
                "Which UDP packets have a destination port of 53 or 5353? The "
                "source port can be anything, and I don't care whether the "
                "payload is DNS or mDNS, a query or a response, only the port "
                "number.",
            ),
            predicate("udp.dstport", Operator.IN, (53, 5353)),
            "udp.dstport in {53, 5353}",
            "udp.port in {53, 5353}",
            oracle(
                {"udp-query", "udp-both-53", "udp-aaaa", "udp-mdns"},
                {
                    "udp-query",
                    "udp-both-53",
                    "udp-aaaa",
                    "udp-mdns",
                    *_RESPONSE_RECIPES,
                },
                witnesses=(
                    _TO_DNS_PORT_WITNESSES,
                    _TO_DNS_PORT_WITNESSES | SOURCE_53_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "dns-query-off-port-53",
            "test",
            (
                "Pull the unicast DNS queries that go out over UDP but aren't "
                "using destination port 53 -- judge it as DNS by content, not "
                "port. I only want the queries, not responses, and skip any "
                "mDNS queries.",
                "I'm looking for DNS lookups over UDP that are not going to "
                "destination port 53. Classify DNS by payload, not port, skip "
                "mDNS queries, and ignore any responses.",
            ),
            All(
                children=(
                    _QUERY,
                    predicate("dns"),
                    predicate("udp.dstport", Operator.NE, 53),
                )
            ),
            "dns.flags.response == 0 && dns && udp.dstport != 53",
            "dns.flags.response == 0 && udp.dstport != 53",
            oracle(
                set(),
                {"udp-mdns"},
                witnesses=(
                    {"dns-query-to-5352", "dns-query-to-private-low"},
                    {"dns-query-to-5352", "dns-query-to-private-low"},
                ),
            ),
        ),
        ModelSemanticCase(
            "dns-response-not-nxdomain",
            "test",
            (
                "I need every DNS response, mDNS included, except the ones "
                "coming back NXDOMAIN -- keep the successful answers and other "
                "errors like SERVFAIL, but leave out the queries entirely.",
                "Can you pull all DNS responses, counting mDNS responses too, "
                "but drop any that came back NXDOMAIN? Keep successful "
                "responses and other error codes like SERVFAIL, and don't "
                "include queries.",
            ),
            All(children=(_RESPONSE, Not(child=_NXDOMAIN))),
            "dns.flags.response == 1 && !(dns.flags.rcode == 3)",
            "dns.flags.response == 1 && dns.flags.rcode == 0",
            oracle(
                {"udp-response"},
                {"udp-response"},
                witnesses=(
                    RESPONSE_WITNESSES,
                    RESPONSE_WITNESSES - {"dns-servfail"},
                ),
            ),
        ),
        ModelSemanticCase(
            "dns-queries-not-a",
            "test",
            (
                "Get me the DNS queries asking for anything other than an A "
                "record -- any other record type counts, mDNS queries included "
                "-- but no responses.",
                "Pull every DNS query whose requested record type isn't A; any "
                "other type counts, and mDNS queries count too, but skip the "
                "responses.",
            ),
            All(children=(_QUERY, Not(child=_QTYPE_A))),
            "dns.flags.response == 0 && !(dns.qry.type == 1)",
            "dns.flags.response == 0 && dns.qry.type == 28",
            oracle(
                {"udp-aaaa"},
                {"udp-aaaa"},
                witnesses=({"dns-mx-query"}, set()),
            ),
        ),
        ModelSemanticCase(
            "unicast-dns-udp-queries",
            "test",
            (
                "Line up the unicast DNS queries sent over UDP, on any port -- "
                "go by the packet content to tell it's DNS, not the port. "
                "Queries only, no responses, and drop mDNS queries as well as "
                "anything running over TCP.",
                "I need the UDP-based unicast DNS queries only, whatever port "
                "they use, judging DNS by the packet itself rather than the "
                "port; no responses, no mDNS queries, no TCP DNS.",
            ),
            All(children=(predicate("udp"), predicate("dns"), _QUERY)),
            "udp && dns && dns.flags.response == 0",
            "udp && dns.flags.response == 0",
            oracle(
                {"udp-query", "udp-both-53", "udp-aaaa"},
                {"udp-query", "udp-both-53", "udp-aaaa", "udp-mdns"},
                witnesses=(
                    A_QUERY_WITNESSES | {"dns-mx-query"},
                    A_QUERY_WITNESSES | {"dns-mx-query"},
                ),
            ),
        ),
        ModelSemanticCase(
            "dns-except-nxdomain",
            "test",
            (
                "Grab all the unicast DNS traffic -- queries and responses "
                "both, whether it's over TCP or UDP, any port -- just drop the "
                "ones with an NXDOMAIN response code, and keep mDNS out of "
                "this entirely.",
                "Narrow the capture to unicast DNS messages of any kind "
                "(queries or responses, TCP or UDP, any port), dropping only "
                "those with an NXDOMAIN response code and excluding mDNS "
                "entirely.",
            ),
            All(children=(predicate("dns"), Not(child=_NXDOMAIN))),
            "dns && !(dns.flags.rcode == 3)",
            "dns && dns.flags.rcode == 0",
            # tshark 4.6.8 leaves dns.flags.rcode off queries, so the
            # mutation keeps successful responses only.
            oracle(
                DNS_RECIPES - {"udp-nxdomain"},
                {"udp-response"},
                witnesses=(
                    DNS_WITNESSES,
                    {"dns-response-53-to-53", "dns-response-to-low-port"},
                ),
            ),
        ),
        ModelSemanticCase(
            "private-source-or-expiring",
            "test",
            (
                "I want IPv4 packets that either originate from somewhere in "
                "10.0.0.0/8, or have a TTL of 1 or less (TTL 0 counts too) -- "
                "for the address part only the source matters, packets that "
                "are just headed into 10.0.0.0/8 don't count. Any protocol is "
                "fine.",
                "Give me any IPv4 traffic, of any protocol, where the sender "
                "is within 10.0.0.0/8 or the TTL is 1 or lower (0 included); "
                "don't count packets that are merely destined for 10.0.0.0/8.",
            ),
            AnyOf(children=(_FROM_PRIVATE, _TTL_AT_MOST_1)),
            "ip.src == 10.0.0.0/8 || ip.ttl <= 1",
            "ip.src == 10.0.0.0/8 || ip.ttl < 1",
            oracle(
                {"udp-private", "udp-lowttl", "tcp-lowttl"},
                {"udp-private"},
                witnesses=(
                    {"udp-from-far-private", "tcp-ttl-0", "udp-ttl-0"},
                    {"udp-from-far-private", "tcp-ttl-0", "udp-ttl-0"},
                ),
            ),
        ),
        ModelSemanticCase(
            "testnet-either-endpoint",
            "test",
            (
                "Can you isolate IPv4 traffic where either the source or the "
                "destination sits in 192.0.2.0/24 (TEST-NET-1)? Any protocol "
                "is fine.",
                "Which IPv4 packets have at least one endpoint within "
                "192.0.2.0/24, the TEST-NET-1 block? Protocol is irrelevant.",
            ),
            _TESTNET_ENDPOINT,
            "ip.addr == 192.0.2.0/24",
            "ip.src == 192.0.2.0/24",
            oracle(
                frozenset(RECIPES) - {"udp-private"},
                _TESTNET_SOURCE_RECIPES,
                witnesses=(
                    frozenset(WITNESS_NAMES) - _OFF_TESTNET_WITNESSES,
                    CLIENT_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "no-testnet-endpoint",
            "test",
            (
                "Only keep packets where neither the source nor the "
                "destination falls inside 192.0.2.0/24 (TEST-NET-1) -- if even "
                "one end lands in that range, drop it. Any protocol counts.",
                "Hide all traffic touching 192.0.2.0/24 (TEST-NET-1) at either "
                "end and give me everything else, any protocol.",
            ),
            Not(child=_TESTNET_ENDPOINT),
            "!(ip.addr == 192.0.2.0/24)",
            "!(ip.src == 192.0.2.0/24)",
            oracle(
                {"udp-private"},
                {"udp-private", "tcp-reverse"},
                witnesses=(
                    _OFF_TESTNET_WITNESSES,
                    frozenset(WITNESS_NAMES) - CLIENT_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "udp-not-from-testnet",
            "test",
            (
                "Round up the UDP traffic whose source address is outside "
                "192.0.2.0/24 (TEST-NET-1) -- only the source matters here, I "
                "don't care where the destination lands. DNS, mDNS, anything "
                "over UDP counts.",
                "Which UDP packets were not sent from TEST-NET-1 "
                "(192.0.2.0/24)? Judge only by source address (it's fine if "
                "the destination sits in that block), and include DNS, mDNS, "
                "and every other kind of UDP.",
            ),
            All(children=(predicate("udp"), Not(child=_FROM_TESTNET))),
            "udp && !(ip.src == 192.0.2.0/24)",
            "udp && ip.src == 10.0.0.0/8",
            oracle(
                {"udp-private"},
                {"udp-private"},
                witnesses=(
                    UDP_WITNESSES - CLIENT_WITNESSES,
                    {"udp-from-far-private"},
                ),
            ),
        ),
        ModelSemanticCase(
            "nondns-udp-from-testnet",
            "test",
            (
                "Sort out the UDP packets sourced from inside 192.0.2.0/24 "
                "(TEST-NET-1) that aren't unicast DNS -- go by content, not "
                "port, to decide what's DNS. mDNS doesn't count as DNS here, "
                "so keep mDNS packets from that range in.",
                "I want the non-DNS UDP traffic sent from 192.0.2.0/24 "
                "(TEST-NET-1): exclude unicast DNS as judged by the packet "
                "itself rather than by port, but keep any mDNS packets from "
                "that source, since mDNS isn't treated as DNS here.",
            ),
            All(
                children=(
                    predicate("udp"),
                    Not(child=predicate("dns")),
                    _FROM_TESTNET,
                )
            ),
            "udp && !dns && ip.src == 192.0.2.0/24",
            "udp && !dns",
            oracle(
                UDP_RECIPES - DNS_RECIPES - {"udp-private"},
                UDP_RECIPES - DNS_RECIPES,
                witnesses=(
                    (UDP_WITNESSES - DNS_WITNESSES) & CLIENT_WITNESSES,
                    UDP_WITNESSES - DNS_WITNESSES,
                ),
            ),
        ),
        ModelSemanticCase(
            "https-from-outside-testnet",
            "test",
            (
                "I'd like the TCP traffic headed to destination port 443 where "
                "the source address is not in 192.0.2.0/24 (TEST-NET-1) -- "
                "only the source side matters, it's fine if the destination "
                "happens to land in that range.",
                "Which TCP packets going to destination port 443 were not sent "
                "from TEST-NET-1 (192.0.2.0/24)? Only the source address is "
                "checked, so a destination inside that range is fine.",
            ),
            All(
                children=(
                    predicate("tcp.dstport", Operator.EQ, 443),
                    Not(child=_FROM_TESTNET),
                )
            ),
            "tcp.dstport == 443 && !(ip.src == 192.0.2.0/24)",
            "tcp.dstport == 443 && !(ip.addr == 192.0.2.0/24)",
            oracle(
                {"tcp-reverse"},
                set(),
                witnesses=({"tcp-near-testnet"}, {"tcp-near-testnet"}),
            ),
        ),
    )
