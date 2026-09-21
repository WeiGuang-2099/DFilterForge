"""Docker-only paired comparison of raw display-filter execution paths."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import hashlib
import inspect
import json
from pathlib import Path
from typing import cast

from dfilterforge import live as live_module
from dfilterforge import replay as replay_module
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import AblationDecision
from dfilterforge.evaluation import AblationReceiptV1
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import ComplexitySnapshotV1
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.live import evaluate_live
from dfilterforge.model_split import generate_model_split
from dfilterforge.replay import replay_live
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner

_CASE_ID = "tcp-expiring-ttl"
_CREATED_AT = datetime(2026, 9, 18, tzinfo=timezone.utc)
_DRIFT_CODE = "reference_label_mismatch"
_DRIFT_FRAME = 99999
_ACCEPTED_ALIAS = "ssl"
_UNKNOWN_FIELD_FILTER = "ip.ttll <= 1"
_TAMPER_CODE = "candidate_filter_mismatch"
_TAMPERED_FILTER = "udp"
_HYPOTHESIS = (
    "Scoring a raw display-filter candidate through the shared oracle "
    "preserves the per-probe reference run and independent label check that "
    "a candidate-only scorer loop drops."
)
_RATIONALE = (
    "The candidate-only loop charges a corrupted probe label to the model "
    "and never verifies a reference, so the shared oracle keeps its one "
    "extra tshark call per probe."
)
_REPLAY_HYPOTHESIS = (
    "Replaying a receipt by its recorded display-filter string through the "
    "shared replay path refuses a string the receipt does not vouch for "
    "before any capture is opened, and still re-executes the reference."
)
_REPLAY_RATIONALE = (
    "Only the full path rejects a tampered string with no tshark call and "
    "still catches a corrupted probe label; its measured cost is one extra "
    "tshark call per probe and no predicate trace."
)


class _CountingRunner(TsharkRunner):
    """Counts executions so both variants are compared on tshark calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self, capture: Path, display_filter: str) -> RunResult:
        self.calls += 1
        return super().run(capture, display_filter)


@dataclass(frozen=True)
class _Outcome:
    """What one variant did with one candidate on one specification."""

    outcome: str
    tshark_calls: int
    reference_verified: bool = False
    exact_probes: int = 0
    non_exact_probes: tuple[str, ...] = ()
    frames: int | None = None

    def row(self) -> dict[str, object]:
        """Returns the recorded columns for this outcome."""
        return {
            "outcome": self.outcome,
            "tshark_calls": self.tshark_calls,
            "reference_verified": self.reference_verified,
            "exact_probes": self.exact_probes,
            "non_exact_probes": list(self.non_exact_probes),
            "frames": self.frames,
        }


@dataclass(frozen=True)
class _Probes:
    """Both variants' probe results for one witness."""

    full: tuple[ProbeResultV1, ...]
    simplified: tuple[ProbeResultV1, ...]


@dataclass(frozen=True)
class _Witness:
    """One paired measurement of both variants over the same input."""

    witness: str
    candidate: str
    full: _Outcome
    simplified: _Outcome

    def row(self) -> dict[str, object]:
        """Returns the recorded columns for this witness."""
        return {
            "witness": self.witness,
            "candidate": self.candidate,
            "full": self.full.row(),
            "simplified": self.simplified.row(),
            "tshark_calls_full": self.full.tshark_calls,
            "tshark_calls_simplified": self.simplified.tshark_calls,
        }


def _simplified_filter_eval(
    spec: SemanticSpecV1,
    display_filter: str,
    capture_root: Path,
    runner: TsharkRunner,
) -> tuple[ProbeResultV1, ...]:
    """Test-only candidate: the scorer-side loop the shared oracle replaces.

    It runs only the candidate string and compares each result with the
    recorded labels. No reference execution, no capture-hash check, and no
    independent label check.
    """
    probes: list[ProbeResultV1] = []
    for expected in spec.probes:
        capture = capture_root / f"{expected.probe_id}.pcap"
        result = runner.run(capture, display_filter)
        probes.append(
            evaluate_probe(
                expected.probe_id,
                expected.expected_frames,
                result.frames,
                result.runtime_ms,
            )
        )
    return tuple(probes)


def _evaluated(
    probes: tuple[ProbeResultV1, ...], calls: int, verified: bool
) -> _Outcome:
    """Summarizes one set of probe results in the shared row shape."""
    return _Outcome(
        outcome="evaluated",
        tshark_calls=calls,
        reference_verified=verified,
        exact_probes=sum(probe.exact for probe in probes),
        non_exact_probes=tuple(
            probe.probe_id for probe in probes if not probe.exact
        ),
    )


def _full_eval(
    spec: SemanticSpecV1, display_filter: str, capture_root: Path
) -> tuple[_Outcome, tuple[ProbeResultV1, ...]]:
    """Runs the shared oracle over a raw display-filter candidate."""
    runner = _CountingRunner()
    try:
        receipt, _ = evaluate_live(
            spec,
            display_filter,
            capture_root,
            run_id="raw-filter-ablation",
            created_at=_CREATED_AT,
            code_revision="ablation",
            runner=runner,
        )
    except DFilterForgeError as error:
        return (
            _Outcome(
                outcome=error.code,
                tshark_calls=runner.calls,
                reference_verified=(
                    error.code != _DRIFT_CODE and runner.calls > 1
                ),
            ),
            (),
        )
    return _evaluated(receipt.probes, runner.calls, True), receipt.probes


def _simplified_eval(
    spec: SemanticSpecV1, display_filter: str, capture_root: Path
) -> tuple[_Outcome, tuple[ProbeResultV1, ...]]:
    """Runs the candidate-only loop over the same inputs."""
    runner = _CountingRunner()
    try:
        probes = _simplified_filter_eval(
            spec, display_filter, capture_root, runner
        )
    except DFilterForgeError as error:
        return _Outcome(outcome=error.code, tshark_calls=runner.calls), ()
    return _evaluated(probes, runner.calls, False), probes


def _witness(
    witness_id: str,
    spec: SemanticSpecV1,
    display_filter: str,
    capture_root: Path,
) -> tuple[_Witness, _Probes]:
    """Measures one paired witness and returns both variants' probes."""
    full, full_probes = _full_eval(spec, display_filter, capture_root)
    simplified, simplified_probes = _simplified_eval(
        spec, display_filter, capture_root
    )
    return (
        _Witness(
            witness=witness_id,
            candidate=display_filter,
            full=full,
            simplified=simplified,
        ),
        _Probes(full=full_probes, simplified=simplified_probes),
    )


def _drifted(spec: SemanticSpecV1) -> SemanticSpecV1:
    """Copies the specification with one corrupted independent label."""
    probe = spec.probes[0]
    corrupted = probe.model_copy(
        update={
            "expected_frames": tuple(
                sorted(set(probe.expected_frames) | {_DRIFT_FRAME})
            )
        }
    )
    return spec.model_copy(update={"probes": (corrupted, *spec.probes[1:])})


def _binding_witness(capture_root: Path, probe_id: str) -> _Witness:
    """Measures a catalog-binding variant against a filter tshark accepts."""
    runner = _CountingRunner()
    intent = IntentIrV1(
        expression=Predicate(field=_ACCEPTED_ALIAS, operator=Operator.EXISTS)
    )
    binding = "bound"
    try:
        bind_catalog(runner, (intent,))
    except DFilterForgeError as error:
        binding = error.code
    executed = runner.run(capture_root / f"{probe_id}.pcap", _ACCEPTED_ALIAS)
    return _Witness(
        witness="o5-catalog-binding-variant",
        candidate=_ACCEPTED_ALIAS,
        full=_Outcome(
            outcome="executed",
            tshark_calls=runner.calls,
            frames=len(executed.frames),
        ),
        simplified=_Outcome(outcome=binding, tshark_calls=0),
    )


def _complexity(source: str) -> ComplexitySnapshotV1:
    """Counts the public symbols one variant keeps in the compared path."""
    tree = ast.parse(source)
    return ComplexitySnapshotV1(
        module_count=1,
        dependency_count=0,
        public_symbol_count=sum(
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and not node.name.startswith("_")
            for node in tree.body
        ),
    )


def _receipt(
    source_revision: str, spec: SemanticSpecV1, honest: _Probes
) -> AblationReceiptV1:
    """Builds the typed receipt from the honest-reference witness."""
    simplified_source = inspect.getsource(_simplified_filter_eval)
    return AblationReceiptV1(
        ablation_id="004-addendum-raw-filter-oracle",
        hypothesis=_HYPOTHESIS,
        full_revision=source_revision,
        simplified_patch_hash=hashlib.sha256(
            simplified_source.encode()
        ).hexdigest(),
        input_hashes=tuple(
            sorted(
                {probe.capture_sha256 for probe in spec.probes}
                | {content_sha256(spec)}
            )
        ),
        full_metrics=aggregate_metrics(honest.full),
        simplified_metrics=aggregate_metrics(honest.simplified),
        full_complexity=_complexity(inspect.getsource(live_module)),
        simplified_complexity=_complexity(simplified_source),
        decision=AblationDecision.KEEP_FULL,
        rationale=_RATIONALE,
    )


def _oracle_witnesses(
    spec: SemanticSpecV1, mutation_filter: str, capture_root: Path
) -> tuple[tuple[_Witness, ...], _Probes]:
    """Measures every oracle witness in order and returns the honest probes."""
    honest, probes = _witness(
        "o1-honest-reference", spec, spec.reference_filter, capture_root
    )
    if not probes.full or not all(probe.exact for probe in probes.full):
        raise ValueError(
            "the reference filter is not exact under the shared oracle"
        )
    mutation, _ = _witness(
        "o2-honest-mutation", spec, mutation_filter, capture_root
    )
    drift, _ = _witness(
        "o3-corrupted-label",
        _drifted(spec),
        spec.reference_filter,
        capture_root,
    )
    unknown, _ = _witness(
        "o4-unknown-field", spec, _UNKNOWN_FIELD_FILTER, capture_root
    )
    binding = _binding_witness(capture_root, spec.probes[0].probe_id)
    return (honest, mutation, drift, unknown, binding), probes


def _payload(
    source_revision: str,
    witnesses: tuple[_Witness, ...],
    receipt: AblationReceiptV1,
) -> dict[str, object]:
    """Assembles the evidence file from the measured witnesses."""
    drift = witnesses[2]
    return {
        "schema_version": "1.0",
        "stage": "oracle",
        "source_revision": source_revision,
        "tshark_version": TsharkRunner().version(),
        "witnesses": [witness.row() for witness in witnesses],
        "full_detects_label_drift": drift.full.outcome == _DRIFT_CODE,
        "simplified_detects_label_drift": (
            drift.simplified.outcome == _DRIFT_CODE
        ),
        "variants_agree_on_honest_specs": all(
            witness.full.non_exact_probes == witness.simplified.non_exact_probes
            for witness in witnesses[:2]
        ),
        "tshark_calls_full": sum(
            witness.full.tshark_calls for witness in witnesses
        ),
        "tshark_calls_simplified": sum(
            witness.simplified.tshark_calls for witness in witnesses
        ),
        "receipt": receipt.model_dump(mode="json"),
    }


def _write_receipt(output: Path, receipt: AblationReceiptV1) -> None:
    """Writes the typed receipt beside the evidence file."""
    receipt_path = output.with_suffix(".receipt.json")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        receipt.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def _oracle_stage(
    output: Path, source_revision: str, work_dir: Path
) -> dict[str, object]:
    """Measures the oracle stage and writes its typed receipt."""
    artifacts = generate_model_split(work_dir)
    case = next(
        gold for gold in artifacts.gold.cases if gold.case_id == _CASE_ID
    )
    capture_root = work_dir / "captures"
    witnesses, honest = _oracle_witnesses(
        case.spec, case.mutation_filter, capture_root
    )
    receipt = _receipt(source_revision, case.spec, honest)
    _write_receipt(output, receipt)
    return _payload(source_revision, witnesses, receipt)


def _simplified_string_replay(
    receipt: EvaluationReceiptV1,
    display_filter: str,
    capture_root: Path,
    runner: TsharkRunner,
) -> tuple[dict[str, object], ...]:
    """Test-only candidate: the replay loop the shared replay path replaces.

    It re-runs only the supplied string and compares each result with the
    recorded candidate frames. It never executes the reference filter and
    never reads the receipt's own ``candidate_filter``, so any string is
    replayed exactly as it was handed in.
    """
    rows: list[dict[str, object]] = []
    for probe in receipt.probes:
        capture = capture_root / f"{probe.probe_id}.pcap"
        result = runner.run(capture, display_filter)
        rows.append(
            {
                "probe_id": probe.probe_id,
                "recorded_frames": list(probe.candidate_frames),
                "replayed_frames": list(result.frames),
                "runtime_ms": result.runtime_ms,
                "exact": result.frames == probe.candidate_frames,
            }
        )
    return tuple(rows)


def _row_probe(row: dict[str, object]) -> ProbeResultV1:
    """Rebuilds one comparable probe result from a simplified row."""
    return evaluate_probe(
        cast(str, row["probe_id"]),
        tuple(cast("list[int]", row["recorded_frames"])),
        tuple(cast("list[int]", row["replayed_frames"])),
        cast(float, row["runtime_ms"]),
    )


def _full_replay(
    receipt: EvaluationReceiptV1,
    spec: SemanticSpecV1,
    display_filter: str,
    capture_root: Path,
) -> tuple[_Outcome, tuple[ProbeResultV1, ...], bool]:
    """Replays a display-filter string through the shared replay path."""
    runner = _CountingRunner()
    try:
        result, _ = replay_live(
            receipt, spec, display_filter, capture_root, runner=runner
        )
    except DFilterForgeError as error:
        outcome = _Outcome(outcome=error.code, tshark_calls=runner.calls)
        return outcome, (), False
    probes = tuple(
        evaluate_probe(
            probe.probe_id,
            probe.recorded_frames,
            probe.replayed_frames,
            probe.runtime_ms,
        )
        for probe in result.probes
    )
    return (
        _evaluated(probes, runner.calls, True),
        probes,
        result.trace is not None,
    )


def _simplified_replay(
    receipt: EvaluationReceiptV1, display_filter: str, capture_root: Path
) -> tuple[_Outcome, tuple[ProbeResultV1, ...]]:
    """Runs the candidate-only replay loop over the same inputs."""
    runner = _CountingRunner()
    try:
        rows = _simplified_string_replay(
            receipt, display_filter, capture_root, runner
        )
    except DFilterForgeError as error:
        return _Outcome(outcome=error.code, tshark_calls=runner.calls), ()
    probes = tuple(_row_probe(row) for row in rows)
    return _evaluated(probes, runner.calls, False), probes


def _replay_witness(
    witness_id: str,
    receipt: EvaluationReceiptV1,
    spec: SemanticSpecV1,
    display_filter: str,
    capture_root: Path,
) -> tuple[_Witness, _Probes, bool]:
    """Measures one paired replay witness over the same supplied string."""
    full, full_probes, traced = _full_replay(
        receipt, spec, display_filter, capture_root
    )
    simplified, simplified_probes = _simplified_replay(
        receipt, display_filter, capture_root
    )
    return (
        _Witness(
            witness=witness_id,
            candidate=display_filter,
            full=full,
            simplified=simplified,
        ),
        _Probes(full=full_probes, simplified=simplified_probes),
        traced,
    )


def _drifted_pair(
    spec: SemanticSpecV1, receipt: EvaluationReceiptV1
) -> tuple[SemanticSpecV1, EvaluationReceiptV1]:
    """Copies both sides with the same single corrupted probe label.

    Only the first probe's independent label moves, so the manifest check
    still passes and the reference filter is the one the honest receipt
    recorded. The detected drift is therefore the label and nothing else.
    """
    drifted_spec = _drifted(spec)
    recorded = receipt.probes[0]
    corrupted = evaluate_probe(
        recorded.probe_id,
        tuple(sorted(set(recorded.expected_frames) | {_DRIFT_FRAME})),
        recorded.candidate_frames,
        recorded.runtime_ms,
    )
    probes = (corrupted, *receipt.probes[1:])
    drifted_receipt = receipt.model_copy(
        update={"probes": probes, "metrics": aggregate_metrics(probes)}
    )
    return drifted_spec, drifted_receipt


def _typed_ir_replay(spec: SemanticSpecV1, capture_root: Path) -> _Outcome:
    """Measures the typed-IR replay of the same case for contrast.

    The string witnesses show what the raw path costs. This records the
    trace the typed path produces on the same probes, so the loss is a
    measured difference rather than an assertion.
    """
    recorded, _ = evaluate_live(
        spec,
        spec.canonical_ir,
        capture_root,
        run_id="raw-filter-replay-ablation-typed",
        created_at=_CREATED_AT,
        code_revision="ablation",
    )
    runner = _CountingRunner()
    try:
        result, _ = replay_live(
            recorded, spec, spec.canonical_ir, capture_root, runner=runner
        )
    except DFilterForgeError as error:
        return _Outcome(outcome=error.code, tshark_calls=runner.calls)
    return _Outcome(
        outcome=(
            "trace_present" if result.trace is not None else "trace_absent"
        ),
        tshark_calls=runner.calls,
        reference_verified=result.reference_verified,
        exact_probes=sum(probe.exact for probe in result.probes),
    )


def _replay_witnesses(
    spec: SemanticSpecV1, receipt: EvaluationReceiptV1, capture_root: Path
) -> tuple[tuple[_Witness, ...], _Probes, bool]:
    """Measures every replay witness in order and returns the honest probes."""
    honest, probes, traced = _replay_witness(
        "r1-honest-receipt",
        receipt,
        spec,
        receipt.candidate_filter,
        capture_root,
    )
    if not probes.full or not all(probe.exact for probe in probes.full):
        raise ValueError("the recorded filter does not replay exactly")
    drifted_spec, drifted_receipt = _drifted_pair(spec, receipt)
    drift, _, _ = _replay_witness(
        "r2-corrupted-label",
        drifted_receipt,
        drifted_spec,
        drifted_receipt.candidate_filter,
        capture_root,
    )
    tampered, _, _ = _replay_witness(
        "r3-tampered-string", receipt, spec, _TAMPERED_FILTER, capture_root
    )
    return (honest, drift, tampered), probes, traced


def _replay_receipt(
    source_revision: str, spec: SemanticSpecV1, honest: _Probes
) -> AblationReceiptV1:
    """Builds the typed receipt from the honest-replay witness."""
    simplified_source = inspect.getsource(_simplified_string_replay)
    return AblationReceiptV1(
        ablation_id="004-addendum-raw-filter-replay",
        hypothesis=_REPLAY_HYPOTHESIS,
        full_revision=source_revision,
        simplified_patch_hash=hashlib.sha256(
            simplified_source.encode()
        ).hexdigest(),
        input_hashes=tuple(
            sorted(
                {probe.capture_sha256 for probe in spec.probes}
                | {content_sha256(spec)}
            )
        ),
        full_metrics=aggregate_metrics(honest.full),
        simplified_metrics=aggregate_metrics(honest.simplified),
        full_complexity=_complexity(inspect.getsource(replay_module)),
        simplified_complexity=_complexity(simplified_source),
        decision=AblationDecision.KEEP_FULL,
        rationale=_REPLAY_RATIONALE,
    )


# pylint: disable-next=too-many-arguments
def _replay_payload(
    source_revision: str,
    witnesses: tuple[_Witness, ...],
    traced: bool,
    typed: _Outcome,
    receipt: AblationReceiptV1,
) -> dict[str, object]:
    """Assembles the replay evidence file from the measured witnesses."""
    drift = witnesses[1]
    tampered = witnesses[2]
    return {
        "schema_version": "1.0",
        "stage": "replay",
        "source_revision": source_revision,
        "tshark_version": TsharkRunner().version(),
        "witnesses": [witness.row() for witness in witnesses],
        "full_detects_label_drift": drift.full.outcome == _DRIFT_CODE,
        "simplified_detects_label_drift": (
            drift.simplified.outcome == _DRIFT_CODE
        ),
        "full_rejects_tampered_string": tampered.full.outcome == _TAMPER_CODE,
        "simplified_rejects_tampered_string": (
            tampered.simplified.outcome == _TAMPER_CODE
        ),
        "full_trace_present": traced,
        "typed_ir_replay": typed.row(),
        "typed_ir_trace_present": typed.outcome == "trace_present",
        "tshark_calls_before_rejection": {
            "full": tampered.full.tshark_calls,
            "simplified": tampered.simplified.tshark_calls,
        },
        "tshark_calls_full": sum(
            witness.full.tshark_calls for witness in witnesses
        ),
        "tshark_calls_simplified": sum(
            witness.simplified.tshark_calls for witness in witnesses
        ),
        "receipt": receipt.model_dump(mode="json"),
    }


def _replay_stage(
    output: Path, source_revision: str, work_dir: Path
) -> dict[str, object]:
    """Measures the replay stage and writes its typed receipt."""
    artifacts = generate_model_split(work_dir)
    case = next(
        gold for gold in artifacts.gold.cases if gold.case_id == _CASE_ID
    )
    capture_root = work_dir / "captures"
    recorded, _ = evaluate_live(
        case.spec,
        case.spec.reference_filter,
        capture_root,
        run_id="raw-filter-replay-ablation",
        created_at=_CREATED_AT,
        code_revision="ablation",
    )
    witnesses, honest, traced = _replay_witnesses(
        case.spec, recorded, capture_root
    )
    typed = _typed_ir_replay(case.spec, capture_root)
    receipt = _replay_receipt(source_revision, case.spec, honest)
    _write_receipt(output, receipt)
    return _replay_payload(source_revision, witnesses, traced, typed, receipt)


def main() -> None:
    """Runs one stage and writes its evidence file and typed receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("oracle", "replay"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--work-dir", type=Path, default=Path("/tmp/raw-filter-work")
    )
    arguments = parser.parse_args()
    stage = _oracle_stage if arguments.stage == "oracle" else _replay_stage
    payload = stage(
        arguments.output, arguments.source_revision, arguments.work_dir
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(arguments.output),
                "receipt": str(arguments.output.with_suffix(".receipt.json")),
                "decision": AblationDecision.KEEP_FULL.value,
            }
        )
    )


if __name__ == "__main__":
    main()
