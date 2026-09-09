"""Measure the reviewed semantic suite and full stability matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from typing import cast

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.benchmark import generate_benchmark
from dfilterforge.benchmark import semantic_cases
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.compiler import compile_intent
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner

_CAPTURE_COUNT = 50
_FILTER_COUNT = 150
_REPETITIONS = 2
_PLANNED_PAIRS = _CAPTURE_COUNT * _FILTER_COUNT
_PLANNED_TSHARK_CALLS = _PLANNED_PAIRS * _REPETITIONS
_REPORT_SIZE_LIMIT = 16 * 1024 * 1024
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}")


def stability_filters() -> tuple[str, ...]:
    """Returns 150 different filter strings without cosmetic padding."""
    filters: dict[str, None] = {}
    for case in semantic_cases():
        for expression in (
            compile_intent(case.canonical_ir),
            case.reference_filter,
            case.mutation_filter,
        ):
            filters[expression] = None
    for field, boundaries in (
        ("tcp.dstport", (53, 80, 443)),
        ("udp.dstport", (53, 5353, 9999)),
        ("ip.ttl", (1, 63, 64)),
        ("frame.len", (59, 60, 100)),
        ("dns.qry.type", (1, 28)),
        ("tcp.flags", (2, 16, 18)),
    ):
        for boundary in boundaries:
            for operator in ("==", "!=", "<", "<=", ">", ">="):
                filters[f"{field} {operator} {boundary}"] = None
    result = tuple(filters)[:_FILTER_COUNT]
    if len(result) != _FILTER_COUNT:
        raise ValueError("Stability gate requires 150 distinct filter strings")
    return result


def _source_revision(value: str) -> str:
    """Validates the human-readable revision supplied by the caller."""
    if _SOURCE_REVISION_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "source revision must be 1-128 safe, non-whitespace characters"
        )
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_manifest() -> dict[str, str]:
    """Hashes every production module plus this measurement script."""
    paths = [
        _PROJECT_ROOT / "scripts" / "benchmark_gate.py",
        *sorted((_PROJECT_ROOT / "src" / "dfilterforge").glob("*.py")),
    ]
    if not paths or any(not path.is_file() for path in paths):
        raise ValueError("Benchmark source manifest is incomplete")
    return {
        path.relative_to(_PROJECT_ROOT).as_posix(): _file_sha256(path)
        for path in paths
    }


def _capture_manifest(probes: tuple[BenchmarkProbe, ...]) -> list[object]:
    return [
        {
            "probe_id": probe.probe_id,
            "capture_sha256": _file_sha256(probe.capture_path),
            "size_bytes": probe.capture_path.stat().st_size,
        }
        for probe in probes
    ]


def _measurement_identity(
    output_dir: Path,
    probes: tuple[BenchmarkProbe, ...],
    catalog: FieldCatalogV1,
    runner: TsharkRunner,
    source_revision: str,
) -> dict[str, object]:
    catalog_identity = catalog.source_catalog_hash
    if catalog_identity is None:
        raise ValueError("Benchmark requires a frozen catalog identity")
    source_files = _source_manifest()
    captures = _capture_manifest(probes)
    runner_limits = cast(dict[str, object], asdict(runner.limits))
    execution = {
        "tshark_version": runner.version(),
        "catalog_identity": catalog_identity,
        "profile_identity": catalog.profile_hash,
        "runner_limits": runner_limits,
    }
    return {
        "source_revision": source_revision,
        "source_files": source_files,
        "source_manifest_sha256": content_sha256(source_files),
        "benchmark_source_sha256": source_files[
            "src/dfilterforge/benchmark.py"
        ],
        "benchmark_manifest_sha256": _file_sha256(output_dir / "manifest.json"),
        "capture_manifest": captures,
        "capture_manifest_sha256": content_sha256(captures),
        "execution": execution,
        "execution_sha256": content_sha256(execution),
    }


def _save(path: Path, report: dict[str, object]) -> None:
    """Replaces a report atomically, preserving the prior valid checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _stale_report(reason: str) -> ValueError:
    return ValueError(
        "Existing stability report is stale or invalid "
        f"({reason}); rerun with --restart-stability"
    )


def _json_object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _stale_report(name)
    mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise _stale_report(name)
    return cast(dict[str, object], value)


def _json_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise _stale_report(name)
    return cast(list[object], value)


def _frame_matrix(value: object, name: str) -> list[list[int]]:
    matrix: list[list[int]] = []
    for raw_frames in _json_list(value, name):
        frames = _json_list(raw_frames, name)
        if any(
            type(frame) is not int or frame < 1  # pylint: disable=unidiomatic-typecheck
            for frame in frames
        ):
            raise _stale_report(name)
        typed_frames = cast(list[int], frames)
        if typed_frames != sorted(set(typed_frames)):
            raise _stale_report(name)
        matrix.append(typed_frames)
    if len(matrix) != _FILTER_COUNT:
        raise _stale_report(name)
    return matrix


def _validate_stability_row(
    raw_row: object, expected_capture: object
) -> dict[str, object]:
    row = _json_object(raw_row, "capture row")
    capture = _json_object(expected_capture, "capture manifest")
    for name in ("probe_id", "capture_sha256"):
        if row.get(name) != capture.get(name):
            raise _stale_report(f"capture row {name}")
    first = _frame_matrix(row.get("first_frames"), "first frame matrix")
    second = _frame_matrix(row.get("second_frames"), "second frame matrix")
    differences = [
        index
        for index, (left, right) in enumerate(zip(first, second, strict=True))
        if left != right
    ]
    if row.get("differing_filter_indexes") != differences:
        raise _stale_report("differing filter indexes")
    if row.get("stable_pairs") != _FILTER_COUNT - len(differences):
        raise _stale_report("stable pair count")
    payload = {
        name: value for name, value in row.items() if name != "row_sha256"
    }
    if row.get("row_sha256") != content_sha256(payload):
        raise _stale_report("capture row hash")
    return row


def _load_stability_rows(
    output: Path, expected: dict[str, object]
) -> list[dict[str, object]]:
    try:
        if output.stat().st_size > _REPORT_SIZE_LIMIT:
            raise _stale_report("report exceeds size limit")
        raw_report: object = json.loads(output.read_text(encoding="utf-8"))
    except ValueError as error:
        if str(error).startswith("Existing stability report"):
            raise
        raise _stale_report("report is not valid JSON") from None
    except OSError:
        raise _stale_report("report cannot be read") from None
    report = _json_object(raw_report, "report root")
    static_names = (
        "schema_version",
        "phase",
        "capture_count",
        "distinct_filter_strings",
        "repetitions",
        "planned_pairs",
        "planned_tshark_calls",
        "comparison",
        "scope",
        "filters",
        "measurement_identity",
        "measurement_identity_sha256",
    )
    for name in static_names:
        if report.get(name) != expected.get(name):
            raise _stale_report(name)
    rows_value = _json_list(report.get("captures"), "capture rows")
    identity = _json_object(
        expected["measurement_identity"], "measurement identity"
    )
    capture_manifest = _json_list(
        identity.get("capture_manifest"), "capture manifest"
    )
    if len(rows_value) > _CAPTURE_COUNT:
        raise _stale_report("capture row count")
    rows = [
        _validate_stability_row(row, capture_manifest[index])
        for index, row in enumerate(rows_value)
    ]
    completed_pairs = len(rows) * _FILTER_COUNT
    stable_pairs = sum(cast(int, row["stable_pairs"]) for row in rows)
    complete = len(rows) == _CAPTURE_COUNT
    progress = {
        "completed_pairs": completed_pairs,
        "completed_tshark_calls": completed_pairs * _REPETITIONS,
        "stable_pairs": stable_pairs,
        "complete": complete,
        "passed": complete and stable_pairs == _PLANNED_PAIRS,
    }
    for name, value in progress.items():
        if report.get(name) != value:
            raise _stale_report(name)
    return rows


def _progress_report(
    base: dict[str, object], rows: list[dict[str, object]]
) -> dict[str, object]:
    completed_pairs = len(rows) * _FILTER_COUNT
    stable_pairs = sum(cast(int, row["stable_pairs"]) for row in rows)
    complete = len(rows) == _CAPTURE_COUNT
    return {
        **base,
        "completed_pairs": completed_pairs,
        "completed_tshark_calls": completed_pairs * _REPETITIONS,
        "stable_pairs": stable_pairs,
        "captures": rows,
        "complete": complete,
        "passed": complete and stable_pairs == _PLANNED_PAIRS,
    }


def _run_filters(
    runner: TsharkRunner,
    probe: BenchmarkProbe,
    filters: tuple[str, ...],
    capture_sha256: str,
) -> list[tuple[int, ...]]:
    frames: list[tuple[int, ...]] = []
    for expression in filters:
        result = runner.run(probe.capture_path, expression)
        if result.capture_sha256 != capture_sha256:
            raise ValueError("Capture changed during stability measurement")
        frames.append(result.frames)
    return frames


def run_stability(
    output_dir: Path,
    output: Path,
    catalog: FieldCatalogV1,
    source_revision: str,
    *,
    restart: bool = False,
    runner: TsharkRunner | None = None,
) -> bool:
    """Runs 7,500 pairs twice, resuming only an identical valid checkpoint."""
    active_runner = runner if runner is not None else TsharkRunner()
    probes = generate_benchmark(output_dir)
    filters = stability_filters()
    if len(probes) != _CAPTURE_COUNT or len(filters) != _FILTER_COUNT:
        raise ValueError("Stability matrix dimensions changed")
    capture_hashes = {
        probe.probe_id: _file_sha256(probe.capture_path) for probe in probes
    }
    if len(set(capture_hashes.values())) != _CAPTURE_COUNT:
        raise ValueError("Stability gate requires 50 byte-distinct captures")
    identity = _measurement_identity(
        output_dir, probes, catalog, active_runner, source_revision
    )
    identity["filters_sha256"] = content_sha256(filters)
    base: dict[str, object] = {
        "schema_version": "stability-report/2.0",
        "phase": "stability",
        "capture_count": _CAPTURE_COUNT,
        "distinct_filter_strings": _FILTER_COUNT,
        "repetitions": _REPETITIONS,
        "planned_pairs": _PLANNED_PAIRS,
        "planned_tshark_calls": _PLANNED_TSHARK_CALLS,
        "comparison": "Exact frame tuples from two executions",
        "scope": (
            "Full Cartesian matrix. Distinct filter strings do not imply 150 "
            "semantically inequivalent predicates."
        ),
        "filters": list(filters),
        "measurement_identity": identity,
        "measurement_identity_sha256": content_sha256(identity),
    }
    rows: list[dict[str, object]]
    if output.exists() and not restart:
        rows = _load_stability_rows(output, base)
    else:
        rows = []
        _save(output, _progress_report(base, rows))
    stable = sum(cast(int, row["stable_pairs"]) for row in rows)
    for probe in probes[len(rows) :]:
        capture_sha256 = capture_hashes[probe.probe_id]
        first = _run_filters(active_runner, probe, filters, capture_sha256)
        reversed_second = _run_filters(
            active_runner, probe, tuple(reversed(filters)), capture_sha256
        )
        second = list(reversed(reversed_second))
        differences = [
            index
            for index, (left, right) in enumerate(
                zip(first, second, strict=True)
            )
            if left != right
        ]
        stable_pairs = _FILTER_COUNT - len(differences)
        stable += stable_pairs
        payload: dict[str, object] = {
            "probe_id": probe.probe_id,
            "capture_sha256": capture_sha256,
            "stable_pairs": stable_pairs,
            "differing_filter_indexes": differences,
            "first_frames": first,
            "second_frames": second,
        }
        rows.append({**payload, "row_sha256": content_sha256(payload)})
        _save(output, _progress_report(base, rows))
        print(
            f"Stability {len(rows)}/50 captures: "
            f"{stable}/{len(rows) * _FILTER_COUNT} pairs stable",
            flush=True,
        )
    return stable == _PLANNED_PAIRS


def _require_capture(result: RunResult, expected_sha256: str) -> None:
    if result.capture_sha256 != expected_sha256:
        raise ValueError("Capture changed during semantic suite measurement")


def run_suite(
    output_dir: Path,
    output: Path,
    catalog: FieldCatalogV1,
    source_revision: str,
    *,
    runner: TsharkRunner | None = None,
) -> bool:
    """Measures compiler/oracle agreement, mutations, latency, and ablation."""
    all_probes = generate_benchmark(output_dir)
    probes = all_probes[:3]
    active_runner = runner if runner is not None else TsharkRunner()
    identity = _measurement_identity(
        output_dir, probes, catalog, active_runner, source_revision
    )
    capture_hashes = {
        probe.probe_id: _file_sha256(probe.capture_path) for probe in probes
    }
    rows: list[dict[str, object]] = []
    timings: list[float] = []
    filter_manifest: list[object] = []
    for case in semantic_cases():
        compiled = compile_intent(case.canonical_ir, catalog)
        filter_manifest.append(
            {
                "task_id": case.task_id,
                "compiled": compiled,
                "reference": case.reference_filter,
                "mutation": case.mutation_filter,
            }
        )
        samples: list[dict[str, object]] = []
        for probe in probes:
            candidate = active_runner.run(probe.capture_path, compiled)
            reference = active_runner.run(
                probe.capture_path, case.reference_filter
            )
            mutation = active_runner.run(
                probe.capture_path, case.mutation_filter
            )
            for result in (candidate, reference, mutation):
                _require_capture(result, capture_hashes[probe.probe_id])
            timings.extend(
                (
                    candidate.runtime_ms,
                    reference.runtime_ms,
                    mutation.runtime_ms,
                )
            )
            expected = probe.labels(case)
            samples.append(
                {
                    "probe_id": probe.probe_id,
                    "expected": expected,
                    "candidate": candidate.frames,
                    "reference": reference.frames,
                    "mutation": mutation.frames,
                    "oracle_agrees": reference.frames == expected,
                    "candidate_agrees": candidate.frames == expected,
                    "mutation_killed": mutation.frames != expected,
                    "candidate_runtime_ms": candidate.runtime_ms,
                    "reference_runtime_ms": reference.runtime_ms,
                    "mutation_runtime_ms": mutation.runtime_ms,
                }
            )
        rows.append(
            {
                "task_id": case.task_id,
                "compiled_filter": compiled,
                "samples": samples,
                "full_mutation_killed": any(
                    cast(bool, sample["mutation_killed"]) for sample in samples
                ),
                "simplified_mutation_killed": samples[0]["mutation_killed"],
            }
        )
        print(f"Semantics {len(rows)}/36: {case.task_id}", flush=True)
    oracle = sum(
        cast(bool, sample["oracle_agrees"])
        for row in rows
        for sample in cast(list[dict[str, object]], row["samples"])
    )
    candidates = sum(
        cast(bool, sample["candidate_agrees"])
        for row in rows
        for sample in cast(list[dict[str, object]], row["samples"])
    )
    full = sum(cast(bool, row["full_mutation_killed"]) for row in rows)
    simplified = sum(
        cast(bool, row["simplified_mutation_killed"]) for row in rows
    )
    p50 = statistics.median(timings)
    p95 = sorted(timings)[math.ceil(len(timings) * 0.95) - 1]
    passed = (
        oracle == 108
        and candidates == 108
        and full / 36 >= 0.95
        and p50 <= 500
        and p95 <= 2000
    )
    identity["filter_manifest"] = filter_manifest
    identity["filters_sha256"] = content_sha256(filter_manifest)
    _save(
        output,
        {
            "schema_version": "semantic-suite-report/2.0",
            "phase": "suite",
            "review_status": "reviewed",
            "measurement_identity": identity,
            "measurement_identity_sha256": content_sha256(identity),
            "spec_count": 36,
            "probes_per_spec": 3,
            "oracle_agreement": {"passed": oracle, "total": 108},
            "typed_candidate_agreement": {
                "passed": candidates,
                "total": 108,
            },
            "mutation_kills": {"passed": full, "total": 36},
            "latency_ms": {
                "p50": p50,
                "p95": p95,
                "samples": len(timings),
            },
            "ablation": {
                "full": "Three probes per specification",
                "simplified": "Only first probe per specification",
                "full_kills": full,
                "simplified_kills": simplified,
                "full_tshark_calls": 324,
                "simplified_tshark_calls": 108,
                "decision": (
                    "keep_full" if full > simplified else "keep_simplified"
                ),
                "scope": (
                    "Ablation reuses first-probe measurements; timing is a "
                    "sample subset, not an independent paired experiment."
                ),
            },
            "model_compile_validity": "unmeasured",
            "silent_wrong_rate": "unmeasured",
            "passed": passed,
            "cases": rows,
        },
    )
    return passed


def main() -> int:
    """Runs independent measurable phases with explicit output evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("stability", "suite", "all"), default="all"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--source-revision", type=_source_revision, required=True
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument(
        "--restart-stability",
        action="store_true",
        help="Explicitly replace an existing stability checkpoint",
    )
    args = parser.parse_args()
    runner = TsharkRunner()
    catalog = bind_catalog(
        runner,
        tuple(case.canonical_ir for case in semantic_cases()),
        path=args.catalog,
    )
    passed = True
    if args.phase in ("suite", "all"):
        passed = run_suite(
            args.output_dir / "captures",
            args.output_dir / "suite.json",
            catalog,
            args.source_revision,
            runner=runner,
        )
    if args.phase in ("stability", "all"):
        passed = (
            run_stability(
                args.output_dir / "captures",
                args.output_dir / "stability.json",
                catalog,
                args.source_revision,
                restart=args.restart_stability,
                runner=runner,
            )
            and passed
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
