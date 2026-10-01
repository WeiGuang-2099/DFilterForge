"""Counterexample cards: frame facts, tshark confirmation and leak tests."""

from collections.abc import Callable
import hashlib
from pathlib import Path
import struct
import sys

from pydantic import ValidationError
import pytest

from dfilterforge import counterexample as counterexample_module
from dfilterforge.benchmark import capture_bytes
from dfilterforge.counterexample import CounterexampleError
from dfilterforge.counterexample import decode_capture
from dfilterforge.counterexample import HeaderFactsV1
from dfilterforge.counterexample import proof_filter
from dfilterforge.counterexample import read_frame_facts
from dfilterforge.counterexample import SHOWN_FIELDS
from dfilterforge.counterexample import TCP_FLAG_NAMES
from dfilterforge.model_feedback import FeedbackProbes
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.runner import RunnerLimits
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner

_POSIX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)
_ETHERNET = bytes.fromhex("0200000000020200000000010800")
_PCAP_HEADER = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
_QUESTION = b"\x07witness\x07example\x00"
# A runner that would fail if a test ever reached tshark.
_NO_TSHARK = TsharkRunner(tshark="dfilterforge-no-such-tshark")


def _pcap(*frames: bytes, header: bytes = _PCAP_HEADER) -> bytes:
    """A little-endian PCAP holding ``frames`` as complete records."""
    records = [header]
    for frame in frames:
        records.append(struct.pack("<IIII", 0, 0, len(frame), len(frame)))
        records.append(frame)
    return b"".join(records)


def _ipv4(
    protocol: int,
    segment: bytes,
    *,
    first_byte: int = 0x45,
    tos: int = 0,
    fragment: int = 0x4000,
    ethernet: bytes = _ETHERNET,
) -> bytes:
    """An Ethernet frame with an IPv4 header and no checksum."""
    header = struct.pack(
        "!BBHHHBBH4s4s",
        first_byte,
        tos,
        20 + len(segment),
        7,
        fragment,
        64,
        protocol,
        0,
        bytes((192, 0, 2, 9)),
        bytes((198, 51, 100, 7)),
    )
    return (ethernet + header + segment).ljust(60, b"\0")


def _udp(payload: bytes, source: int = 41001, destination: int = 53) -> bytes:
    return struct.pack("!HHHH", source, destination, 8 + len(payload), 0) + (
        payload
    )


def _tcp(payload: bytes, flags: int = 0x018, offset_byte: int = 0x50) -> bytes:
    return (
        struct.pack(
            "!HHIIBBHHH",
            41001,
            53,
            1,
            1,
            offset_byte | flags >> 8,
            flags & 0xFF,
            8192,
            0,
            0,
        )
        + payload
    )


def _dns(
    flags: int = 0x0100, question: bytes = _QUESTION, count: int = 1
) -> bytes:
    header = struct.pack("!6H", 9, flags, count, 0, 0, 0)
    return header + question + struct.pack("!HH", 28, 1)


def _facts(**values: object) -> HeaderFactsV1:
    """Builds facts from tshark names written with underscores."""
    return HeaderFactsV1.model_validate(
        {name.replace("__", "."): value for name, value in values.items()}
    )


def _refusal(
    data: bytes, dns_frames: frozenset[int] = frozenset({1})
) -> CounterexampleError:
    with pytest.raises(CounterexampleError) as error:
        decode_capture(data, dns_frames)
    return error.value


@pytest.fixture(name="split", scope="module")
def fixture_split(
    tmp_path_factory: pytest.TempPathFactory,
) -> ModelSplitArtifacts:
    return generate_model_split(tmp_path_factory.mktemp("split"))


@pytest.fixture(name="feedback", scope="module")
def fixture_feedback(split: ModelSplitArtifacts) -> FeedbackProbes:
    return generate_feedback_probes(split)


def test_the_shown_fields_and_flag_names_are_fixed() -> None:
    assert len(SHOWN_FIELDS) == 13
    assert TCP_FLAG_NAMES == (
        "FIN",
        "SYN",
        "RST",
        "PSH",
        "ACK",
        "URG",
        "ECE",
        "CWR",
        "AE",
    )
    assert set(
        HeaderFactsV1.model_validate({}).model_dump(by_alias=True)
    ) == set(SHOWN_FIELDS)


def test_dns_over_tcp_is_read_after_its_two_byte_length() -> None:
    """The generator's tcp-query recipe, seed 5, frame 1."""
    data = capture_bytes(("tcp-query",), 5)

    (facts,) = decode_capture(data, frozenset({1})).values()

    assert facts.model_dump(by_alias=True, exclude_none=True) == {
        "ip.src": "192.0.2.6",
        "ip.dst": "198.51.100.1",
        "ip.ttl": 64,
        "ip.dsfield.ecn": 0,
        "tcp.srcport": 41006,
        "tcp.dstport": 53,
        "tcp.flags": ("PSH", "ACK"),
        # The 35-byte message plus its two-byte length.
        "tcp.len": 37,
        "dns.flags.response": False,
        "dns.qry.type": 1,
    }


def test_a_query_shows_no_rcode_and_its_proof_requires_none() -> None:
    data = capture_bytes(("udp-query", "udp-response", "udp-nxdomain"), 5)

    query, response, nxdomain = decode_capture(
        data, frozenset({1, 2, 3})
    ).values()

    assert query.dns_flags_response is False
    assert query.dns_flags_rcode is None
    assert response.dns_flags_rcode == 0
    assert nxdomain.dns_flags_rcode == 3
    assert "dns.flags.response === 0 && !dns.flags.rcode && " in (
        proof_filter(1, query)
    )
    assert "dns.flags.response === 1 && dns.flags.rcode === 3 && " in (
        proof_filter(3, nxdomain)
    )


def test_the_proof_states_every_shown_field_or_its_absence() -> None:
    data = capture_bytes(("ecn-syn", "udp-other"), 5)

    syn, other = decode_capture(data, frozenset()).values()

    assert proof_filter(1, syn) == (
        "frame.number == 1 && ip.src === 192.0.2.6 && "
        "ip.dst === 198.51.100.1 && ip.ttl === 64 && ip.dsfield.ecn === 0 "
        "&& tcp.srcport === 41006 && tcp.dstport === 443 && "
        "tcp.flags === 0x0c2 && tcp.len === 0 && !udp.srcport && "
        "!udp.dstport && !dns.flags.response && !dns.flags.rcode && "
        "!dns.qry.type"
    )
    assert syn.tcp_flags == ("SYN", "ECE", "CWR")
    assert proof_filter(2, other).endswith(
        "!tcp.srcport && !tcp.dstport && !tcp.flags && !tcp.len && "
        "udp.srcport === 41007 && udp.dstport === 9999 && "
        "!dns.flags.response && !dns.flags.rcode && !dns.qry.type"
    )


def test_ecn_ae_and_a_question_free_message_are_read() -> None:
    data = _pcap(
        _ipv4(6, _tcp(b"", flags=0x111), tos=0x03),
        _ipv4(17, _udp(struct.pack("!6H", 9, 0x8183, 0, 0, 0, 0))),
    )

    tcp, dns = decode_capture(data, frozenset({2})).values()

    assert tcp.ip_dsfield_ecn == 3
    assert tcp.tcp_flags == ("FIN", "ACK", "AE")
    assert "tcp.flags === 0x111" in proof_filter(1, tcp)
    assert (dns.dns_flags_rcode, dns.dns_qry_type) == (3, None)
    assert proof_filter(2, dns).endswith(
        "dns.flags.rcode === 3 && !dns.qry.type"
    )


@pytest.mark.parametrize(
    "data",
    [
        capture_bytes(("udp-query",), 5)[:-1],
        capture_bytes(("udp-query",), 5)[:30],
        _pcap(_ipv4(17, _udp(_dns())))[:-1],
        # A record captured shorter than the packet on the wire.
        _PCAP_HEADER + struct.pack("<IIII", 0, 0, 60, 61) + b"\0" * 60,
        # An IPv4 total length past the bytes its record holds.
        _pcap(_ipv4(17, _udp(_dns()))[:40]),
    ],
    ids=["last-byte", "record-header", "frame", "snapped", "ip-length"],
)
def test_a_truncated_record_is_unreadable(data: bytes) -> None:
    assert _refusal(data).code == "facts_unreadable"


def test_a_compression_pointer_in_the_question_is_refused() -> None:
    pointer = _dns(question=b"\xc0\x0c")
    extended = _dns(question=b"\x41" + b"a" * 65 + b"\x00")

    first = _refusal(_pcap(_ipv4(17, _udp(pointer))))
    second = _refusal(_pcap(_ipv4(17, _udp(extended))))

    assert first.code == second.code == "facts_unreadable"
    assert str(first) == (
        "Feedback capture frame 1: DNS question name is compressed"
    )


def test_a_dns_name_is_bounded_and_never_read_past_its_message() -> None:
    labels = b"".join(b"\x3f" + b"a" * 63 for _ in range(4))
    longest = b"".join(b"\x3f" + b"a" * 63 for _ in range(3))
    fits = longest + b"\x3d" + b"a" * 61 + b"\x00"

    (facts,) = decode_capture(
        _pcap(_ipv4(17, _udp(_dns(question=fits)))), frozenset({1})
    ).values()

    assert facts.dns_qry_type == 28
    assert "exceeds 255 bytes" in str(
        _refusal(_pcap(_ipv4(17, _udp(_dns(question=labels + b"\x00")))))
    )
    assert "name out of bounds" in str(
        _refusal(_pcap(_ipv4(17, _udp(_dns()[:20]))))
    )
    assert "question out of bounds" in str(
        _refusal(_pcap(_ipv4(17, _udp(_dns()[:-2]))))
    )


@pytest.mark.parametrize(
    "data,dns_frames,reason",
    [
        (b"\0" * 10, frozenset[int](), "PCAP header"),
        (
            _pcap(
                header=struct.pack(">IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
            ),
            frozenset[int](),
            "little-endian",
        ),
        (
            _pcap(
                header=struct.pack(
                    "<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 101
                )
            ),
            frozenset[int](),
            "little-endian",
        ),
        (_pcap(), frozenset[int](), "no frames"),
        (
            _pcap(_ipv4(17, _udp(b""), ethernet=_ETHERNET[:12] + b"\x08\x06")),
            frozenset[int](),
            "not IPv4",
        ),
        (
            _pcap(_ipv4(17, _udp(b""), first_byte=0x44)),
            frozenset[int](),
            "IPv4 header",
        ),
        (
            _pcap(_ipv4(17, _udp(b""), first_byte=0x65)),
            frozenset[int](),
            "IPv4 header",
        ),
        (
            _pcap(_ipv4(17, _udp(b""), fragment=0x2000)),
            frozenset[int](),
            "fragment",
        ),
        (
            _pcap(_ipv4(1, b"\x08\0\0\0\0\0\0\0")),
            frozenset[int](),
            "neither TCP",
        ),
        (_pcap(_ipv4(6, _tcp(b"")[:19])), frozenset[int](), "TCP header"),
        (
            _pcap(_ipv4(6, _tcp(b"", offset_byte=0x60))),
            frozenset[int](),
            "data offset",
        ),
        (
            _pcap(_ipv4(6, _tcp(b"", offset_byte=0x40))),
            frozenset[int](),
            "data offset",
        ),
        (_pcap(_ipv4(6, _tcp(b"", flags=0x210))), frozenset[int](), "reserved"),
        (
            _pcap(_ipv4(17, _udp(b"x")[:-2] + b"x")),
            frozenset[int](),
            "UDP length",
        ),
        (_pcap(_ipv4(17, _udp(b"\0" * 11))), frozenset({1}), "DNS header"),
        (_pcap(_ipv4(6, _tcp(_dns()))), frozenset({1}), "DNS over TCP"),
        (_pcap(_ipv4(6, _tcp(b"\0"))), frozenset({1}), "DNS over TCP"),
    ],
)
def test_any_other_surprise_is_unreadable(
    data: bytes, dns_frames: frozenset[int], reason: str
) -> None:
    error = _refusal(data, dns_frames)

    assert error.code == "facts_unreadable"
    assert reason in str(error)


def test_a_capture_past_the_frame_bound_is_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(counterexample_module, "MAX_FRAME_NUMBER", 1)

    error = _refusal(capture_bytes(("syn", "ack"), 5), frozenset())

    assert str(error) == "Feedback capture frame 2: too many frames"


def test_a_dns_frame_the_capture_lacks_is_unproven() -> None:
    data = capture_bytes(("udp-query",), 5)

    assert _refusal(data, frozenset({1, 2})).code == "facts_unproven"


def test_the_header_facts_schema_is_closed() -> None:
    hostile: list[dict[str, object]] = [
        {"ip.src": "192.0.2.1 || frame"},
        {"ip.src": "192.000.002.001"},
        {"ip.src": "::1"},
        {"ip_src": "192.0.2.1"},
        {"dns.qry.name": "witness-1.example"},
        {"tcp.flags": ("SYN; drop",)},
        {"tcp.flags": ("ACK", "SYN")},
        {"tcp.flags": ("SYN", "SYN")},
        {"tcp.flags": ["SYN"]},
        {"ip.ttl": 256},
        {"ip.ttl": "64"},
        {"ip.ttl": True},
        {"ip.dsfield.ecn": 4},
        {"tcp.srcport": 1, "udp.dstport": 2},
        {"dns.flags.response": False, "dns.flags.rcode": 0},
        {"dns.qry.type": 1},
        {"dns.flags.response": 1},
    ]

    for values in hostile:
        with pytest.raises(ValidationError):
            HeaderFactsV1.model_validate(values)
    assert _facts(ip__src="10.1.2.3").ip_src == "10.1.2.3"


def test_a_capture_that_differs_from_its_digest_is_never_decoded(
    tmp_path: Path,
) -> None:
    data = capture_bytes(("udp-query",), 5)
    capture = tmp_path / "probe.pcap"
    capture.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    link = tmp_path / "link.pcap"
    link.symlink_to(capture)
    small = TsharkRunner(
        tshark="dfilterforge-no-such-tshark",
        limits=RunnerLimits(max_capture_bytes=len(data) - 1),
    )
    calls: list[tuple[Path, str, TsharkRunner]] = [
        (capture, "0" * 64, _NO_TSHARK),
        (capture, digest, small),
        (link, digest, _NO_TSHARK),
        (tmp_path, digest, _NO_TSHARK),
        (tmp_path / "missing.pcap", digest, _NO_TSHARK),
    ]

    for path, expected, runner in calls:
        with pytest.raises(CounterexampleError) as error:
            read_frame_facts(path, expected, runner)
        assert error.value.code == "facts_unreadable"
    with pytest.raises(CounterexampleError) as reached:
        read_frame_facts(capture, digest, _NO_TSHARK)
    assert reached.value.code == "facts_unproven"
    assert str(reached.value).endswith("tshark_unavailable")


def test_tshark_must_read_the_bytes_the_decoder_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = capture_bytes(("udp-query",), 5)
    capture = tmp_path / "probe.pcap"
    capture.write_bytes(data)
    runner = TsharkRunner()

    def changed(path: Path, display_filter: str) -> RunResult:
        del path, display_filter
        return RunResult(frames=(1,), runtime_ms=1.0, capture_sha256="f" * 64)

    monkeypatch.setattr(runner, "run", changed)

    with pytest.raises(CounterexampleError) as error:
        read_frame_facts(capture, hashlib.sha256(data).hexdigest(), runner)

    assert error.value.code == "facts_unreadable"
    assert str(error.value) == "Feedback capture changed while it was read"


@_POSIX_ONLY
def test_tshark_confirms_every_frame_of_both_feedback_probes(
    feedback: FeedbackProbes,
) -> None:
    runner = TsharkRunner()

    for probe in feedback.probes:
        data = probe.capture_path.read_bytes()
        facts = read_frame_facts(
            probe.capture_path, hashlib.sha256(data).hexdigest(), runner
        )

        assert list(facts) == list(range(1, len(probe.recipes) + 1))
        for frame, recipe in enumerate(probe.recipes, 1):
            dns = facts[frame].dns_flags_response is not None
            # mDNS carries the DNS header fields under its own protocol.
            assert dns == (
                "query" in recipe
                or "dns" in recipe
                or recipe
                in {"udp-response", "udp-aaaa", "udp-nxdomain", "udp-both-53"}
            ), recipe
    assert [len(probe.recipes) for probe in feedback.probes] == [62, 63]


@_POSIX_ONLY
def test_a_decoded_value_tshark_does_not_confirm_stops_the_facts(
    feedback: FeedbackProbes, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = feedback.probes[0]
    data = probe.capture_path.read_bytes()
    decode: Callable[[bytes, frozenset[int]], dict[int, HeaderFactsV1]] = (
        counterexample_module.decode_capture
    )

    def drifted(
        capture: bytes, dns_frames: frozenset[int]
    ) -> dict[int, HeaderFactsV1]:
        facts = decode(capture, dns_frames)
        facts[2] = facts[2].model_copy(update={"ip_ttl": 63})
        return facts

    monkeypatch.setattr(counterexample_module, "decode_capture", drifted)

    with pytest.raises(CounterexampleError) as error:
        read_frame_facts(
            probe.capture_path,
            hashlib.sha256(data).hexdigest(),
            TsharkRunner(),
        )

    assert error.value.code == "facts_unproven"
    assert str(error.value) == "tshark does not confirm the facts of frame 2"
