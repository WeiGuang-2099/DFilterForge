"""Witness packets appended to the model split probe copies.

The benchmark recipes leave some near-miss filters indistinguishable from
the gold on every probe: a port written for either side, the ACK number read
as the ACK flag, a flag read as the whole flag byte, DNS read as port 53, a
TTL, port or subnet bound moved by one, a DNS code read as a range. Each
witness below is one packet that separates at least one such
near miss from its gold case. The model split appends the same witness tail
to all six probe copies, after the last benchmark frame, so frames 1..N keep
their bytes and labels.

Packets follow the fixtures conventions: the probe's client
192.0.2.(seed % 200 + 1), a server 198.51.100.<ordinal>, ephemeral port
41000 + seed + ordinal, sequence number seed * 100 + ordinal, IP ID
seed + ordinal, TTL 64, no TCP payload, correct checksums and 60-byte
minimum frames. A witness that continues an earlier witness's flow reuses
that witness's ordinal for its addresses, ports and sequence number, so the
two share one TCP stream. Seed-derived bytes keep dev and test tails
distinct. Which cases each witness belongs to is authored in
``dfilterforge.model_split``, never derived from a filter.

Pinned tshark 4.6.8 decodes every witness as its table entry says, with no
malformed frame and no TCP analysis flag. The only expert items are the ones
any such packet carries: a note for a TTL below 5 or a nonzero ACK field
without the ACK flag, a chat for a SYN, a chat and a note for a FIN and a
warning for a reset. UDP witnesses without DNS carry no payload, so no
port-based dissector runs even when an ephemeral port is registered (udp
41170 is Manolito). The one DNS message whose ports both lack a dissector is
decoded by tshark's DNS-over-UDP heuristic, which is enabled by default.
Server addresses stay inside the hosts of 198.51.100.0/24, .1 to .254.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Address
import struct
from typing import Literal, TypeAlias

from dfilterforge.fixtures import internet_checksum

Host: TypeAlias = Literal["client", "server"] | IPv4Address
Transport: TypeAlias = Literal["tcp", "udp"]

# A UDP port above the 5353 and 5354 bounds with no registered tshark 4.6.8
# dissector for UDP or TCP.
HIGH_PORT = 6100
# A UDP port below 53 with no registered dissector, so tshark tries it first
# and then decodes DNS from port 53 on the other side, or with its DNS-over-UDP
# heuristic when the other side has no dissector either.
LOW_PORT = 52

_ETHERNET = bytes.fromhex("0200000000020200000000010800")
_EPHEMERAL_BASE = 41000
_FIN, _SYN, _RST, _ACK, _ECE, _CWR = 0x01, 0x02, 0x04, 0x10, 0x40, 0x80


@dataclass(frozen=True, slots=True)
class Endpoint:
    """One side of a witness packet.

    Attributes:
        host: The probe's client, the flow's server or a fixed address.
        port: A fixed port, or ``None`` for the flow's ephemeral port.
    """

    host: Host
    port: int | None = None


@dataclass(frozen=True, slots=True)
class TcpHeader:
    """The TCP fields a witness sets; the rest follow the fixtures.

    Attributes:
        flags: The TCP flag byte.
        ack_number: The raw acknowledgment number, or with
            ``from_sequence`` the amount added to the flow's sequence number.
        from_sequence: Whether the acknowledgment number counts from the
            flow's sequence number, as a peer acknowledging the other side's
            segments would.
    """

    flags: int
    ack_number: int = 0
    from_sequence: bool = False


@dataclass(frozen=True, slots=True)
class DnsMessage:
    """A one-question DNS message with no answer records."""

    response: bool
    qtype: int = 1
    rcode: int = 0


@dataclass(frozen=True, slots=True)
class Witness:
    """One named witness packet.

    Attributes:
        name: Label name, distinct from every benchmark recipe.
        source: The sending side.
        destination: The receiving side.
        tcp: The TCP header, or ``None`` for UDP.
        dns: The DNS message a UDP witness carries, if any; other UDP
            witnesses carry no payload, so no port-based dissector runs.
        ttl: The IPv4 time to live.
        flow_of: An earlier witness whose flow this one continues.
    """

    name: str
    source: Endpoint
    destination: Endpoint
    tcp: TcpHeader | None = None
    dns: DnsMessage | None = None
    ttl: int = 64
    flow_of: str | None = None

    @property
    def transport(self) -> Transport:
        """The IPv4 payload protocol."""
        return "udp" if self.tcp is None else "tcp"


_CLIENT = Endpoint("client")
_SERVER = Endpoint("server")
_SERVER_443 = Endpoint("server", 443)
_SERVER_53 = Endpoint("server", 53)
_SERVER_HIGH = Endpoint("server", HIGH_PORT)
_FAR_PRIVATE = IPv4Address("10.200.3.4")
_NEAR_TESTNET = IPv4Address("192.0.3.9")

WITNESSES: tuple[Witness, ...] = (
    # ACK sent from port 443, then a second ACK on the same stream whose
    # relative acknowledgment number is not 1.
    Witness("server-ack", _SERVER_443, _CLIENT, TcpHeader(_ACK, 1)),
    Witness(
        "server-ack-next",
        _SERVER_443,
        _CLIENT,
        TcpHeader(_ACK, 5000),
        flow_of="server-ack",
    ),
    # The same pair from the client to port 443.
    Witness("client-ack", _CLIENT, _SERVER_443, TcpHeader(_ACK, 1)),
    Witness(
        "client-ack-next",
        _CLIENT,
        _SERVER_443,
        TcpHeader(_ACK, 5000),
        flow_of="client-ack",
    ),
    # An ACK from port 443 that opens its stream by acknowledging the
    # client's sequence number plus one, then a client ACK to 443 at that
    # sequence number, shaped like a keep-alive probe. tshark takes the
    # client's base sequence from the first ACK, so the client segment shows
    # relative sequence 0 with no SYN, no reset and no analysis flag.
    Witness(
        "keepalive-server-ack",
        _SERVER_443,
        _CLIENT,
        TcpHeader(_ACK, 1, from_sequence=True),
    ),
    Witness(
        "keepalive-ack",
        _CLIENT,
        _SERVER_443,
        TcpHeader(_ACK, 0, from_sequence=True),
        flow_of="keepalive-server-ack",
    ),
    # ECE without SYN.
    Witness("ece-ack", _CLIENT, _SERVER_443, TcpHeader(_ACK | _ECE, 1)),
    # A SYN with CWR but not ECE, which no reading counts as an ECN-setup
    # SYN, then a reset with ECE at the SYN's own sequence number: relative
    # sequence 0 on a segment that is no SYN.
    Witness("cwr-syn", _CLIENT, _SERVER_443, TcpHeader(_SYN | _CWR)),
    Witness(
        "ece-syn-reset",
        _CLIENT,
        _SERVER_443,
        TcpHeader(_RST | _ECE),
        flow_of="cwr-syn",
    ),
    # SYN sent from port 443.
    Witness("server-syn", _SERVER_443, _CLIENT, TcpHeader(_SYN)),
    # SYN with ACK clear but a nonzero acknowledgment field.
    Witness("syn-nonzero-ack", _CLIENT, _SERVER_443, TcpHeader(_SYN, 1)),
    # TTL on either side of the at-most-one bound.
    Witness("tcp-ttl-0", _CLIENT, _SERVER_443, TcpHeader(_ACK, 1), ttl=0),
    Witness("tcp-ttl-2", _CLIENT, _SERVER_443, TcpHeader(_ACK, 1), ttl=2),
    Witness("udp-ttl-0", _CLIENT, _SERVER_HIGH, ttl=0),
    Witness("udp-ttl-2", _CLIENT, _SERVER_HIGH, ttl=2),
    # TTL on either side of the at-least-64 bound.
    Witness("udp-ttl-63", _CLIENT, _SERVER_HIGH, ttl=63),
    Witness("udp-ttl-128", _CLIENT, _SERVER_HIGH, ttl=128),
    # The first destination port above 5353.
    Witness("udp-to-5354", _CLIENT, Endpoint("server", 5354)),
    # DNS codes other than A, AAAA, NOERROR and NXDOMAIN.
    Witness(
        "dns-mx-query",
        _CLIENT,
        _SERVER_53,
        dns=DnsMessage(response=False, qtype=15),
    ),
    Witness(
        "dns-servfail",
        _SERVER_53,
        _CLIENT,
        dns=DnsMessage(response=True, rcode=2),
    ),
    # Successful responses that each break one conjunct of "from port 53,
    # not to port 53": both ports 53, mDNS, and a destination below 53.
    Witness(
        "dns-response-53-to-53",
        _SERVER_53,
        Endpoint("client", 53),
        dns=DnsMessage(response=True),
    ),
    Witness(
        "mdns-response",
        Endpoint("server", 5353),
        Endpoint("client", 5353),
        dns=DnsMessage(response=True),
    ),
    Witness(
        "dns-response-to-low-port",
        _SERVER_53,
        Endpoint("client", LOW_PORT),
        dns=DnsMessage(response=True),
    ),
    # A queries whose ports sit on a bound: from below 53, and to 5352
    # (decoded as DNS because the source port is 53).
    Witness(
        "dns-query-from-low-port",
        Endpoint("client", LOW_PORT),
        _SERVER_53,
        dns=DnsMessage(response=False),
    ),
    Witness(
        "dns-query-to-5352",
        Endpoint("client", 53),
        Endpoint("server", 5352),
        dns=DnsMessage(response=False),
    ),
    # Private destinations and sources outside 10.0.0.0/9 and 10.1.0.0/16,
    # a non-UDP packet and a DNS query to a private address.
    Witness("udp-to-far-private", _CLIENT, Endpoint(_FAR_PRIVATE, HIGH_PORT)),
    Witness("udp-from-far-private", Endpoint(_FAR_PRIVATE), _SERVER_HIGH),
    Witness(
        "tcp-to-private",
        _SERVER,
        Endpoint(IPv4Address("10.2.3.4"), HIGH_PORT),
        TcpHeader(_ACK, 1),
    ),
    Witness(
        "dns-to-private",
        _CLIENT,
        Endpoint(IPv4Address("10.2.3.5"), 53),
        dns=DnsMessage(response=False),
    ),
    # Sources inside 192.0.0.0/16 but outside TEST-NET-1.
    Witness(
        "tcp-near-testnet",
        Endpoint(_NEAR_TESTNET),
        _SERVER_443,
        TcpHeader(_ACK, 1),
    ),
    Witness("udp-near-testnet", Endpoint(_NEAR_TESTNET), _SERVER_HIGH),
    # A DNS query to a private address on a port that is not 53: DNS by its
    # dissector, not by its port. Both ports lack a dissector, so no
    # registered ephemeral port can claim it first.
    Witness(
        "dns-query-to-private-low",
        Endpoint("client", HIGH_PORT),
        Endpoint(IPv4Address("10.2.3.6"), LOW_PORT),
        dns=DnsMessage(response=False),
    ),
    # FIN together with ACK, as a server closes its side of a stream.
    Witness("server-fin-ack", _SERVER_443, _CLIENT, TcpHeader(_FIN | _ACK, 1)),
)
WITNESS_NAMES: tuple[str, ...] = tuple(witness.name for witness in WITNESSES)

# Families authored from the table above, as benchmark.py does for recipes.
# Case memberships in dfilterforge.model_split are built from them.
TCP_WITNESSES = frozenset(
    (
        "server-ack",
        "server-ack-next",
        "client-ack",
        "client-ack-next",
        "keepalive-server-ack",
        "keepalive-ack",
        "ece-ack",
        "cwr-syn",
        "ece-syn-reset",
        "server-syn",
        "syn-nonzero-ack",
        "tcp-ttl-0",
        "tcp-ttl-2",
        "tcp-to-private",
        "tcp-near-testnet",
        "server-fin-ack",
    )
)
UDP_WITNESSES = frozenset(
    (
        "udp-ttl-0",
        "udp-ttl-2",
        "udp-ttl-63",
        "udp-ttl-128",
        "udp-to-5354",
        "dns-mx-query",
        "dns-servfail",
        "dns-response-53-to-53",
        "mdns-response",
        "dns-response-to-low-port",
        "dns-query-from-low-port",
        "dns-query-to-5352",
        "udp-to-far-private",
        "udp-from-far-private",
        "dns-to-private",
        "udp-near-testnet",
        "dns-query-to-private-low",
    )
)
# Sourced from the probe's own client in 192.0.2.0/24.
CLIENT_WITNESSES = frozenset(
    (
        "client-ack",
        "client-ack-next",
        "keepalive-ack",
        "ece-ack",
        "cwr-syn",
        "ece-syn-reset",
        "syn-nonzero-ack",
        "tcp-ttl-0",
        "tcp-ttl-2",
        "udp-ttl-0",
        "udp-ttl-2",
        "udp-ttl-63",
        "udp-ttl-128",
        "udp-to-5354",
        "dns-mx-query",
        "dns-query-from-low-port",
        "dns-query-to-5352",
        "udp-to-far-private",
        "dns-to-private",
        "dns-query-to-private-low",
    )
)
ACK_WITNESSES = frozenset(
    (
        "server-ack",
        "server-ack-next",
        "client-ack",
        "client-ack-next",
        "keepalive-server-ack",
        "keepalive-ack",
        "ece-ack",
        "tcp-ttl-0",
        "tcp-ttl-2",
        "tcp-to-private",
        "tcp-near-testnet",
        "server-fin-ack",
    )
)
SYN_WITNESSES = frozenset(("cwr-syn", "server-syn", "syn-nonzero-ack"))
FIN_WITNESSES = frozenset(("server-fin-ack",))
# TCP sent to destination port 443.
HTTPS_WITNESSES = frozenset(
    (
        "client-ack",
        "client-ack-next",
        "keepalive-ack",
        "ece-ack",
        "cwr-syn",
        "ece-syn-reset",
        "syn-nonzero-ack",
        "tcp-ttl-0",
        "tcp-ttl-2",
        "tcp-near-testnet",
    )
)
# Decoded as unicast DNS; the mDNS response is not in it.
DNS_WITNESSES = frozenset(
    (
        "dns-mx-query",
        "dns-servfail",
        "dns-response-53-to-53",
        "dns-response-to-low-port",
        "dns-query-from-low-port",
        "dns-query-to-5352",
        "dns-to-private",
        "dns-query-to-private-low",
    )
)
# DNS or mDNS responses, each with an A question.
RESPONSE_WITNESSES = frozenset(
    (
        "dns-servfail",
        "dns-response-53-to-53",
        "mdns-response",
        "dns-response-to-low-port",
    )
)
# DNS queries for A records.
A_QUERY_WITNESSES = frozenset(
    (
        "dns-query-from-low-port",
        "dns-query-to-5352",
        "dns-to-private",
        "dns-query-to-private-low",
    )
)
# UDP sent from source port 53.
SOURCE_53_WITNESSES = frozenset(
    (
        "dns-servfail",
        "dns-response-53-to-53",
        "dns-response-to-low-port",
        "dns-query-to-5352",
    )
)
# An endpoint inside 10.0.0.0/8.
PRIVATE_WITNESSES = frozenset(
    (
        "udp-to-far-private",
        "udp-from-far-private",
        "tcp-to-private",
        "dns-to-private",
        "dns-query-to-private-low",
    )
)
TTL_BELOW_64_WITNESSES = frozenset(
    ("tcp-ttl-0", "tcp-ttl-2", "udp-ttl-0", "udp-ttl-2", "udp-ttl-63")
)
# UDP sent to a destination port above 5353.
HIGH_PORT_WITNESSES = frozenset(
    (
        "udp-ttl-0",
        "udp-ttl-2",
        "udp-ttl-63",
        "udp-ttl-128",
        "udp-to-5354",
        "dns-servfail",
        "udp-to-far-private",
        "udp-from-far-private",
        "udp-near-testnet",
    )
)


def _address(host: Host, seed: int, flow: int) -> bytes:
    if isinstance(host, IPv4Address):
        return host.packed
    if host == "client":
        return bytes((192, 0, 2, seed % 200 + 1))
    return bytes((198, 51, 100, flow))


def _dns_payload(message: DnsMessage, seed: int, ordinal: int) -> bytes:
    flags = (0x8180 | message.rcode) if message.response else 0x0100
    labels = (f"witness-{seed}-{ordinal}".encode("ascii"), b"example")
    question = b"".join(bytes((len(label),)) + label for label in labels)
    header = struct.pack("!6H", seed + ordinal, flags, 1, 0, 0, 0)
    return header + question + b"\0" + struct.pack("!HH", message.qtype, 1)


def _segment(
    witness: Witness, seed: int, ordinal: int, flow: int, pseudo: bytes
) -> bytes:
    """Builds the transport segment with its pseudo-header checksum."""
    ephemeral = _EPHEMERAL_BASE + seed + flow
    source_port, destination_port = (
        ephemeral if side.port is None else side.port
        for side in (witness.source, witness.destination)
    )
    if witness.tcp is not None:
        sequence = seed * 100 + flow
        acknowledged = witness.tcp.ack_number + (
            sequence if witness.tcp.from_sequence else 0
        )
        segment = struct.pack(
            "!HHIIBBHHH",
            source_port,
            destination_port,
            sequence,
            acknowledged,
            0x50,
            witness.tcp.flags,
            8192,
            0,
            0,
        )
        offset = 16
    else:
        payload = (
            b""
            if witness.dns is None
            else _dns_payload(witness.dns, seed, ordinal)
        )
        segment = (
            struct.pack(
                "!HHHH", source_port, destination_port, len(payload) + 8, 0
            )
            + payload
        )
        offset = 6
    header = pseudo + struct.pack("!H", len(segment))
    checksum = internet_checksum(header + segment) or 0xFFFF
    return (
        segment[:offset] + struct.pack("!H", checksum) + segment[offset + 2 :]
    )


def _frame(witness: Witness, seed: int, ordinal: int, flow: int) -> bytes:
    """Builds one complete Ethernet/IPv4 frame for a witness."""
    source = _address(witness.source.host, seed, flow)
    destination = _address(witness.destination.host, seed, flow)
    protocol = 6 if witness.transport == "tcp" else 17
    segment = _segment(
        witness,
        seed,
        ordinal,
        flow,
        source + destination + bytes((0, protocol)),
    )
    # Version 4 with a 20-byte header and DF set; the checksum goes in last.
    total_length, ip_id = len(segment) + 20, seed + ordinal
    header = bytearray(20)
    struct.pack_into(
        "!BBHHHBB",
        header,
        0,
        0x45,
        0,
        total_length,
        ip_id,
        0x4000,
        witness.ttl,
        protocol,
    )
    header[12:20] = source + destination
    header[10:12] = internet_checksum(bytes(header)).to_bytes(2, "big")
    return (_ETHERNET + bytes(header) + segment).ljust(60, b"\0")


def witness_frames(seed: int, first_ordinal: int) -> tuple[bytes, ...]:
    """Builds the witness tail's frames in table order.

    Args:
        seed: The probe's benchmark seed, 1 to 10000.
        first_ordinal: The frame number of the first witness, one past the
            probe's last frame.

    Returns:
        One Ethernet frame per entry of ``WITNESSES``.

    Raises:
        ValueError: If the seed is out of range or a server address would
            leave the hosts of 198.51.100.0/24.
    """
    last_ordinal = first_ordinal + len(WITNESSES) - 1
    if not 1 <= seed <= 10000 or first_ordinal < 1 or last_ordinal > 254:
        raise ValueError("Witness seed or ordinals are outside their bounds")
    ordinals = {
        witness.name: first_ordinal + index
        for index, witness in enumerate(WITNESSES)
    }
    return tuple(
        _frame(
            witness,
            seed,
            ordinals[witness.name],
            ordinals[witness.flow_of or witness.name],
        )
        for witness in WITNESSES
    )


def append_witnesses(capture: bytes, seed: int, frame_count: int) -> bytes:
    """Returns a capture with the witness tail after its last frame.

    The capture's own bytes are kept unchanged as a prefix. Each witness
    record carries the benchmark timestamp convention: the second
    1700000000 + seed and ordinal milliseconds.

    Args:
        capture: A benchmark PCAP with ``frame_count`` frames.
        seed: The seed the benchmark built the capture with.
        frame_count: The number of frames already in the capture.

    Returns:
        The extended PCAP bytes.
    """
    first = frame_count + 1
    records = [capture]
    for ordinal, frame in enumerate(witness_frames(seed, first), first):
        records.append(
            struct.pack(
                "<IIII",
                1700000000 + seed,
                ordinal * 1000,
                len(frame),
                len(frame),
            )
        )
        records.append(frame)
    return b"".join(records)
