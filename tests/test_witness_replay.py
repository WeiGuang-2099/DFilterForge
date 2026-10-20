"""Verifier v1: tail-free probes, cut labels and verdicts, with tshark.

The probes come from the split generator, the labels from its gold and the
benchmark recipes; the filters below are answers the committed hosted test
runs gave, replayed on both verifiers with the pinned tshark.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.benchmark import generate_benchmark
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.runner import TsharkRunner
from dfilterforge.witness_replay import ProbeFrames
from dfilterforge.witness_replay import ProbePair
from dfilterforge.witness_replay import replay
from dfilterforge.witness_replay import strip_witness_tail
from dfilterforge.witness_replay import tail_free
from dfilterforge.witness_replay import v1_labels
from dfilterforge.witness_replay import verdict
from dfilterforge.witness_replay import WitnessReplayError
from dfilterforge.witnesses import WITNESS_NAMES

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)

_ROOT = Path(__file__).resolve().parents[1]
_TEST_PROBES = ("semantic-31", "semantic-37", "semantic-43")
# The tail-free captures that
# docs/ablations/evidence/005-probe-adequacy-simplified.json measured; the
# test image carries no docs/ tree.
_V1_SHA256 = {
    "semantic-31": (
        "29b88f4757becf19f21b3b86c1c31920b688925b8f80798008af3e35773e804d"
    ),
    "semantic-37": (
        "d0d8a23552042a0d44168c4e0d7aeefbf11576290feae69b08232fbe8866d4fa"
    ),
    "semantic-43": (
        "0ca13772dd23204e106b60cb912a41b9e39db9e5c614850ded3b5a80ceac3a6a"
    ),
}
_TAIL_ONLY = {
    "dns-query-off-port-53",
    "fin-from-https-port",
    "tcp-from-https-port",
    "ttl-between",
}
_RUNNER = TsharkRunner()


@pytest.fixture(name="split", scope="module")
def fixture_split(
    tmp_path_factory: pytest.TempPathFactory,
) -> ModelSplitArtifacts:
    return generate_model_split(tmp_path_factory.mktemp("split"))


@pytest.fixture(name="probes", scope="module")
def fixture_probes(split: ModelSplitArtifacts) -> tuple[BenchmarkProbe, ...]:
    return tuple(
        probe for probe in split.probes if probe.probe_id in _TEST_PROBES
    )


@pytest.fixture(name="specs", scope="module")
def fixture_specs(split: ModelSplitArtifacts) -> dict[str, SemanticSpecV1]:
    return {
        case.case_id: case.spec
        for case in split.gold.cases
        if case.spec.split == "test"
    }


@pytest.fixture(name="pairs", scope="module")
def fixture_pairs(
    probes: tuple[BenchmarkProbe, ...],
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[ProbePair, ...]:
    return tail_free(probes, tmp_path_factory.mktemp("v1"))


def _scored(
    probes: tuple[BenchmarkProbe, ...], display_filter: str
) -> ProbeFrames:
    """One filter's frames on the scored captures, as the scorer ran it."""
    return tuple(
        _RUNNER.run(probe.capture_path, display_filter).frames
        for probe in probes
    )


def _labels(spec: SemanticSpecV1) -> ProbeFrames:
    return tuple(probe.expected_frames for probe in spec.probes)


def test_v1_is_a_prefix_of_v2_and_both_match_their_anchors(
    probes: tuple[BenchmarkProbe, ...],
    pairs: tuple[ProbePair, ...],
    tmp_path: Path,
) -> None:
    benchmark = {
        probe.probe_id: probe.capture_path.read_bytes()
        for probe in generate_benchmark(tmp_path / "benchmark")
    }
    freeze = json.loads(
        (_ROOT / "src/dfilterforge/held_out_freeze.json").read_text("utf-8")
    )

    assert [pair.probe_id for pair in pairs] == list(_TEST_PROBES)
    assert [pair.frames for pair in pairs] == [26, 27, 33]
    assert [len(pair.names) for pair in pairs] == [59, 60, 66]
    for probe, pair in zip(probes, pairs, strict=True):
        with_tail = probe.capture_path.read_bytes()
        without = pair.path.read_bytes()
        assert with_tail.startswith(without)
        assert without == benchmark[pair.probe_id]
        assert pair.names == probe.recipes
        assert pair.sha256 == (
            hashlib.sha256(without).hexdigest(),
            hashlib.sha256(with_tail).hexdigest(),
        )
        assert pair.sha256[0] == _V1_SHA256[pair.probe_id]
        assert pair.sha256[1] == freeze["digests"][pair.probe_id]


def test_a_capture_not_ending_in_the_tail_is_refused(
    probes: tuple[BenchmarkProbe, ...], pairs: tuple[ProbePair, ...]
) -> None:
    with_tail = probes[0].capture_path.read_bytes()
    frames = pairs[0].frames
    # The benchmark capture alone, a frame too many or too few, one tail
    # byte changed, no PCAP magic, and a first timestamp no seed gives.
    for capture, count in (
        (pairs[0].path.read_bytes(), frames),
        (with_tail, frames + 1),
        (with_tail, frames - 1),
        (with_tail[:-1] + bytes([with_tail[-1] ^ 1]), frames),
        (bytes(4) + with_tail[4:], frames),
        (with_tail[:24] + bytes(4) + with_tail[28:], frames),
    ):
        with pytest.raises(WitnessReplayError) as caught:
            strip_witness_tail(capture, count)
        assert caught.value.code == "witness_tail_mismatch"
    misnamed = BenchmarkProbe(
        probes[0].probe_id, probes[0].capture_path, probes[0].recipes[:-1]
    )
    with pytest.raises(WitnessReplayError) as caught:
        tail_free([misnamed], pairs[0].path.parent)
    assert caught.value.code == "frames_unnamed"


def test_v1_labels_are_the_recipe_labels_of_every_ready_test_case(
    specs: dict[str, SemanticSpecV1],
    pairs: tuple[ProbePair, ...],
    tmp_path: Path,
) -> None:
    benchmark = {
        probe.probe_id: probe
        for probe in generate_benchmark(tmp_path / "benchmark")
    }
    cases = {case.case_id: case for case in model_semantic_cases()}

    assert len(specs) == 40
    for case_id, spec in specs.items():
        assert v1_labels(spec, pairs) == tuple(
            cases[case_id].labels(benchmark[probe_id])
            for probe_id in _TEST_PROBES
        )


def test_a_miss_only_a_witness_shows_passes_v1_and_fails_v2(
    specs: dict[str, SemanticSpecV1],
    probes: tuple[BenchmarkProbe, ...],
    pairs: tuple[ProbePair, ...],
) -> None:
    """test-deepseek-v4-pro-0813-2026-09-26 C1 mei-1031 answered this."""
    spec = specs["tcp-destination-not-https"]
    answer = "tcp && !(tcp.port == 443)"

    frames = replay(_RUNNER, pairs, answer)
    assert verdict(frames, v1_labels(spec, pairs), shortcut=False) == (
        "strong_exact"
    )
    scored = _scored(probes, answer)
    assert verdict(scored, _labels(spec), shortcut=False) == "silent_wrong"
    missed = {
        pair.names[n - 1]
        for pair, found, expected in zip(
            pairs, scored, _labels(spec), strict=True
        )
        for n in set(expected) ^ set(found)
    }
    assert missed == {
        "server-ack",
        "server-ack-next",
        "keepalive-server-ack",
        "server-syn",
        "server-fin-ack",
    }
    assert missed <= set(WITNESS_NAMES)


def test_an_answer_a_benchmark_frame_disproves_fails_both(
    specs: dict[str, SemanticSpecV1],
    probes: tuple[BenchmarkProbe, ...],
    pairs: tuple[ProbePair, ...],
) -> None:
    """The case's authored mutation, which misses its HTTP frames."""
    spec = specs["tcp-destination-not-https"]
    answer = "tcp.dstport == 53"
    labels = v1_labels(spec, pairs)

    frames = replay(_RUNNER, pairs, answer)
    assert verdict(frames, labels, shortcut=False) == "silent_wrong"
    assert verdict(_scored(probes, answer), _labels(spec), shortcut=False) == (
        "silent_wrong"
    )
    # A shortcut hit leaves a wrong answer wrong and marks a right one.
    assert verdict(frames, labels, shortcut=True) == "silent_wrong"
    assert verdict(labels, labels, shortcut=True) == "shortcut"


def test_the_four_tail_only_cases_are_unscorable_on_v1(
    specs: dict[str, SemanticSpecV1], pairs: tuple[ProbePair, ...]
) -> None:
    unscorable = {
        case_id
        for case_id, spec in specs.items()
        if verdict(
            v1_labels(spec, pairs), v1_labels(spec, pairs), shortcut=False
        )
        == "unscorable"
    }

    assert unscorable == _TAIL_ONLY
    for case_id in sorted(_TAIL_ONLY):
        spec = specs[case_id]
        assert replay(_RUNNER, pairs, spec.reference_filter) == ((), (), ())
        assert all(_labels(spec))


def test_a_capture_changed_after_the_cut_is_refused(
    pairs: tuple[ProbePair, ...], tmp_path: Path
) -> None:
    other = tmp_path / pairs[0].path.name
    other.write_bytes(pairs[1].path.read_bytes())
    changed = ProbePair(
        pairs[0].probe_id,
        pairs[0].names,
        pairs[0].frames,
        other,
        pairs[0].sha256,
    )

    with pytest.raises(WitnessReplayError) as caught:
        replay(_RUNNER, [changed], "tcp")
    assert caught.value.code == "capture_changed"
