"""The registered descriptive analyses of the self-served rows, as tables.

``docs/protocol.md`` registers them (Training rules, amended 2026-10-18);
``scripts/sft_analysis.py`` reads the committed rows into :class:`Row` and
writes these tables to ``docs/results/sft-v1/analysis.json``. The first row
is the base model, then one per seed. The error classes and the proximity
strata were defined after seed 2026's test scores were known; the tables
describe and decide nothing.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import random
from typing import Any

from dfilterforge.answer_classes import Atoms
from dfilterforge.answer_classes import atoms
from dfilterforge.answer_classes import error_class
from dfilterforge.answer_classes import ErrorClass
from dfilterforge.answer_classes import fields
from dfilterforge.answer_classes import nearest
from dfilterforge.answer_classes import proximity
from dfilterforge.answer_classes import Proximity
from dfilterforge.intent_ir import Expression
from dfilterforge.score_summary import case_means
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.train_combos import canonical_key

# A loud failure is refused by tshark or is no answer the scorer can read;
# an executed answer ran, rightly or not.
LOUD = (OutcomeV1.INVALID, OutcomeV1.MALFORMED)
EXECUTED = (OutcomeV1.STRONG_EXACT, OutcomeV1.SHORTCUT, OutcomeV1.SILENT_WRONG)
# The outcomes whose answer has a stored IR.
WITH_IR = (OutcomeV1.INVALID, *EXECUTED)
CHECK_SEED = 17
CHECK_SIZE = 10
_EXACT = OutcomeV1.STRONG_EXACT
_SILENT = OutcomeV1.SILENT_WRONG
_DIGITS = 6

Items = Mapping[str, ItemOutcomeV1]
Document = dict[str, Any]
Keep = Callable[[ItemOutcomeV1], bool]


def covered(item: ItemOutcomeV1) -> bool:
    """Whether the item's retrieved list holds every gold field."""
    return item.retrieved_gold_field_count == item.gold_field_count


STRATA: dict[str, Keep] = {
    "every_gold_field_retrieved": covered,
    "some_gold_field_missing": lambda item: not covered(item),
}


@dataclass(frozen=True)
class Row:
    """One self-served row's test C4 answers.

    Attributes:
        run: The run id.
        items: The ready items by item id.
        non_ready: The items whose gold is not ready, by item id.
        answers: The stored IR's expression of each ready answer with one.
        gold: The gold expression of each case.
        listed: The retrieved field names of each item's prompt.
    """

    run: str
    items: Items
    non_ready: Items
    answers: Mapping[str, Expression]
    gold: Mapping[str, Expression]
    listed: Mapping[str, frozenset[str]]

    def kind(self, key: str) -> str:
        """The ready item's error class, or strong_exact."""
        item = self.items[key]
        if item.outcome is _EXACT:
            return item.outcome.value
        answer = self.answers.get(key)
        return error_class(item, answer, self.gold[item.case_id]).value


@dataclass(frozen=True)
class Target:
    """One ready training target, as the proximity table shows it."""

    id: str
    request: str
    filter: str
    atoms: Atoms


def transitions(
    rows: Sequence[Row], seeds: Sequence[int], ready: bool
) -> list[Document]:
    """Per seed, each base outcome against the seed's on the same item."""
    table: list[Document] = []
    for seed, row in zip(seeds, rows[1:], strict=True):
        base, mine = (
            (rows[0].items, row.items)
            if ready
            else (rows[0].non_ready, row.non_ready)
        )
        pairs = Counter(
            (base[key].outcome.value, mine[key].outcome.value) for key in base
        )
        flows: dict[str, dict[str, int]] = {}
        for (first, then), number in sorted(pairs.items()):
            flows.setdefault(first, {})[then] = number
        table.append({"seed": seed, "flows": flows})
    return table


_MOVES = {
    "loud_ran": (LOUD, EXECUTED),
    "loud_exact": (LOUD, (_EXACT,)),
    "loud_silent": (LOUD, (_SILENT,)),
    "silent_exact": ((_SILENT,), (_EXACT,)),
    "exact_silent": ((_EXACT,), (_SILENT,)),
}


def summary(rows: Sequence[Row]) -> Document:
    """The page's opening counts per seed, and their range over the seeds."""
    base = rows[0].items
    seeds = [
        {
            name: sum(
                base[key].outcome in first and row.items[key].outcome in then
                for key in base
            )
            for name, (first, then) in _MOVES.items()
        }
        for row in rows[1:]
    ]
    return {
        "seeds": seeds,
        "range": {
            name: {
                "low": min(seed[name] for seed in seeds),
                "high": max(seed[name] for seed in seeds),
            }
            for name in _MOVES
        },
    }


def classes(rows: Sequence[Row]) -> Document:
    """Class counts, the first item of each class, and the check sample.

    The sample is ``CHECK_SIZE`` items, or every one when fewer, drawn by
    ``random.Random(CHECK_SEED)`` from every classified item, listed by row
    and then by item id.
    """
    order = [_EXACT.value, *(kind.value for kind in ErrorClass)]
    every = [{key: row.kind(key) for key in sorted(row.items)} for row in rows]
    table: list[Document] = []
    classified: list[tuple[str, str, str]] = []
    for row, kinds in zip(rows, every, strict=True):
        counts = Counter(kinds.values())
        table.append(
            {
                "run": row.run,
                "counts": {kind: counts[kind] for kind in order},
                "examples": {
                    kind: min(key for key in kinds if kinds[key] == kind)
                    for kind in order
                    if counts[kind]
                },
            }
        )
        classified.extend(
            (row.run, key, kind)
            for key, kind in kinds.items()
            if kind != _EXACT.value
        )
    size = min(CHECK_SIZE, len(classified))
    sample = random.Random(CHECK_SEED).sample(classified, size)
    return {
        "order": order,
        "rows": table,
        "items": [
            {
                "item_id": key,
                "case_id": rows[0].items[key].case_id,
                "classes": [kinds[key] for kinds in every],
            }
            for key in sorted(rows[0].items)
        ],
        "check": {
            "seed": CHECK_SEED,
            "classified": len(classified),
            "sample": [
                {"run": run, "item_id": key, "class": kind}
                for run, key, kind in sample
            ],
        },
    }


def _case_mean(items: Iterable[ItemOutcomeV1]) -> float:
    shares = case_means(
        [(i.case_id, float(i.outcome is _EXACT)) for i in items]
    )
    return round(sum(shares.values()) / len(shares), _DIGITS)


def nearness(rows: Sequence[Row], targets: Sequence[Target]) -> Document:
    """Each case's stratum and shown target, and strong exact per stratum."""
    sets = [target.atoms for target in targets]
    cases: list[Document] = []
    for case_id, gold in sorted(rows[0].gold.items()):
        mine = atoms(gold)
        shown = targets[nearest(mine, sets)]
        cases.append(
            {
                "case_id": case_id,
                "stratum": proximity(mine, sets).value,
                "atoms": len(mine),
                "nearest": {
                    "id": shown.id,
                    "shared": len(mine & shown.atoms),
                    "request": shown.request,
                    "filter": shown.filter,
                },
            }
        )
    strata: list[Document] = []
    for stratum in Proximity:
        members = {c["case_id"] for c in cases if c["stratum"] == stratum}
        if members:
            chosen = [
                [i for i in row.items.values() if i.case_id in members]
                for row in rows
            ]
            strata.append(
                {
                    "stratum": stratum.value,
                    "cases": len(members),
                    "items": len(chosen[0]),
                    "rows": [
                        {"run": row.run, "strong_exact": _case_mean(items)}
                        for row, items in zip(rows, chosen, strict=True)
                    ],
                }
            )
    return {"targets": len(targets), "cases": cases, "strata": strata}


def _share(part: int, whole: int) -> float | None:
    return None if whole == 0 else round(part / whole, _DIGITS)


def copies(
    rows: Sequence[Row], targets: Sequence[Expression]
) -> list[Document]:
    """Per row and coverage stratum, the copies and the unlisted fields.

    Over the ready answers with a stored IR: those whose canonical form is a
    training target's, and those that test a field their prompt's retrieved
    list lacks, each with how many are strong exact.
    """
    keys = {canonical_key(target) for target in targets}
    table: list[Document] = []
    for row in rows:
        strata: Document = {}
        for name, keep in STRATA.items():
            chosen = [
                (row.items[key], answer)
                for key, answer in sorted(row.answers.items())
                if keep(row.items[key])
            ]
            copied = [i for i, e in chosen if canonical_key(e) in keys]
            unlisted = [
                i for i, e in chosen if not fields(e) <= row.listed[i.item_id]
            ]
            strata[name] = {
                "with_ir": len(chosen),
                "copies": len(copied),
                "copies_exact": sum(i.outcome is _EXACT for i in copied),
                "copy_share": _share(len(copied), len(chosen)),
                "unlisted": len(unlisted),
                "unlisted_exact": sum(i.outcome is _EXACT for i in unlisted),
                "unlisted_share": _share(len(unlisted), len(chosen)),
            }
        table.append({"run": row.run, "strata": strata})
    return table
