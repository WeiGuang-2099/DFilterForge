"""Packet-set evaluation contracts, metrics, and receipts."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from enum import StrEnum
import math
from typing import Literal, TypedDict

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from dfilterforge.canonical import content_sha256
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Predicate


def _normalize_frame_numbers(
    frames: tuple[int, ...], *, description: str
) -> tuple[int, ...]:
    """Sorts frame numbers and rejects duplicates or non-positive IDs."""
    if any(frame < 1 for frame in frames):
        raise ValueError(f"{description} must be positive")
    if len(set(frames)) != len(frames):
        raise ValueError(f"{description} must be unique")
    return tuple(sorted(frames))


class PredicateTraceV1(FrozenModel):
    """Raw tshark match evidence for one typed predicate."""

    node_path: tuple[int, ...]
    predicate: Predicate
    display_filter: str
    matched_frames: tuple[int, ...]

    @field_validator("node_path")
    @classmethod
    def validate_node_path(cls, path: tuple[int, ...]) -> tuple[int, ...]:
        """Rejects child indexes that cannot identify an AST node."""
        if any(index < 0 for index in path):
            raise ValueError("node path indexes must be non-negative")
        return path

    @field_validator("matched_frames")
    @classmethod
    def normalize_matched_frames(
        cls, frames: tuple[int, ...]
    ) -> tuple[int, ...]:
        """Normalizes validated predicate-match frame numbers."""
        return _normalize_frame_numbers(
            frames, description="matched frame numbers"
        )


class ProbeTraceV1(FrozenModel):
    """Candidate and canonical predicate evidence for one packet diff."""

    probe_id: str
    counterexample_frames: tuple[int, ...]
    candidate_predicates: tuple[PredicateTraceV1, ...] = ()
    canonical_predicates: tuple[PredicateTraceV1, ...] = ()

    @field_validator("counterexample_frames")
    @classmethod
    def normalize_counterexample_frames(
        cls, frames: tuple[int, ...]
    ) -> tuple[int, ...]:
        """Normalizes validated counterexample frame numbers."""
        return _normalize_frame_numbers(
            frames, description="counterexample frame numbers"
        )

    @model_validator(mode="after")
    def validate_predicate_evidence(self) -> "ProbeTraceV1":
        """Checks trace coverage, paths, and packet-diff membership."""
        sides = (self.candidate_predicates, self.canonical_predicates)
        if not self.counterexample_frames:
            if any(sides):
                raise ValueError("exact probes cannot contain predicate traces")
            return self
        if not all(sides):
            raise ValueError(
                "counterexample probes require candidate and canonical traces"
            )
        counterexamples = set(self.counterexample_frames)
        for traces in sides:
            paths = [trace.node_path for trace in traces]
            if len(set(paths)) != len(paths):
                raise ValueError(
                    "predicate trace paths must be unique per side"
                )
            if any(
                not set(trace.matched_frames).issubset(counterexamples)
                for trace in traces
            ):
                raise ValueError("matched frames must be counterexample frames")
        return self


class EvaluationTraceV1(FrozenModel):
    """Versioned predicate-level evidence for one evaluation run."""

    schema_version: Literal["predicate-trace/1.0"] = "predicate-trace/1.0"
    run_id: str
    probes: tuple[ProbeTraceV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_probe_ids(self) -> "EvaluationTraceV1":
        """Rejects ambiguous duplicate probe identifiers."""
        if len({probe.probe_id for probe in self.probes}) != len(self.probes):
            raise ValueError("trace probe IDs must be unique")
        return self


class ProbeResultV1(FrozenModel):
    """Candidate/reference packet-set comparison for one capture."""

    schema_version: Literal["1.0"] = "1.0"
    probe_id: str
    expected_frames: tuple[int, ...]
    candidate_frames: tuple[int, ...]
    runtime_ms: float = Field(ge=0)
    intersection: tuple[int, ...] = ()
    reference_only: tuple[int, ...] = ()
    candidate_only: tuple[int, ...] = ()
    exact: bool = False
    empty_set_coincidence: bool = False
    precision: float = Field(default=0, ge=0, le=1)
    recall: float = Field(default=0, ge=0, le=1)
    f1: float = Field(default=0, ge=0, le=1)
    jaccard: float = Field(default=0, ge=0, le=1)

    @field_validator("expected_frames", "candidate_frames")
    @classmethod
    def normalize_frames(cls, frames: tuple[int, ...]) -> tuple[int, ...]:
        """Sorts frame numbers and rejects duplicates or non-positive IDs."""
        if any(frame < 1 for frame in frames):
            raise ValueError("frame numbers must be positive")
        if len(set(frames)) != len(frames):
            raise ValueError("frame numbers must be unique")
        return tuple(sorted(frames))

    @model_validator(mode="after")
    def validate_derived_fields(self) -> "ProbeResultV1":
        """Rejects manually supplied metrics inconsistent with packet sets."""
        expected = _calculate_probe_metrics(
            self.expected_frames, self.candidate_frames
        )
        names = (
            "intersection",
            "reference_only",
            "candidate_only",
            "exact",
            "empty_set_coincidence",
            "precision",
            "recall",
            "f1",
            "jaccard",
        )
        for name in names:
            if getattr(self, name) != expected[name]:
                raise ValueError(f"{name} does not match packet sets")
        return self


class AggregateMetricsV1(FrozenModel):
    """Macro metrics across independent probes."""

    probe_count: int = Field(ge=1)
    strong_exact_count: int = Field(ge=0)
    empty_set_coincidence_count: int = Field(ge=0)
    macro_precision: float = Field(ge=0, le=1)
    macro_recall: float = Field(ge=0, le=1)
    macro_f1: float = Field(ge=0, le=1)
    macro_jaccard: float = Field(ge=0, le=1)
    p50_runtime_ms: float = Field(ge=0)
    p95_runtime_ms: float = Field(ge=0)


def _safe_ratio(
    numerator: int | float, denominator: int | float, empty: float
) -> float:
    return numerator / denominator if denominator else empty


class _DerivedProbeMetrics(TypedDict):
    intersection: tuple[int, ...]
    reference_only: tuple[int, ...]
    candidate_only: tuple[int, ...]
    exact: bool
    empty_set_coincidence: bool
    precision: float
    recall: float
    f1: float
    jaccard: float


def _calculate_probe_metrics(
    expected_frames: tuple[int, ...] | list[int],
    candidate_frames: tuple[int, ...] | list[int],
) -> _DerivedProbeMetrics:
    """Calculates the derived values shared by construction and validation."""
    expected = set(expected_frames)
    candidate = set(candidate_frames)
    intersection = expected & candidate
    precision = _safe_ratio(
        len(intersection), len(candidate), 1.0 if not expected else 0.0
    )
    recall = _safe_ratio(
        len(intersection), len(expected), 1.0 if not candidate else 0.0
    )
    return {
        "intersection": tuple(sorted(intersection)),
        "reference_only": tuple(sorted(expected - candidate)),
        "candidate_only": tuple(sorted(candidate - expected)),
        "exact": expected == candidate,
        "empty_set_coincidence": not expected and not candidate,
        "precision": precision,
        "recall": recall,
        "f1": _safe_ratio(2 * precision * recall, precision + recall, 0.0),
        "jaccard": _safe_ratio(
            len(intersection), len(expected | candidate), 1.0
        ),
    }


def evaluate_probe(
    probe_id: str,
    expected_frames: tuple[int, ...] | list[int],
    candidate_frames: tuple[int, ...] | list[int],
    runtime_ms: float,
) -> ProbeResultV1:
    """Evaluates one candidate packet set against its expected packet set."""
    return ProbeResultV1(
        probe_id=probe_id,
        expected_frames=tuple(expected_frames),
        candidate_frames=tuple(candidate_frames),
        runtime_ms=runtime_ms,
        **_calculate_probe_metrics(expected_frames, candidate_frames),
    )


def _percentile_nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def aggregate_metrics(probes: tuple[ProbeResultV1, ...]) -> AggregateMetricsV1:
    """Computes macro metrics and nearest-rank latency percentiles."""
    if not probes:
        raise ValueError("at least one probe is required")
    count = len(probes)
    runtimes = [probe.runtime_ms for probe in probes]
    return AggregateMetricsV1(
        probe_count=count,
        strong_exact_count=sum(
            probe.exact and not probe.empty_set_coincidence for probe in probes
        ),
        empty_set_coincidence_count=sum(
            probe.empty_set_coincidence for probe in probes
        ),
        macro_precision=sum(probe.precision for probe in probes) / count,
        macro_recall=sum(probe.recall for probe in probes) / count,
        macro_f1=sum(probe.f1 for probe in probes) / count,
        macro_jaccard=sum(probe.jaccard for probe in probes) / count,
        p50_runtime_ms=_percentile_nearest_rank(runtimes, 0.50),
        p95_runtime_ms=_percentile_nearest_rank(runtimes, 0.95),
    )


class EnvironmentManifestV1(FrozenModel):
    """Execution environment identity used by reproducible receipts."""

    schema_version: Literal["1.0"] = "1.0"
    tshark_version: str
    image_digest: str
    profile_hash: str
    catalog_hash: str
    timezone: Literal["UTC"] = "UTC"
    name_resolution: Literal[False] = False
    pass_mode: Literal["single", "two-pass"] = "single"
    enabled_protocols: tuple[str, ...] = ()
    decode_as: tuple[str, ...] = ()
    plugins_enabled: Literal[False] = False

    def environment_hash(self) -> str:
        """Returns the canonical environment identity."""
        return content_sha256(self)


class ProbeExpectationV1(FrozenModel):
    """Expected frames for one immutable probe capture."""

    probe_id: str
    capture_sha256: str
    expected_frames: tuple[int, ...]

    @field_validator("expected_frames")
    @classmethod
    def normalize_frames(cls, frames: tuple[int, ...]) -> tuple[int, ...]:
        """Sorts expected frames and rejects invalid identifiers."""
        if len(set(frames)) != len(frames) or any(
            frame < 1 for frame in frames
        ):
            raise ValueError("expected frames must be unique and positive")
        return tuple(sorted(frames))


class SemanticSpecV1(FrozenModel):
    """A reviewed semantic task and its multi-probe ground truth."""

    schema_version: Literal["1.0"] = "1.0"
    task_id: str
    intent: str
    status: Literal["ready"] = "ready"
    assumptions: tuple[str, ...] = ()
    canonical_ir: IntentIrV1
    reference_filter: str
    probes: tuple[ProbeExpectationV1, ...] = Field(min_length=1)
    split: str
    provenance: str
    license: str
    review_status: Literal["double-reviewed", "reviewed"]

    @model_validator(mode="after")
    def validate_probe_ids(self) -> "SemanticSpecV1":
        """Rejects ambiguous duplicate probe identifiers."""
        if len({probe.probe_id for probe in self.probes}) != len(self.probes):
            raise ValueError("probe IDs must be unique")
        return self


class EvaluationReceiptV1(FrozenModel):
    """Immutable inputs and packet-level results for one evaluation."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    created_at: datetime
    code_revision: str
    environment_hash: str
    data_hash: str
    model_hash: str | None = None
    prompt_hash: str | None = None
    candidate_filter: str
    reference_filter: str
    probes: tuple[ProbeResultV1, ...] = Field(min_length=1)
    metrics: AggregateMetricsV1

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalizes an aware timestamp to UTC for stable hashing."""
        if value.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_metrics(self) -> "EvaluationReceiptV1":
        """Rejects aggregate metrics inconsistent with probe results."""
        if self.metrics != aggregate_metrics(self.probes):
            raise ValueError("metrics do not match probe results")
        return self

    def receipt_hash(self) -> str:
        """Returns the canonical hash for receipt contents."""
        return content_sha256(self)


class AblationDecision(StrEnum):
    """Allowed outcomes from a Full/Simplified comparison."""

    KEEP_FULL = "keep_full"
    KEEP_SIMPLIFIED = "keep_simplified"
    KEEP_PROTECTED = "keep_protected"
    INCONCLUSIVE = "inconclusive"


class ComplexitySnapshotV1(FrozenModel):
    """Comparable maintainability counters for one implementation variant."""

    module_count: int = Field(ge=0)
    dependency_count: int = Field(ge=0)
    public_symbol_count: int = Field(ge=0)


class AblationReceiptV1(FrozenModel):
    """Reproducible Full/Simplified slice comparison."""

    schema_version: Literal["1.0"] = "1.0"
    ablation_id: str
    hypothesis: str
    full_revision: str
    simplified_patch_hash: str
    input_hashes: tuple[str, ...]
    seeds: tuple[int, ...] = (17, 42, 2026)
    full_metrics: AggregateMetricsV1
    simplified_metrics: AggregateMetricsV1
    full_complexity: ComplexitySnapshotV1
    simplified_complexity: ComplexitySnapshotV1
    decision: AblationDecision
    rationale: str
