"""Witness packets: table, byte layout, determinism and tshark decoding."""

from collections.abc import Callable
from ipaddress import IPv4Address
from ipaddress import IPv4Network
from pathlib import Path
import struct
import sys

import pytest

from dfilterforge import witnesses
from dfilterforge.benchmark import capture_bytes
from dfilterforge.benchmark import RECIPES
from dfilterforge.fixtures import internet_checksum
from dfilterforge.model_split import generate_model_split
from dfilterforge.runner import TsharkRunner
from dfilterforge.witnesses import append_witnesses
from dfilterforge.witnesses import Witness
from dfilterforge.witnesses import witness_frames
from dfilterforge.witnesses import WITNESS_NAMES
from dfilterforge.witnesses import WITNESSES

_ETHERNET = bytes.fromhex("0200000000020200000000010800")
# The three stream pairs and the reset that continues a SYN.
_FLOW_OF = {
    "server-ack-next": "server-ack",
    "client-ack-next": "client-ack",
    "keepalive-ack": "keepalive-server-ack",
    "ece-syn-reset": "cwr-syn",
}


def _parse(frame: bytes) -> dict[str, int | bytes]:
    """Reads the header fields a witness sets, checking both checksums."""
    assert frame[:14] == _ETHERNET
    assert len(frame) >= 60
    ip_end = 14 + int.from_bytes(frame[16:18], "big")
    header, segment = frame[14:34], frame[34:ip_end]
    assert header[0] == 0x45 and header[6:8] == b"\x40\x00"
    assert frame[ip_end:] == b"\0" * (len(frame) - ip_end)
    assert internet_checksum(header) == 0
    pseudo = header[12:20] + struct.pack("!BBH", 0, header[9], len(segment))
    assert internet_checksum(pseudo + segment) == 0
    fields: dict[str, int | bytes] = {
        "ip_id": int.from_bytes(header[4:6], "big"),
        "ttl": header[8],
        "protocol": header[9],
        "source": header[12:16],
        "destination": header[16:20],
        "source_port": int.from_bytes(segment[0:2], "big"),
        "destination_port": int.from_bytes(segment[2:4], "big"),
    }
    if header[9] == 6:
        fields.update(
            seq=int.from_bytes(segment[4:8], "big"),
            ack=int.from_bytes(segment[8:12], "big"),
            offset=segment[12],
            flags=segment[13],
            payload=segment[20:],
        )
    else:
        assert int.from_bytes(segment[4:6], "big") == len(segment)
        fields.update(payload=segment[8:])
    return fields


def _witness(name: str) -> Witness:
    return WITNESSES[WITNESS_NAMES.index(name)]


def test_names_are_unique_and_never_benchmark_recipes() -> None:
    assert len(set(WITNESS_NAMES)) == len(WITNESS_NAMES) == 33
    assert not set(WITNESS_NAMES) & set(RECIPES)
    for name, first in _FLOW_OF.items():
        assert _witness(name).flow_of == first
        assert WITNESS_NAMES.index(first) < WITNESS_NAMES.index(name)
    assert {w.name for w in WITNESSES if w.flow_of} == set(_FLOW_OF)


def _private(host: object) -> bool:
    return isinstance(host, IPv4Address) and host in IPv4Network("10.0.0.0/8")


def _high(witness: Witness) -> bool:
    # A missing destination port is the ephemeral port, above 41000.
    port = witness.destination.port
    return witness.transport == "udp" and (port is None or port > 5353)


def _flags(witness: Witness) -> int:
    return 0 if witness.tcp is None else witness.tcp.flags


# Each authored family against the table field it names.
_FAMILY_RULES: dict[str, Callable[[Witness], bool]] = {
    "TCP_WITNESSES": lambda w: w.transport == "tcp",
    "UDP_WITNESSES": lambda w: w.transport == "udp",
    "CLIENT_WITNESSES": lambda w: w.source.host == "client",
    "ACK_WITNESSES": lambda w: bool(_flags(w) & 0x10),
    "SYN_WITNESSES": lambda w: bool(_flags(w) & 0x02),
    "FIN_WITNESSES": lambda w: bool(_flags(w) & 0x01),
    "HTTPS_WITNESSES": lambda w: (
        w.transport == "tcp" and w.destination.port == 443
    ),
    "DNS_WITNESSES": lambda w: w.dns is not None and w.source.port != 5353,
    "RESPONSE_WITNESSES": lambda w: w.dns is not None and w.dns.response,
    "A_QUERY_WITNESSES": lambda w: (
        w.dns is not None and not w.dns.response and w.dns.qtype == 1
    ),
    "SOURCE_53_WITNESSES": lambda w: w.source.port == 53,
    "PRIVATE_WITNESSES": lambda w: _private(w.source.host)
    or _private(w.destination.host),
    "TTL_BELOW_64_WITNESSES": lambda w: w.ttl < 64,
    "HIGH_PORT_WITNESSES": _high,
}


@pytest.mark.parametrize("family", sorted(_FAMILY_RULES))
def test_authored_families_match_the_packet_table(family: str) -> None:
    rule = _FAMILY_RULES[family]

    assert getattr(witnesses, family) == {w.name for w in WITNESSES if rule(w)}


def test_frames_follow_the_fixture_conventions() -> None:
    seed, first = 110, 22
    frames = witness_frames(seed, first)
    ordinals = {name: first + i for i, name in enumerate(WITNESS_NAMES)}
    client = bytes((192, 0, 2, 111))

    assert len(frames) == len(WITNESSES)
    for witness, frame in zip(WITNESSES, frames, strict=True):
        fields = _parse(frame)
        ordinal = ordinals[witness.name]
        flow = ordinals[witness.flow_of or witness.name]
        hosts = {"client": client, "server": bytes((198, 51, 100, flow))}
        assert fields["ip_id"] == seed + ordinal
        assert fields["ttl"] == witness.ttl
        assert fields["protocol"] == (6 if witness.transport == "tcp" else 17)
        for side, endpoint in (
            ("source", witness.source),
            ("destination", witness.destination),
        ):
            host = endpoint.host
            expected = (
                host.packed if isinstance(host, IPv4Address) else hosts[host]
            )
            assert fields[side] == expected
            assert fields[f"{side}_port"] == (
                41000 + seed + flow if endpoint.port is None else endpoint.port
            )
        if witness.tcp is not None:
            assert fields["seq"] == seed * 100 + flow
            assert fields["ack"] == witness.tcp.ack_number + (
                seed * 100 + flow if witness.tcp.from_sequence else 0
            )
            assert (fields["offset"], fields["flags"]) == (
                0x50,
                witness.tcp.flags,
            )
            assert fields["payload"] == b""
        elif witness.dns is None:
            assert fields["payload"] == b""
        else:
            payload = fields["payload"]
            assert isinstance(payload, bytes)
            flags = int.from_bytes(payload[2:4], "big")
            assert int.from_bytes(payload[0:2], "big") == seed + ordinal
            assert bool(flags & 0x8000) is witness.dns.response
            assert flags & 0xF == witness.dns.rcode
            assert payload[4:12] == struct.pack("!4H", 1, 0, 0, 0)
            assert payload[-4:] == struct.pack("!HH", witness.dns.qtype, 1)
            assert f"witness-{seed}-{ordinal}".encode() in payload


def test_flow_pairs_share_one_stream_and_differ_only_where_named() -> None:
    frames = dict(zip(WITNESS_NAMES, witness_frames(130, 27), strict=True))

    for second, first in _FLOW_OF.items():
        one, two = _parse(frames[first]), _parse(frames[second])
        # The keep-alive pair runs in both directions of one stream.
        turn = second == "keepalive-ack"
        for key, other in (
            ("source", "destination"),
            ("source_port", "destination_port"),
        ):
            assert one[key] == two[other if turn else key]
            assert one[other] == two[key if turn else other]
        assert one["seq"] == two["seq"]
        assert one["ip_id"] != two["ip_id"]
    assert _parse(frames["server-ack-next"])["ack"] == 5000
    assert _parse(frames["client-ack-next"])["ack"] == 5000
    assert _parse(frames["ece-syn-reset"])["flags"] == 0x44
    # The server acknowledges the client's sequence number plus one, and
    # the client segment sits at that sequence number.
    server, client = (
        _parse(frames[name])
        for name in ("keepalive-server-ack", "keepalive-ack")
    )
    client_seq = client["seq"]
    assert isinstance(client_seq, int)
    assert server["ack"] == client_seq + 1
    assert client["ack"] == server["seq"]


def test_tails_are_deterministic_and_disjoint_across_seeds() -> None:
    dev = witness_frames(110, 22)

    assert witness_frames(110, 22) == dev
    # Seed-derived addresses, ports, IDs and sequence numbers leave no
    # witness frame shared between a dev and a test probe.
    assert not set(dev) & set(witness_frames(130, 22))
    assert not set(dev) & set(witness_frames(110, 23))


def test_append_keeps_the_capture_and_continues_its_records() -> None:
    capture = capture_bytes(RECIPES[:3], 110)

    extended = append_witnesses(capture, 110, 3)

    assert extended.startswith(capture)
    offset = len(capture)
    for ordinal, frame in enumerate(witness_frames(110, 4), 4):
        header = struct.unpack("<IIII", extended[offset : offset + 16])
        assert header == (1700000110, ordinal * 1000, len(frame), len(frame))
        assert extended[offset + 16 : offset + 16 + len(frame)] == frame
        offset += 16 + len(frame)
    assert offset == len(extended)


# The largest first ordinal that keeps every server address a host.
_LAST_FIRST = 255 - len(WITNESSES)


@pytest.mark.parametrize(
    ("seed", "first"),
    [(0, 22), (10001, 22), (110, 0), (110, _LAST_FIRST + 1)],
)
def test_out_of_range_seeds_and_ordinals_are_refused(
    seed: int, first: int
) -> None:
    with pytest.raises(ValueError):
        witness_frames(seed, first)


def test_the_last_server_address_is_the_last_host() -> None:
    frames = witness_frames(110, _LAST_FIRST)

    # The last witness comes from its own server, 198.51.100.254, never
    # from the broadcast address .255.
    assert WITNESSES[-1].source.host == "server"
    assert _parse(frames[-1])["source"] == bytes((198, 51, 100, 254))


# What tshark 4.6.8 must decode for each witness, written from the packet
# intent rather than from the table: {c} is the probe's client, {s} the
# flow's server and {e} the flow's ephemeral port.
_TCP = 'frame.protocols == "eth:ethertype:ip:tcp" && '
_UDP = 'frame.protocols == "eth:ethertype:ip:udp" && '
_DNS = 'frame.protocols == "eth:ethertype:ip:udp:dns" && '
_TO_443 = "ip.src == {c} && ip.dst == {s} && tcp.srcport == {e} && "
_FROM_443 = "ip.src == {s} && ip.dst == {c} && tcp.srcport == 443 && "
_UDP_OUT = "ip.src == {c} && ip.dst == {s} && udp.srcport == {e} && "
_DECODES = {
    "server-ack": _TCP
    + _FROM_443
    + "tcp.dstport == {e} && tcp.flags == 0x010 && tcp.ack == 1",
    "server-ack-next": _TCP
    + _FROM_443
    + "tcp.dstport == {e} && tcp.flags == 0x010 && tcp.ack == 5000",
    "client-ack": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x010 && tcp.ack == 1",
    "client-ack-next": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x010 && tcp.ack == 5000",
    # The server's ACK sets the client's base sequence, so the client ACK
    # shows relative sequence 0 while the server's own shows 1.
    "keepalive-server-ack": _TCP
    + _FROM_443
    + "tcp.dstport == {e} && tcp.flags == 0x010 && tcp.seq == 1 && "
    "tcp.ack == 1",
    "keepalive-ack": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x010 && tcp.seq == 0 && "
    "tcp.ack == 1",
    "ece-ack": _TCP + _TO_443 + "tcp.dstport == 443 && tcp.flags == 0x050",
    "cwr-syn": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x082 && tcp.seq == 0",
    "ece-syn-reset": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x044 && tcp.seq == 0",
    "server-syn": _TCP
    + _FROM_443
    + "tcp.dstport == {e} && tcp.flags == 0x002 && tcp.ack == 0",
    "syn-nonzero-ack": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x002 && tcp.ack == 1",
    "tcp-ttl-0": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x010 && ip.ttl == 0",
    "tcp-ttl-2": _TCP
    + _TO_443
    + "tcp.dstport == 443 && tcp.flags == 0x010 && ip.ttl == 2",
    "udp-ttl-0": _UDP + _UDP_OUT + "udp.dstport == 6100 && ip.ttl == 0",
    "udp-ttl-2": _UDP + _UDP_OUT + "udp.dstport == 6100 && ip.ttl == 2",
    "udp-ttl-63": _UDP + _UDP_OUT + "udp.dstport == 6100 && ip.ttl == 63",
    "udp-ttl-128": _UDP + _UDP_OUT + "udp.dstport == 6100 && ip.ttl == 128",
    "udp-to-5354": _UDP + _UDP_OUT + "udp.dstport == 5354",
    "dns-mx-query": _DNS
    + _UDP_OUT
    + "udp.dstport == 53 && dns.flags.response == 0 && dns.qry.type == 15"
    " && !dns.flags.rcode",
    "dns-servfail": _DNS
    + "ip.src == {s} && ip.dst == {c} && udp.srcport == 53 && "
    "udp.dstport == {e} && dns.flags.response == 1 && dns.qry.type == 1 && "
    "dns.flags.rcode == 2",
    "dns-response-53-to-53": _DNS
    + "ip.src == {s} && ip.dst == {c} && udp.srcport == 53 && "
    "udp.dstport == 53 && dns.flags.response == 1 && dns.flags.rcode == 0",
    "mdns-response": 'frame.protocols == "eth:ethertype:ip:udp:mdns" && '
    "ip.src == {s} && ip.dst == {c} && udp.srcport == 5353 && "
    "udp.dstport == 5353 && dns.flags.response == 1 && dns.flags.rcode == 0",
    "dns-response-to-low-port": _DNS
    + "ip.src == {s} && ip.dst == {c} && udp.srcport == 53 && "
    "udp.dstport == 52 && dns.flags.response == 1 && dns.flags.rcode == 0",
    "dns-query-from-low-port": _DNS
    + "ip.src == {c} && ip.dst == {s} && udp.srcport == 52 && "
    "udp.dstport == 53 && dns.flags.response == 0 && dns.qry.type == 1",
    "dns-query-to-5352": _DNS
    + "ip.src == {c} && ip.dst == {s} && udp.srcport == 53 && "
    "udp.dstport == 5352 && dns.flags.response == 0 && dns.qry.type == 1",
    "udp-to-far-private": _UDP
    + "ip.src == {c} && ip.dst == 10.200.3.4 && udp.dstport == 6100",
    "udp-from-far-private": _UDP
    + "ip.src == 10.200.3.4 && ip.dst == {s} && udp.dstport == 6100",
    "tcp-to-private": _TCP
    + "ip.src == {s} && ip.dst == 10.2.3.4 && tcp.srcport == {e} && "
    "tcp.dstport == 6100 && tcp.flags == 0x010",
    "dns-to-private": _DNS
    + "ip.src == {c} && ip.dst == 10.2.3.5 && udp.dstport == 53 && "
    "dns.flags.response == 0 && dns.qry.type == 1",
    "tcp-near-testnet": _TCP
    + "ip.src == 192.0.3.9 && ip.dst == {s} && tcp.dstport == 443 && "
    "tcp.flags == 0x010",
    "udp-near-testnet": _UDP
    + "ip.src == 192.0.3.9 && ip.dst == {s} && udp.dstport == 6100",
    # DNS on port 52 from port 6100, found by the heuristic, not a port.
    "dns-query-to-private-low": _DNS
    + "ip.src == {c} && ip.dst == 10.2.3.6 && udp.srcport == 6100 && "
    "udp.dstport == 52 && dns.flags.response == 0 && dns.qry.type == 1",
    "server-fin-ack": _TCP
    + _FROM_443
    + "tcp.dstport == {e} && tcp.flags == 0x011 && tcp.ack == 1",
}
# Expert items each witness may carry: the SYN and reset notes every such
# segment gets, the FIN chat and closing note, the ACK-number note, and the
# TTL-below-5 note.
_EXPERTS = {
    "cwr-syn": "chat",
    "ece-syn-reset": "warn",
    "server-syn": "chat",
    "syn-nonzero-ack": "note",
    "tcp-ttl-0": "note",
    "tcp-ttl-2": "note",
    "udp-ttl-0": "note",
    "udp-ttl-2": "note",
    "server-fin-ack": "note",
}
_SEVERITY = {"chat": 0x00200000, "note": 0x00400000, "warn": 0x00600000}


@pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)
def test_every_witness_decodes_as_intended_on_all_six_probes(
    tmp_path: Path,
) -> None:
    runner = TsharkRunner()
    artifacts = generate_model_split(tmp_path)
    assert set(_DECODES) == set(WITNESS_NAMES)

    for probe in artifacts.probes:
        base = len(probe.recipes) - len(WITNESS_NAMES)
        assert probe.recipes[base:] == WITNESS_NAMES
        seed = 100 + int(probe.probe_id.removeprefix("semantic-")) - 1
        ordinals = {name: base + 1 + i for i, name in enumerate(WITNESS_NAMES)}
        for name, template in _DECODES.items():
            flow = ordinals[_FLOW_OF.get(name, name)]
            clause = template.format(
                c=f"192.0.2.{seed % 200 + 1}",
                s=f"198.51.100.{flow}",
                e=41000 + seed + flow,
            )
            if "ip.ttl" not in clause:
                clause += " && ip.ttl == 64"
            selected = runner.run(
                probe.capture_path,
                f"frame.number == {ordinals[name]} && {clause} && "
                "!_ws.malformed && !tcp.analysis.flags",
            ).frames
            assert selected == (ordinals[name],), (probe.probe_id, name)
        tail = f"frame.number > {base} && "
        # The worst expert severity of each witness is the one it is
        # allowed; a missing entry allows none.
        for above, severity in ((None, 0), *_SEVERITY.items()):
            expected = tuple(
                sorted(
                    ordinals[name]
                    for name, level in _EXPERTS.items()
                    if _SEVERITY[level] > severity
                )
            )
            display_filter = (
                f"{tail}_ws.expert"
                if above is None
                else f"{tail}_ws.expert.severity > {severity:#010x}"
            )
            assert (
                runner.run(probe.capture_path, display_filter).frames
                == expected
            ), (probe.probe_id, above)
        assert (
            runner.run(
                probe.capture_path,
                f"{tail}(_ws.malformed || tcp.analysis.flags)",
            ).frames
            == ()
        )
