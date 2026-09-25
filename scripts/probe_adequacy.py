"""Mutation-adequacy gate for the model split probes.

The gate regenerates the model split and, for every ready dev and test case,
proves the reference filter and the compiled canonical IR against the
case's authored labels on all six scored and both feedback probes, proves
the authored mutation against its own authored labels on the same eight
probes and requires it to differ from the case's labels on at least one
scored probe of its split and on its feedback probe, and executes every
single-site mutant of the canonical IR. A mutant whose frames equal the
labels on every scored probe of its split survives: the probes cannot tell
it from the gold. Survivors are matched against the reasoned waivers kept
beside the gold. Every mutant also runs on its split's feedback probe, which
decides no survivor.

Strict mode exits 1 on a label mismatch of any of the three filters, an
authored mutation the scored or the feedback probes do not tell apart, a
killed mutant the feedback probe does not tell apart, an unwaived survivor,
a waiver that matches no survivor or a waived survivor the feedback probe
tells apart.
Report mode records the same receipt and exits 0. An execution failure
exits 2 in both modes.
"""

# The error envelope and the revision check repeat scripts/retrieval_recall.py
# on purpose: each script is a standalone file loaded by path, and neither may
# import the other.
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field
import json
import math
from pathlib import Path
import re
import statistics
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import cast

from pydantic import ValidationError

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.canonical import file_sha256
from dfilterforge.compiler import compile_intent
from dfilterforge.compiler import CompileError
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.live import measure_environment
from dfilterforge.model_cases import ModelSemanticCase
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import FEEDBACK_PROBE_IDS
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import MUTANT_WAIVERS
from dfilterforge.mutants import MutantCategory
from dfilterforge.mutants import MutantWaiver
from dfilterforge.mutants import single_site_mutants
from dfilterforge.runner import RunnerError
from dfilterforge.runner import TsharkRunner

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}")
_SCHEMA_VERSION = "probe-adequacy/1.2"
_SPLITS: tuple[str, ...] = ("dev", "test")
_STATUSES: tuple[str, ...] = ("killed", "survived", "rejected", "uncompilable")
# A mutant tshark refuses to compile is invalid for a model too, so it can
# never be scored strong exact; every other runner failure stops the gate.
_REJECTED_CODES = frozenset({"filter_rejected", "filter_unknown_field"})
_FAILED = 1
_ERROR = 2
_OUTPUT_EXISTS = "The receipt file already exists"
_NOTES: tuple[str, ...] = (
    "A survivor matches its case's labels on all three scored probes of its "
    "split.",
    "Labels are checked on all eight probes, the six scored and both "
    "feedback probes, dev and test: the reference "
    "filter and the compiled canonical IR must each select exactly the "
    "frames the case's recipe oracle names, and the authored mutation "
    "exactly the frames its mutation memberships name.",
    "Each executed mutant and the authored mutation also run on their "
    "split's feedback probe, which decides no survivor: a killed mutant or "
    "an authored mutation equal to the labels there, or a waived survivor "
    "that differs there, fails the gate.",
    "Mutants come from the fixed operator set in dfilterforge.mutants, not "
    "from an enumeration of near misses; the gate never judges equivalence, "
    "only a waiver does.",
    "Mutants are deduplicated by compiled filter text, including the "
    "reference filter and the compiled canonical IR, keeping the first.",
    "A mutant tshark rejects is listed under rejected; it cannot be scored "
    "strong exact, so it is neither killed nor a survivor.",
    "A waiver applies only when its case, edit label and compiled filter "
    "all match one survivor.",
    "runtime varies between runs and is not part of the gate.",
)


class AdequacyError(DFilterForgeError, RuntimeError):
    """A gate failure carrying only a stable code and safe text."""


@dataclass(frozen=True)
class Survivor:
    """One mutant equal to the labels on every scored probe of its split."""

    case_id: str
    split: str
    category: str
    edit: str
    display_filter: str
    # Whether the split's feedback probe tells the mutant from the gold.
    feedback_separated: bool = False


@dataclass(frozen=True)
class _Probe:
    """One probe capture with the labels one case expects on it."""

    probe_id: str
    capture: Path
    capture_sha256: str
    expected: tuple[int, ...]


class _Executor:
    """Runs filters on probes, checks capture identity and keeps timings."""

    def __init__(self, runner: TsharkRunner) -> None:
        self.runner = runner
        self.timings: list[float] = []

    def frames(self, probe: _Probe, display_filter: str) -> tuple[int, ...]:
        """Returns one filter's frames on one probe."""
        result = self.runner.run(probe.capture, display_filter)
        if result.capture_sha256 != probe.capture_sha256:
            raise AdequacyError(
                "capture_hash_mismatch",
                "Capture bytes do not match the gold specification",
            )
        self.timings.append(result.runtime_ms)
        return result.frames

    def killing_probes(
        self, probes: Sequence[_Probe], display_filter: str
    ) -> list[str]:
        """Returns the probes whose frames differ from the labels."""
        return [
            probe.probe_id
            for probe in probes
            if self.frames(probe, display_filter) != probe.expected
        ]

    def mutant_status(
        self, probes: Sequence[_Probe], feedback: _Probe, display_filter: str
    ) -> tuple[str, str | None, bool]:
        """Classifies one compiled mutant on its scored probes.

        The feedback probe runs after them and decides nothing: the third
        value only says whether it tells the mutant from the gold.
        """
        try:
            killers = self.killing_probes([*probes, feedback], display_filter)
        except RunnerError as error:
            if error.code in _REJECTED_CODES:
                return "rejected", error.code, False
            raise
        scored = [
            probe_id for probe_id in killers if probe_id != feedback.probe_id
        ]
        separated = len(scored) < len(killers)
        return ("killed" if scored else "survived"), None, separated


def apply_waivers(
    survivors: Sequence[Survivor], waivers: Sequence[MutantWaiver]
) -> tuple[list[dict[str, object]], list[MutantWaiver]]:
    """Marks the survivors a waiver covers and finds stale waivers.

    A waiver covers a survivor only when its case, edit label and compiled
    filter all match. A waiver whose label matches a survivor with another
    filter was reasoned about a different mutant, so it covers nothing.

    Args:
        survivors: Surviving mutants in gate order.
        waivers: Reasoned waivers, each naming one case, one edit label and
            the compiled filter of that mutant.

    Returns:
        One receipt row per survivor, in order, and the waivers that cover
        no survivor.

    Raises:
        AdequacyError: If two waivers name the same case and edit.
    """
    by_key: dict[tuple[str, str], MutantWaiver] = {}
    for waiver in waivers:
        key = (waiver.case_id, waiver.edit)
        if key in by_key:
            raise AdequacyError(
                "waiver_duplicate", "Two waivers name the same mutant"
            )
        by_key[key] = waiver
    rows: list[dict[str, object]] = []
    matched: set[tuple[str, str]] = set()
    for survivor in survivors:
        key = (survivor.case_id, survivor.edit)
        waiver = by_key.get(key)
        if waiver is not None and (
            waiver.display_filter != survivor.display_filter
        ):
            waiver = None
        if waiver is not None:
            matched.add(key)
        rows.append(
            {
                "case_id": survivor.case_id,
                "split": survivor.split,
                "category": survivor.category,
                "edit": survivor.edit,
                "filter": survivor.display_filter,
                "waived": waiver is not None,
                "waiver_kind": None if waiver is None else waiver.kind,
                "feedback_separated": survivor.feedback_separated,
            }
        )
    stale = [
        waiver
        for waiver in waivers
        if (waiver.case_id, waiver.edit) not in matched
    ]
    return rows, stale


def _new_counts() -> dict[str, dict[str, dict[str, int]]]:
    """Zeroed status counts per scope, as a total plus one per category."""
    keys = ("total", *(category.value for category in MutantCategory))
    return {
        scope: {key: dict.fromkeys(_STATUSES, 0) for key in keys}
        for scope in ("all", *_SPLITS)
    }


@dataclass
class _Tally:
    """Everything the gate accumulates over the cases."""

    counts: dict[str, dict[str, dict[str, int]]] = field(
        default_factory=_new_counts
    )
    cases: list[dict[str, object]] = field(
        default_factory=list[dict[str, object]]
    )
    survivors: list[Survivor] = field(default_factory=list[Survivor])
    rejected: list[dict[str, object]] = field(
        default_factory=list[dict[str, object]]
    )
    generated: int = 0
    duplicates: int = 0
    label_checks: int = 0

    def count(self, split: str, category: str, status: str) -> None:
        """Adds one mutant outcome to the totals of every scope it is in."""
        for scope in ("all", split):
            self.counts[scope]["total"][status] += 1
            self.counts[scope][category][status] += 1


def _summarize_counts(
    counts: dict[str, dict[str, dict[str, int]]],
    rows: Sequence[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Adds executed, waived and unwaived counts to each scope."""
    summary: dict[str, dict[str, object]] = {}
    for scope, keyed in counts.items():
        total = keyed["total"]
        waived = sum(
            bool(row["waived"])
            for row in rows
            if scope in ("all", row["split"])
        )
        summary[scope] = {
            **total,
            "executed": total["killed"] + total["survived"] + total["rejected"],
            "waived": waived,
            "unwaived": total["survived"] - waived,
            "by_category": {
                key: value for key, value in keyed.items() if key != "total"
            },
        }
    return summary


@dataclass(frozen=True)
class _SplitProbes:
    """The generated probe copies, their hashes and the feedback specs."""

    captures: Mapping[str, BenchmarkProbe]
    hashes: Mapping[str, str]
    feedback: Mapping[str, SemanticSpecV1]

    def capture(self, probe_id: str) -> BenchmarkProbe:
        """Returns one generated probe or stops the gate."""
        probe = self.captures.get(probe_id)
        if probe is None:
            raise AdequacyError(
                "capture_missing", "A gold probe has no generated capture"
            )
        return probe

    def split_probes(self, spec: SemanticSpecV1) -> list[_Probe]:
        """The probes of one specification, labelled from its expectations."""
        return [
            _Probe(
                expected.probe_id,
                self.capture(expected.probe_id).capture_path,
                expected.capture_sha256,
                expected.expected_frames,
            )
            for expected in spec.probes
        ]

    def feedback_probe(self, case_id: str) -> _Probe:
        """A case's split feedback probe, labelled from its feedback spec."""
        (probe,) = self.split_probes(self.feedback[case_id])
        return probe

    def label_probes(
        self, case: ModelSemanticCase, *, mutation: bool = False
    ) -> list[_Probe]:
        """Every scored and feedback probe, labelled from the case oracle."""
        probes: list[_Probe] = []
        for probe_id, capture_sha256 in self.hashes.items():
            probe = self.capture(probe_id)
            probes.append(
                _Probe(
                    probe_id,
                    probe.capture_path,
                    capture_sha256,
                    case.labels(probe, mutation=mutation),
                )
            )
        return probes


def _checked_frames(
    executor: _Executor, probes: Sequence[_Probe], display_filter: str
) -> tuple[dict[str, tuple[int, ...]], list[dict[str, object]]]:
    """Runs one filter on every probe; returns its frames and disagreements."""
    frames = {
        probe.probe_id: executor.frames(probe, display_filter)
        for probe in probes
    }
    mismatches: list[dict[str, object]] = [
        {
            "probe_id": probe.probe_id,
            "expected": probe.expected,
            "frames": frames[probe.probe_id],
        }
        for probe in probes
        if frames[probe.probe_id] != probe.expected
    ]
    return frames, mismatches


def _label_mismatches(
    executor: _Executor, probes: Sequence[_Probe], display_filter: str
) -> list[dict[str, object]]:
    """Runs one gold filter on every probe and returns each disagreement."""
    return _checked_frames(executor, probes, display_filter)[1]


def _run_mutants(
    executor: _Executor,
    case: ModelGoldCaseV1,
    probes: Sequence[_Probe],
    feedback: _Probe,
    tally: _Tally,
) -> tuple[dict[str, int], list[dict[str, object]]]:
    """Executes one case's single-site mutants.

    Returns its counts and the killed mutants its feedback probe cannot tell
    from the gold.
    """
    spec = case.spec
    # The reference filter and the compiled canonical IR are not mutants.
    seen = {compile_intent(spec.canonical_ir), spec.reference_filter}
    blind: list[dict[str, object]] = []
    mutants = single_site_mutants(spec.canonical_ir)
    tally.generated += len(mutants)
    counts: dict[str, int] = dict.fromkeys(
        ("executed", "rejected", "survived"), 0
    )
    for mutant in mutants:
        try:
            text = compile_intent(mutant.intent)
        except CompileError:
            tally.count(spec.split, mutant.category.value, "uncompilable")
            continue
        if text in seen:
            tally.duplicates += 1
            continue
        seen.add(text)
        counts["executed"] += 1
        status, error_code, separated = executor.mutant_status(
            probes, feedback, text
        )
        tally.count(spec.split, mutant.category.value, status)
        if status == "killed" and not separated:
            blind.append(
                {
                    "category": mutant.category.value,
                    "edit": mutant.edit,
                    "filter": text,
                }
            )
        elif status == "survived":
            counts["survived"] += 1
            tally.survivors.append(
                Survivor(
                    case.case_id,
                    spec.split,
                    mutant.category.value,
                    mutant.edit,
                    text,
                    separated,
                )
            )
        elif status == "rejected":
            counts["rejected"] += 1
            tally.rejected.append(
                {
                    "case_id": case.case_id,
                    "split": spec.split,
                    "category": mutant.category.value,
                    "edit": mutant.edit,
                    "filter": text,
                    "error_code": error_code,
                }
            )
    return counts, blind


# pylint: disable-next=too-many-locals
def _measure_case(
    executor: _Executor,
    case: ModelGoldCaseV1,
    oracle: ModelSemanticCase,
    probes: _SplitProbes,
    tally: _Tally,
) -> None:
    """Checks one case's gold on every probe and executes its mutants."""
    spec = case.spec
    canonical = compile_intent(spec.canonical_ir)
    labelled = probes.label_probes(oracle)
    tally.label_checks += len(labelled)
    mismatches = _label_mismatches(executor, labelled, spec.reference_filter)
    # The same text selects the same frames, so it is not run twice.
    canonical_mismatches = (
        mismatches
        if canonical == spec.reference_filter
        else _label_mismatches(executor, labelled, canonical)
    )
    own = probes.split_probes(spec)
    feedback = probes.feedback_probe(case.case_id)
    mutation_frames, mutation_mismatches = _checked_frames(
        executor,
        probes.label_probes(oracle, mutation=True),
        case.mutation_filter,
    )
    killers = [
        probe.probe_id
        for probe in own
        if mutation_frames[probe.probe_id] != probe.expected
    ]
    counts, blind = _run_mutants(executor, case, own, feedback, tally)
    tally.cases.append(
        {
            "case_id": case.case_id,
            "split": spec.split,
            "reference_filter": spec.reference_filter,
            "canonical_filter": canonical,
            "label_mismatches": mismatches,
            "canonical_mismatches": canonical_mismatches,
            "mutation_filter": case.mutation_filter,
            "mutation_label_mismatches": mutation_mismatches,
            "mutation_killing_probes": killers,
            "feedback_probe_id": feedback.probe_id,
            "feedback_expected_count": len(feedback.expected),
            "mutation_separated_on_feedback": (
                mutation_frames[feedback.probe_id] != feedback.expected
            ),
            "feedback_blind_mutants": blind,
            "mutants_executed": counts["executed"],
            "mutants_rejected": counts["rejected"],
            "survivors": counts["survived"],
        }
    )


def _manifest(
    probes: Sequence[BenchmarkProbe], splits: Mapping[str, str]
) -> list[dict[str, object]]:
    """One row per capture: its id, split, file hash and size."""
    return [
        {
            "probe_id": probe.probe_id,
            "split": splits.get(probe.probe_id),
            "capture_sha256": file_sha256(probe.capture_path),
            "size_bytes": probe.capture_path.stat().st_size,
        }
        for probe in probes
    ]


def _measure_split(executor: _Executor, tally: _Tally) -> dict[str, object]:
    """Regenerates the model split, runs every case and returns its identity."""
    oracles = {case.case_id: case for case in model_semantic_cases()}
    with TemporaryDirectory(prefix="dfilterforge-adequacy-") as staging:
        artifacts = generate_model_split(Path(staging))
        feedback = generate_feedback_probes(artifacts)
        specs = (
            *(case.spec for case in artifacts.gold.cases),
            *feedback.specs.values(),
        )
        probes = _SplitProbes(
            {
                probe.probe_id: probe
                for probe in (*artifacts.probes, *feedback.probes)
            },
            {
                probe.probe_id: probe.capture_sha256
                for spec in specs
                for probe in spec.probes
            },
            feedback.specs,
        )
        splits = {
            probe.probe_id: spec.split
            for spec in specs
            for probe in spec.probes
        }
        manifest = _manifest(artifacts.probes, splits)
        feedback_manifest = _manifest(feedback.probes, splits)
        for case in artifacts.gold.cases:
            _measure_case(executor, case, oracles[case.case_id], probes, tally)
    return {
        "gold_sha256": content_sha256(artifacts.gold),
        "capture_manifest": manifest,
        "capture_manifest_sha256": content_sha256(manifest),
        "feedback_manifest": feedback_manifest,
        "feedback_labels_sha256": {
            split: feedback_labels_sha256(feedback, split)
            for split in FEEDBACK_PROBE_IDS
        },
    }


def _source_files() -> dict[str, str]:
    """Hashes every production module plus this gate script."""
    paths = [
        _PROJECT_ROOT / "scripts" / "probe_adequacy.py",
        *sorted((_PROJECT_ROOT / "src" / "dfilterforge").glob("*.py")),
    ]
    return {
        path.relative_to(_PROJECT_ROOT).as_posix(): file_sha256(path)
        for path in paths
    }


def _identity(
    runner: TsharkRunner, split: dict[str, object]
) -> dict[str, object]:
    environment = measure_environment(runner)
    sources = _source_files()
    return {
        **split,
        "source_files": sources,
        "source_manifest_sha256": content_sha256(sources),
        "environment": environment.model_dump(mode="json"),
        "environment_sha256": environment.environment_hash(),
    }


def _failures(
    cases: Sequence[dict[str, object]],
    rows: Sequence[dict[str, object]],
    stale: Sequence[MutantWaiver],
) -> dict[str, int]:
    def mismatches(name: str) -> int:
        return sum(len(cast(list[object], row[name])) for row in cases)

    return {
        "label_mismatches": mismatches("label_mismatches"),
        "canonical_mismatches": mismatches("canonical_mismatches"),
        "mutation_label_mismatches": mismatches("mutation_label_mismatches"),
        "undistinguished_mutations": sum(
            not row["mutation_killing_probes"] for row in cases
        ),
        "unwaived_survivors": sum(not row["waived"] for row in rows),
        "stale_waivers": len(stale),
        "feedback_undistinguished_mutations": sum(
            not row["mutation_separated_on_feedback"] for row in cases
        ),
        "feedback_blind_mutants": mismatches("feedback_blind_mutants"),
        "disproved_waivers": sum(
            bool(row["waived"]) and bool(row["feedback_separated"])
            for row in rows
        ),
    }


def _runtime(
    timings: Sequence[float], wall_seconds: float
) -> dict[str, object]:
    ordered = sorted(timings)
    return {
        "timed_runs": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
        "max_ms": round(ordered[-1], 3),
        "wall_seconds": round(wall_seconds, 3),
    }


def measure(
    runner: TsharkRunner,
    *,
    source_revision: str,
    strict: bool,
    waivers: Sequence[MutantWaiver] = MUTANT_WAIVERS,
) -> dict[str, object]:
    """Runs the gate once over every ready model split case.

    Args:
        runner: The bounded tshark runner every filter goes through.
        source_revision: Human-readable revision recorded in the receipt.
        strict: Whether the receipt records strict or report mode.
        waivers: Reasoned waivers for surviving mutants.

    Returns:
        The complete receipt; ``passed`` applies the strict criteria in both
        modes.

    Raises:
        AdequacyError: If a capture is missing or changed, or two waivers
            name one mutant.
        RunnerError: If tshark fails on anything but a rejected mutant.
    """
    started = perf_counter()
    executor = _Executor(runner)
    tally = _Tally()
    identity = _identity(runner, _measure_split(executor, tally))
    rows, stale = apply_waivers(tally.survivors, waivers)
    summary = _summarize_counts(tally.counts, rows)
    failures = _failures(tally.cases, rows, stale)
    return {
        "schema_version": _SCHEMA_VERSION,
        "mode": "strict" if strict else "report",
        "source_revision": source_revision,
        "measurement_identity": identity,
        "measurement_identity_sha256": content_sha256(identity),
        "categories": [category.value for category in MutantCategory],
        "case_count": len(tally.cases),
        "label_checks": {
            "reference_checked": tally.label_checks,
            "canonical_checked": tally.label_checks,
            "mutation_checked": tally.label_checks,
        },
        "mutants": {
            "generated": tally.generated,
            "duplicates": tally.duplicates,
            **{
                name: value
                for name, value in summary["all"].items()
                if name != "by_category"
            },
        },
        "counts": summary,
        "cases": tally.cases,
        "survivors": rows,
        "rejected": tally.rejected,
        "waivers": {
            "declared": len(waivers),
            "applied": len(waivers) - len(stale),
            "stale": [
                {
                    "case_id": waiver.case_id,
                    "edit": waiver.edit,
                    "filter": waiver.display_filter,
                    "kind": waiver.kind,
                }
                for waiver in stale
            ],
        },
        "failures": failures,
        "passed": not any(failures.values()),
        "runtime": _runtime(executor.timings, perf_counter() - started),
        "notes": list(_NOTES),
    }


def _print_error(code: str, message: str) -> None:
    """Writes the machine-readable error envelope to stderr."""
    envelope = {"error": {"code": code, "message": message}}
    print(canonical_json(envelope), file=sys.stderr)


def _source_revision(value: str) -> str:
    """Validates the human-readable revision supplied by the caller."""
    if _SOURCE_REVISION.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "source revision must be 1-128 safe, non-whitespace characters"
        )
    return value


def _run(arguments: argparse.Namespace) -> int:
    """Measures, writes the receipt once and prints survivors and totals."""
    output = cast(Path, arguments.output)
    report = cast(bool, arguments.report)
    # Refuse before the long measurement; the exclusive open below still
    # guards against a receipt that appears while it runs.
    if output.exists():
        raise AdequacyError("output_exists", _OUTPUT_EXISTS)
    receipt = measure(
        TsharkRunner(),
        source_revision=cast(str, arguments.source_revision),
        strict=not report,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            # Sorted and indented like the other ablation evidence, so a
            # Simplified to Full comparison reads as a line diff.
            stream.write(
                json.dumps(receipt, allow_nan=False, indent=2, sort_keys=True)
                + "\n"
            )
    except FileExistsError:
        raise AdequacyError("output_exists", _OUTPUT_EXISTS) from None
    for row in cast(list[object], receipt["survivors"]):
        print(canonical_json(row))
    counts = cast(dict[str, dict[str, object]], receipt["counts"])
    print(
        canonical_json(
            {
                "mode": receipt["mode"],
                "failures": receipt["failures"],
                "passed": receipt["passed"],
                **{
                    scope: {
                        name: scoped[name]
                        for name in ("executed", "survived", "unwaived")
                    }
                    for scope, scoped in counts.items()
                },
            }
        )
    )
    return 0 if report or receipt["passed"] else _FAILED


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the gate once and returns a process exit code.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        0 when the gate passes or runs in report mode, 1 when strict mode
        finds a failure, 2 when the gate cannot run.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-revision", type=_source_revision, required=True
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="record failures in the receipt without failing the process",
    )
    arguments = parser.parse_args(argv)
    try:
        return _run(arguments)
    except DFilterForgeError as error:
        _print_error(error.code, str(error))
        return _ERROR
    except ValidationError:
        _print_error(
            "schema_invalid", "Input does not match the required schema"
        )
        return _ERROR
    except OSError:
        _print_error("io_error", "File operation failed")
        return _ERROR


if __name__ == "__main__":
    raise SystemExit(main())
