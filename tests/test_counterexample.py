"""Counterexample cards: frame facts, tshark confirmation and leak tests."""

from collections import Counter
from collections import defaultdict
from collections.abc import Callable, Sequence
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import Any

from pydantic import ValidationError
import pytest

from dfilterforge import counterexample as counterexample_module
from dfilterforge.benchmark import capture_bytes
from dfilterforge.benchmark import RECIPES
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.counterexample import card_json
from dfilterforge.counterexample import CARD_MAX_BYTES
from dfilterforge.counterexample import CardBuilder
from dfilterforge.counterexample import CounterexampleError
from dfilterforge.counterexample import decode_capture
from dfilterforge.counterexample import ErrorCardV1
from dfilterforge.counterexample import FrameFactV1
from dfilterforge.counterexample import frames_card
from dfilterforge.counterexample import FramesCardV1
from dfilterforge.counterexample import HeaderFactsV1
from dfilterforge.counterexample import MAX_CARD_FRAMES
from dfilterforge.counterexample import proof_filter
from dfilterforge.counterexample import read_frame_facts
from dfilterforge.counterexample import SHOWN_FIELDS
from dfilterforge.counterexample import TCP_FLAG_NAMES
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import CatalogError
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.live import LiveError
from dfilterforge.model_feedback import FeedbackProbes
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.model_split import MUTANT_WAIVERS
from dfilterforge.mutants import single_site_mutants
from dfilterforge.runner import RunnerError
from dfilterforge.runner import RunnerLimits
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner
from dfilterforge.witnesses import WITNESS_NAMES

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


@pytest.fixture(name="builder", scope="module")
def fixture_builder(
    split: ModelSplitArtifacts, feedback: FeedbackProbes
) -> CardBuilder:
    """A builder whose split keeps no scored capture: feedback alone."""
    for capture in split.capture_paths:
        capture.unlink()
    return CardBuilder(feedback)


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
    # Three 63-byte labels, a fourth label and the terminator: the wire
    # name, length octets included, is 255 bytes with a 61-byte fourth
    # label and one byte over with a 62-byte one.
    longest = b"".join(b"\x3f" + b"a" * 63 for _ in range(3))
    fits = longest + b"\x3d" + b"a" * 61 + b"\x00"
    over = longest + b"\x3e" + b"a" * 62 + b"\x00"

    (facts,) = decode_capture(
        _pcap(_ipv4(17, _udp(_dns(question=fits)))), frozenset({1})
    ).values()

    assert (len(fits), len(over)) == (255, 256)
    assert facts.dns_qry_type == 28
    assert str(_refusal(_pcap(_ipv4(17, _udp(_dns(question=over)))))) == (
        "Feedback capture frame 1: DNS question name exceeds 255 bytes"
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
    assert _facts(ip__src=None) == _facts()


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


def _probe(expected: Sequence[int], candidate: Sequence[int]) -> ProbeResultV1:
    return evaluate_probe("semantic-29", tuple(expected), tuple(candidate), 1.0)


def _shown(card: FramesCardV1) -> list[tuple[int, bool, bool]]:
    return [
        (fact.frame, fact.answer_matched, fact.should_match)
        for fact in card.frames
    ]


def _worst(ttl: int) -> HeaderFactsV1:
    """The longest entry the schema allows: TCP and DNS, every value wide."""
    return _facts(
        ip__src="255.255.255.255",
        ip__dst="255.255.255.255",
        ip__ttl=ttl,
        ip__dsfield__ecn=3,
        tcp__srcport=65535,
        tcp__dstport=65535,
        tcp__flags=TCP_FLAG_NAMES,
        tcp__len=65535,
        dns__flags__response=True,
        dns__flags__rcode=15,
        dns__qry__type=65535,
    )


def _udp_facts(source: int, destination: int = 53) -> HeaderFactsV1:
    return _facts(
        ip__src="192.0.2.9",
        ip__dst="198.51.100.7",
        ip__ttl=64,
        udp__srcport=source,
        udp__dstport=destination,
    )


def test_frames_alternate_missed_and_wrong_in_frame_order() -> None:
    facts = {frame: _facts(ip__ttl=frame) for frame in range(1, 13)}

    # Frame 1 agrees; 5, 9 and 12 are missed; 2 and 7 wrongly selected.
    card = frames_card(_probe((1, 12, 5, 9), (7, 1, 2)), facts)
    short = frames_card(_probe((5,), (2, 7, 8)), facts)
    two = frames_card(_probe((), (4, 3)), facts)

    assert _shown(card) == [
        (5, False, True),
        (2, True, False),
        (9, False, True),
    ]
    assert [fact.frame for fact in short.frames] == [5, 2, 7]
    assert [fact.frame for fact in two.frames] == [3, 4]


def test_a_frame_equal_but_for_its_number_and_ephemeral_ports_is_skipped() -> (
    None
):
    facts = {
        1: _udp_facts(41000),
        # Differs from 1 only by an ephemeral port.
        2: _udp_facts(51254),
        3: _udp_facts(40999),
        4: _udp_facts(41005),
        5: _udp_facts(51255),
        # Equal to 1, but wrongly selected rather than missed.
        6: _udp_facts(41000),
        7: _udp_facts(41000, 41001),
    }

    card = frames_card(_probe((1, 2, 3, 4, 5), (6,)), facts)
    after_repeats = frames_card(_probe((1, 2, 4, 5), ()), facts)
    both_ports = frames_card(_probe((1, 7), ()), facts)

    assert _shown(card) == [
        (1, False, True),
        (6, True, False),
        (3, False, True),
    ]
    assert [fact.frame for fact in after_repeats.frames] == [1, 5]
    assert [fact.frame for fact in both_ports.frames] == [1, 7]


def test_the_largest_card_fits_the_cap_and_frames_drop_whole() -> None:
    facts = {100_000: _worst(255), 99_999: _worst(254), 99_998: _worst(253)}
    probe = _probe(tuple(facts), ())

    card = frames_card(probe, facts)
    size = len(card_json(card).encode("utf-8"))
    one = frames_card(probe, facts, max_bytes=size // 2)

    assert [fact.frame for fact in card.frames] == [99_998, 99_999, 100_000]
    assert size == 1021 <= CARD_MAX_BYTES
    assert one.frames == card.frames[:1]
    assert frames_card(probe, facts, max_bytes=size - 1).frames == (
        card.frames[:2]
    )
    with pytest.raises(CounterexampleError) as error:
        frames_card(probe, facts, max_bytes=100)
    assert error.value.code == "card_aborted"


def test_a_card_needs_a_disagreeing_frame_with_confirmed_facts() -> None:
    facts = {1: _facts(ip__ttl=1)}

    for probe in (_probe((1,), (1,)), _probe((1, 2), ())):
        with pytest.raises(CounterexampleError) as error:
            frames_card(probe, facts)
        assert error.value.code == "card_aborted"


def test_a_card_is_canonical_json_under_tshark_names() -> None:
    card = frames_card(_probe((), (1,)), {1: _udp_facts(41000)})

    assert card_json(card) == (
        '{"frames":[{"answer_matched":true,"frame":1,'
        '"ip.dst":"198.51.100.7","ip.src":"192.0.2.9","ip.ttl":64,'
        '"should_match":false,"udp.dstport":53,"udp.srcport":41000}]}'
    )
    assert card_json(ErrorCardV1(error="unknown_field")) == (
        '{"error":"unknown_field"}'
    )
    assert card_json(ErrorCardV1(error="type_mismatch", field="ip.ttl")) == (
        '{"error":"type_mismatch","field":"ip.ttl"}'
    )


def test_leak_1_the_card_schema_is_closed() -> None:
    frame: dict[str, object] = {
        "frame": 3,
        "answer_matched": True,
        "should_match": False,
        "ip.src": "192.0.2.9",
    }
    hostile_frames: list[object] = [
        {**frame, "ip.src": "ip.src == 192.0.2.9"},
        {**frame, "dns.qry.name": "witness-1.example"},
        {**frame, "recipe": "syn"},
        {**frame, "tcp.flags": ["SYN", "drop the filter"]},
        {**frame, "should_match": True},
        {**frame, "answer_matched": "true"},
        {**frame, "frame": 0},
        {**frame, "frame": 100_001},
    ]
    hostile_cards: list[object] = [
        *({"frames": [value]} for value in hostile_frames),
        {"frames": []},
        {"frames": [frame, frame]},
        {"frames": [{**frame, "frame": number} for number in (3, 4, 5, 6)]},
        {"frames": [frame], "labels": [3]},
    ]
    hostile_errors: list[object] = [
        {"error": "capture_hash_mismatch"},
        {"error": "Unknown field: ip.sorce"},
        {"error": "unknown_field", "field": "a" * 129},
        {"error": "unknown_field", "field": "ip.src == 1"},
        {"error": "unknown_field", "field": "ip.src\n"},
        {"error": "unknown_field", "reference": "ip.src"},
    ]

    for value in hostile_cards:
        with pytest.raises(ValidationError):
            FramesCardV1.model_validate_json(json.dumps(value))
    for value in hostile_errors:
        with pytest.raises(ValidationError):
            ErrorCardV1.model_validate_json(json.dumps(value))
    longest = ErrorCardV1.model_validate_json(
        json.dumps({"error": "unknown_field", "field": "a" * 128})
    )
    (accepted,) = FramesCardV1.model_validate_json(
        json.dumps({"frames": [frame]})
    ).frames
    assert longest.field == "a" * 128
    assert isinstance(accepted, FrameFactV1)
    assert accepted.ip_src == "192.0.2.9"


def test_a_harness_failure_never_becomes_a_card(
    feedback: FeedbackProbes, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = CardBuilder(feedback, _NO_TSHARK)

    def broken(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise LiveError("capture_hash_mismatch", "bounded message")

    monkeypatch.setattr(counterexample_module, "evaluate_live", broken)

    for case_id in ("dns-a-queries", "no-such-case"):
        with pytest.raises(CounterexampleError) as error:
            builder.card(case_id, "tcp")
        assert error.value.code == "card_aborted"
    with pytest.raises(CounterexampleError) as unknown:
        CardBuilder(
            FeedbackProbes(feedback.capture_dir, (), feedback.specs),
            _NO_TSHARK,
        ).facts(feedback.specs["dns-a-queries"].probes[0])
    assert unknown.value.code == "card_aborted"


def test_a_field_lookup_that_fails_for_the_harness_stops_the_card(
    feedback: FeedbackProbes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CatalogError("unknown_field", "bounded message")

    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CatalogError("catalog_unavailable", "bounded message")

    monkeypatch.setattr(counterexample_module, "evaluate_live", unknown)
    monkeypatch.setattr(counterexample_module, "bind_catalog", unavailable)
    answer = IntentIrV1(
        expression=Predicate(field="ip.sorce", operator=Operator.EXISTS)
    )

    with pytest.raises(CounterexampleError) as error:
        CardBuilder(feedback, _NO_TSHARK).card("dns-a-queries", answer)

    assert error.value.code == "card_aborted"
    assert str(error.value) == "Field lookup failed: catalog_unavailable"


@_POSIX_ONLY
@pytest.mark.parametrize("clean", [True, False])
def test_a_resource_bound_is_the_answers_only_if_the_reference_reruns_clean(
    feedback: FeedbackProbes, monkeypatch: pytest.MonkeyPatch, clean: bool
) -> None:
    real = counterexample_module.evaluate_live
    spec = feedback.specs["dns-a-queries"]

    def bounded(
        rerun: SemanticSpecV1,
        candidate: IntentIrV1 | str,
        capture_root: Path,
        **kwargs: Any,
    ) -> tuple[EvaluationReceiptV1, LiveEnvironmentV1]:
        if clean and candidate == rerun.canonical_ir:
            return real(rerun, candidate, capture_root, **kwargs)
        raise RunnerError("timeout", "bounded message")

    monkeypatch.setattr(counterexample_module, "evaluate_live", bounded)
    builder = CardBuilder(feedback)

    if clean:
        assert builder.card(spec.task_id, "tcp") == ErrorCardV1(error="timeout")
    else:
        with pytest.raises(CounterexampleError) as error:
            builder.card(spec.task_id, "tcp")
        assert str(error.value) == "dns-a-queries: timeout"


@_POSIX_ONLY
def test_no_field_is_named_when_no_predicate_raises_the_code_alone(
    feedback: FeedbackProbes, monkeypatch: pytest.MonkeyPatch
) -> None:
    def mismatch(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise CatalogError("type_mismatch", "bounded message")

    monkeypatch.setattr(counterexample_module, "evaluate_live", mismatch)
    answer = IntentIrV1(
        expression=Predicate(field="ip.ttl", operator=Operator.EQ, value=64)
    )

    assert CardBuilder(feedback).card("dns-a-queries", answer) == (
        ErrorCardV1(error="type_mismatch")
    )


@_POSIX_ONLY
def test_an_invalid_answer_gets_its_code_and_its_first_refused_field(
    builder: CardBuilder,
) -> None:
    def ir(*predicates: Predicate) -> IntentIrV1:
        if len(predicates) == 1:
            return IntentIrV1(expression=predicates[0])
        return IntentIrV1(expression=All(children=predicates))

    mismatch = Predicate(
        field="ip.ttl", operator=Operator.EQ, value="sixty-four"
    )
    # Binding sorts names, so the answer-level error is about aa.unknown;
    # the card names the first refused field in reading order instead.
    answers: list[tuple[IntentIrV1 | str, ErrorCardV1]] = [
        (
            ir(
                mismatch,
                Predicate(field="zz.unknown", operator=Operator.EXISTS),
                Predicate(field="aa.unknown", operator=Operator.EXISTS),
            ),
            ErrorCardV1(error="unknown_field", field="zz.unknown"),
        ),
        (
            ir(Predicate(field="tcp", operator=Operator.EXISTS), mismatch),
            ErrorCardV1(error="type_mismatch", field="ip.ttl"),
        ),
        (
            ir(
                Predicate(
                    field="dns.qry.name", operator=Operator.EQ, value="a\x01"
                )
            ),
            ErrorCardV1(error="invalid_value", field="dns.qry.name"),
        ),
        (
            ir(Predicate(field="a" * 129, operator=Operator.EXISTS)),
            ErrorCardV1(error="unknown_field"),
        ),
        ("ip.src ==", ErrorCardV1(error="filter_rejected")),
        ("ip.sorce == 1", ErrorCardV1(error="filter_unknown_field")),
    ]

    for answer, expected in answers:
        assert builder.card("dns-a-queries", answer) == expected


def _gold_texts(case: ModelGoldCaseV1, runner: TsharkRunner) -> set[str]:
    """The gold filters a card must never contain, in both spellings.

    A bare protocol leaf such as ``dns`` is field vocabulary, not gold.
    """
    canonical = case.spec.canonical_ir
    leaves = [
        IntentIrV1(expression=predicate)
        for _, predicate in walk_predicates(canonical.expression)
        if predicate.operator is not Operator.EXISTS
    ]
    catalog = bind_catalog(runner, (canonical,))
    return {
        case.spec.reference_filter,
        *(compile_intent(ir) for ir in (canonical, *leaves)),
        *(compile_intent(ir, catalog) for ir in (canonical, *leaves)),
    }


def _walked(card: FramesCardV1, probe: ProbeResultV1) -> list[int]:
    """The frames the selection walk reached before it stopped."""
    missed, wrong = probe.reference_only, probe.candidate_only
    order = [
        frame
        for index in range(max(len(missed), len(wrong)))
        for frame in (*missed[index : index + 1], *wrong[index : index + 1])
    ]
    if len(card.frames) < MAX_CARD_FRAMES:
        return order
    return order[: order.index(card.frames[-1].frame) + 1]


@_POSIX_ONLY
def test_leak_2_mutations_and_killed_mutants_get_cards_without_gold(
    split: ModelSplitArtifacts, feedback: FeedbackProbes, builder: CardBuilder
) -> None:
    runner = TsharkRunner()
    waived = {(waiver.case_id, waiver.edit) for waiver in MUTANT_WAIVERS}
    items: dict[str, set[str]] = defaultdict(set)
    for item_id, case_id in split.gold.item_to_case.items():
        items[case_id].add(item_id)
    captures = {probe.probe_id: probe.capture_path for probe in feedback.probes}
    names = {*RECIPES, *WITNESS_NAMES}
    counted: Counter[str] = Counter()

    for case in split.gold.cases:
        (expected,) = feedback.specs[case.case_id].probes
        forbidden = {
            case.case_id,
            *items[case.case_id],
            expected.probe_id,
            *(probe.probe_id for probe in case.spec.probes),
            *names,
            *_gold_texts(case, runner),
        }
        candidates: list[IntentIrV1 | str] = [
            case.mutation_filter,
            *(
                mutant.intent
                for mutant in single_site_mutants(case.spec.canonical_ir)
                if (case.case_id, mutant.edit) not in waived
            ),
        ]
        for candidate in candidates:
            card = builder.card(case.case_id, candidate)
            assert isinstance(card, FramesCardV1), (case.case_id, candidate)
            text = card_json(card)
            assert len(text.encode("utf-8")) <= CARD_MAX_BYTES
            assert not {value for value in forbidden if value in text}
            display = (
                candidate
                if isinstance(candidate, str)
                else compile_intent(
                    candidate, bind_catalog(runner, (candidate,))
                )
            )
            selected = runner.run(captures[expected.probe_id], display).frames
            for fact in card.frames:
                assert fact.should_match == (
                    fact.frame in expected.expected_frames
                )
                assert fact.answer_matched == (fact.frame in selected)
            counted[case.spec.split] += 1

    # 52 authored mutations and the 340 killed mutants.
    assert sum(counted.values()) == 392
    assert set(counted) == {"dev", "test"}


@_POSIX_ONLY
def test_leak_3_the_canonical_ir_never_gets_a_card(
    split: ModelSplitArtifacts, builder: CardBuilder
) -> None:
    for case in split.gold.cases:
        assert builder.card(case.case_id, case.spec.canonical_ir) is None


@_POSIX_ONLY
def test_leak_4_a_card_reads_labels_only_where_it_shows_them(
    split: ModelSplitArtifacts, feedback: FeedbackProbes, builder: CardBuilder
) -> None:
    runner = TsharkRunner()
    captures = {probe.probe_id: probe.capture_path for probe in feedback.probes}
    flips = 0

    for case in split.gold.cases:
        (expected,) = feedback.specs[case.case_id].probes
        facts = builder.facts(expected)
        labels = set(expected.expected_frames)
        selected = set(
            runner.run(captures[expected.probe_id], case.mutation_filter).frames
        )
        probe = evaluate_probe(
            expected.probe_id, tuple(labels), tuple(selected), 1.0
        )
        card = frames_card(probe, facts)
        text = card_json(card)
        assert builder.card(case.case_id, case.mutation_filter) == card
        # An agreeing frame stays agreeing when its label and the answer
        # flip together.
        for frame in (
            set(facts) - set(probe.reference_only) - set(probe.candidate_only)
        ):
            flipped = evaluate_probe(
                expected.probe_id,
                tuple(labels ^ {frame}),
                tuple(selected ^ {frame}),
                1.0,
            )
            assert card_json(frames_card(flipped, facts)) == text
            flips += 1
        # A disagreeing frame the walk never reached becomes agreeing when
        # its label flips.
        walked = _walked(card, probe)
        for frame in {*probe.reference_only, *probe.candidate_only} - set(
            walked
        ):
            flipped = evaluate_probe(
                expected.probe_id,
                tuple(labels ^ {frame}),
                tuple(selected),
                1.0,
            )
            assert card_json(frames_card(flipped, facts)) == text
            flips += 1

    assert flips > 1000


@_POSIX_ONLY
def test_leak_5_cards_need_no_scored_capture(
    split: ModelSplitArtifacts, builder: CardBuilder, tmp_path: Path
) -> None:
    fresh = generate_model_split(tmp_path / "split")
    with_captures = CardBuilder(generate_feedback_probes(fresh))

    assert not list((split.gold_path.parent / "captures").iterdir())
    assert all(path.is_file() for path in fresh.capture_paths)
    for case in split.gold.cases:
        before = with_captures.card(case.case_id, case.mutation_filter)
        after = builder.card(case.case_id, case.mutation_filter)
        assert before is not None and after is not None
        assert card_json(after) == card_json(before)
