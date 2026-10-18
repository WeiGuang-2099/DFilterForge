"""Write the SFT headline from the committed test scores.

Each seed's test C4 strong exact minus the base row's, the three-seed
mean, the coverage split (shown, never read) and the hosted rows against
the mean, as ``docs/protocol.md`` (Training rules, amended 2026-10-18) and
ADR 0002's amendment of that day say; where they are silent, this file
decides. The numbers come from the committed ``scored/outcomes.jsonl``
files through :mod:`dfilterforge.score_summary`'s public statistics. With
a denominator of 1 per case, ``ratio_rate`` is the scorer's case mean, so
every row's C4 rate must equal its own ``summary.json``.

``--check`` rebuilds ``docs/results/sft-v1/headline.json`` and compares it
byte for byte. Exit 0 on success, 1 on a mismatch, 2 when a run is not
scored, a summary disagrees or the rows answer different items.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
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

SCHEMA_VERSION = "sft-headline/1.0"
RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"
OUTPUT = Path("sft-v1") / "headline.json"
BASE = "test-qwen3-1.7b-2026-10-07"
SEEDS: dict[int, str] = {
    17: "test-qwen3-1.7b-sft-s17-2026-10-07",
    42: "test-qwen3-1.7b-sft-s42-2026-10-07",
    2026: "test-qwen3-1.7b-sft-s2026-2026-10-07",
}
# The hosted test rows in the protocol's pool order: the three slot
# winners, then qwen/qwen3-32b by its A/A pass A.
HOSTED: tuple[str, ...] = (
    "test-qwen3.5-9b-2026-09-26",
    "test-qwen3.5-122b-a10b-2026-09-26",
    "test-deepseek-v4-pro-0813-2026-09-26",
    "test-qwen3-32b-2026-09-26",
)
CONDITION = "C4"
# What a difference reads as when positive, negative and otherwise.
_GAIN = ("gain", "loss", "inconclusive")
_SIDE = ("higher", "lower", "not separable on these 40 cases")
_MISMATCH = 1
_FAILURE = 2

Items = dict[str, ItemOutcomeV1]
Shares = dict[str, float]
Keep = Callable[[ItemOutcomeV1], bool]


def _scored(results: Path, run: str) -> tuple[Items, ScoreSummaryV1]:
    """A run's ready C4 items by item id, and its summary.

    Raises:
        DFilterForgeError: The run has no scored outcomes.
    """
    scored = results / run / "scored"
    if not (scored / "outcomes.jsonl").is_file():
        raise DFilterForgeError("run_not_scored", f"{run} is not scored")
    lines = (scored / "outcomes.jsonl").read_text("utf-8").splitlines()
    items = (ItemOutcomeV1.model_validate_json(line) for line in lines)
    summary = (scored / "summary.json").read_text("utf-8")
    return {
        item.item_id: item
        for item in items
        if item.condition == CONDITION and item.gold_status == "ready"
    }, ScoreSummaryV1.model_validate_json(summary)


def _covered(item: ItemOutcomeV1) -> bool:
    """Whether the item's retrieved list holds every gold field."""
    return item.retrieved_gold_field_count == item.gold_field_count


STRATA: dict[str, Keep] = {
    "every_gold_field_retrieved": _covered,
    "some_gold_field_missing": lambda item: not _covered(item),
}


def _shares(items: Items, keep: Keep) -> Shares:
    """Per case, the share of its items that ``keep`` takes and are exact."""
    exact = OutcomeV1.STRONG_EXACT
    return case_means(
        [
            (item.case_id, float(keep(item) and item.outcome is exact))
            for item in items.values()
        ]
    )


def _same_items(rows: Mapping[str, Items]) -> Items:
    """Returns the base row's items once every row answers the same ones.

    Raises:
        DFilterForgeError: A row answers other items or cases, or puts an
            item in another coverage stratum.
    """
    base = rows[BASE]
    for run, items in rows.items():
        if items.keys() != base.keys() or any(
            item.case_id != base[key].case_id
            or _covered(item) != _covered(base[key])
            for key, item in items.items()
        ):
            raise DFilterForgeError(
                "rows_differ", f"{run} does not answer the base row's items"
            )
    return base


class Universe:
    """The ready cases every row shares, and their resample vectors."""

    def __init__(self, items: Items) -> None:
        self.case_ids = tuple(sorted({item.case_id for item in items.values()}))
        self.vectors = draw_indices(len(self.case_ids))
        self.ones = {key: 1.0 for key in self.case_ids}

    def rate(self, numerators: Shares, denominators: Shares) -> RateV1:
        """The summed numerators over the summed denominators."""
        return ratio_rate(
            {key: numerators[key] for key in denominators},
            denominators,
            self.vectors,
            self.case_ids,
        )

    def paired(
        self,
        first: Shares,
        second: Shares,
        denominators: Shares,
        words: Sequence[str] | None,
    ) -> dict[str, Any]:
        """Two rows' difference and counts; ``words`` None leaves it unread."""
        differences = {key: first[key] - second[key] for key in denominators}
        difference = self.rate(differences, denominators)
        counts = discordance(differences)
        paired: dict[str, Any] = {
            "difference": difference.model_dump(),
            "first_better_cases": counts.first_better,
            "second_better_cases": counts.second_better,
            "discordant_cases": counts.discordant,
        }
        if words is not None:
            # An endpoint at 0, or none, does not exclude 0.
            sure = counts.discordant >= MIN_DISCORDANT_CASES
            low, high = difference.low or 0.0, difference.high or 0.0
            sign = 0 if sure and low > 0 else 1 if sure and high < 0 else 2
            paired["reading"] = words[sign]
        return paired


def _mean(rows: Sequence[Shares]) -> Shares:
    """Averages the seeds' case shares, case by case."""
    return {key: sum(row[key] for row in rows) / len(rows) for key in rows[0]}


def _ladder(
    universe: Universe,
    shares: Mapping[str, Shares],
    denominators: Shares,
    words: Sequence[str] | None,
) -> dict[str, Any]:
    """The base row, each seed against it in seed order, and their mean."""
    mean = _mean([shares[run] for run in SEEDS.values()])
    base = shares[BASE]
    return {
        "base": universe.rate(base, denominators).model_dump(),
        "seeds": [
            {
                "seed": seed,
                "run": run,
                "rate": universe.rate(shares[run], denominators).model_dump(),
                **universe.paired(shares[run], base, denominators, words),
            }
            for seed, run in sorted(SEEDS.items())
        ],
        "mean": {
            "rate": universe.rate(mean, denominators).model_dump(),
            **universe.paired(mean, base, denominators, words),
        },
    }


def _coverage(universe: Universe, rows: Mapping[str, Items]) -> dict[str, Any]:
    """The ladder inside each field-coverage stratum, as ratios, unread."""
    strata: dict[str, Any] = {}
    for name, keep in STRATA.items():
        base = rows[BASE].values()
        share = case_means([(item.case_id, float(keep(item))) for item in base])
        present = {key: value for key, value in share.items() if value}
        shares = {run: _shares(items, keep) for run, items in rows.items()}
        strata[name] = {
            "items": sum(1 for item in base if keep(item)),
            **_ladder(universe, shares, present, None),
        }
    return strata


def build(results: Path) -> dict[str, Any]:
    """Computes the headline from the committed scores under ``results``.

    Raises:
        DFilterForgeError: A run is not scored, its summary reports another
            C4 rate, or the rows answer different items.
    """
    runs = (BASE, *SEEDS.values(), *HOSTED)
    scored = {run: _scored(results, run) for run in runs}
    rows = {run: items for run, (items, _) in scored.items()}
    universe = Universe(_same_items(rows))
    exact = {run: _shares(items, lambda _: True) for run, items in rows.items()}
    for run, (_, summary) in scored.items():
        rate = universe.rate(exact[run], universe.ones)
        if summary.conditions[CONDITION].strong_exact != rate:
            raise DFilterForgeError(
                "summary_mismatch", f"{run} summary reports another C4 rate"
            )
    mean = _mean([exact[run] for run in SEEDS.values()])
    return {
        "schema_version": SCHEMA_VERSION,
        "split": "test",
        "condition": CONDITION,
        "metric": "strong_exact",
        "cases": len(universe.case_ids),
        "items": len(rows[BASE]),
        "bootstrap": {
            "seed": BOOTSTRAP_SEED,
            "resamples": BOOTSTRAP_RESAMPLES,
            "low_percentile": LOW_PERCENTILE,
            "high_percentile": HIGH_PERCENTILE,
            "min_discordant_cases": MIN_DISCORDANT_CASES,
        },
        "base_run": BASE,
        **_ladder(universe, exact, universe.ones, _GAIN),
        "coverage": _coverage(universe, rows),
        "hosted": [
            {
                "run": run,
                "model_id": scored[run][1].model_id,
                "rate": universe.rate(exact[run], universe.ones).model_dump(),
                **universe.paired(mean, exact[run], universe.ones, _SIDE),
            }
            for run in HOSTED
        ],
        "self_served_rerun_noise": "not_measured",
        "sources": {
            run: file_sha256(results / run / "scored" / "outcomes.jsonl")
            for run in runs
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Writes or checks the headline; returns the exit status."""
    parser = argparse.ArgumentParser(description="Write the SFT headline.")
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    output = args.results / OUTPUT
    try:
        data = (canonical_json(build(args.results)) + "\n").encode("utf-8")
    except DFilterForgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return _FAILURE
    # Bytes, so a Windows checkout writes and compares what CI does.
    if not args.check:
        output.write_bytes(data)
        return 0
    if output.is_file() and output.read_bytes() == data:
        return 0
    print(f"{output} differs from its rebuild", file=sys.stderr)
    return _MISMATCH


if __name__ == "__main__":
    sys.exit(main())
