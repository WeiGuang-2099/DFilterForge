"""Write the untrained-baseline ladder from the committed test scores.

``docs/protocol.md`` (Training rules, amended 2026-10-26 and 2026-10-31)
and the self-served note's Baseline rows register it: base (JSON mode),
base + typed-IR schema, base + eight examples + schema and the three SFT
seeds on the ready test C4 items. Three differences are read with the SFT
headline's estimator and rule: schema minus base, few-shot minus schema
and the seed mean minus few-shot. Each row's outcome counts, malformed
split at the token cap, and coverage split are shown, never read. All of
it was designed after the base and SFT test scores were known: post hoc.
Where this file and that text differ, the text holds. The cost the same
amendment registers is not computed here.

``--check`` rebuilds ``docs/results/sft-v1/ladder.json`` and compares it
byte for byte. Exit 0 on success, 1 on a mismatch, 2 when a row is not
scored or published, a summary disagrees, the rows answer other items or a
baseline row was not sent as the self-served note registers.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from typing import Any

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.errors import DFilterForgeError
from dfilterforge.score_summary import BOOTSTRAP_RESAMPLES
from dfilterforge.score_summary import BOOTSTRAP_SEED
from dfilterforge.score_summary import case_means
from dfilterforge.score_summary import discordance
from dfilterforge.score_summary import draw_indices
from dfilterforge.score_summary import HIGH_PERCENTILE
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import LOW_PERCENTILE
from dfilterforge.score_summary import MIN_DISCORDANT_CASES
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import RateV1
from dfilterforge.score_summary import ratio_rate
from dfilterforge.score_summary import ScoreSummaryV1
from dfilterforge.sft_rates import coverage
from dfilterforge.sft_tables import covered
from dfilterforge.sft_tables import STRATA

SCHEMA_VERSION = "baseline-ladder/1.0"
RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"
OUTPUT = Path("sft-v1") / "ladder.json"
CONDITION = "C4"
# The self-served note's Runs (the SFT headline's rows) and its Baseline
# rows as corrected on 2026-10-31.
BASE = "test-qwen3-1.7b-2026-10-07"
SCHEMA = "test-qwen3-1.7b-schema-ord-2026-10-26"
FEW_SHOT = "test-qwen3-1.7b-fs8-ord-2026-10-26"
SEEDS: dict[int, str] = {
    17: "test-qwen3-1.7b-sft-s17-2026-10-07",
    42: "test-qwen3-1.7b-sft-s42-2026-10-07",
    2026: "test-qwen3-1.7b-sft-s2026-2026-10-07",
}
# Ladder order: row, seed, run, and whether it was designed post hoc.
ROWS: tuple[tuple[str, int | None, str, bool], ...] = (
    ("base", None, BASE, False),
    ("schema", None, SCHEMA, True),
    ("few_shot", None, FEW_SHOT, True),
    *(("sft", seed, run, False) for seed, run in SEEDS.items()),
)
# The registered differences, each the upper rung minus the lower.
RUNGS = (
    ("schema_minus_base", "schema", "base"),
    ("few_shot_minus_schema", "few_shot", "schema"),
    ("sft_mean_minus_few_shot", "sft_mean", "few_shot"),
)
# The baseline rows decode under this schema; all else is the base row's.
TYPED_IR = "typed-ir/1"
FINGERPRINT = "vllm-0.21.0-84f508c7"
_SENT_AS_BASE = ("endpoint_host", "max_attempts", "min_interval_seconds")
# Malformed and cut at the token cap: answer_classes' truncated class.
_LENGTH = "length"
_EXACT = OutcomeV1.STRONG_EXACT
_GAIN = ("gain", "loss", "inconclusive")
_MISMATCH = 1
_FAILURE = 2

Items = dict[str, ItemOutcomeV1]
Shares = dict[str, float]


def _file(results: Path, run: str, name: str) -> Path:
    """A committed file of a row; refuses a row that lacks it."""
    path = results / run / name
    if not path.is_file():
        raise DFilterForgeError("run_not_scored", f"{run} has no {name}")
    return path


def _json(results: Path, run: str, name: str) -> Any:
    """A committed JSON file of a row, as plain data."""
    return json.loads(_file(results, run, name).read_bytes())


def _row(results: Path, run: str) -> tuple[Items, ScoreSummaryV1]:
    """A row's ready C4 items by item id, and its scored summary."""
    outcomes = _file(results, run, "scored/outcomes.jsonl").read_text("utf-8")
    summary = _file(results, run, "scored/summary.json").read_text("utf-8")
    ready: Items = {}
    for line in outcomes.splitlines():
        item = ItemOutcomeV1.model_validate_json(line)
        if item.condition == CONDITION and item.gold_status == "ready":
            ready[item.item_id] = item
    return ready, ScoreSummaryV1.model_validate_json(summary)


def _shape(items: Items) -> dict[str, tuple[str, bool]]:
    """Each item's case and whether every gold field was retrieved."""
    return {key: (item.case_id, covered(item)) for key, item in items.items()}


def _exact(items: Items) -> Shares:
    """Per case, the share of its items that are strong exact."""
    pairs = [(i.case_id, float(i.outcome is _EXACT)) for i in items.values()]
    return case_means(pairs)


class _Cases:
    """The shared ready cases and their resample vectors, as the headline's."""

    def __init__(self, items: Items) -> None:
        self.ids = tuple(sorted({item.case_id for item in items.values()}))
        self.vectors = draw_indices(len(self.ids))
        self.ones = dict.fromkeys(self.ids, 1.0)

    def rate(self, shares: Shares) -> RateV1:
        """The mean of the case shares, every item in its case's share."""
        numerators = {key: shares[key] for key in self.ones}
        return ratio_rate(numerators, self.ones, self.vectors, self.ids)

    def paired(self, upper: Shares, lower: Shares) -> dict[str, Any]:
        """The upper rung minus the lower, by case, and its reading."""
        gaps = {key: upper[key] - lower[key] for key in self.ones}
        rate = self.rate(gaps)
        counts = discordance(gaps)
        enough = counts.discordant >= MIN_DISCORDANT_CASES
        low, high = rate.low or 0.0, rate.high or 0.0
        # An endpoint at 0, or none, does not exclude 0.
        sign = 0 if enough and low > 0 else 1 if enough and high < 0 else 2
        return {
            "difference": rate.model_dump(),
            "first_better_cases": counts.first_better,
            "second_better_cases": counts.second_better,
            "discordant_cases": counts.discordant,
            "reading": _GAIN[sign],
        }


def _census(items: Items) -> dict[str, Any]:
    """The outcome counts, and malformed split at the token cap."""
    counts = dict.fromkeys((outcome.value for outcome in OutcomeV1), 0)
    for item in items.values():
        counts[item.outcome.value] += 1
    cut = sum(
        item.outcome is OutcomeV1.MALFORMED and item.finish_reason == _LENGTH
        for item in items.values()
    )
    malformed = counts[OutcomeV1.MALFORMED.value]
    return {
        "outcomes": counts,
        "malformed": {"truncated": cut, "other": malformed - cut},
    }


def _registered(results: Path) -> None:
    """Refuses a baseline row not sent as the self-served note registers."""
    base = _json(results, BASE, "run_manifest.json")
    for run in (SCHEMA, FEW_SHOT):
        manifest = _json(results, run, "run_manifest.json")
        replies = _json(results, run, "completions/C4.json")["completions"]
        checks = {
            "settings": manifest["settings"]
            == base["settings"] | {"response_schema": TYPED_IR},
            "host and call options": all(
                manifest[key] == base[key] for key in _SENT_AS_BASE
            ),
            "fingerprint": all(
                reply.get("system_fingerprint") == FINGERPRINT
                for reply in replies
                if reply["status"] == "completed"
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise DFilterForgeError(
                "not_registered",
                f"{run} was not sent as registered: {', '.join(failed)}",
            )


def build(results: Path) -> dict[str, Any]:
    """Computes the ladder from the committed rows under ``results``.

    Raises:
        DFilterForgeError: A row is not scored or published, the rows
            answer different items, a summary reports another C4 rate, or
            a baseline row was not sent as registered.
    """
    scored = {run: _row(results, run) for _, _, run, _ in ROWS}
    rows = {run: items for run, (items, _) in scored.items()}
    base = rows[BASE]
    cases = _Cases(base)
    exact = {run: _exact(items) for run, items in rows.items()}
    for run, (items, summary) in scored.items():
        if _shape(items) != _shape(base):
            raise DFilterForgeError("rows_differ", f"{run} answers other items")
        if summary.conditions[CONDITION].strong_exact != cases.rate(exact[run]):
            raise DFilterForgeError(
                "summary_mismatch", f"{run} summary reports another C4 rate"
            )
    _registered(results)
    sides = {name: exact[run] for name, _, run, _ in ROWS[:3]}
    seeds = [exact[run] for run in SEEDS.values()]
    sides["sft_mean"] = {
        key: sum(seed[key] for seed in seeds) / len(seeds) for key in cases.ids
    }
    # Keys in the order canonical_json writes them.
    return {
        "bootstrap": {
            "high_percentile": HIGH_PERCENTILE,
            "low_percentile": LOW_PERCENTILE,
            "min_discordant_cases": MIN_DISCORDANT_CASES,
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "cases": len(cases.ids),
        "condition": CONDITION,
        "coverage_items": {
            name: sum(map(keep, base.values())) for name, keep in STRATA.items()
        },
        "items": len(base),
        "metric": "strong_exact",
        "post_hoc": True,
        "rows": [
            {
                "row": name,
                "seed": seed,
                "run": run,
                "post_hoc": post_hoc,
                "rate": cases.rate(exact[run]).model_dump(),
                **_census(rows[run]),
                "coverage": split["strata"],
            }
            for (name, seed, run, post_hoc), split in zip(
                ROWS, coverage(rows), strict=True
            )
        ],
        "rungs": [
            {"rung": rung, "first": upper, "second": lower}
            | cases.paired(sides[upper], sides[lower])
            for rung, upper, lower in RUNGS
        ],
        "schema_version": SCHEMA_VERSION,
        "sft_mean": {
            "seeds": list(SEEDS),
            "rate": cases.rate(sides["sft_mean"]).model_dump(),
        },
        "sources": {
            f"docs/results/{run}/scored/outcomes.jsonl": file_sha256(
                results / run / "scored" / "outcomes.jsonl"
            )
            for _, _, run, _ in ROWS
        },
        "split": "test",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Writes or checks the ladder; returns the exit status."""
    parser = argparse.ArgumentParser(description="Write the baseline ladder.")
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        document = build(args.results)
    except DFilterForgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return _FAILURE
    output = args.results / OUTPUT
    data = (canonical_json(document) + "\n").encode("utf-8")
    if not args.check:
        # Bytes, so a Windows checkout writes and compares what CI does.
        output.write_bytes(data)
        return 0
    if not output.is_file() or output.read_bytes() != data:
        print(f"{output} differs from its rebuild", file=sys.stderr)
        return _MISMATCH
    return 0


if __name__ == "__main__":
    sys.exit(main())
