"""The coverage split and the seeds' mean, on hand-built rows."""

from __future__ import annotations

import pytest

from dfilterforge.errors import DFilterForgeError
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.sft_rates import coverage
from dfilterforge.sft_rates import seed_mean

EXACT = OutcomeV1.STRONG_EXACT
SILENT = OutcomeV1.SILENT_WRONG


def _row(*items: tuple[str, str, OutcomeV1, bool]) -> dict[str, ItemOutcomeV1]:
    """Items as (item id, case id, outcome, every gold field retrieved)."""
    return {
        key: ItemOutcomeV1(
            condition="C4",
            item_id=key,
            case_id=case,
            outcome=outcome,
            gold_field_count=2,
            retrieved_gold_field_count=2 if listed else 1,
            latency_ms=1.0,
        )
        for key, case, outcome, listed in items
    }


def test_the_seeds_mean_averages_each_case_then_the_cases() -> None:
    first = _row(
        ("i-1", "a", EXACT, True),
        ("i-2", "a", EXACT, True),
        ("i-3", "b", SILENT, True),
    )
    second = _row(
        ("i-1", "a", EXACT, True),
        ("i-2", "a", EXACT, True),
        ("i-3", "b", SILENT, True),
    )

    # Case a is exact, case b is not: 0.5, where pooling items gives 0.667.
    assert seed_mean([first, second]) == 0.5


BASE = _row(
    ("i-1", "a", EXACT, True),
    ("i-2", "a", SILENT, False),
    ("i-3", "b", SILENT, False),
    ("i-4", "b", SILENT, False),
)


def test_coverage_splits_each_row_by_the_first_rows_strata() -> None:
    (table,) = coverage({"base": BASE})

    assert table["strata"]["every_gold_field_retrieved"]["value"] == 1.0
    assert table["strata"]["some_gold_field_missing"]["value"] == 0.0


def test_coverage_refuses_a_row_that_puts_an_item_in_another_stratum() -> None:
    moved = dict(BASE)
    moved["i-1"] = BASE["i-1"].model_copy(
        update={"retrieved_gold_field_count": 1}
    )

    with pytest.raises(DFilterForgeError, match="differs"):
        coverage({"base": BASE, "moved": moved})
