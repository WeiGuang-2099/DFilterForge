"""Local execution boundary joining curated captures and domain evaluation."""

# pylint: disable=line-too-long,too-many-arguments,too-many-positional-arguments,too-many-locals

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import platform
import re
import stat
from typing import Literal, TypeAlias

from dfilterforge import runner as runner_module
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import EvaluationTraceV1
from dfilterforge.evaluation import PredicateTraceV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import ProbeTraceV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.runner import TsharkRunner

_PROBE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z")
_MAX_TRACE_PREDICATE_PATHS = 64
_MAX_TRACE_CALLS = 64
_MAX_TRACE_COUNTEREXAMPLES = 1024
_MAX_TRACE_CELLS = 65_536
_CompiledPredicate: TypeAlias = tuple[tuple[int, ...], Predicate, str]


class LiveError(DFilterForgeError, RuntimeError):
    """A sanitized failure at the local evaluation boundary."""


class LiveEnvironmentV1(FrozenModel):
    """Measured binary and policy identity, not an OCI image attestation.

    Shared libraries, system dissector data, and container build options are
    outside this manifest's scope. The Docker build disables plugins and Lua;
    this manifest does not claim to independently attest those build options.
    """

    schema_version: Literal["live-environment/1.0"] = "live-environment/1.0"
    identity_scope: Literal["binary-and-runner-source"] = (
        "binary-and-runner-source"
    )
    tshark_version: str
    executable_sha256: str
    runner_source_sha256: str
    runner_limits_hash: str
    catalog_hash: str | None
    catalog_profile_hash: str | None = None
    python_version: str
    platform_machine: str
    unmeasured: tuple[str, ...] = (
        "container_image_digest",
        "shared_libraries",
        "system_dissector_data",
        "plugin_and_lua_build_options",
    )

    def environment_hash(self) -> str:
        """Returns the canonical identity of the measured evidence."""
        return content_sha256(self)


def _file_hash(path: Path, max_bytes: int | None = None) -> str:
    """Hashes a file while bounding capture reads and sanitizing IO errors."""
    try:
        digest = hashlib.sha256()
        total = 0
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise LiveError("input_invalid", "Input must be a regular file")
            while chunk := source.read(65536):
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise LiveError(
                        "capture_too_large", "Capture exceeds the byte limit"
                    )
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        raise LiveError(
            "input_unavailable", "Cannot read execution input"
        ) from None


def _capture_path(capture_root: Path, probe_id: str) -> Path:
    """Resolves only regular probe files contained by the capture root."""
    if not _PROBE_ID.fullmatch(probe_id):
        raise LiveError("capture_path_invalid", "Probe identifier is not safe")
    try:
        root = capture_root.resolve(strict=True)
        capture = (root / f"{probe_id}.pcap").resolve(strict=True)
        if not root.is_dir() or not capture.is_relative_to(root):
            raise LiveError(
                "capture_path_invalid", "Capture must stay inside its root"
            )
        if not capture.is_file():
            raise LiveError(
                "capture_path_invalid", "Capture must be a regular file"
            )
        return capture
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, LiveError):
            raise
        raise LiveError(
            "capture_unavailable", "Cannot resolve capture"
        ) from None


def _check_capture_hash(actual: str, expected: str) -> None:
    if actual != expected:
        raise LiveError(
            "capture_hash_mismatch",
            "Capture bytes do not match the specification",
        )


def _environment(
    runner: TsharkRunner, catalog: FieldCatalogV1 | None
) -> LiveEnvironmentV1:
    version = runner.version()
    if catalog is not None and catalog.tshark_version != version:
        raise LiveError(
            "catalog_version_mismatch", "Catalog and executable versions differ"
        )
    return LiveEnvironmentV1(
        tshark_version=version,
        executable_sha256=_file_hash(runner.executable_path),
        runner_source_sha256=_file_hash(Path(runner_module.__file__)),
        runner_limits_hash=content_sha256(
            {
                "timeout_seconds": runner.limits.timeout_seconds,
                "max_capture_bytes": runner.limits.max_capture_bytes,
                "max_filter_bytes": runner.limits.max_filter_bytes,
                "max_stdout_bytes": runner.limits.max_stdout_bytes,
                "max_stderr_bytes": runner.limits.max_stderr_bytes,
                "max_frames": runner.limits.max_frames,
            }
        ),
        catalog_hash=None
        if catalog is None
        else catalog.source_catalog_hash or catalog.compute_hash(),
        catalog_profile_hash=None if catalog is None else catalog.profile_hash,
        python_version=platform.python_version(),
        platform_machine=platform.machine(),
    )


def packet_set_hash(receipt: EvaluationReceiptV1) -> str:
    """Hashes packet sets independently of timings and run metadata."""
    return content_sha256(
        [
            {
                "probe_id": probe.probe_id,
                "expected_frames": probe.expected_frames,
                "candidate_frames": probe.candidate_frames,
            }
            for probe in receipt.probes
        ]
    )


def _compiled_predicates(
    intent: IntentIrV1, catalog: FieldCatalogV1
) -> tuple[_CompiledPredicate, ...]:
    """Compiles leaf predicates while preserving their stable AST paths."""
    return tuple(
        (
            path,
            predicate,
            compile_intent(IntentIrV1(expression=predicate), catalog),
        )
        for path, predicate in walk_predicates(intent.expression)
    )


def _counterexample_frames(probe: ProbeResultV1) -> tuple[int, ...]:
    return tuple(sorted((*probe.reference_only, *probe.candidate_only)))


def _check_trace_budget(
    probes: tuple[ProbeResultV1, ...],
    candidate: tuple[_CompiledPredicate, ...],
    canonical: tuple[_CompiledPredicate, ...],
    candidate_filter: str,
    reference_filter: str,
) -> None:
    """Rejects trace work that could amplify an untrusted intent."""
    predicate_paths = len(candidate) + len(canonical)
    counterexample_count = sum(
        len(_counterexample_frames(probe)) for probe in probes
    )
    if predicate_paths > _MAX_TRACE_PREDICATE_PATHS:
        raise LiveError("trace_limit", "Predicate trace exceeds its node limit")
    if counterexample_count > _MAX_TRACE_COUNTEREXAMPLES:
        raise LiveError(
            "trace_limit", "Predicate trace exceeds its frame limit"
        )
    if predicate_paths * counterexample_count > _MAX_TRACE_CELLS:
        raise LiveError("trace_limit", "Predicate trace exceeds its cell limit")
    leaf_filters = {
        display_filter for _, _, display_filter in (*candidate, *canonical)
    }
    reusable = {candidate_filter, reference_filter}
    mismatched_probes = sum(not probe.exact for probe in probes)
    trace_calls = len(leaf_filters - reusable) * mismatched_probes
    if trace_calls > _MAX_TRACE_CALLS:
        raise LiveError("trace_limit", "Predicate trace exceeds its call limit")


def _expression_match(
    expression: Expression,
    matches: dict[tuple[int, ...], frozenset[int]],
    frame: int,
    path: tuple[int, ...] = (),
) -> bool:
    """Recomposes one frame from tshark-grounded raw predicate matches."""
    if isinstance(expression, Predicate):
        return frame in matches[path]
    if isinstance(expression, All):
        return all(
            _expression_match(child, matches, frame, (*path, index))
            for index, child in enumerate(expression.children)
        )
    if isinstance(expression, AnyOf):
        return any(
            _expression_match(child, matches, frame, (*path, index))
            for index, child in enumerate(expression.children)
        )
    assert isinstance(expression, Not)
    return not _expression_match(expression.child, matches, frame, (*path, 0))


def _trace_entries(
    plans: tuple[_CompiledPredicate, ...],
    frames_by_filter: dict[str, frozenset[int]],
    counterexamples: tuple[int, ...],
) -> tuple[PredicateTraceV1, ...]:
    return tuple(
        PredicateTraceV1(
            node_path=path,
            predicate=predicate,
            display_filter=display_filter,
            matched_frames=tuple(
                frame
                for frame in counterexamples
                if frame in frames_by_filter[display_filter]
            ),
        )
        for path, predicate, display_filter in plans
    )


def _verify_trace_composition(
    expression: Expression,
    entries: tuple[PredicateTraceV1, ...],
    counterexamples: tuple[int, ...],
    root_frames: tuple[int, ...],
) -> None:
    matches = {
        entry.node_path: frozenset(entry.matched_frames) for entry in entries
    }
    root = frozenset(root_frames)
    if any(
        _expression_match(expression, matches, frame) != (frame in root)
        for frame in counterexamples
    ):
        raise LiveError(
            "trace_inconsistent",
            "Predicate trace disagrees with root filter execution",
        )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments,too-many-locals
def _trace_probe(
    spec: SemanticSpecV1,
    candidate_ir: IntentIrV1,
    capture_root: Path,
    probe: ProbeResultV1,
    expected_hash: str,
    candidate: tuple[_CompiledPredicate, ...],
    canonical: tuple[_CompiledPredicate, ...],
    runner: TsharkRunner,
    candidate_filter: str,
) -> ProbeTraceV1:
    """Executes and records both sides of one counterexample trace."""
    counterexamples = _counterexample_frames(probe)
    if not counterexamples:
        return ProbeTraceV1(
            probe_id=probe.probe_id,
            counterexample_frames=(),
            candidate_predicates=(),
            canonical_predicates=(),
        )
    candidate_frames = frozenset(probe.candidate_frames)
    reference_frames = frozenset(probe.expected_frames)
    frames_by_filter = {candidate_filter: candidate_frames}
    if (
        spec.reference_filter in frames_by_filter
        and frames_by_filter[spec.reference_filter] != reference_frames
    ):
        raise LiveError(
            "trace_inconsistent",
            "Root filter executions disagree for the same filter",
        )
    frames_by_filter[spec.reference_filter] = reference_frames
    capture = _capture_path(capture_root, probe.probe_id)
    for _, _, display_filter in (*candidate, *canonical):
        if display_filter in frames_by_filter:
            continue
        result = runner.run(capture, display_filter)
        _check_capture_hash(result.capture_sha256, expected_hash)
        frames_by_filter[display_filter] = frozenset(result.frames)
    candidate_entries = _trace_entries(
        candidate, frames_by_filter, counterexamples
    )
    canonical_entries = _trace_entries(
        canonical, frames_by_filter, counterexamples
    )
    _verify_trace_composition(
        candidate_ir.expression,
        candidate_entries,
        counterexamples,
        probe.candidate_frames,
    )
    _verify_trace_composition(
        spec.canonical_ir.expression,
        canonical_entries,
        counterexamples,
        probe.expected_frames,
    )
    return ProbeTraceV1(
        probe_id=probe.probe_id,
        counterexample_frames=counterexamples,
        candidate_predicates=candidate_entries,
        canonical_predicates=canonical_entries,
    )


# pylint: disable-next=too-many-arguments,too-many-locals
def evaluate_live_with_trace(
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
    """Executes a live evaluation and traces actual counterexample predicates."""
    active_runner = runner if runner is not None else TsharkRunner()
    receipt, environment = evaluate_live(
        spec,
        candidate_ir,
        capture_root,
        run_id=run_id,
        created_at=created_at,
        code_revision=code_revision,
        catalog=catalog,
        runner=active_runner,
    )
    bound_catalog = bind_catalog(
        active_runner, (candidate_ir, spec.canonical_ir), catalog
    )
    candidate = _compiled_predicates(candidate_ir, bound_catalog)
    canonical = _compiled_predicates(spec.canonical_ir, bound_catalog)
    _check_trace_budget(
        receipt.probes,
        candidate,
        canonical,
        receipt.candidate_filter,
        receipt.reference_filter,
    )
    expected_by_id = {expected.probe_id: expected for expected in spec.probes}
    traces = tuple(
        _trace_probe(
            spec,
            candidate_ir,
            capture_root,
            probe,
            expected_by_id[probe.probe_id].capture_sha256,
            candidate,
            canonical,
            active_runner,
            receipt.candidate_filter,
        )
        for probe in receipt.probes
    )
    return (
        receipt,
        environment,
        EvaluationTraceV1(run_id=run_id, probes=traces),
    )


# pylint: disable-next=too-many-arguments,too-many-locals
def evaluate_live(
    spec: SemanticSpecV1,
    candidate_ir: IntentIrV1,
    capture_root: Path,
    *,
    run_id: str,
    created_at: datetime,
    code_revision: str,
    catalog: FieldCatalogV1 | None = None,
    runner: TsharkRunner | None = None,
) -> tuple[EvaluationReceiptV1, LiveEnvironmentV1]:
    """Executes each reference and candidate against independent labels.

    A mismatched reference invalidates the oracle and aborts the evaluation.
    A mismatched candidate is a measured result and remains in the receipt.
    This local-only boundary accepts captures pinned by a specification hash;
    it is not a public upload or execution API.
    """
    if created_at.tzinfo is None:
        raise LiveError(
            "timestamp_invalid", "created_at must include a timezone"
        )
    active_runner = runner if runner is not None else TsharkRunner()
    catalog = bind_catalog(
        active_runner, (candidate_ir, spec.canonical_ir), catalog
    )
    candidate_filter = compile_intent(candidate_ir, catalog)
    compile_intent(spec.canonical_ir, catalog)
    environment = _environment(active_runner, catalog)
    probes: list[ProbeResultV1] = []
    for expected in spec.probes:
        capture = _capture_path(capture_root, expected.probe_id)
        _check_capture_hash(
            _file_hash(capture, active_runner.limits.max_capture_bytes),
            expected.capture_sha256,
        )
        reference = active_runner.run(capture, spec.reference_filter)
        _check_capture_hash(reference.capture_sha256, expected.capture_sha256)
        if reference.frames != expected.expected_frames:
            raise LiveError(
                "reference_label_mismatch",
                "Reference execution disagrees with independent packet labels",
            )
        candidate = active_runner.run(capture, candidate_filter)
        _check_capture_hash(candidate.capture_sha256, expected.capture_sha256)
        probes.append(
            evaluate_probe(
                expected.probe_id,
                expected.expected_frames,
                candidate.frames,
                candidate.runtime_ms,
            )
        )
    typed_probes = tuple(probes)
    receipt = EvaluationReceiptV1(
        run_id=run_id,
        created_at=created_at,
        code_revision=code_revision,
        environment_hash=environment.environment_hash(),
        data_hash=content_sha256(spec),
        candidate_filter=candidate_filter,
        reference_filter=spec.reference_filter,
        probes=typed_probes,
        metrics=aggregate_metrics(typed_probes),
    )
    return receipt, environment
