"""Write the descriptive analyses of the self-served rows on test C4.

``docs/protocol.md`` registers them (Training rules, amended 2026-10-18):
transitions, error classes with a hand-check sample, field coverage,
proximity to training, and copies and unlisted fields. The classes and the
strata were defined after seed 2026's test scores were known; they describe
and decide nothing, and where this file and that text differ, the text
holds. The rows are the ones ``docs/results/sft-v1/headline.json`` names,
read from their committed scored runs, and the training targets are the
ready rows of ``data/train/v1/train.jsonl``. :mod:`dfilterforge.sft_tables`
builds the tables and :mod:`dfilterforge.sft_rates` the coverage split of
every headline row and the seeds' mean strong exact per condition; this file
reads the files and checks that the rows agree with each other and with the
headline.

``--check`` rebuilds ``docs/results/sft-v1/analysis.json`` and compares it
byte for byte. Exit 0 on success, 1 on a mismatch, 2 when an input is
missing or the rows disagree.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from typing import Any

from dfilterforge import sft_rates
from dfilterforge.answer_classes import atoms
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.errors import DFilterForgeError
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.sft_tables import classes
from dfilterforge.sft_tables import copies
from dfilterforge.sft_tables import covered
from dfilterforge.sft_tables import Document
from dfilterforge.sft_tables import nearness
from dfilterforge.sft_tables import Row
from dfilterforge.sft_tables import STRATA
from dfilterforge.sft_tables import summary
from dfilterforge.sft_tables import Target
from dfilterforge.sft_tables import transitions
from dfilterforge.sft_tables import WITH_IR

SCHEMA_VERSION = "sft-analysis/1.0"
_ROOT = Path(__file__).resolve().parents[1]
RESULTS = _ROOT / "docs" / "results"
TRAIN = _ROOT / "data" / "train" / "v1" / "train.jsonl"
HEADLINE = Path("sft-v1") / "headline.json"
OUTPUT = Path("sft-v1") / "analysis.json"
CONDITION = "C4"
CONDITIONS = ("C1", "C2", "C3", "C4")
_MISMATCH = 1
_FAILURE = 2


def _read(path: Path) -> Any:
    if not path.is_file():
        raise DFilterForgeError("input_missing", f"{path.name} is missing")
    return json.loads(path.read_text("utf-8"))


def _items(
    results: Path, run: str, condition: str, ready: bool = True
) -> dict[str, ItemOutcomeV1]:
    """A run's scored items of one condition, ready gold or not, by id."""
    path = results / run / "scored" / "outcomes.jsonl"
    if not path.is_file():
        raise DFilterForgeError("run_not_scored", f"{run} is not scored")
    lines = path.read_text("utf-8").splitlines()
    items = (ItemOutcomeV1.model_validate_json(line) for line in lines)
    return {
        item.item_id: item
        for item in items
        if item.condition == condition
        and (item.gold_status == "ready") is ready
    }


def _row(results: Path, run: str) -> Row:
    """Reads one self-served row's ready C4 answers, gold and prompts."""
    scored = results / run / "scored"
    items = _items(results, run, CONDITION)
    prompts = _read(results / run / "prepared" / f"{CONDITION}.json")
    return Row(
        run=run,
        items=items,
        non_ready=_items(results, run, CONDITION, ready=False),
        answers={
            key: IntentIrV1.model_validate(
                _read(scored / "intents" / CONDITION / f"{key}.json")
            ).expression
            for key, item in items.items()
            if item.outcome in WITH_IR
        },
        gold={
            item.case_id: IntentIrV1.model_validate(
                _read(scored / "specs" / f"{item.case_id}.json")["canonical_ir"]
            ).expression
            for item in items.values()
        },
        listed={
            prompt["item_id"]: frozenset(
                field["abbreviation"] for field in prompt["retrieved_fields"]
            )
            for prompt in prompts["prompts"]
        },
    )


def _agree(rows: Sequence[Row]) -> None:
    """Refuses rows that answer other items, gold, strata or prompts."""
    base = rows[0]
    for row in rows[1:]:
        same = (
            row.items.keys() == base.items.keys()
            and row.non_ready.keys() == base.non_ready.keys()
            and row.gold == base.gold
            and row.listed == base.listed
            and all(
                item.case_id == base.items[key].case_id
                and covered(item) == covered(base.items[key])
                for key, item in row.items.items()
            )
        )
        if not same:
            raise DFilterForgeError("rows_differ", f"{row.run} differs")


def _check_headline(
    headline: Document, coverage: Sequence[Document], mean: dict[str, float]
) -> None:
    """Refuses a coverage split or a C4 mean the headline does not hold."""
    ladder = headline["coverage"]
    for index, entry in enumerate(coverage[: len(headline["seeds"]) + 1]):
        for name in STRATA:
            rate = (
                ladder[name]["base"]
                if index == 0
                else ladder[name]["seeds"][index - 1]["rate"]
            )
            if entry["strata"][name] != rate:
                raise DFilterForgeError("headline_differs", entry["run"])
    if mean[CONDITION] != headline["mean"]["rate"]["value"]:
        raise DFilterForgeError("headline_differs", "the seeds' mean")


def _targets(train_path: Path) -> list[tuple[Target, Expression]]:
    """The ready training targets, in file order, with their expressions."""
    if not train_path.is_file():
        raise DFilterForgeError("input_missing", "the training set is missing")
    targets: list[tuple[Target, Expression]] = []
    for line in train_path.read_text("utf-8").splitlines():
        row = json.loads(line)
        if row["target"]["status"] == "ready":
            ir = IntentIrV1.model_validate(row["target"]["intent_ir"])
            target = Target(
                row["id"], row["request"], row["filter"], atoms(ir.expression)
            )
            targets.append((target, ir.expression))
    return targets


def build(results: Path, train_path: Path) -> Document:
    """Computes every registered analysis from the committed files.

    Raises:
        DFilterForgeError: An input is missing, a run is not scored or the
            rows disagree with each other or with the headline.
    """
    headline = _read(results / HEADLINE)
    numbers = [seed["seed"] for seed in headline["seeds"]]
    seeds = [seed["run"] for seed in headline["seeds"]]
    runs = [headline["base_run"], *seeds]
    hosted = [row["run"] for row in headline["hosted"]]
    rows = [_row(results, run) for run in runs]
    _agree(rows)
    targets = _targets(train_path)
    coverage = sft_rates.coverage(
        {run: _items(results, run, CONDITION) for run in [*runs, *hosted]}
    )
    mean = {
        condition: sft_rates.seed_mean(
            [_items(results, run, condition) for run in seeds]
        )
        for condition in CONDITIONS
    }
    _check_headline(headline, coverage, mean)
    scored = [results / run / "scored" / "outcomes.jsonl" for run in runs]
    scored += [results / run / "scored" / "outcomes.jsonl" for run in hosted]
    return {
        "schema_version": SCHEMA_VERSION,
        "split": "test",
        "condition": CONDITION,
        "post_hoc": True,
        "base_run": runs[0],
        "seeds": [
            {"seed": seed, "run": run}
            for seed, run in zip(numbers, seeds, strict=True)
        ],
        "items": len(rows[0].items),
        "non_ready_items": len(rows[0].non_ready),
        "cases": len(rows[0].gold),
        "transitions": {
            "ready": transitions(rows, numbers, ready=True),
            "non_ready": transitions(rows, numbers, ready=False),
        },
        "summary": summary(rows),
        "classes": classes(rows),
        "proximity": nearness(rows, [target for target, _ in targets]),
        "copies": copies(rows, [expression for _, expression in targets]),
        "coverage": coverage,
        "seed_mean": mean,
        "sources": {
            f"docs/results/{path.relative_to(results).as_posix()}": (
                file_sha256(path)
            )
            for path in [results / HEADLINE, *scored]
        }
        | {"data/train/v1/train.jsonl": file_sha256(train_path)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Writes or checks the analyses; returns the exit status."""
    parser = argparse.ArgumentParser(description="Write the SFT analyses.")
    parser.add_argument("--results", type=Path, default=RESULTS)
    parser.add_argument("--train", type=Path, default=TRAIN)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    output = args.results / OUTPUT
    try:
        document = build(args.results, args.train)
        data = (canonical_json(document) + "\n").encode("utf-8")
    except DFilterForgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return _FAILURE
    # Bytes, so a Windows checkout writes and compares what CI does.
    if args.check:
        same = output.is_file() and output.read_bytes() == data
        if not same:
            print(f"{output} differs from its rebuild", file=sys.stderr)
        return 0 if same else _MISMATCH
    output.write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
