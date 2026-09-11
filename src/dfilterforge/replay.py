"""Executable replay orchestration for recorded evaluation receipts."""

# pylint: disable=duplicate-code,too-many-arguments

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import EvaluationTraceV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.live import evaluate_live_with_trace
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.runner import TsharkRunner


class ReplayError(RuntimeError):
    """A sanitized executable replay failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReplayProbeResultV1(FrozenModel):
    """Recorded and replayed candidate packet sets for one probe."""

    probe_id: str
    recorded_frames: tuple[int, ...]
    replayed_frames: tuple[int, ...]
    runtime_ms: float = Field(ge=0)
    recorded_only: tuple[int, ...] = ()
    replayed_only: tuple[int, ...] = ()
    exact: bool = False

    @field_validator(
        "recorded_frames",
        "replayed_frames",
        "recorded_only",
        "replayed_only",
    )
    @classmethod
    def normalize_frames(cls, frames: tuple[int, ...]) -> tuple[int, ...]:
        """Sort frame numbers and reject duplicates or non-positive IDs."""
        if any(frame < 1 for frame in frames):
            raise ValueError("frame numbers must be positive")
        if len(set(frames)) != len(frames):
            raise ValueError("frame numbers must be unique")
        return tuple(sorted(frames))

    @model_validator(mode="after")
    def validate_derived_fields(self) -> "ReplayProbeResultV1":
        """Reject manually supplied differences inconsistent with frames."""
        recorded = set(self.recorded_frames)
        replayed = set(self.replayed_frames)
        recorded_only = tuple(sorted(recorded - replayed))
        replayed_only = tuple(sorted(replayed - recorded))
        if self.recorded_only != recorded_only:
            raise ValueError("recorded_only does not match packet sets")
        if self.replayed_only != replayed_only:
            raise ValueError("replayed_only does not match packet sets")
        if self.exact != (self.recorded_frames == self.replayed_frames):
            raise ValueError("exact does not match packet sets")
        return self


class ExecutableReplayResultV1(FrozenModel):
    """Result of actually re-running a recorded candidate with tshark."""

    schema_version: Literal["executable-replay/1.0"] = "executable-replay/1.0"
    run_id: str
    executed: Literal[True] = True
    reference_verified: Literal[True] = True
    exact: bool
    probes: tuple[ReplayProbeResultV1, ...] = Field(min_length=1)
    trace: EvaluationTraceV1

    @model_validator(mode="after")
    def validate_result(self) -> "ExecutableReplayResultV1":
        """Validate aggregate equality and trace-to-probe alignment."""
        probe_ids = tuple(probe.probe_id for probe in self.probes)
        if len(set(probe_ids)) != len(probe_ids):
            raise ValueError("replay probe IDs must be unique")
        if self.exact != all(probe.exact for probe in self.probes):
            raise ValueError("exact does not match replay probes")
        if self.trace.run_id != self.run_id:
            raise ValueError("trace run ID does not match replay")
        if tuple(probe.probe_id for probe in self.trace.probes) != probe_ids:
            raise ValueError("trace probes do not match replay probes")
        return self


def _validate_receipt_spec(
    receipt: EvaluationReceiptV1, spec: SemanticSpecV1
) -> None:
    """Reject receipt/spec structure drift before capture execution."""
    receipt_ids = tuple(probe.probe_id for probe in receipt.probes)
    spec_ids = tuple(probe.probe_id for probe in spec.probes)
    if len(set(receipt_ids)) != len(receipt_ids) or len(set(spec_ids)) != len(
        spec_ids
    ):
        raise ReplayError(
            "probe_manifest_mismatch",
            "Replay probe identifiers must be unique",
        )
    if receipt.reference_filter != spec.reference_filter:
        raise ReplayError(
            "reference_filter_mismatch",
            "Receipt and specification reference filters differ",
        )
    if len(receipt.probes) != len(spec.probes) or any(
        recorded.probe_id != expected.probe_id
        or recorded.expected_frames != expected.expected_frames
        for recorded, expected in zip(receipt.probes, spec.probes, strict=True)
    ):
        raise ReplayError(
            "probe_manifest_mismatch",
            "Receipt and specification probes differ",
        )


def _replay_probe(
    recorded_probe: ProbeResultV1, replayed_probe: ProbeResultV1
) -> ReplayProbeResultV1:
    """Build one strongly validated replay comparison."""
    if recorded_probe.probe_id != replayed_probe.probe_id:
        raise ReplayError(
            "execution_result_invalid", "Executable replay probes differ"
        )
    recorded_frames = recorded_probe.candidate_frames
    replayed_frames = replayed_probe.candidate_frames
    recorded_set = set(recorded_frames)
    replayed_set = set(replayed_frames)
    return ReplayProbeResultV1(
        probe_id=recorded_probe.probe_id,
        recorded_frames=recorded_frames,
        replayed_frames=replayed_frames,
        runtime_ms=replayed_probe.runtime_ms,
        recorded_only=tuple(sorted(recorded_set - replayed_set)),
        replayed_only=tuple(sorted(replayed_set - recorded_set)),
        exact=recorded_frames == replayed_frames,
    )


# pylint: disable-next=too-many-arguments
def replay_live(
    receipt: EvaluationReceiptV1,
    spec: SemanticSpecV1,
    candidate_ir: IntentIrV1,
    capture_root: Path,
    *,
    catalog: FieldCatalogV1 | None = None,
    runner: TsharkRunner | None = None,
) -> tuple[ExecutableReplayResultV1, LiveEnvironmentV1]:
    """Re-run a receipt's filters without trusting recorded hash claims.

    The receipt and specification must agree structurally. The candidate IR is
    rebound to the current frozen catalog and must compile to the exact filter
    stored in the receipt. Data, receipt, packet-set, and recorded environment
    hashes are intentionally not compared here.
    """
    _validate_receipt_spec(receipt, spec)
    active_runner = runner if runner is not None else TsharkRunner()
    bound_catalog = bind_catalog(
        active_runner, (candidate_ir, spec.canonical_ir), catalog
    )
    if compile_intent(candidate_ir, bound_catalog) != receipt.candidate_filter:
        raise ReplayError(
            "candidate_filter_mismatch",
            "Candidate IR does not compile to the recorded filter",
        )

    replayed_receipt, environment, trace = evaluate_live_with_trace(
        spec,
        candidate_ir,
        capture_root,
        run_id=receipt.run_id,
        created_at=receipt.created_at,
        code_revision=receipt.code_revision,
        catalog=bound_catalog,
        runner=active_runner,
    )
    if replayed_receipt.run_id != receipt.run_id or len(
        replayed_receipt.probes
    ) != len(receipt.probes):
        raise ReplayError(
            "execution_result_invalid", "Executable replay result is invalid"
        )
    probes = tuple(
        _replay_probe(recorded, replayed)
        for recorded, replayed in zip(
            receipt.probes, replayed_receipt.probes, strict=True
        )
    )
    result = ExecutableReplayResultV1(
        run_id=receipt.run_id,
        exact=all(probe.exact for probe in probes),
        probes=probes,
        trace=trace,
    )
    return result, environment
