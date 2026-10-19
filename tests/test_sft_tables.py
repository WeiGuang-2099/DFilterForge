"""The descriptive tables of the self-served rows, on rows built in memory."""

from __future__ import annotations

import random
from typing import Any

from dfilterforge.answer_classes import atoms
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.sft_tables import classes
from dfilterforge.sft_tables import copies
from dfilterforge.sft_tables import nearness
from dfilterforge.sft_tables import Row
from dfilterforge.sft_tables import summary
from dfilterforge.sft_tables import Target
from dfilterforge.sft_tables import transitions

SYN = Predicate(field="tcp.flags.syn", operator=Operator.EQ, value=True)
ACK = Predicate(field="tcp.flags.ack", operator=Operator.EQ, value=True)
DNS = Predicate(field="udp.srcport", operator=Operator.EQ, value=53)
GOLD: dict[str, Expression] = {
    "case-a": All(children=(SYN, ACK)),
    "case-b": DNS,
}
EXACT = OutcomeV1.STRONG_EXACT
SILENT = OutcomeV1.SILENT_WRONG
INVALID = OutcomeV1.INVALID
MALFORMED = OutcomeV1.MALFORMED
ABSTAINED = OutcomeV1.ABSTAINED
FALSE_READY = OutcomeV1.FALSE_READY
# The items of each case, in item id order.
CASES = {"case-a": ("i-1", "i-2"), "case-b": ("i-3", "i-4")}


def _item(key: str, outcome: OutcomeV1, **fields: Any) -> ItemOutcomeV1:
    case = next((c for c, keys in CASES.items() if key in keys), "case-n")
    return ItemOutcomeV1(
        condition="C4",
        item_id=key,
        case_id=case,
        outcome=outcome,
        gold_field_count=2,
        retrieved_gold_field_count=fields.pop("hits", 2),
        latency_ms=1.0,
        gold_status=fields.pop("gold_status", "ready"),
        **fields,
    )


def _row(
    run: str,
    outcomes: dict[str, OutcomeV1],
    answers: dict[str, Expression] | None = None,
    non_ready: dict[str, OutcomeV1] | None = None,
    hits: dict[str, int] | None = None,
) -> Row:
    extra = {"error_code": "unknown_field"}
    return Row(
        run=run,
        items={
            key: _item(
                key,
                outcome,
                hits=(hits or {}).get(key, 2),
                **(extra if outcome is INVALID else {}),
            )
            for key, outcome in outcomes.items()
        },
        non_ready={
            key: _item(key, outcome, gold_status="needs_clarification")
            for key, outcome in (non_ready or {}).items()
        },
        answers=answers or {},
        gold=GOLD,
        listed={
            key: frozenset({"tcp.flags.syn", "tcp.flags.ack"})
            for key in ("i-1", "i-2", "i-3", "i-4")
        },
    )


BASE = _row(
    "base",
    {"i-1": SILENT, "i-2": INVALID, "i-3": MALFORMED, "i-4": EXACT},
    answers={"i-1": SYN, "i-2": SYN, "i-4": DNS},
    non_ready={"i-9": FALSE_READY},
)
SEED = _row(
    "seed",
    {"i-1": EXACT, "i-2": SILENT, "i-3": SILENT, "i-4": SILENT},
    answers={
        "i-1": All(children=(ACK, SYN)),
        "i-2": All(children=(SYN, ACK, DNS)),
        "i-3": SYN,
        "i-4": DNS.model_copy(update={"operator": Operator.NE}),
    },
    non_ready={"i-9": ABSTAINED},
)


def test_transitions_count_each_base_outcome_against_the_seed() -> None:
    assert transitions([BASE, SEED], [17], ready=True) == [
        {
            "seed": 17,
            "flows": {
                "invalid": {"silent_wrong": 1},
                "malformed": {"silent_wrong": 1},
                "silent_wrong": {"strong_exact": 1},
                "strong_exact": {"silent_wrong": 1},
            },
        }
    ]
    assert transitions([BASE, SEED], [17], ready=False) == [
        {"seed": 17, "flows": {"false_ready": {"abstained": 1}}}
    ]


def test_the_summary_counts_the_moves_of_each_seed_and_their_range() -> None:
    other = _row(
        "other", {"i-1": SILENT, "i-2": EXACT, "i-3": EXACT, "i-4": EXACT}
    )

    table = summary([BASE, SEED, other])

    assert table["seeds"] == [
        {
            "loud_ran": 2,
            "loud_exact": 0,
            "loud_silent": 2,
            "silent_exact": 1,
            "exact_silent": 1,
        },
        {
            "loud_ran": 2,
            "loud_exact": 2,
            "loud_silent": 0,
            "silent_exact": 0,
            "exact_silent": 0,
        },
    ]
    assert table["range"]["loud_silent"] == {"low": 0, "high": 2}
    assert table["range"]["loud_ran"] == {"low": 2, "high": 2}
    assert table["range"]["loud_exact"] == {"low": 0, "high": 2}


def test_classes_count_each_row_and_draw_the_check_sample() -> None:
    table = classes([BASE, SEED])

    base, seed = table["rows"]
    assert base["counts"]["missing_field"] == 1
    assert base["counts"]["unknown_field"] == 1
    assert base["counts"]["malformed"] == 1
    assert base["counts"]["strong_exact"] == 1
    assert seed["counts"]["extra_field"] == 1
    assert seed["counts"]["missing_field"] == 1
    assert seed["counts"]["structure"] == 0
    assert seed["examples"] == {
        "strong_exact": "i-1",
        "missing_field": "i-3",
        "extra_field": "i-2",
        "operator": "i-4",
    }
    assert table["items"][0] == {
        "item_id": "i-1",
        "case_id": "case-a",
        "classes": ["missing_field", "strong_exact"],
    }
    classified = [
        ("base", "i-1", "missing_field"),
        ("base", "i-2", "unknown_field"),
        ("base", "i-3", "malformed"),
        ("seed", "i-2", "extra_field"),
        ("seed", "i-3", "missing_field"),
        ("seed", "i-4", "operator"),
    ]
    drawn = random.Random(17).sample(classified, len(classified))
    assert table["check"]["classified"] == len(classified)
    assert [
        (each["run"], each["item_id"], each["class"])
        for each in table["check"]["sample"]
    ] == drawn


def test_nearness_strata_average_each_rows_strong_exact_by_case() -> None:
    targets = [
        Target("t-1", "Show SYN or ACK.", "a", atoms(All(children=(SYN, ACK)))),
        Target(
            "t-2", "Show DNS and SYN.", "b", atoms(All(children=(DNS, SYN)))
        ),
    ]

    table = nearness([BASE, SEED], targets)

    assert [case["stratum"] for case in table["cases"]] == [
        "same_atoms",
        "inside_one_target",
    ]
    assert table["cases"][1]["nearest"] == {
        "id": "t-2",
        "shared": 1,
        "request": "Show DNS and SYN.",
        "filter": "b",
    }
    assert table["strata"][1] == {
        "stratum": "inside_one_target",
        "cases": 1,
        "items": 2,
        "rows": [
            {"run": "base", "strong_exact": 0.5},
            {"run": "seed", "strong_exact": 0.0},
        ],
    }


def test_copies_count_training_forms_and_unlisted_fields_by_coverage() -> None:
    row = _row(
        "seed",
        {"i-1": EXACT, "i-2": SILENT, "i-3": SILENT, "i-4": EXACT},
        answers={
            "i-1": All(children=(ACK, SYN)),
            "i-2": SYN,
            "i-3": DNS,
            "i-4": DNS,
        },
        hits={"i-3": 1, "i-4": 1},
    )

    (table,) = copies([row], [All(children=(SYN, ACK)), DNS])

    assert table["strata"]["every_gold_field_retrieved"] == {
        "with_ir": 2,
        "copies": 1,
        "copies_exact": 1,
        "copy_share": 0.5,
        "unlisted": 0,
        "unlisted_exact": 0,
        "unlisted_share": 0.0,
    }
    assert table["strata"]["some_gold_field_missing"] == {
        "with_ir": 2,
        "copies": 2,
        "copies_exact": 1,
        "copy_share": 1.0,
        "unlisted": 2,
        "unlisted_exact": 1,
        "unlisted_share": 1.0,
    }
