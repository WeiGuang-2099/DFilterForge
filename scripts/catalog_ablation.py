"""Measure frozen-catalog determinism and an executable simplification."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time

from pydantic import ValidationError

from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import freeze_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.compiler import CompileError
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.live import evaluate_live
from dfilterforge.live import LiveError
from dfilterforge.runner import RunnerError
from dfilterforge.runner import RunResult
from dfilterforge.runner import TsharkRunner


@dataclass(frozen=True)
class _Case:
    spec: SemanticSpecV1
    mutation: str
    probes: tuple[dict[str, object], ...]


class _CountingRunner(TsharkRunner):
    """Count calls that reach the bounded capture execution method."""

    def __init__(self) -> None:
        super().__init__()
        self.capture_calls = 0

    def run(self, capture: Path, display_filter: str) -> RunResult:
        self.capture_calls += 1
        return super().run(capture, display_filter)


def _sha256(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _same_bytes(first: Path, second: Path) -> bool:
    """Compare two regular files byte for byte."""
    if first.stat().st_size != second.stat().st_size:
        return False
    with first.open("rb") as left, second.open("rb") as right:
        while True:
            chunk = left.read(1024 * 1024)
            if chunk != right.read(1024 * 1024):
                return False
            if not chunk:
                return True


def _compact_summary(summary: dict[str, object]) -> dict[str, object]:
    """Keep catalog identity without embedding large tshark reports."""
    raw_profile = summary.get("profile")
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    return {
        "schema_version": summary.get("schema_version"),
        "catalog_hash": summary.get("catalog_hash"),
        "counts": summary.get("counts"),
        "tshark_version": profile.get("tshark_version"),
        "profile_hash": content_sha256(profile),
    }


def _database_summary(path: Path) -> dict[str, object]:
    """Read and compact the identity stored in a frozen catalog."""
    with sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    ) as database:
        database.execute("PRAGMA trusted_schema = OFF")
        rows = database.execute("SELECT name, value FROM metadata")
        metadata = {str(name): json.loads(str(value)) for name, value in rows}
    return _compact_summary(metadata)


def _inventory_counts(path: Path) -> dict[str, object]:
    """Summarize registrations without expanding enum records into JSON."""
    types: Counter[str] = Counter()
    with sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
    ) as database:
        database.execute("PRAGMA trusted_schema = OFF")
        for (record,) in database.execute("SELECT record FROM fields_records"):
            columns = str(record).split("\t")
            if columns[0] == "P":
                types["FT_PROTOCOL"] += 1
            elif columns[0] == "F" and len(columns) > 3:
                types[columns[3]] += 1
        enum_rows = database.execute(
            "SELECT substr(record, 1, 1), count(*) FROM values_records "
            "GROUP BY substr(record, 1, 1)"
        )
        enums = {str(kind): int(count) for kind, count in enum_rows}
        unique_row = database.execute(
            "SELECT count(DISTINCT name) FROM fields_records"
        ).fetchone()
    assert unique_row is not None
    return {
        "raw_types": dict(sorted(types.items())),
        "enum_record_kinds": dict(sorted(enums.items())),
        "unique_field_names": int(unique_row[0]),
    }


def _load_cases(fixtures: Path) -> tuple[_Case, ...]:
    manifest = json.loads((fixtures / "manifest.json").read_bytes())
    return tuple(
        _Case(
            spec=SemanticSpecV1.model_validate_json(
                (fixtures / case["spec_path"]).read_bytes()
            ),
            mutation=str(case["near_wrong_filter"]),
            probes=tuple(case["probes"]),
        )
        for case in manifest["cases"]
    )


def _simplified_compile(
    runner: TsharkRunner, intent: IntentIrV1, catalog: FieldCatalogV1
) -> str:
    """Executable candidate: retain version pinning, omit catalog binding."""
    if runner.version() != catalog.tshark_version:
        raise CatalogError("catalog_version_mismatch", "Version differs")
    return compile_intent(intent)


def _execute_filters(
    runner: TsharkRunner,
    capture: Path,
    filters: tuple[tuple[str, str], ...],
) -> tuple[dict[str, tuple[int, ...]], float]:
    """Execute each display filter through the production bounded runner."""
    frames: dict[str, tuple[int, ...]] = {}
    reported_runtime_ms = 0.0
    for kind, expression in filters:
        result = runner.run(capture, expression)
        frames[kind] = result.frames
        reported_runtime_ms += result.runtime_ms
    return frames, reported_runtime_ms


def _measure(
    cases: tuple[_Case, ...],
    fixtures: Path,
    runner: TsharkRunner,
    catalog: FieldCatalogV1,
    repetitions: int,
) -> list[dict[str, object]]:
    """Run valid Full/Simplified pairs with alternating first position."""
    rows: list[dict[str, object]] = []
    sample_number = 0
    for repetition in range(repetitions):
        for case in cases:
            for probe in case.probes:
                order = (
                    ("full", "simplified")
                    if sample_number % 2 == 0
                    else ("simplified", "full")
                )
                sample_number += 1
                capture = fixtures / str(probe["capture_path"])
                results: dict[str, dict[str, tuple[int, ...]]] = {}
                timings: dict[str, dict[str, float]] = {}
                for variant in order:
                    started = time.perf_counter()
                    if variant == "full":
                        bound = bind_catalog(
                            runner, (case.spec.canonical_ir,), supplied=catalog
                        )
                        compiled = compile_intent(case.spec.canonical_ir, bound)
                    else:
                        compiled = _simplified_compile(
                            runner, case.spec.canonical_ir, catalog
                        )
                    compiled_at = time.perf_counter()
                    results[variant], tshark_ms = _execute_filters(
                        runner,
                        capture,
                        (
                            ("compiled", compiled),
                            ("reference", case.spec.reference_filter),
                            ("mutation", case.mutation),
                        ),
                    )
                    timings[variant] = {
                        "bind_compile_ms": (compiled_at - started) * 1000,
                        "reported_tshark_ms": tshark_ms,
                        "total_wall_ms": (time.perf_counter() - started) * 1000,
                    }
                expected = tuple(probe["expected_frames"])
                mutation = tuple(probe["near_wrong_frames"])
                labels_match = all(
                    result["compiled"] == result["reference"] == expected
                    and result["mutation"] == mutation
                    for result in results.values()
                )
                rows.append(
                    {
                        "probe_id": probe["probe_id"],
                        "repetition": repetition,
                        "order": order,
                        "expected_frames": expected,
                        "expected_mutation_frames": mutation,
                        "frames": results,
                        "labels_match": labels_match,
                        "paired_equal": results["full"]
                        == results["simplified"],
                        "mutation_killed": all(
                            result["mutation"] != expected
                            for result in results.values()
                        ),
                        "runtime_ms": timings,
                    }
                )
    return rows


def _intent(
    field: str, operator: str, value: object = None
) -> dict[str, object]:
    return {
        "expression": {
            "kind": "predicate",
            "field": field,
            "operator": operator,
            "value": value,
        }
    }


def _safety_inputs(catalog: FieldCatalogV1) -> list[tuple[str, object, object]]:
    """Build invalid or identity-mismatched inputs for both variants."""
    base = catalog.model_dump(mode="json")
    valid = _intent("udp.dstport", "eq", 53)
    inputs = [
        ("unknown-field", _intent("missing.nonexistent", "exists"), base),
        ("integer-string", _intent("udp.dstport", "eq", "53"), base),
        ("boolean-integer", _intent("tcp.flags.syn", "eq", 1), base),
        ("invalid-operator", _intent("udp.dstport", "contains", "5"), base),
        ("malformed-field", _intent("tcp;whoami", "exists"), base),
    ]
    for name, key, value in (
        ("wrong-version", "tshark_version", "4.6.7"),
        ("wrong-profile", "profile_hash", "0" * 64),
        ("wrong-source-identity", "source_catalog_hash", "0" * 64),
    ):
        altered = {**base, key: value, "catalog_hash": None}
        inputs.append((name, valid, altered))
    stale = {
        **base,
        "catalog_hash": None,
        "fields": [
            field
            for field in base["fields"]
            if field["abbreviation"] != "udp.dstport"
        ],
    }
    inputs.append(("stale-missing-field", valid, stale))
    altered_fields = [
        {**field, "field_type": "string"}
        if field["abbreviation"] == "udp.dstport"
        else field
        for field in base["fields"]
    ]
    tampered = {**base, "catalog_hash": None, "fields": altered_fields}
    inputs.append(("tampered-field-type", valid, tampered))
    return inputs


def _safety_outcome(
    variant: str,
    runner: _CountingRunner,
    case: _Case,
    fixtures: Path,
    intent_data: object,
    catalog_data: object,
) -> dict[str, object]:
    """Run one witness and record whether capture execution was reached."""
    before = runner.capture_calls
    frames: tuple[int, ...] | None = None
    try:
        intent = IntentIrV1.model_validate(intent_data)
        supplied = FieldCatalogV1.model_validate(catalog_data)
        if variant == "full":
            evaluate_live(
                case.spec,
                intent,
                fixtures / "captures",
                run_id="catalog-ablation-safety",
                created_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
                code_revision="catalog-ablation",
                catalog=supplied,
                runner=runner,
            )
        else:
            compiled = _simplified_compile(runner, intent, supplied)
            capture = fixtures / str(case.probes[0]["capture_path"])
            frames = runner.run(capture, compiled).frames
        outcome = "accepted"
    except ValidationError:
        outcome = "schema_invalid"
    except (CatalogError, CompileError, LiveError, RunnerError) as error:
        outcome = error.code
    return {
        "outcome": outcome,
        "capture_calls": runner.capture_calls - before,
        "frames": frames,
    }


def _safety(
    case: _Case, fixtures: Path, catalog: FieldCatalogV1
) -> list[dict[str, object]]:
    """Compare real Full and Simplified behavior on safety witnesses."""
    rows: list[dict[str, object]] = []
    runner = _CountingRunner()
    for name, intent_data, catalog_data in _safety_inputs(catalog):
        full = _safety_outcome(
            "full", runner, case, fixtures, intent_data, catalog_data
        )
        simplified = _safety_outcome(
            "simplified", runner, case, fixtures, intent_data, catalog_data
        )
        full_rejected = (
            full["capture_calls"] == 0 and full["outcome"] != "accepted"
        )
        rows.append(
            {
                "witness": name,
                "full": full,
                "simplified": simplified,
                "full_rejected_before_capture": full_rejected,
                "simplified_reached_capture": int(simplified["capture_calls"])
                > 0,
            }
        )
    return rows


def _latency(
    rows: list[dict[str, object]], variant: str, metric: str
) -> dict[str, float]:
    values = sorted(float(row["runtime_ms"][variant][metric]) for row in rows)
    position = (len(values) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return {
        "p50_ms": statistics.median(values),
        "p95_ms": values[lower]
        + (values[upper] - values[lower]) * (position - lower),
    }


def _nonblank_source_lines(source: str) -> int:
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in source.splitlines()
    )


def _source_identity(fixtures: Path) -> dict[str, object]:
    """Record all source and fixture inputs that define this experiment."""
    paths = {
        "experiment_script": Path(__file__),
        "catalog_runtime": Path(freeze_catalog.__code__.co_filename),
        "compiler": Path(compile_intent.__code__.co_filename),
        "live_boundary": Path(evaluate_live.__code__.co_filename),
        "runner": Path(TsharkRunner.run.__code__.co_filename),
        "fixture_manifest": fixtures / "manifest.json",
    }
    return {
        name: {"path": str(path), "sha256": _sha256(path)}
        for name, path in paths.items()
    }


def _implementation_size() -> dict[str, object]:
    full_path = Path(freeze_catalog.__code__.co_filename)
    full_source = full_path.read_text(encoding="utf-8")
    simplified_source = inspect.getsource(_simplified_compile)
    return {
        "scope": (
            "catalog_runtime module versus experiment-only compile function"
        ),
        "full_nonblank_source_lines": _nonblank_source_lines(full_source),
        "simplified_nonblank_source_lines": _nonblank_source_lines(
            simplified_source
        ),
        "full_modules": 1,
        "simplified_modules": 0,
        "additional_third_party_dependencies": 0,
    }


def main() -> int:  # pylint: disable=too-many-locals
    """Write compact direct-comparison evidence and signal inconclusive runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions must be between 1 and 20")
    cases = _load_cases(args.fixtures)
    if len(cases) != 3 or sum(len(case.probes) for case in cases) != 9:
        parser.error("Expected the existing three pilot cases and nine probes")
    if not DEFAULT_CATALOG_PATH.is_file():
        parser.error(
            "Run inside the Docker image containing the frozen catalog"
        )

    experiment_started = time.perf_counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    freeze_rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(
        prefix="catalog-freeze-", dir=args.output.parent
    ) as directory:
        freeze_paths = (
            Path(directory) / "freeze-a.sqlite3",
            Path(directory) / "freeze-b.sqlite3",
        )
        for label, path in zip(("a", "b"), freeze_paths, strict=True):
            started = time.perf_counter()
            summary = freeze_catalog(path, TsharkRunner())
            freeze_rows.append(
                {
                    "label": label,
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                    "runtime_ms": (time.perf_counter() - started) * 1000,
                    "summary": _compact_summary(summary),
                }
            )
        freezes_equal = _same_bytes(*freeze_paths)
        image_matches = _same_bytes(freeze_paths[0], DEFAULT_CATALOG_PATH)
        inventory = _inventory_counts(freeze_paths[0])

    image_row = {
        "path": str(DEFAULT_CATALOG_PATH),
        "sha256": _sha256(DEFAULT_CATALOG_PATH),
        "size_bytes": DEFAULT_CATALOG_PATH.stat().st_size,
        "summary": _database_summary(DEFAULT_CATALOG_PATH),
    }
    runner = TsharkRunner()
    catalog = bind_catalog(
        runner, tuple(case.spec.canonical_ir for case in cases)
    )
    _measure(cases[:1], args.fixtures, runner, catalog, 1)
    rows = _measure(cases, args.fixtures, runner, catalog, args.repetitions)
    safety = _safety(cases[0], args.fixtures, catalog)

    correctness = all(
        row["labels_match"] and row["paired_equal"] and row["mutation_killed"]
        for row in rows
    )
    full_safe = all(row["full_rejected_before_capture"] for row in safety)
    safety_difference = any(row["simplified_reached_capture"] for row in safety)
    latency = {
        variant: {
            metric: _latency(rows, variant, metric)
            for metric in ("bind_compile_ms", "total_wall_ms")
        }
        for variant in ("full", "simplified")
    }
    full_p95 = latency["full"]["total_wall_ms"]["p95_ms"]
    simplified_p95 = latency["simplified"]["total_wall_ms"]["p95_ms"]
    performance_regression_pct = (simplified_p95 / full_p95 - 1) * 100
    performance_within_threshold = performance_regression_pct <= 5.0
    evidence_complete = (
        freezes_equal and image_matches and correctness and full_safe
    )
    if not evidence_complete:
        decision = "inconclusive"
    elif safety_difference:
        decision = "keep_protected"
    elif performance_within_threshold:
        decision = "keep_simplified"
    else:
        decision = "keep_full"

    payload = {
        "schema_version": "catalog-ablation/2.0",
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "code_revision": args.code_revision,
        "decision": decision,
        "evidence_complete": evidence_complete,
        "thresholds": {
            "freeze_bytes_equal": True,
            "matches_image_catalog_bytes": True,
            "all_valid_labels_pairs_and_mutations": True,
            "full_rejects_all_safety_witnesses_before_capture": True,
            "simplified_p95_max_regression_pct": 5.0,
            "simplified_must_not_reach_capture_when_full_rejects": True,
        },
        "source_identity": _source_identity(args.fixtures),
        "catalog_freeze": {
            "independent_freezes": freeze_rows,
            "direct_bytes_equal": freezes_equal,
            "image_catalog": image_row,
            "matches_image_catalog_bytes": image_matches,
            "generated_catalogs_retained": False,
            "inventory_counts": inventory,
        },
        "runtime_binding": {
            "verified": True,
            "tshark_version": runner.version(),
            "tshark_executable_sha256": _sha256(runner.executable_path),
            "source_catalog_hash": catalog.source_catalog_hash,
            "projected_catalog_hash": catalog.compute_hash(),
            "profile_hash": catalog.profile_hash,
            "projected_field_types": dict(
                Counter(field.field_type.value for field in catalog.fields)
            ),
        },
        "valid_workload": {
            "case_count": len(cases),
            "probe_count": 9,
            "repetitions": args.repetitions,
            "paired_samples": len(rows),
            "capture_calls_per_variant": len(rows) * 3,
            "all_labels_and_pairs_match": correctness,
            "samples": rows,
        },
        "safety": {
            "witness_count": len(safety),
            "full_rejects_all_before_capture": full_safe,
            "simplified_reached_capture_count": sum(
                bool(row["simplified_reached_capture"]) for row in safety
            ),
            "simplified_preserves_safety": not safety_difference,
            "witnesses": safety,
        },
        "performance": {
            "scope": (
                "Warm bind/compile plus three bounded tshark calls per sample; "
                "variants alternate first position."
            ),
            "latency": latency,
            "simplified_total_p95_regression_pct": (performance_regression_pct),
            "within_five_percent_threshold": performance_within_threshold,
        },
        "simplified_scope": (
            "Version-only compile followed by real bounded tshark execution; "
            "frozen inventory, profile binding, field existence, type, "
            "operator, and supplied-definition checks are omitted."
        ),
        "implementation_size": _implementation_size(),
        "pilot_scale_gate_verified": False,
        "experiment_runtime_ms": (time.perf_counter() - experiment_started)
        * 1000,
    }
    args.output.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "decision": decision,
                "evidence_complete": evidence_complete,
            }
        )
    )
    return 0 if evidence_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
