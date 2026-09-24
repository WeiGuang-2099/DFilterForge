"""Tests for the held-out model split and its leak-free model inputs."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from dfilterforge.benchmark import generate_benchmark
from dfilterforge.benchmark import RECIPES
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelGoldV1
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.witnesses import WITNESS_NAMES

_ALLOWED_KEYS = {"item_id", "intent", "user_assumptions", "split"}


def _split(tmp_path: Path) -> tuple[ModelSplitArtifacts, list[str]]:
    artifacts = generate_model_split(tmp_path / "split")
    lines = artifacts.inputs_path.read_text(encoding="utf-8").splitlines()
    return artifacts, lines


def test_model_inputs_lines_contain_exactly_the_allowed_keys(
    tmp_path: Path,
) -> None:
    artifacts, lines = _split(tmp_path)

    assert len(lines) == 2 * len(model_semantic_cases()) == 48
    documents = [json.loads(line) for line in lines]
    assert all(set(document) == _ALLOWED_KEYS for document in documents)
    items = [
        ModelInputItemV1.model_validate(document) for document in documents
    ]
    assert tuple(items) == artifacts.inputs
    item_ids = [item.item_id for item in items]
    assert len(set(item_ids)) == len(item_ids)
    assert all(re.fullmatch(r"mei-\d{4}", item_id) for item_id in item_ids)
    assert {item.split for item in items} == {"dev", "test"}


def test_model_inputs_never_leak_evaluator_gold(tmp_path: Path) -> None:
    artifacts, lines = _split(tmp_path)
    text = "\n".join(lines)

    for marker in (
        "reference_filter",
        "mutation_filter",
        "expected_frames",
        "intent_ir",
        "canonical_ir",
        "case_id",
        "probe",
        "sha256",
    ):
        assert marker not in text
    for case in artifacts.gold.cases:
        assert case.case_id not in text
        assert case.spec.reference_filter not in text
        assert case.mutation_filter not in text
        assert case.spec.canonical_ir.model_dump_json() not in text
        for probe in case.spec.probes:
            assert probe.probe_id not in text
            assert probe.capture_sha256 not in text
            frames = list(probe.expected_frames)
            assert json.dumps(frames) not in text
            assert repr(tuple(frames)) not in text


def test_every_gold_case_routes_exactly_two_distinct_paraphrases(
    tmp_path: Path,
) -> None:
    artifacts, _ = _split(tmp_path)
    gold = artifacts.gold
    inputs = {item.item_id: item for item in artifacts.inputs}
    cases = {case.case_id: case for case in gold.cases}

    assert set(gold.item_to_case) == set(inputs)
    assert set(Counter(gold.item_to_case.values()).values()) == {2}
    for case_id, case in cases.items():
        routed = [
            inputs[item_id]
            for item_id, target in gold.item_to_case.items()
            if target == case_id
        ]
        assert len(routed) == 2
        assert len({item.intent for item in routed}) == 2
        assert {item.split for item in routed} == {case.spec.split}
        assert case.spec.intent in {item.intent for item in routed}
    assert (
        ModelGoldV1.model_validate_json(artifacts.gold_path.read_bytes())
        == gold
    )


def test_dev_and_test_captures_are_disjoint_and_hash_verified(
    tmp_path: Path,
) -> None:
    artifacts, _ = _split(tmp_path)
    probe_ids = {
        split: {
            probe.probe_id
            for case in artifacts.gold.cases
            if case.spec.split == split
            for probe in case.spec.probes
        }
        for split in ("dev", "test")
    }
    captures = {path.stem: path for path in artifacts.capture_paths}

    assert probe_ids["dev"] and probe_ids["test"]
    assert not probe_ids["dev"] & probe_ids["test"]
    assert set(captures) == probe_ids["dev"] | probe_ids["test"]
    for case in artifacts.gold.cases:
        for probe in case.spec.probes:
            digest = hashlib.sha256(
                captures[probe.probe_id].read_bytes()
            ).hexdigest()
            assert digest == probe.capture_sha256


def _packets(capture: bytes) -> list[bytes]:
    """Splits a little-endian PCAP into its packet bytes."""
    packets: list[bytes] = []
    offset = 24
    while offset < len(capture):
        length = int.from_bytes(capture[offset + 8 : offset + 12], "little")
        packets.append(capture[offset + 16 : offset + 16 + length])
        offset += 16 + length
    return packets


def test_generation_is_deterministic_and_mutations_stay_distinguishable(
    tmp_path: Path,
) -> None:
    first, _ = _split(tmp_path / "one")
    second, _ = _split(tmp_path / "two")
    benchmark = {
        probe.probe_id: probe
        for probe in generate_benchmark(tmp_path / "benchmark")
    }
    probes = {probe.probe_id: probe for probe in first.probes}
    cases = {case.case_id: case for case in model_semantic_cases()}

    assert first.inputs_path.read_bytes() == second.inputs_path.read_bytes()
    assert first.gold_path.read_bytes() == second.gold_path.read_bytes()
    for gold_case in first.gold.cases:
        case = cases[gold_case.case_id]
        canonical = {
            probe.probe_id: probe.expected_frames
            for probe in gold_case.spec.probes
        }
        for probe_id, frames in canonical.items():
            probe = probes[probe_id]
            original = benchmark[probe_id]
            assert frames == case.labels(probe)
            assert frames
            assert len(frames) < len(probe.recipes)
            # The witness tail leaves the benchmark frames' labels alone.
            assert tuple(
                frame for frame in frames if frame <= len(original.recipes)
            ) == case.labels(original)
        assert any(
            case.labels(probes[probe_id], mutation=True) != frames
            for probe_id, frames in canonical.items()
        )


def test_probe_copies_keep_benchmark_bytes_and_share_no_packet(
    tmp_path: Path,
) -> None:
    artifacts, _ = _split(tmp_path)
    benchmark = {
        probe.probe_id: probe
        for probe in generate_benchmark(tmp_path / "benchmark")
    }
    splits = {
        probe.probe_id: case.spec.split
        for case in artifacts.gold.cases
        for probe in case.spec.probes
    }
    packets: dict[str, set[bytes]] = {"dev": set(), "test": set()}

    for probe in artifacts.probes:
        original = benchmark[probe.probe_id]
        capture = probe.capture_path.read_bytes()
        assert capture.startswith(original.capture_path.read_bytes())
        assert probe.recipes == original.recipes + WITNESS_NAMES
        found = _packets(capture)
        assert len(found) == len(probe.recipes)
        packets[splits[probe.probe_id]].update(found)
    assert not packets["dev"] & packets["test"]


def test_every_oracle_name_is_a_recipe_or_a_witness() -> None:
    known = set(RECIPES) | set(WITNESS_NAMES)

    for case in model_semantic_cases():
        oracle = case.recipe_oracle
        assert oracle.canonical | oracle.mutation <= known, case.case_id
        assert oracle.canonical != oracle.mutation, case.case_id


def test_case_readings_reach_the_gold_but_never_the_model(
    tmp_path: Path,
) -> None:
    artifacts, lines = _split(tmp_path)
    text = "\n".join(lines)
    shared = min(
        (case.spec.assumptions for case in artifacts.gold.cases), key=len
    )
    readings = {
        case.case_id: case.spec.assumptions[len(shared) :]
        for case in artifacts.gold.cases
        if case.spec.assumptions != shared
    }

    # Only the mDNS reading of "all DNS responses" is case-specific.
    assert list(readings) == ["fin-or-dns-response"]
    for case in artifacts.gold.cases:
        assert case.spec.assumptions[: len(shared)] == shared
    (reading,) = readings["fin-or-dns-response"]
    assert "mDNS" in reading
    assert reading not in text
