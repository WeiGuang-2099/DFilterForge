"""Local execution boundary joining curated captures and domain evaluation."""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
from pathlib import Path
import platform
import re
import stat
from typing import Literal

from dfilterforge import runner as runner_module
from dfilterforge.canonical import content_sha256
from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.runner import TsharkRunner

_PROBE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z")


class LiveError(RuntimeError):
    """A sanitized failure at the local evaluation boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        catalog_hash=None if catalog is None else catalog.compute_hash(),
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
    candidate_filter = compile_intent(candidate_ir, catalog)
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
