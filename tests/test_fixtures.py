"""Checks reproducible fixture artifacts and live multi-probe witnesses."""

import hashlib
import json
from pathlib import Path
import struct

import pytest

from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.fixtures import generate_fixtures
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.runner import TsharkRunner


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_fixture_generation_is_byte_stable_and_preserves_other_files(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_fixtures(first)
    generate_fixtures(second)
    original = _snapshot(first)
    assert original == _snapshot(second)
    assert len(original) == 16

    (first / "unrelated.txt").write_text("keep", encoding="utf-8")
    (first / "captures/tcp-syn-no-ack-17.pcap").write_bytes(b"replace me")
    generate_fixtures(first)

    assert (first / "unrelated.txt").read_text(encoding="utf-8") == "keep"
    assert all(
        (first / name).read_bytes() == data for name, data in original.items()
    )


def test_fixture_manifest_specs_and_checksums_agree(tmp_path: Path) -> None:
    manifest_path = generate_fixtures(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["seeds"] == [17, 42, 2026]
    assert manifest["split"] == "pilot"
    assert manifest["license"] == "MIT"
    assert manifest["review_status"] == "reviewed"
    assert len(manifest["cases"]) == 3
    capture_hashes: set[str] = set()
    for case in manifest["cases"]:
        spec_bytes = (tmp_path / case["spec_path"]).read_bytes()
        intent_bytes = (tmp_path / case["intent_path"]).read_bytes()
        assert hashlib.sha256(spec_bytes).hexdigest() == case["spec_sha256"]
        assert hashlib.sha256(intent_bytes).hexdigest() == case["intent_sha256"]
        spec = SemanticSpecV1.model_validate_json(spec_bytes)
        intent = IntentIrV1.model_validate_json(intent_bytes)
        assert spec.canonical_ir == intent
        assert spec.task_id == case["task_id"]
        assert spec.split == "pilot"
        assert spec.license == "MIT"
        assert spec.provenance == manifest["provenance"]
        assert spec.review_status == "reviewed"
        assert len(spec.probes) == 3
        for expected, probe in zip(spec.probes, case["probes"], strict=True):
            capture = (tmp_path / probe["capture_path"]).read_bytes()
            capture_hash = hashlib.sha256(capture).hexdigest()
            capture_hashes.add(capture_hash)
            assert (
                expected.capture_sha256
                == capture_hash
                == probe["capture_sha256"]
            )
            assert expected.probe_id == probe["probe_id"]
            assert probe["capture_path"] == f"captures/{expected.probe_id}.pcap"
            assert expected.expected_frames == tuple(probe["expected_frames"])
            assert probe["expected_frames"]
            assert probe["near_wrong_frames"] != probe["expected_frames"]
            assert max(probe["near_wrong_frames"]) <= probe["packet_count"]
    assert len(capture_hashes) == 9


def test_generated_pcaps_have_complete_ethernet_ipv4_packets(
    tmp_path: Path,
) -> None:
    generate_fixtures(tmp_path)
    for path in (tmp_path / "captures").glob("*.pcap"):
        capture = path.read_bytes()
        assert struct.unpack("<IHHIIII", capture[:24]) == (
            0xA1B2C3D4,
            2,
            4,
            0,
            0,
            65535,
            1,
        )
        offset = 24
        packet_count = 0
        while offset < len(capture):
            _, microseconds, captured, original = struct.unpack(
                "<IIII",
                capture[offset : offset + 16],
            )
            assert 0 <= microseconds < 1000000
            assert captured == original >= 60
            packet = capture[offset + 16 : offset + 16 + captured]
            assert len(packet) == captured
            assert packet[12:14] == b"\x08\x00"
            assert packet[14] == 0x45
            ip_length = int.from_bytes(packet[16:18], "big")
            assert ip_length + 14 <= len(packet)
            header_sum = sum(struct.unpack("!10H", packet[14:34]))
            while header_sum >> 16:
                header_sum = (header_sum & 0xFFFF) + (header_sum >> 16)
            assert header_sum == 0xFFFF
            segment = packet[34 : 14 + ip_length]
            protocol = packet[23]
            assert protocol in (6, 17)
            pseudo_header = packet[26:34] + bytes((0, protocol))
            pseudo_header += len(segment).to_bytes(2, "big")
            checksum_input = pseudo_header + segment
            if len(checksum_input) % 2:
                checksum_input += b"\0"
            transport_sum = sum(
                int.from_bytes(checksum_input[index : index + 2], "big")
                for index in range(0, len(checksum_input), 2)
            )
            while transport_sum >> 16:
                transport_sum = (transport_sum & 0xFFFF) + (transport_sum >> 16)
            assert transport_sum == 0xFFFF
            offset += captured + 16
            packet_count += 1
        assert offset == len(capture)
        assert packet_count >= 4


@pytest.mark.parametrize(
    "task_id",
    ("tcp-syn-no-ack", "dns-udp-query", "udp-destination-53"),
)
def test_live_tshark_matches_labels_and_kills_near_wrong_filters(
    tmp_path: Path,
    task_id: str,
) -> None:
    manifest = json.loads(
        generate_fixtures(tmp_path).read_text(encoding="utf-8")
    )
    case = next(
        case for case in manifest["cases"] if case["task_id"] == task_id
    )
    spec = SemanticSpecV1.model_validate_json(
        (tmp_path / case["spec_path"]).read_bytes(),
    )
    runner = TsharkRunner()
    assert runner.version() == "4.6.8"
    candidate_filter = compile_intent(spec.canonical_ir)
    for probe in case["probes"]:
        capture = tmp_path / probe["capture_path"]
        candidate = runner.run(capture, candidate_filter)
        reference = runner.run(capture, spec.reference_filter)
        mutation = runner.run(capture, case["near_wrong_filter"])
        assert candidate.capture_sha256 == reference.capture_sha256
        assert candidate.capture_sha256 == probe["capture_sha256"]
        assert (
            candidate.frames
            == reference.frames
            == tuple(probe["expected_frames"])
        )
        assert mutation.frames == tuple(probe["near_wrong_frames"])
        assert mutation.frames != candidate.frames
