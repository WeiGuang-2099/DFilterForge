"""Tests for capture confinement, oracle integrity, and measured receipts."""

from datetime import datetime
from datetime import timezone
import hashlib
import os
from pathlib import Path

import pytest

from dfilterforge import live
from dfilterforge.canonical import canonical_json
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.live import evaluate_live
from dfilterforge.live import evaluate_live_with_trace
from dfilterforge.live import LiveError
from dfilterforge.live import packet_set_hash
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.runner import RunnerError
from dfilterforge.runner import RunnerLimits
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner

_CAPTURE = b"synthetic unit-test capture"
_CAPTURE_HASH = hashlib.sha256(_CAPTURE).hexdigest()
_TIME = datetime(2026, 9, 4, tzinfo=timezone.utc)


class _RecordedRunner(TsharkRunner):
    """Controlled execution results for testing the orchestration boundary."""

    def __init__(
        self,
        results: list[RunResult] | None = None,
        limits: RunnerLimits = RunnerLimits(),
    ) -> None:
        super().__init__(tshark="/usr/bin/true", limits=limits)
        self.calls: list[tuple[Path, str]] = []
        self.results = (
            results
            if results is not None
            else [RunResult((1, 3), 10, _CAPTURE_HASH)] * 2
        )

    def version(self) -> str:
        return "4.6.8"

    def report(self, name: str) -> bytes:
        return TsharkRunner().report(name)

    def run(self, capture: Path, display_filter: str) -> RunResult:
        self.calls.append((capture, display_filter))
        return self.results.pop(0)


def _spec(tmp_path: Path) -> SemanticSpecV1:
    (tmp_path / "probe.pcap").write_bytes(_CAPTURE)
    return SemanticSpecV1.model_validate(
        {
            "task_id": "tcp",
            "intent": "Show TCP packets",
            "canonical_ir": {
                "expression": {
                    "kind": "predicate",
                    "field": "tcp",
                    "operator": "exists",
                }
            },
            "reference_filter": "tcp",
            "probes": [
                {
                    "probe_id": "probe",
                    "capture_sha256": _CAPTURE_HASH,
                    "expected_frames": [1, 3],
                }
            ],
            "split": "test",
            "provenance": "generated",
            "license": "CC0",
            "review_status": "reviewed",
        }
    )


def _syn_spec(tmp_path: Path) -> tuple[SemanticSpecV1, IntentIrV1]:
    (tmp_path / "syn-probe.pcap").write_bytes(_CAPTURE)
    syn = Predicate(field="tcp.flags.syn", operator=Operator.EQ, value=True)
    canonical = IntentIrV1(
        expression=All(
            children=(
                syn,
                Predicate(
                    field="tcp.flags.ack",
                    operator=Operator.EQ,
                    value=False,
                ),
            )
        )
    )
    spec = SemanticSpecV1(
        task_id="syn-no-ack",
        intent="Show SYN packets without ACK",
        canonical_ir=canonical,
        reference_filter=("(tcp.flags.syn == true && tcp.flags.ack == false)"),
        probes=(
            ProbeExpectationV1(
                probe_id="syn-probe",
                capture_sha256=_CAPTURE_HASH,
                expected_frames=(1,),
            ),
        ),
        split="test",
        provenance="generated",
        license="CC0",
        review_status="reviewed",
    )
    return spec, IntentIrV1(expression=syn)


def test_receipt_records_candidate_difference_and_measured_environment(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    runner = _RecordedRunner(
        [
            RunResult((1, 3), 4, _CAPTURE_HASH),
            RunResult((1, 2, 3), 9, _CAPTURE_HASH),
        ]
    )
    receipt, environment = evaluate_live(
        spec,
        spec.canonical_ir,
        tmp_path,
        run_id="run",
        created_at=_TIME,
        code_revision="test",
        runner=runner,
    )
    assert receipt.probes[0].candidate_only == (2,)
    assert receipt.metrics.strong_exact_count == 0
    assert receipt.probes[0].runtime_ms == 9
    assert (
        environment.executable_sha256
        == hashlib.sha256(runner.executable_path.read_bytes()).hexdigest()
    )
    assert receipt.environment_hash == environment.environment_hash()
    assert "container_image_digest" in environment.unmeasured
    assert len(runner.calls) == 2


@pytest.mark.parametrize(
    "probe_id", ["../outside", "/outside", "..", "x/y", "x\\y"]
)
def test_rejects_capture_path_traversal(tmp_path: Path, probe_id: str) -> None:
    spec = _spec(tmp_path)
    probe = spec.probes[0].model_copy(update={"probe_id": probe_id})
    spec = spec.model_copy(update={"probes": (probe,)})
    runner = _RecordedRunner()
    with pytest.raises(LiveError, match="identifier"):
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )
    assert not runner.calls


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    root.mkdir()
    spec = _spec(root)
    capture = root / "probe.pcap"
    capture.unlink()
    outside = tmp_path / "outside.pcap"
    outside.write_bytes(_CAPTURE)
    capture.symlink_to(outside)
    with pytest.raises(LiveError, match="inside"):
        evaluate_live(
            spec,
            spec.canonical_ir,
            root,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=_RecordedRunner(),
        )


@pytest.mark.parametrize("replacement", ["fifo", "symlink"])
def test_file_replaced_after_path_check_fails_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    spec = _spec(tmp_path)
    capture = tmp_path / "probe.pcap"
    real_is_file = Path.is_file

    def replace_after_check(path: Path) -> bool:
        if path == capture:
            capture.unlink()
            if replacement == "fifo":
                os.mkfifo(capture)
            else:
                capture.symlink_to("/etc/passwd")
            return True
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", replace_after_check)
    runner = _RecordedRunner()
    with pytest.raises(LiveError):
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )
    assert not runner.calls


@pytest.mark.parametrize(
    "capture_state", ["missing", "directory", "tampered", "large"]
)
def test_rejects_invalid_capture_before_execution(
    tmp_path: Path,
    capture_state: str,
) -> None:
    spec = _spec(tmp_path)
    capture = tmp_path / "probe.pcap"
    if capture_state == "missing":
        capture.unlink()
    elif capture_state == "directory":
        capture.unlink()
        capture.mkdir()
    elif capture_state == "tampered":
        capture.write_bytes(b"changed")
    runner = _RecordedRunner(
        limits=RunnerLimits(
            max_capture_bytes=1 if capture_state == "large" else 1024,
        )
    )
    with pytest.raises(LiveError):
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )
    assert not runner.calls


def test_reference_mismatch_invalidates_oracle(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    runner = _RecordedRunner([RunResult((1,), 2, _CAPTURE_HASH)])
    with pytest.raises(LiveError) as caught:
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )
    assert caught.value.code == "reference_label_mismatch"
    assert len(runner.calls) == 1


@pytest.mark.parametrize("changed_call", [0, 1])
def test_capture_replacement_during_execution_cannot_claim_success(
    tmp_path: Path,
    changed_call: int,
) -> None:
    spec = _spec(tmp_path)
    results = [RunResult((1, 3), 2, _CAPTURE_HASH)] * 2
    results[changed_call] = RunResult((1, 3), 2, "changed")
    with pytest.raises(LiveError) as caught:
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=_RecordedRunner(results),
        )
    assert caught.value.code == "capture_hash_mismatch"


@pytest.mark.parametrize("version", ["4.6.7", "4.6.8"])
def test_catalog_version_must_match_runtime(
    tmp_path: Path, version: str
) -> None:
    spec = _spec(tmp_path)
    catalog = bind_catalog(_RecordedRunner(), (spec.canonical_ir,)).model_copy(
        update={"tshark_version": version}
    )
    if version == "4.6.8":
        _, environment = evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=_RecordedRunner(),
            catalog=catalog,
        )
        assert environment.catalog_hash == catalog.source_catalog_hash
        return
    with pytest.raises(CatalogError) as caught:
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=_RecordedRunner(),
            catalog=catalog,
        )
    assert caught.value.code == "catalog_version_mismatch"


def test_naive_timestamp_fails_before_execution(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with pytest.raises(LiveError) as caught:
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path,
            run_id="run",
            created_at=datetime(2026, 9, 4),
            code_revision="test",
            runner=_RecordedRunner(),
        )
    assert caught.value.code == "timestamp_invalid"


def test_invalid_capture_root_returns_sanitized_error(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with pytest.raises(LiveError) as caught:
        evaluate_live(
            spec,
            spec.canonical_ir,
            tmp_path / "\x00private-path",
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=_RecordedRunner(),
        )
    assert caught.value.code == "capture_unavailable"
    assert "private-path" not in str(caught.value)


def test_packet_hash_excludes_runtime_and_metadata(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    first, _ = evaluate_live(
        spec,
        spec.canonical_ir,
        tmp_path,
        run_id="first",
        created_at=_TIME,
        code_revision="test",
        runner=_RecordedRunner(),
    )
    second, _ = evaluate_live(
        spec,
        IntentIrV1.model_validate(spec.canonical_ir),
        tmp_path,
        run_id="second",
        created_at=_TIME,
        code_revision="test",
        runner=_RecordedRunner([RunResult((1, 3), 100, _CAPTURE_HASH)] * 2),
    )
    assert packet_set_hash(first) == packet_set_hash(second)
    assert first.receipt_hash() != second.receipt_hash()


def test_trace_executes_both_sides_for_actual_counterexamples(
    tmp_path: Path,
) -> None:
    spec, candidate = _syn_spec(tmp_path)
    runner = _RecordedRunner(
        [
            RunResult((1,), 2, _CAPTURE_HASH),
            RunResult((1, 2), 3, _CAPTURE_HASH),
            RunResult((1,), 4, _CAPTURE_HASH),
        ]
    )

    receipt, _, trace = evaluate_live_with_trace(
        spec,
        candidate,
        tmp_path,
        run_id="trace",
        created_at=_TIME,
        code_revision="test",
        runner=runner,
    )

    assert receipt.probes[0].candidate_only == (2,)
    probe = trace.probes[0]
    assert probe.counterexample_frames == (2,)
    assert probe.candidate_predicates[0].matched_frames == (2,)
    assert [entry.matched_frames for entry in probe.canonical_predicates] == [
        (2,),
        (),
    ]
    assert [display_filter for _, display_filter in runner.calls] == [
        spec.reference_filter,
        "tcp.flags.syn == true",
        "tcp.flags.ack == false",
    ]
    serialized = canonical_json(trace)
    assert "observed" not in serialized
    assert "synthetic unit-test capture" not in serialized


def test_exact_probe_skips_predicate_execution(tmp_path: Path) -> None:
    spec, _ = _syn_spec(tmp_path)
    runner = _RecordedRunner(
        [
            RunResult((1,), 2, _CAPTURE_HASH),
            RunResult((1,), 3, _CAPTURE_HASH),
        ]
    )

    _, _, trace = evaluate_live_with_trace(
        spec,
        spec.canonical_ir,
        tmp_path,
        run_id="exact",
        created_at=_TIME,
        code_revision="test",
        runner=runner,
    )

    assert len(runner.calls) == 2
    assert trace.probes[0].counterexample_frames == ()
    assert trace.probes[0].candidate_predicates == ()
    assert trace.probes[0].canonical_predicates == ()


def test_trace_budget_fails_before_first_leaf_call(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    predicates = tuple(
        Predicate(field="tcp", operator=Operator.EXISTS) for _ in range(33)
    )
    large = IntentIrV1(expression=All(children=predicates))
    spec = spec.model_copy(update={"canonical_ir": large})
    runner = _RecordedRunner(
        [
            RunResult((1, 3), 2, _CAPTURE_HASH),
            RunResult((1, 2, 3), 3, _CAPTURE_HASH),
        ]
    )

    with pytest.raises(LiveError) as caught:
        evaluate_live_with_trace(
            spec,
            large,
            tmp_path,
            run_id="limited",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )

    assert caught.value.code == "trace_limit"
    assert len(runner.calls) == 2


def test_display_filter_candidate_runs_after_each_verified_reference(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    runner = _RecordedRunner(
        [
            RunResult((1, 3), 4, _CAPTURE_HASH),
            RunResult((1, 2, 3), 9, _CAPTURE_HASH),
        ]
    )

    receipt, _ = evaluate_live(
        spec,
        "tcp || udp",
        tmp_path,
        run_id="run",
        created_at=_TIME,
        code_revision="test",
        runner=runner,
    )

    assert runner.calls == [
        (tmp_path / "probe.pcap", "tcp"),
        (tmp_path / "probe.pcap", "tcp || udp"),
    ]
    assert receipt.candidate_filter == "tcp || udp"
    assert receipt.probes[0].candidate_only == (2,)
    assert receipt.probes[0].exact is False


def test_display_filter_candidate_binds_only_canonical_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec(tmp_path)
    recorded: list[tuple[IntentIrV1, ...]] = []
    real = live.bind_catalog

    def record(
        runner: TsharkRunner,
        intents: tuple[IntentIrV1, ...],
        supplied: FieldCatalogV1 | None = None,
    ) -> FieldCatalogV1:
        recorded.append(intents)
        return real(runner, intents, supplied)

    monkeypatch.setattr(live, "bind_catalog", record)
    evaluate_live(
        spec,
        "tcp",
        tmp_path,
        run_id="string",
        created_at=_TIME,
        code_revision="test",
        runner=_RecordedRunner(),
    )
    candidate_ir = IntentIrV1(
        expression=Predicate(field="udp", operator=Operator.EXISTS)
    )
    evaluate_live(
        spec,
        candidate_ir,
        tmp_path,
        run_id="typed",
        created_at=_TIME,
        code_revision="test",
        runner=_RecordedRunner(),
    )

    assert recorded == [
        (spec.canonical_ir,),
        (candidate_ir, spec.canonical_ir),
    ]


def test_rejected_display_filter_propagates_after_reference(
    tmp_path: Path,
) -> None:
    class _RejectingRunner(_RecordedRunner):
        """Accepts the reference filter and rejects the candidate string."""

        def run(self, capture: Path, display_filter: str) -> RunResult:
            if len(self.calls) == 1:
                self.calls.append((capture, display_filter))
                raise RunnerError(
                    "filter_rejected", "tshark rejected the display filter"
                )
            return super().run(capture, display_filter)

    spec = _spec(tmp_path)
    runner = _RejectingRunner([RunResult((1, 3), 4, _CAPTURE_HASH)])

    with pytest.raises(RunnerError) as caught:
        evaluate_live(
            spec,
            "tcp &&",
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )

    assert caught.value.code == "filter_rejected"
    assert len(runner.calls) == 2


def test_receipt_records_model_and_prompt_hashes(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    labelled, _ = evaluate_live(
        spec,
        "tcp",
        tmp_path,
        run_id="run",
        created_at=_TIME,
        code_revision="test",
        runner=_RecordedRunner(),
        model_hash="m",
        prompt_hash="p",
    )
    plain, _ = evaluate_live(
        spec,
        "tcp",
        tmp_path,
        run_id="run",
        created_at=_TIME,
        code_revision="test",
        runner=_RecordedRunner(),
    )

    assert labelled.model_hash == "m"
    assert labelled.prompt_hash == "p"
    assert plain.model_hash is None
    assert labelled.receipt_hash() != plain.receipt_hash()


def test_string_candidate_still_aborts_on_a_bad_oracle(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    runner = _RecordedRunner([RunResult((1, 2), 4, _CAPTURE_HASH)])

    with pytest.raises(LiveError) as caught:
        evaluate_live(
            spec,
            "tcp || udp",
            tmp_path,
            run_id="run",
            created_at=_TIME,
            code_revision="test",
            runner=runner,
        )

    assert caught.value.code == "reference_label_mismatch"
    assert len(runner.calls) == 1


def _dev_case(tmp_path: Path) -> ModelGoldCaseV1:
    """Materializes the dev split and returns its low-TTL TCP gold case."""
    artifacts = generate_model_split(tmp_path)
    return next(
        gold
        for gold in artifacts.gold.cases
        if gold.case_id == "tcp-expiring-ttl"
    )


def _evaluate_dev_case(
    case: ModelGoldCaseV1, candidate: str, capture_root: Path
) -> EvaluationReceiptV1:
    receipt, _ = evaluate_live(
        case.spec,
        candidate,
        capture_root,
        run_id="real",
        created_at=_TIME,
        code_revision="test",
        runner=TsharkRunner(),
    )
    return receipt


@pytest.mark.parametrize("candidate_kind", ["reference", "mutation"])
def test_real_display_filter_candidates_against_dev_labels(
    tmp_path: Path,
    candidate_kind: str,
) -> None:
    case = _dev_case(tmp_path)
    candidate = (
        case.spec.reference_filter
        if candidate_kind == "reference"
        else case.mutation_filter
    )

    receipt = _evaluate_dev_case(case, candidate, tmp_path / "captures")

    assert len(receipt.probes) == 3
    if candidate_kind == "reference":
        assert all(probe.exact for probe in receipt.probes)
        assert receipt.metrics.strong_exact_count == 3
        return
    assert receipt.metrics.strong_exact_count < 3
    assert any(probe.candidate_only for probe in receipt.probes)


def test_real_unknown_field_candidate_is_rejected_by_tshark(
    tmp_path: Path,
) -> None:
    case = _dev_case(tmp_path)

    with pytest.raises(RunnerError) as caught:
        _evaluate_dev_case(case, "ip.ttll <= 1", tmp_path / "captures")

    assert caught.value.code == "filter_unknown_field"
