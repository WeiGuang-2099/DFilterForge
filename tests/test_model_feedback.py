"""The unscored feedback probes: construction, labels and isolation."""

from datetime import datetime
from datetime import timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from pydantic import ValidationError
import pytest

from dfilterforge.benchmark import generate_benchmark
from dfilterforge.live import evaluate_live
from dfilterforge.live import evaluate_live_with_trace
from dfilterforge.live import LiveError
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import FEEDBACK_PROBE_IDS
from dfilterforge.model_feedback import FeedbackProbes
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.mutants import single_site_mutants
from dfilterforge.witnesses import WITNESS_NAMES

_ROOT = Path(__file__).parents[1]
# benchmark.py, fixtures.py and witnesses.py are not prepare-hashed, so these
# are what keeps a refactor from moving a feedback probe unnoticed.
_FEEDBACK_SHA256 = {
    "semantic-29": (
        "1a0ef0e69d85bf39f5f982261fa48822991d00e3c21ae0a26bd190d67c59ec1b"
    ),
    "semantic-35": (
        "3ca0673f7a0da4571cefa72360f2edbd657bf8b5c2042f26aacf24758b10f816"
    ),
}
# The pilot fixtures' seeds, which a feedback seed must also avoid.
_PILOT_SEEDS = frozenset({17, 42, 2026})
_POSIX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)


@pytest.fixture(name="split", scope="module")
def fixture_split(
    tmp_path_factory: pytest.TempPathFactory,
) -> ModelSplitArtifacts:
    return generate_model_split(tmp_path_factory.mktemp("split"))


@pytest.fixture(name="feedback", scope="module")
def fixture_feedback(split: ModelSplitArtifacts) -> FeedbackProbes:
    return generate_feedback_probes(split)


def _seed(probe_id: str) -> int:
    """generate_benchmark builds capture i, semantic-(i + 1), with 100 + i."""
    return 100 + int(probe_id.removeprefix("semantic-")) - 1


def _packets(capture: bytes) -> set[bytes]:
    """The packet bytes of a little-endian PCAP."""
    packets: set[bytes] = set()
    offset = 24
    while offset < len(capture):
        length = int.from_bytes(capture[offset + 8 : offset + 12], "little")
        packets.add(capture[offset + 16 : offset + 16 + length])
        offset += 16 + length
    return packets


def test_feedback_probes_are_benchmark_copies_with_the_witness_tail(
    split: ModelSplitArtifacts, feedback: FeedbackProbes, tmp_path: Path
) -> None:
    benchmark = {
        probe.probe_id: probe for probe in generate_benchmark(tmp_path / "b")
    }

    assert feedback.capture_dir == split.gold_path.parent / "feedback"
    assert [probe.probe_id for probe in feedback.probes] == [
        FEEDBACK_PROBE_IDS["dev"],
        FEEDBACK_PROBE_IDS["test"],
    ]
    assert sorted(path.name for path in feedback.capture_dir.iterdir()) == [
        f"{probe_id}.pcap" for probe_id in sorted(_FEEDBACK_SHA256)
    ]
    for probe in feedback.probes:
        original = benchmark[probe.probe_id]
        capture = probe.capture_path.read_bytes()
        assert capture.startswith(original.capture_path.read_bytes())
        assert probe.recipes == original.recipes + WITNESS_NAMES
        assert len(_packets(capture)) == len(probe.recipes)
        assert hashlib.sha256(capture).hexdigest() == (
            _FEEDBACK_SHA256[probe.probe_id]
        )


def test_feedback_probes_share_no_seed_client_or_packet_with_another_probe(
    split: ModelSplitArtifacts, feedback: FeedbackProbes
) -> None:
    scored = {probe.probe_id for probe in split.probes}
    ids = [probe.probe_id for probe in feedback.probes]
    seeds = [_seed(probe_id) for probe_id in (*scored, *ids)]
    clients = [seed % 200 + 1 for seed in seeds]

    assert not set(ids) & (
        scored | {"semantic-01", "semantic-02", "semantic-03"}
    )
    assert not {_seed(probe_id) for probe_id in ids} & (
        {_seed(probe_id) for probe_id in scored} | _PILOT_SEEDS
    )
    # A client at .128 or above separates the /25 narrowing of TEST-NET-1.
    assert all(_seed(probe_id) % 200 + 1 >= 128 for probe_id in ids)
    assert len(set(clients)) == len(clients) == 8
    scored_packets = set[bytes]().union(
        *(_packets(probe.capture_path.read_bytes()) for probe in split.probes)
    )
    dev, test = (
        _packets(probe.capture_path.read_bytes()) for probe in feedback.probes
    )
    assert not dev & scored_packets
    assert not test & scored_packets
    assert not dev & test


def test_every_ready_case_is_labelled_on_its_feedback_probe_alone(
    split: ModelSplitArtifacts, feedback: FeedbackProbes, tmp_path: Path
) -> None:
    oracles = {case.case_id: case for case in model_semantic_cases()}
    probes = {probe.probe_id: probe for probe in feedback.probes}
    benchmark = {
        probe.probe_id: probe for probe in generate_benchmark(tmp_path / "b")
    }

    assert list(feedback.specs) == [case.case_id for case in split.gold.cases]
    for gold in split.gold.cases:
        spec = feedback.specs[gold.case_id]
        (expected,) = spec.probes
        probe = probes[expected.probe_id]
        case = oracles[gold.case_id]
        assert expected.probe_id == FEEDBACK_PROBE_IDS[case.split]
        assert expected.capture_sha256 == _FEEDBACK_SHA256[probe.probe_id]
        assert expected.expected_frames == case.labels(probe)
        assert 0 < len(expected.expected_frames) < len(probe.recipes)
        assert case.labels(probe, mutation=True) != expected.expected_frames
        # The witness tail leaves the benchmark frames' labels alone.
        original = benchmark[probe.probe_id]
        assert tuple(
            frame
            for frame in expected.expected_frames
            if frame <= len(original.recipes)
        ) == case.labels(original)
        excluded = {"probes", "provenance"}
        assert spec.model_dump(exclude=excluded) == gold.spec.model_dump(
            exclude=excluded
        )
        with pytest.raises(ValidationError):
            ModelGoldCaseV1(
                case_id=gold.case_id,
                spec=spec,
                mutation_filter=gold.mutation_filter,
            )


def test_feedback_generation_leaves_the_scored_split_untouched(
    tmp_path: Path,
) -> None:
    split = generate_model_split(tmp_path / "split")
    root = split.gold_path.parent

    def scored_files() -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file() and "feedback" not in path.relative_to(root).parts
        }

    before = scored_files()
    first = generate_feedback_probes(split)
    first_bytes = [p.capture_path.read_bytes() for p in first.probes]
    second = generate_feedback_probes(split)

    assert scored_files() == before
    assert sorted(path.name for path in (root / "captures").iterdir()) == [
        path.name for path in sorted(split.capture_paths)
    ]
    assert [p.capture_path.read_bytes() for p in second.probes] == first_bytes
    assert second.specs == first.specs
    gold = split.gold_path.read_text(encoding="utf-8")
    for probe_id, digest in _FEEDBACK_SHA256.items():
        assert probe_id not in gold
        assert digest not in gold


def test_model_inputs_never_name_a_feedback_probe(
    split: ModelSplitArtifacts, feedback: FeedbackProbes
) -> None:
    text = split.inputs_path.read_text(encoding="utf-8")

    for spec in feedback.specs.values():
        for probe in spec.probes:
            assert probe.probe_id not in text
            assert probe.capture_sha256 not in text
            frames = list(probe.expected_frames)
            assert json.dumps(frames) not in text
            assert repr(tuple(frames)) not in text


def test_the_labels_digest_covers_one_split_and_only_its_expectations(
    feedback: FeedbackProbes,
) -> None:
    dev_case = next(
        case_id
        for case_id, spec in feedback.specs.items()
        if spec.split == "dev"
    )
    test_case = next(
        case_id
        for case_id, spec in feedback.specs.items()
        if spec.split == "test"
    )
    (dev_probe,) = feedback.specs[dev_case].probes
    edited = dict(feedback.specs)
    # A dev label moves only the dev digest; test wording moves neither.
    edited[dev_case] = feedback.specs[dev_case].model_copy(
        update={
            "probes": (
                dev_probe.model_copy(
                    update={"expected_frames": dev_probe.expected_frames[1:]}
                ),
            )
        }
    )
    edited[test_case] = feedback.specs[test_case].model_copy(
        update={"intent": "Reworded."}
    )
    changed = FeedbackProbes(feedback.capture_dir, feedback.probes, edited)

    assert feedback_labels_sha256(feedback, "dev") != feedback_labels_sha256(
        feedback, "test"
    )
    assert feedback_labels_sha256(changed, "dev") != feedback_labels_sha256(
        feedback, "dev"
    )
    assert feedback_labels_sha256(changed, "test") == feedback_labels_sha256(
        feedback, "test"
    )
    with pytest.raises(TypeError):
        FEEDBACK_PROBE_IDS["dev"] = "semantic-11"  # type: ignore[index]


# The feedback probe, the cards drawn from it and the plans that carry them.
_FEEDBACK_MODULES = (
    "dfilterforge.counterexample",
    "dfilterforge.model_feedback",
    "dfilterforge.repair",
)
_CLOSURE_CHECK = """
import importlib.util
import sys
import dfilterforge.scoring
spec = importlib.util.spec_from_file_location("model_run", sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules["model_run"] = module
spec.loader.exec_module(module)
print(",".join(name for name in sys.argv[2:] if name in sys.modules))
"""


def test_scoring_and_the_call_path_never_load_feedback_cards_or_plans() -> None:
    """Covers scripts/model_run.py, which import-linter does not see."""
    loaded = subprocess.run(
        [
            sys.executable,
            "-c",
            _CLOSURE_CHECK,
            str(_ROOT / "scripts" / "model_run.py"),
            # Loaded by the check itself, so a broken lookup cannot pass.
            "dfilterforge.scoring",
            # Where the repair plan schema lives, loaded without either one.
            "dfilterforge.completions",
            *_FEEDBACK_MODULES,
        ],
        capture_output=True,
        check=True,
        text=True,
        timeout=120,
    )

    assert loaded.stdout.strip() == (
        "dfilterforge.scoring,dfilterforge.completions"
    )


@_POSIX_ONLY
def test_live_evaluation_of_a_feedback_spec_reads_only_its_probe(
    split: ModelSplitArtifacts, feedback: FeedbackProbes
) -> None:
    created = datetime(2026, 9, 25, tzinfo=timezone.utc)
    for case_id in ("udp-expiring-ttl", "https-without-syn"):
        spec = feedback.specs[case_id]
        # evaluate_live re-runs the reference against the stored labels.
        receipt, _ = evaluate_live(
            spec,
            spec.canonical_ir,
            feedback.capture_dir,
            run_id="feedback-check",
            created_at=created,
            code_revision="unit-test",
        )
        assert [probe.probe_id for probe in receipt.probes] == [
            spec.probes[0].probe_id
        ]
        assert receipt.metrics.strong_exact_count == 1
        with pytest.raises(LiveError) as caught:
            evaluate_live(
                spec,
                spec.canonical_ir,
                split.capture_paths[0].parent,
                run_id="feedback-check",
                created_at=created,
                code_revision="unit-test",
            )
        assert caught.value.code == "capture_unavailable"
    spec = feedback.specs["udp-expiring-ttl"]
    mutant = single_site_mutants(spec.canonical_ir)[0]
    _, _, trace = evaluate_live_with_trace(
        spec,
        mutant.intent,
        feedback.capture_dir,
        run_id="feedback-check",
        created_at=created,
        code_revision="unit-test",
    )
    assert [probe.probe_id for probe in trace.probes] == [
        FEEDBACK_PROBE_IDS["dev"]
    ]
    assert trace.probes[0].counterexample_frames
