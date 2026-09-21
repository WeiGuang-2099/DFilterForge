"""Tests for executable replay contracts and orchestration."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from pathlib import Path

from pydantic import ValidationError
import pytest

from dfilterforge import replay as replay_module
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import EvaluationTraceV1
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import ProbeTraceV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.live import LiveError
from dfilterforge.replay import ExecutableReplayResultV1
from dfilterforge.replay import replay_live
from dfilterforge.replay import ReplayError
from dfilterforge.replay import ReplayProbeResultV1
from dfilterforge.runner import TsharkRunner

_CREATED_AT = datetime(2026, 9, 10, tzinfo=timezone.utc)


def _intent() -> IntentIrV1:
    return IntentIrV1.model_validate(
        {
            "expression": {
                "kind": "predicate",
                "field": "tcp",
                "operator": "exists",
            }
        }
    )


def _spec(*, expected_frames: tuple[int, ...] = (1, 2)) -> SemanticSpecV1:
    return SemanticSpecV1(
        task_id="tcp",
        intent="Show TCP packets",
        canonical_ir=_intent(),
        reference_filter="tcp",
        probes=(
            ProbeExpectationV1(
                probe_id="probe-a",
                capture_sha256="capture-identity-is-not-read-by-replay",
                expected_frames=expected_frames,
            ),
        ),
        split="test",
        provenance="generated",
        license="MIT",
        review_status="reviewed",
    )


def _receipt(
    *,
    expected_frames: tuple[int, ...] = (1, 2),
    candidate_frames: tuple[int, ...] = (1, 2),
    runtime_ms: float = 3.0,
    candidate_filter: str = "tcp",
    reference_filter: str = "tcp",
) -> EvaluationReceiptV1:
    probe = evaluate_probe(
        "probe-a", expected_frames, candidate_frames, runtime_ms
    )
    return EvaluationReceiptV1(
        run_id="run-a",
        created_at=_CREATED_AT,
        code_revision="recorded-revision",
        environment_hash="recorded-environment-is-not-compared",
        data_hash="recorded-data-is-not-compared",
        candidate_filter=candidate_filter,
        reference_filter=reference_filter,
        probes=(probe,),
        metrics=aggregate_metrics((probe,)),
    )


def _trace(
    probe_ids: tuple[str, ...] = ("probe-a",), *, run_id: str = "run-a"
) -> EvaluationTraceV1:
    return EvaluationTraceV1(
        run_id=run_id,
        probes=tuple(
            ProbeTraceV1(probe_id=probe_id, counterexample_frames=())
            for probe_id in probe_ids
        ),
    )


def _environment() -> LiveEnvironmentV1:
    return LiveEnvironmentV1(
        tshark_version="4.6.8",
        executable_sha256="measured-by-live-boundary",
        runner_source_sha256="measured-by-live-boundary",
        runner_limits_hash="measured-by-live-boundary",
        catalog_hash="measured-by-live-boundary",
        catalog_profile_hash="measured-by-live-boundary",
        python_version="3.12.3",
        platform_machine="x86_64",
    )


def _catalog() -> FieldCatalogV1:
    return FieldCatalogV1(
        tshark_version="4.6.8", profile_hash="profile", fields=()
    )


def _install_execution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    replayed_frames: tuple[int, ...],
    replayed_runtime_ms: float = 11.0,
    compiled_filter: str = "tcp",
) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []
    bound_catalog = _catalog()
    environment = _environment()

    def fake_bind_catalog(
        runner: TsharkRunner,
        intents: tuple[IntentIrV1, ...],
        supplied: FieldCatalogV1 | None = None,
    ) -> FieldCatalogV1:
        calls.append(("bind", (runner, intents, supplied)))
        return bound_catalog

    def fake_compile_intent(
        intent: IntentIrV1, catalog: FieldCatalogV1 | None = None
    ) -> str:
        calls.append(("compile", (intent, catalog)))
        return compiled_filter

    def replayed(
        spec: SemanticSpecV1,
        candidate_filter: str,
        run_id: str,
        created_at: datetime,
        code_revision: str,
    ) -> EvaluationReceiptV1:
        probe = evaluate_probe(
            "probe-a",
            spec.probes[0].expected_frames,
            replayed_frames,
            replayed_runtime_ms,
        )
        return EvaluationReceiptV1(
            run_id=run_id,
            created_at=created_at,
            code_revision=code_revision,
            environment_hash="fresh-environment",
            data_hash="fresh-data",
            candidate_filter=candidate_filter,
            reference_filter=spec.reference_filter,
            probes=(probe,),
            metrics=aggregate_metrics((probe,)),
        )

    def fake_evaluate_live_with_trace(
        spec: SemanticSpecV1,
        candidate_ir: IntentIrV1,
        capture_root: Path,
        *,
        run_id: str,
        created_at: datetime,
        code_revision: str,
        catalog: FieldCatalogV1 | None = None,
        runner: TsharkRunner | None = None,
    ) -> tuple[EvaluationReceiptV1, LiveEnvironmentV1, EvaluationTraceV1]:
        calls.append(
            (
                "execute",
                (
                    spec,
                    candidate_ir,
                    capture_root,
                    run_id,
                    created_at,
                    code_revision,
                    catalog,
                    runner,
                ),
            )
        )
        replayed_receipt = replayed(
            spec, compiled_filter, run_id, created_at, code_revision
        )
        return replayed_receipt, environment, _trace(run_id=run_id)

    def fake_evaluate_live(
        spec: SemanticSpecV1,
        candidate: IntentIrV1 | str,
        capture_root: Path,
        *,
        run_id: str,
        created_at: datetime,
        code_revision: str,
        catalog: FieldCatalogV1 | None = None,
        runner: TsharkRunner | None = None,
    ) -> tuple[EvaluationReceiptV1, LiveEnvironmentV1]:
        calls.append(
            (
                "execute",
                (
                    spec,
                    candidate,
                    capture_root,
                    run_id,
                    created_at,
                    code_revision,
                    catalog,
                    runner,
                ),
            )
        )
        replayed_receipt = replayed(
            spec,
            candidate if isinstance(candidate, str) else compiled_filter,
            run_id,
            created_at,
            code_revision,
        )
        return replayed_receipt, environment

    monkeypatch.setattr(replay_module, "bind_catalog", fake_bind_catalog)
    monkeypatch.setattr(replay_module, "compile_intent", fake_compile_intent)
    monkeypatch.setattr(
        replay_module,
        "evaluate_live_with_trace",
        fake_evaluate_live_with_trace,
    )
    monkeypatch.setattr(replay_module, "evaluate_live", fake_evaluate_live)
    return calls


def _replay_probe(
    probe_id: str = "probe-a",
    *,
    recorded: tuple[int, ...] = (1, 2),
    replayed: tuple[int, ...] = (1, 2),
) -> ReplayProbeResultV1:
    recorded_set = set(recorded)
    replayed_set = set(replayed)
    return ReplayProbeResultV1(
        probe_id=probe_id,
        recorded_frames=recorded,
        replayed_frames=replayed,
        runtime_ms=5,
        recorded_only=tuple(sorted(recorded_set - replayed_set)),
        replayed_only=tuple(sorted(replayed_set - recorded_set)),
        exact=recorded == replayed,
    )


def test_probe_result_normalizes_and_validates_derived_fields() -> None:
    result = ReplayProbeResultV1(
        probe_id="probe-a",
        recorded_frames=(2, 1),
        replayed_frames=(3, 1),
        runtime_ms=4,
        recorded_only=(2,),
        replayed_only=(3,),
        exact=False,
    )

    assert result.recorded_frames == (1, 2)
    assert result.replayed_frames == (1, 3)
    with pytest.raises(ValidationError, match="recorded_only"):
        ReplayProbeResultV1(
            probe_id="probe-a",
            recorded_frames=(1, 2),
            replayed_frames=(1,),
            runtime_ms=4,
            recorded_only=(),
            exact=False,
        )
    with pytest.raises(ValidationError, match="exact"):
        ReplayProbeResultV1(
            probe_id="probe-a",
            recorded_frames=(1,),
            replayed_frames=(1,),
            runtime_ms=4,
            exact=False,
        )


def test_executable_result_validates_exact_and_trace_alignment() -> None:
    probe = _replay_probe()
    result = ExecutableReplayResultV1(
        run_id="run-a", exact=True, probes=(probe,), trace=_trace()
    )

    assert result.executed is True
    assert result.reference_verified is True
    with pytest.raises(ValidationError, match="exact"):
        ExecutableReplayResultV1(
            run_id="run-a", exact=False, probes=(probe,), trace=_trace()
        )
    with pytest.raises(ValidationError, match="trace run ID"):
        ExecutableReplayResultV1(
            run_id="run-a",
            exact=True,
            probes=(probe,),
            trace=_trace(run_id="other-run"),
        )
    with pytest.raises(ValidationError, match="trace probes"):
        ExecutableReplayResultV1(
            run_id="run-a",
            exact=True,
            probes=(probe,),
            trace=_trace(("other-probe",)),
        )
    with pytest.raises(ValidationError, match="unique"):
        ExecutableReplayResultV1(
            run_id="run-a",
            exact=True,
            probes=(probe, probe),
            trace=_trace(),
        )


def test_replay_executes_live_path_without_comparing_recorded_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_execution(monkeypatch, replayed_frames=(1, 2))
    runner = TsharkRunner("not-executed-directly")

    result, environment = replay_live(
        _receipt(), _spec(), _intent(), tmp_path, runner=runner
    )

    assert [name for name, _ in calls] == ["bind", "compile", "execute"]
    assert result.executed is True
    assert result.reference_verified is True
    assert result.exact is True
    assert result.probes[0].runtime_ms == 11
    assert environment == _environment()
    execute_arguments = calls[-1][1]
    assert isinstance(execute_arguments, tuple)
    assert execute_arguments[2] == tmp_path
    assert execute_arguments[-1] is runner


def test_candidate_packet_drift_is_a_result_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_execution(monkeypatch, replayed_frames=(1, 3))

    result, _ = replay_live(
        _receipt(), _spec(), _intent(), tmp_path, runner=TsharkRunner("unused")
    )

    assert result.exact is False
    assert result.probes[0].recorded_only == (2,)
    assert result.probes[0].replayed_only == (3,)
    assert result.probes[0].exact is False


def test_replay_runtime_does_not_affect_exactness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_execution(
        monkeypatch, replayed_frames=(1, 2), replayed_runtime_ms=999
    )

    result, _ = replay_live(
        _receipt(runtime_ms=1),
        _spec(),
        _intent(),
        tmp_path,
        runner=TsharkRunner("unused"),
    )

    assert result.exact is True
    assert result.probes[0].runtime_ms == 999


def test_reference_filter_mismatch_fails_before_binding(tmp_path: Path) -> None:
    with pytest.raises(ReplayError) as caught:
        replay_live(
            _receipt(reference_filter="udp"),
            _spec(),
            _intent(),
            tmp_path,
            runner=TsharkRunner("must-not-run"),
        )

    assert caught.value.code == "reference_filter_mismatch"


def test_probe_manifest_mismatch_fails_before_binding(tmp_path: Path) -> None:
    with pytest.raises(ReplayError) as caught:
        replay_live(
            _receipt(expected_frames=(2,)),
            _spec(expected_frames=(1,)),
            _intent(),
            tmp_path,
            runner=TsharkRunner("must-not-run"),
        )

    assert caught.value.code == "probe_manifest_mismatch"


def test_duplicate_receipt_probe_ids_fail_before_binding(
    tmp_path: Path,
) -> None:
    probe = evaluate_probe("probe-a", (1, 2), (1, 2), 1)
    receipt = EvaluationReceiptV1(
        run_id="run-a",
        created_at=_CREATED_AT,
        code_revision="revision",
        environment_hash="ignored",
        data_hash="ignored",
        candidate_filter="tcp",
        reference_filter="tcp",
        probes=(probe, probe),
        metrics=aggregate_metrics((probe, probe)),
    )

    with pytest.raises(ReplayError) as caught:
        replay_live(
            receipt,
            _spec(),
            _intent(),
            tmp_path,
            runner=TsharkRunner("must-not-run"),
        )

    assert caught.value.code == "probe_manifest_mismatch"


def test_candidate_compile_mismatch_does_not_execute_live_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_execution(
        monkeypatch, replayed_frames=(1, 2), compiled_filter="udp"
    )

    with pytest.raises(ReplayError) as caught:
        replay_live(
            _receipt(candidate_filter="tcp"),
            _spec(),
            _intent(),
            tmp_path,
            runner=TsharkRunner("unused"),
        )

    assert caught.value.code == "candidate_filter_mismatch"
    assert [name for name, _ in calls] == ["bind", "compile"]


def test_reference_execution_failure_remains_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_execution(monkeypatch, replayed_frames=(1, 2))

    def fail_reference(*args: object, **kwargs: object) -> object:
        del args, kwargs
        calls.append(("reference-failed", None))
        raise LiveError(
            "reference_label_mismatch",
            "Reference execution disagrees with independent packet labels",
        )

    monkeypatch.setattr(
        replay_module, "evaluate_live_with_trace", fail_reference
    )

    with pytest.raises(LiveError) as caught:
        replay_live(
            _receipt(),
            _spec(),
            _intent(),
            tmp_path,
            runner=TsharkRunner("unused"),
        )

    assert caught.value.code == "reference_label_mismatch"
    assert [name for name, _ in calls] == [
        "bind",
        "compile",
        "reference-failed",
    ]


def test_display_filter_replay_executes_recorded_string_without_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_execution(monkeypatch, replayed_frames=(1, 2))
    receipt = _receipt()

    result, _ = replay_live(
        receipt,
        _spec(),
        receipt.candidate_filter,
        tmp_path,
        runner=TsharkRunner("unused"),
    )

    assert [name for name, _ in calls] == ["execute"]
    assert result.trace is None
    assert result.exact is True
    assert result.executed is True
    assert result.reference_verified is True
    execute_arguments = calls[-1][1]
    assert isinstance(execute_arguments, tuple)
    assert execute_arguments[1] == "tcp"


def test_display_filter_replay_rejects_a_different_string_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_execution(monkeypatch, replayed_frames=(1, 2))

    with pytest.raises(ReplayError) as caught:
        replay_live(
            _receipt(candidate_filter="tcp"),
            _spec(),
            "udp",
            tmp_path,
            runner=TsharkRunner("must-not-run"),
        )

    assert caught.value.code == "candidate_filter_mismatch"
    assert str(caught.value) == (
        "Candidate filter differs from the recorded filter"
    )
    assert calls == []


def test_display_filter_replay_reports_packet_drift_as_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_execution(monkeypatch, replayed_frames=(1, 3))
    receipt = _receipt()

    result, _ = replay_live(
        receipt,
        _spec(),
        receipt.candidate_filter,
        tmp_path,
        runner=TsharkRunner("unused"),
    )

    assert result.exact is False
    assert result.probes[0].recorded_only == (2,)
    assert result.probes[0].replayed_only == (3,)
    assert result.probes[0].exact is False
    assert result.trace is None


def test_replay_result_accepts_a_missing_trace_and_checks_probes() -> None:
    probe = _replay_probe()

    result = ExecutableReplayResultV1(
        run_id="run-a", exact=True, probes=(probe,)
    )

    assert result.trace is None
    with pytest.raises(ValidationError, match="unique"):
        ExecutableReplayResultV1(
            run_id="run-a", exact=True, probes=(probe, probe)
        )
    with pytest.raises(ValidationError, match="exact"):
        ExecutableReplayResultV1(run_id="run-a", exact=False, probes=(probe,))
    with pytest.raises(ValidationError, match="trace run ID"):
        ExecutableReplayResultV1(
            run_id="run-a",
            exact=True,
            probes=(probe,),
            trace=_trace(run_id="other-run"),
        )


def test_typed_ir_replay_still_binds_compiles_and_traces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_execution(monkeypatch, replayed_frames=(1, 2))

    result, _ = replay_live(
        _receipt(),
        _spec(),
        _intent(),
        tmp_path,
        runner=TsharkRunner("unused"),
    )

    assert [name for name, _ in calls] == ["bind", "compile", "execute"]
    assert result.trace is not None
    assert result.trace.run_id == "run-a"
