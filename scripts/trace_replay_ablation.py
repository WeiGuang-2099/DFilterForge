"""Measure dual-sided predicate trace and executable replay behavior.

This Docker-only experiment compares the production Full replay with a real
candidate-only simplification.  It intentionally does not perform standalone
hash validation or the separate pilot stability gate.
"""

# pylint: disable=duplicate-code,missing-function-docstring,too-many-instance-attributes,too-many-locals

from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import json
import math
from pathlib import Path
import re
import statistics
import time
from typing import TypedDict

from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import EvaluationTraceV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.fixtures import generate_fixtures
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.live import evaluate_live_with_trace
from dfilterforge.live import LiveError
from dfilterforge.replay import replay_live
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner

_CASES = ("tcp-syn-no-ack", "dns-udp-query", "udp-destination-53")
_PROBE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z")
_CREATED_AT = datetime(2026, 9, 10, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _RunnerSnapshot:
    tshark_calls: int
    version_validation_requests: int


class _CountingRunner(TsharkRunner):
    """Production runner with non-sensitive operation counters."""

    def __init__(self) -> None:
        super().__init__()
        self.tshark_calls = 0
        self.version_validation_requests = 0

    def version(self) -> str:
        self.version_validation_requests += 1
        return super().version()

    def run(self, capture: Path, display_filter: str) -> RunResult:
        self.tshark_calls += 1
        return super().run(capture, display_filter)

    def snapshot(self) -> _RunnerSnapshot:
        return _RunnerSnapshot(
            tshark_calls=self.tshark_calls,
            version_validation_requests=self.version_validation_requests,
        )


@dataclass(frozen=True)
class _SimplifiedProbe:
    probe_id: str
    recorded_frames: tuple[int, ...]
    replayed_frames: tuple[int, ...]
    runtime_ms: float
    exact: bool


@dataclass(frozen=True)
class _SimplifiedReplay:
    exact: bool
    probes: tuple[_SimplifiedProbe, ...]


@dataclass(frozen=True)
class _TraceCoverage:
    counterexample_frames: int = 0
    dual_side_covered_frames: int = 0
    candidate_predicate_paths: int = 0
    canonical_predicate_paths: int = 0
    candidate_trace_cells: int = 0
    canonical_trace_cells: int = 0

    def __add__(self, other: "_TraceCoverage") -> "_TraceCoverage":
        return _TraceCoverage(
            counterexample_frames=(
                self.counterexample_frames + other.counterexample_frames
            ),
            dual_side_covered_frames=(
                self.dual_side_covered_frames + other.dual_side_covered_frames
            ),
            candidate_predicate_paths=(
                self.candidate_predicate_paths + other.candidate_predicate_paths
            ),
            canonical_predicate_paths=(
                self.canonical_predicate_paths + other.canonical_predicate_paths
            ),
            candidate_trace_cells=(
                self.candidate_trace_cells + other.candidate_trace_cells
            ),
            canonical_trace_cells=(
                self.canonical_trace_cells + other.canonical_trace_cells
            ),
        )


@dataclass(frozen=True)
class _Diagnosis:
    extra_frames: int = 0
    candidate_broad_match_frames: int = 0
    canonical_ack_rejection_frames: int = 0

    def __add__(self, other: "_Diagnosis") -> "_Diagnosis":
        return _Diagnosis(
            extra_frames=self.extra_frames + other.extra_frames,
            candidate_broad_match_frames=(
                self.candidate_broad_match_frames
                + other.candidate_broad_match_frames
            ),
            canonical_ack_rejection_frames=(
                self.canonical_ack_rejection_frames
                + other.canonical_ack_rejection_frames
            ),
        )


@dataclass(frozen=True)
class _Measurement:
    wall_ms: float
    tshark_calls: int
    version_validation_requests: int
    candidate_tuple_validations: int
    reference_tuple_validations: int
    exact: bool
    reference_verified: bool
    trace: _TraceCoverage = _TraceCoverage()
    diagnosis: _Diagnosis = _Diagnosis()


class _VariantSummary(TypedDict):
    samples: int
    all_candidate_replays_exact: bool
    reference_verified_samples: int
    tshark_calls: int
    version_validation_requests: int
    candidate_tuple_validations: int
    reference_tuple_validations: int
    wall_ms: dict[str, float]


class _DriftFull(TypedDict):
    outcome: str
    failed_closed: bool
    tshark_calls: int
    version_validation_requests: int
    wall_ms: float


class _DriftSimplified(TypedDict):
    outcome: str
    candidate_exact: bool
    reference_executed: bool
    candidate_tuple_validations: int
    tshark_calls: int
    version_validation_requests: int
    wall_ms: float


class _DriftWitness(TypedDict):
    reference_filter_change: str
    spec_and_receipt_changed_together: bool
    full: _DriftFull
    simplified: _DriftSimplified


@dataclass(frozen=True)
class _Workload:
    name: str
    kind: str
    spec: SemanticSpecV1
    candidate_ir: IntentIrV1
    receipt: EvaluationReceiptV1


def _counter_delta(
    before: _RunnerSnapshot, after: _RunnerSnapshot
) -> _RunnerSnapshot:
    return _RunnerSnapshot(
        tshark_calls=after.tshark_calls - before.tshark_calls,
        version_validation_requests=(
            after.version_validation_requests
            - before.version_validation_requests
        ),
    )


def _capture_path(capture_root: Path, probe_id: str) -> Path:
    """Resolve a generated probe without allowing path traversal."""
    if not _PROBE_ID.fullmatch(probe_id):
        raise ValueError("Probe identifier is not safe")
    root = capture_root.resolve(strict=True)
    capture = (root / f"{probe_id}.pcap").resolve(strict=True)
    if not root.is_dir() or not capture.is_relative_to(root):
        raise ValueError("Capture must stay inside its root")
    if not capture.is_file():
        raise ValueError("Capture must be a regular file")
    return capture


def _simplified_replay(
    receipt: EvaluationReceiptV1,
    capture_root: Path,
    runner: _CountingRunner,
) -> _SimplifiedReplay:
    """Executable candidate-only replay used as the Simplified variant.

    Each probe executes exactly the candidate filter recorded in the receipt.
    It performs an exact tuple comparison, but deliberately does not execute a
    reference filter or either side's leaf predicates.
    """
    probes: list[_SimplifiedProbe] = []
    for recorded in receipt.probes:
        result = runner.run(
            _capture_path(capture_root, recorded.probe_id),
            receipt.candidate_filter,
        )
        probes.append(
            _SimplifiedProbe(
                probe_id=recorded.probe_id,
                recorded_frames=recorded.candidate_frames,
                replayed_frames=result.frames,
                runtime_ms=result.runtime_ms,
                exact=recorded.candidate_frames == result.frames,
            )
        )
    typed_probes = tuple(probes)
    return _SimplifiedReplay(
        exact=all(probe.exact for probe in typed_probes),
        probes=typed_probes,
    )


def _trace_coverage(trace: EvaluationTraceV1) -> _TraceCoverage:
    coverage = _TraceCoverage()
    for probe in trace.probes:
        frame_count = len(probe.counterexample_frames)
        dual_covered = (
            frame_count
            if probe.candidate_predicates and probe.canonical_predicates
            else 0
        )
        coverage += _TraceCoverage(
            counterexample_frames=frame_count,
            dual_side_covered_frames=dual_covered,
            candidate_predicate_paths=len(probe.candidate_predicates),
            canonical_predicate_paths=len(probe.canonical_predicates),
            candidate_trace_cells=(
                frame_count * len(probe.candidate_predicates)
            ),
            canonical_trace_cells=(
                frame_count * len(probe.canonical_predicates)
            ),
        )
    return coverage


def _syn_no_ack_diagnosis(
    trace: EvaluationTraceV1, receipt: EvaluationReceiptV1
) -> _Diagnosis:
    """Count broad SYN extras diagnosed by the omitted ACK-clear predicate."""
    recorded_by_id = {probe.probe_id: probe for probe in receipt.probes}
    result = _Diagnosis()
    for probe_trace in trace.probes:
        recorded = recorded_by_id[probe_trace.probe_id]
        extra_frames = recorded.candidate_only
        candidate_matches = {
            frame
            for predicate in probe_trace.candidate_predicates
            for frame in predicate.matched_frames
        }
        ack_clear = tuple(
            predicate
            for predicate in probe_trace.canonical_predicates
            if predicate.predicate.field == "tcp.flags.ack"
            and predicate.predicate.operator == Operator.EQ
            and predicate.predicate.value is False
        )
        rejected = sum(
            bool(ack_clear)
            and all(
                frame not in predicate.matched_frames for predicate in ack_clear
            )
            for frame in extra_frames
        )
        result += _Diagnosis(
            extra_frames=len(extra_frames),
            candidate_broad_match_frames=sum(
                frame in candidate_matches for frame in extra_frames
            ),
            canonical_ack_rejection_frames=rejected,
        )
    return result


def _measure_full(
    workload: _Workload,
    capture_root: Path,
    runner: _CountingRunner,
) -> _Measurement:
    before = runner.snapshot()
    started = time.perf_counter()
    result, _ = replay_live(
        workload.receipt,
        workload.spec,
        workload.candidate_ir,
        capture_root,
        runner=runner,
    )
    wall_ms = (time.perf_counter() - started) * 1000
    calls = _counter_delta(before, runner.snapshot())
    diagnosis = (
        _syn_no_ack_diagnosis(result.trace, workload.receipt)
        if workload.kind == "broad-syn"
        else _Diagnosis()
    )
    return _Measurement(
        wall_ms=wall_ms,
        tshark_calls=calls.tshark_calls,
        version_validation_requests=calls.version_validation_requests,
        candidate_tuple_validations=len(result.probes),
        reference_tuple_validations=(
            len(result.probes) if result.reference_verified else 0
        ),
        exact=result.exact,
        reference_verified=result.reference_verified,
        trace=_trace_coverage(result.trace),
        diagnosis=diagnosis,
    )


def _measure_simplified(
    workload: _Workload,
    capture_root: Path,
    runner: _CountingRunner,
) -> _Measurement:
    before = runner.snapshot()
    started = time.perf_counter()
    result = _simplified_replay(workload.receipt, capture_root, runner)
    wall_ms = (time.perf_counter() - started) * 1000
    calls = _counter_delta(before, runner.snapshot())
    return _Measurement(
        wall_ms=wall_ms,
        tshark_calls=calls.tshark_calls,
        version_validation_requests=calls.version_validation_requests,
        candidate_tuple_validations=len(result.probes),
        reference_tuple_validations=0,
        exact=result.exact,
        reference_verified=False,
    )


def _load_spec(work_dir: Path, case: str) -> SemanticSpecV1:
    return SemanticSpecV1.model_validate_json(
        (work_dir / "specs" / f"{case}.json").read_text(encoding="utf-8")
    )


def _load_intent(work_dir: Path, case: str) -> IntentIrV1:
    return IntentIrV1.model_validate_json(
        (work_dir / "intents" / f"{case}.json").read_text(encoding="utf-8")
    )


def _prepare_workloads(
    work_dir: Path, source_revision: str
) -> tuple[tuple[_Workload, ...], _CountingRunner]:
    generate_fixtures(work_dir)
    capture_root = work_dir / "captures"
    setup_runner = _CountingRunner()
    workloads: list[_Workload] = []
    specs: dict[str, SemanticSpecV1] = {}
    for case in _CASES:
        spec = _load_spec(work_dir, case)
        candidate_ir = _load_intent(work_dir, case)
        specs[case] = spec
        receipt, _, _ = evaluate_live_with_trace(
            spec,
            candidate_ir,
            capture_root,
            run_id=f"ablation-canonical-{case}",
            created_at=_CREATED_AT,
            code_revision=source_revision,
            runner=setup_runner,
        )
        workloads.append(
            _Workload(
                name=f"canonical-{case}",
                kind="canonical",
                spec=spec,
                candidate_ir=candidate_ir,
                receipt=receipt,
            )
        )

    broad_ir = IntentIrV1(
        expression=Predicate(
            field="tcp.flags.syn", operator=Operator.EQ, value=True
        )
    )
    syn_spec = specs["tcp-syn-no-ack"]
    broad_receipt, _, _ = evaluate_live_with_trace(
        syn_spec,
        broad_ir,
        capture_root,
        run_id="ablation-broad-syn",
        created_at=_CREATED_AT,
        code_revision=source_revision,
        runner=setup_runner,
    )
    workloads.append(
        _Workload(
            name="broad-syn-versus-syn-no-ack",
            kind="broad-syn",
            spec=syn_spec,
            candidate_ir=broad_ir,
            receipt=broad_receipt,
        )
    )
    if sum(len(workload.spec.probes) for workload in workloads[:3]) != 9:
        raise ValueError("Expected the existing three cases and nine probes")
    return tuple(workloads), setup_runner


def _percentiles(values: list[float]) -> dict[str, object]:
    if not values:
        raise ValueError("At least one latency sample is required")
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "samples": len(values),
        "p50": statistics.median(ordered),
        "p95": ordered[p95_index],
    }


def _measurement_row(
    measurement: _Measurement,
    *,
    repetition: int,
    workload: _Workload,
    order: tuple[str, str],
    variant: str,
) -> dict[str, object]:
    return {
        "repetition": repetition,
        "workload": workload.name,
        "candidate_kind": workload.kind,
        "order": order,
        "variant": variant,
        "wall_ms": measurement.wall_ms,
        "tshark_calls": measurement.tshark_calls,
        "version_validation_requests": (
            measurement.version_validation_requests
        ),
        "candidate_tuple_validations": (
            measurement.candidate_tuple_validations
        ),
        "reference_tuple_validations": (
            measurement.reference_tuple_validations
        ),
        "exact": measurement.exact,
        "reference_verified": measurement.reference_verified,
        "trace": asdict(measurement.trace),
        "diagnosis": asdict(measurement.diagnosis),
    }


def _measure_variants(
    workloads: tuple[_Workload, ...],
    capture_root: Path,
    repetitions: int,
) -> tuple[list[_Measurement], list[_Measurement], list[dict[str, object]]]:
    full_runner = _CountingRunner()
    simplified_runner = _CountingRunner()
    full_runner.version()
    simplified_runner.version()
    full_rows: list[_Measurement] = []
    simplified_rows: list[_Measurement] = []
    evidence_rows: list[dict[str, object]] = []
    sample_index = 0
    for repetition in range(repetitions):
        for workload in workloads:
            order = (
                ("full", "simplified")
                if sample_index % 2 == 0
                else ("simplified", "full")
            )
            sample_index += 1
            results: dict[str, _Measurement] = {}
            for variant in order:
                if variant == "full":
                    results[variant] = _measure_full(
                        workload, capture_root, full_runner
                    )
                else:
                    results[variant] = _measure_simplified(
                        workload, capture_root, simplified_runner
                    )
            full_rows.append(results["full"])
            simplified_rows.append(results["simplified"])
            evidence_rows.extend(
                _measurement_row(
                    results[variant],
                    repetition=repetition,
                    workload=workload,
                    order=order,
                    variant=variant,
                )
                for variant in order
            )
    return full_rows, simplified_rows, evidence_rows


def _sum_trace(rows: list[_Measurement]) -> _TraceCoverage:
    result = _TraceCoverage()
    for row in rows:
        result += row.trace
    return result


def _sum_diagnosis(rows: list[_Measurement]) -> _Diagnosis:
    result = _Diagnosis()
    for row in rows:
        result += row.diagnosis
    return result


def _variant_summary(rows: list[_Measurement]) -> _VariantSummary:
    return {
        "samples": len(rows),
        "all_candidate_replays_exact": all(row.exact for row in rows),
        "reference_verified_samples": sum(
            row.reference_verified for row in rows
        ),
        "tshark_calls": sum(row.tshark_calls for row in rows),
        "version_validation_requests": sum(
            row.version_validation_requests for row in rows
        ),
        "candidate_tuple_validations": sum(
            row.candidate_tuple_validations for row in rows
        ),
        "reference_tuple_validations": sum(
            row.reference_tuple_validations for row in rows
        ),
        "wall_ms": _percentiles([row.wall_ms for row in rows]),
    }


def _reference_drift_witness(
    canonical: _Workload, capture_root: Path
) -> _DriftWitness:
    """Use real tshark output to expose trust in stale reference labels."""
    drift_spec = canonical.spec.model_copy(update={"reference_filter": "tcp"})
    drift_receipt = canonical.receipt.model_copy(
        update={"reference_filter": "tcp"}
    )
    full_runner = _CountingRunner()
    full_before = full_runner.snapshot()
    full_started = time.perf_counter()
    full_outcome = "accepted"
    try:
        replay_live(
            drift_receipt,
            drift_spec,
            canonical.candidate_ir,
            capture_root,
            runner=full_runner,
        )
    except LiveError as error:
        full_outcome = error.code
    full_wall_ms = (time.perf_counter() - full_started) * 1000
    full_calls = _counter_delta(full_before, full_runner.snapshot())

    simplified_runner = _CountingRunner()
    simplified_before = simplified_runner.snapshot()
    simplified_started = time.perf_counter()
    simplified = _simplified_replay(
        drift_receipt, capture_root, simplified_runner
    )
    simplified_wall_ms = (time.perf_counter() - simplified_started) * 1000
    simplified_calls = _counter_delta(
        simplified_before, simplified_runner.snapshot()
    )
    return {
        "reference_filter_change": "canonical expression to broader tcp",
        "spec_and_receipt_changed_together": True,
        "full": {
            "outcome": full_outcome,
            "failed_closed": full_outcome == "reference_label_mismatch",
            "tshark_calls": full_calls.tshark_calls,
            "version_validation_requests": (
                full_calls.version_validation_requests
            ),
            "wall_ms": full_wall_ms,
        },
        "simplified": {
            "outcome": "candidate_exact" if simplified.exact else "drift",
            "candidate_exact": simplified.exact,
            "reference_executed": False,
            "candidate_tuple_validations": len(simplified.probes),
            "tshark_calls": simplified_calls.tshark_calls,
            "version_validation_requests": (
                simplified_calls.version_validation_requests
            ),
            "wall_ms": simplified_wall_ms,
        },
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _source_revision(value: str) -> str:
    if not value or len(value) > 256 or any(ord(char) < 0x20 for char in value):
        raise argparse.ArgumentTypeError("source revision must be printable")
    return value


def main() -> int:  # pylint: disable=too-many-locals
    """Run the paired experiment and write compact executable evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument(
        "--source-revision", required=True, type=_source_revision
    )
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions must be between 1 and 20")

    workloads, setup_runner = _prepare_workloads(
        args.work_dir, args.source_revision
    )
    capture_root = args.work_dir / "captures"
    full_rows, simplified_rows, evidence_rows = _measure_variants(
        workloads, capture_root, args.repetitions
    )
    canonical_syn = next(
        workload
        for workload in workloads
        if workload.name == "canonical-tcp-syn-no-ack"
    )
    drift = _reference_drift_witness(canonical_syn, capture_root)

    full_trace = _sum_trace(full_rows)
    simplified_trace = _sum_trace(simplified_rows)
    diagnosis = _sum_diagnosis(full_rows)
    full_summary = _variant_summary(full_rows)
    simplified_summary = _variant_summary(simplified_rows)
    expected_samples = len(workloads) * args.repetitions
    trace_complete = (
        full_trace.counterexample_frames > 0
        and full_trace.dual_side_covered_frames
        == full_trace.counterexample_frames
    )
    diagnosis_complete = (
        diagnosis.extra_frames > 0
        and diagnosis.candidate_broad_match_frames == diagnosis.extra_frames
        and diagnosis.canonical_ack_rejection_frames == diagnosis.extra_frames
    )
    valid_workload_complete = (
        len(full_rows) == expected_samples
        and len(simplified_rows) == expected_samples
        and all(row.exact and row.reference_verified for row in full_rows)
        and all(
            row.exact and not row.reference_verified for row in simplified_rows
        )
    )
    drift_exposes_difference = bool(
        drift["full"]["failed_closed"]
        and drift["simplified"]["candidate_exact"]
        and not drift["simplified"]["reference_executed"]
    )
    evidence_complete = (
        valid_workload_complete
        and trace_complete
        and diagnosis_complete
        and drift_exposes_difference
    )
    behavior_equivalent = not (
        drift_exposes_difference
        or full_trace.dual_side_covered_frames
        > simplified_trace.dual_side_covered_frames
    )
    if not evidence_complete:
        decision = "inconclusive"
    elif behavior_equivalent:
        full_p95 = float(full_summary["wall_ms"]["p95"])
        simplified_p95 = float(simplified_summary["wall_ms"]["p95"])
        decision = (
            "keep_simplified"
            if simplified_p95 <= full_p95 * 1.05
            else "keep_full"
        )
    else:
        decision = "keep_full"

    payload = {
        "schema_version": "trace-replay-ablation/1.0",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "source_revision": args.source_revision,
        "standalone_hash_validation": "not_run",
        "stability_gate_verified": False,
        "packet_payload_fields_read": False,
        "environment": {"tshark_version": setup_runner.version()},
        "inputs": {
            "curated_cases": list(_CASES),
            "canonical_probe_count": sum(
                len(workload.spec.probes) for workload in workloads[:3]
            ),
            "workloads_per_repetition": len(workloads),
            "repetitions": args.repetitions,
            "comparison": "Exact candidate frame tuples",
        },
        "variants": {
            "full": (
                "Production executable replay with reference verification and "
                "candidate plus canonical predicate traces"
            ),
            "simplified": (
                "Candidate-only executable replay; one candidate-filter run "
                "per probe with no reference or predicate trace execution"
            ),
        },
        "valid_workload": {
            "expected_samples_per_variant": expected_samples,
            "full": full_summary,
            "simplified": simplified_summary,
            "samples": evidence_rows,
        },
        "trace_coverage": {
            "full": asdict(full_trace),
            "simplified": asdict(simplified_trace),
            "full_dual_side_complete": trace_complete,
            "syn_no_ack_broad_candidate": asdict(diagnosis),
            "omitted_ack_clear_diagnosed": diagnosis_complete,
        },
        "reference_drift_witness": drift,
        "excluded_setup": {
            "purpose": "Create current receipts before paired replay timing",
            "tshark_calls": setup_runner.tshark_calls,
            "version_validation_requests": (
                setup_runner.version_validation_requests
            ),
        },
        "thresholds": {
            "all_valid_candidate_replays_exact": True,
            "full_verifies_every_valid_reference": True,
            "full_dual_side_trace_coverage": 1.0,
            "full_diagnoses_all_broad_syn_extra_frames": True,
            "full_rejects_real_reference_drift": True,
            "simplified_max_p95_regression_pct_if_equivalent": 5.0,
        },
        "valid_workload_complete": valid_workload_complete,
        "behavior_equivalent": behavior_equivalent,
        "evidence_complete": evidence_complete,
        "decision": decision,
    }
    _write_json(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "decision": decision,
                "evidence_complete": evidence_complete,
            },
            sort_keys=True,
        )
    )
    return 0 if evidence_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
