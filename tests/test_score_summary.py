"""Behavioral tests for pure per-case aggregation and the seeded bootstrap."""

from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError
import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.score_report import render_markdown
from dfilterforge.score_summary import BOOTSTRAP_RESAMPLES
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import EffectiveSettingsV1
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import ScoreSummaryV1
from dfilterforge.score_summary import SpendV1
from dfilterforge.score_summary import summarize

_PRICES = (0.117, 0.455)


def _item(
    condition: ConditionLabel,
    case_id: str,
    item_id: str,
    outcome: OutcomeV1,
    **overrides: Any,
) -> ItemOutcomeV1:
    """Builds one scored item with test-friendly defaults."""
    values: dict[str, Any] = {
        "condition": condition,
        "case_id": case_id,
        "item_id": item_id,
        "outcome": outcome,
        "gold_field_count": 1,
        "latency_ms": 10.0,
    }
    values.update(overrides)
    return ItemOutcomeV1(**values)


def _summarize(
    outcomes: Sequence[ItemOutcomeV1], **overrides: Any
) -> ScoreSummaryV1:
    """Summarizes items with fixed run identity fields."""
    values: dict[str, Any] = {
        "run": "run-0001",
        "model_id": "vendor/model-a",
        "split": "dev",
        "gold_hash": "0123456789abcdef0123",
        "capture_hashes": {"dns.pcapng": "aa" * 32},
        "batch_hashes": {"C1": "bb" * 32},
    }
    values.update(overrides)
    return summarize(outcomes, **values)


def _settings(**overrides: Any) -> EffectiveSettingsV1:
    """Builds one effective-settings block with test-friendly defaults."""
    values: dict[str, Any] = {
        "requested_model": "vendor/model-a",
        "served_models": ("vendor/model-a",),
        "served_models_distinct": 1,
        "served_model_changed": False,
        "providers": ("alibaba",),
        "providers_distinct": 1,
        "provider_changed": False,
        "system_fingerprints": (),
        "system_fingerprints_distinct": 0,
        "reasoning_tokens_total": 0,
        "items_with_reasoning": 0,
        "thinking": "honoured",
        "thinking_evidence_items": 4,
        "seed_requested": 17,
        "temperature": 0.0,
        "max_output_tokens": 2048,
        "json_mode": True,
        "provider_order": ("alibaba",),
        "allow_fallbacks": False,
        "timeout_seconds": 120.0,
    }
    values.update(overrides)
    return EffectiveSettingsV1(**values)


def _spend(**overrides: Any) -> SpendV1:
    """Builds one spend block with test-friendly defaults."""
    values: dict[str, Any] = {
        "price_derived_usd": 0.000689,
        "price_derived_is_lower_bound": False,
        "usage_missing": 0,
        "retried_items": 0,
        "provider_reported_usd": 0.0431,
        "charged_usd_upper_bound": 0.06,
    }
    values.update(overrides)
    return SpendV1(**values)


def _paired(discordant: int) -> list[ItemOutcomeV1]:
    """Builds twelve cases where C4 beats C2 on the first few."""
    items: list[ItemOutcomeV1] = []
    for index in range(12):
        case_id = f"case-{index:02d}"
        loser = (
            OutcomeV1.SILENT_WRONG
            if index < discordant
            else OutcomeV1.STRONG_EXACT
        )
        items.append(
            _item("C4", case_id, f"{case_id}-c4", OutcomeV1.STRONG_EXACT)
        )
        items.append(_item("C2", case_id, f"{case_id}-c2", loser))
    return items


def test_paraphrases_are_averaged_inside_a_case() -> None:
    """A case counts once however many paraphrases it contributes."""
    outcomes = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-1", "i2", OutcomeV1.SILENT_WRONG),
        _item("C1", "case-2", "i3", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-2", "i4", OutcomeV1.STRONG_EXACT),
    ]

    condition = _summarize(outcomes).conditions["C1"]

    assert condition.strong_exact.value == 0.75
    assert condition.compile_valid.value == 1.0


@pytest.mark.parametrize(
    "failure",
    [OutcomeV1.PROVIDER_FAILED, OutcomeV1.MALFORMED, OutcomeV1.ABSTAINED],
)
def test_every_outcome_stays_in_the_denominator(
    failure: OutcomeV1,
) -> None:
    """Failed, malformed and abstained items keep their place below."""
    outcomes = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-1", "i2", failure),
    ]

    condition = _summarize(outcomes).conditions["C1"]

    assert condition.strong_exact.value == 0.5
    assert condition.compile_valid.value == 0.5
    assert set(condition.outcomes) == {outcome.value for outcome in OutcomeV1}
    assert condition.outcomes[OutcomeV1.STRONG_EXACT.value] == 1
    assert condition.outcomes[failure.value] == 1


def test_every_rate_counts_its_own_outcome() -> None:
    """The five reported rates are distinct and none stands in for another."""
    first_case = [
        OutcomeV1.SILENT_WRONG,
        OutcomeV1.SILENT_WRONG,
        OutcomeV1.STRONG_EXACT,
        OutcomeV1.ABSTAINED,
    ]
    second_case = [
        OutcomeV1.ABSTAINED,
        OutcomeV1.ABSTAINED,
        OutcomeV1.ABSTAINED,
        OutcomeV1.MALFORMED,
    ]
    outcomes = [
        _item("C4", case_id, f"{case_id}-{index}", outcome)
        for case_id, case in (("case-1", first_case), ("case-2", second_case))
        for index, outcome in enumerate(case)
    ]

    condition = _summarize(outcomes).conditions["C4"]

    assert condition.compile_valid.value == 0.375
    assert condition.strong_exact.value == 0.125
    assert condition.silent_wrong_all.value == 0.25
    assert condition.over_abstention.value == 0.5
    assert condition.silent_wrong_of_executable.value == 0.666667


def test_invalid_output_is_neither_compile_valid_nor_executable() -> None:
    """A rejected filter compiles to nothing, so it leaves the numerator.

    It stays in every denominator that counts items, and it leaves the
    executable denominator that silent-wrong is reported against.
    """
    outcomes = [
        _item("C4", "case-1", "i1", OutcomeV1.SILENT_WRONG),
        _item("C4", "case-1", "i2", OutcomeV1.INVALID),
        _item("C4", "case-2", "i3", OutcomeV1.STRONG_EXACT),
        _item("C4", "case-2", "i4", OutcomeV1.INVALID),
    ]

    condition = _summarize(outcomes).conditions["C4"]

    assert condition.outcomes[OutcomeV1.INVALID.value] == 2
    assert condition.compile_valid.value == 0.5
    assert condition.strong_exact.value == 0.25
    assert condition.silent_wrong_of_executable.value == 0.5


def test_silent_wrong_of_executable_is_a_ratio() -> None:
    """The executable share divides summed case means, not mean ratios."""
    outcomes = [
        _item("C4", "case-1", "i1", OutcomeV1.SILENT_WRONG),
        _item("C4", "case-1", "i2", OutcomeV1.STRONG_EXACT),
        _item("C4", "case-2", "i3", OutcomeV1.STRONG_EXACT),
        _item("C4", "case-2", "i4", OutcomeV1.STRONG_EXACT),
    ]

    condition = _summarize(outcomes).conditions["C4"]

    assert condition.silent_wrong_of_executable.value == 0.25


def test_silent_wrong_of_executable_is_null_without_executable_items() -> None:
    """With nothing executable the ratio is reported as absent."""
    outcomes = [
        _item("C4", "case-1", "i1", OutcomeV1.PROVIDER_FAILED),
        _item("C4", "case-2", "i2", OutcomeV1.PROVIDER_FAILED),
    ]

    rate = _summarize(outcomes).conditions["C4"].silent_wrong_of_executable

    assert rate.value is None
    assert rate.low is None
    assert rate.high is None


def test_error_codes_break_out_budget_exhausted() -> None:
    """An empty reply cut off by the token budget is counted twice."""
    truncated = [
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.PROVIDER_FAILED,
            error_code="empty_content",
            finish_reason="length",
        )
    ]
    stopped = [
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.PROVIDER_FAILED,
            error_code="empty_content",
            finish_reason="stop",
        )
    ]

    cut = _summarize(truncated).conditions["C1"]
    clean = _summarize(stopped).conditions["C1"]

    assert cut.error_codes == {"empty_content": 1, "budget_exhausted": 1}
    assert clean.error_codes == {"empty_content": 1}
    assert cut.outcomes[OutcomeV1.PROVIDER_FAILED.value] == 1
    assert clean.outcomes[OutcomeV1.PROVIDER_FAILED.value] == 1


def test_failure_details_keep_http_statuses_apart() -> None:
    """A 402, a 429, a 404 and a 503 stay distinguishable when reported."""
    outcomes = [
        _item(
            "C1",
            f"case-{index}",
            f"i{index}",
            OutcomeV1.PROVIDER_FAILED,
            error_code="http_error",
            http_status=status,
        )
        for index, status in enumerate((402, 429, 404, 503))
    ]

    condition = _summarize(outcomes).conditions["C1"]

    assert condition.error_codes == {"http_error": 4}
    assert condition.failure_details == {
        "http_error:http_402": 1,
        "http_error:http_429": 1,
        "http_error:http_404": 1,
        "http_error:http_503": 1,
    }


def test_failure_details_add_the_provider_code_without_recounting() -> None:
    """A provider code refines the census instead of enlarging it."""
    outcomes = [
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.PROVIDER_FAILED,
            error_code="http_error",
            http_status=402,
            provider_error_code="402",
        ),
        _item(
            "C1",
            "case-2",
            "i2",
            OutcomeV1.PROVIDER_FAILED,
            error_code="timeout",
        ),
    ]

    condition = _summarize(outcomes).conditions["C1"]

    assert condition.error_codes == {"http_error": 1, "timeout": 1}
    assert condition.failure_details == {
        "http_error:http_402": 1,
        "http_error:provider_402": 1,
    }


def test_unknown_finish_reasons_are_bucketed() -> None:
    """A provider cannot choose an object key in a published file."""
    known = ("stop", "length", "content_filter")
    unknown = ("SURPRISE\nprompt injection", "router_fallback")
    outcomes = [
        _item(
            "C1",
            f"case-{index}",
            f"i{index}",
            OutcomeV1.STRONG_EXACT,
            finish_reason=reason,
        )
        for index, reason in enumerate(known + unknown)
    ]

    summary = _summarize(outcomes)
    encoded = canonical_json(summary)

    assert summary.conditions["C1"].finish_reasons == {
        "stop": 1,
        "length": 1,
        "content_filter": 1,
        "other": 2,
    }
    assert "SURPRISE" not in encoded
    assert "router_fallback" not in encoded


def test_bootstrap_is_seeded_shared_and_nearest_rank() -> None:
    """One draw of index vectors serves every metric and condition."""
    base = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-2", "i2", OutcomeV1.SILENT_WRONG),
    ]
    extended = base + [
        _item("C3", "case-1", "i3", OutcomeV1.STRONG_EXACT),
        _item("C3", "case-2", "i4", OutcomeV1.STRONG_EXACT),
    ]

    first = _summarize(base)
    second = _summarize(base)
    with_c3 = _summarize(extended)
    strong = with_c3.conditions["C3"].strong_exact

    assert canonical_json(first) == canonical_json(second)
    assert strong.value == 1.0
    assert strong.low == 1.0
    assert strong.high == 1.0
    assert strong.resamples_used == BOOTSTRAP_RESAMPLES
    assert first.bootstrap["cases"] == with_c3.bootstrap["cases"]
    assert (
        first.conditions["C1"].compile_valid.low
        == with_c3.conditions["C1"].compile_valid.low
    )
    assert (
        first.conditions["C1"].compile_valid.high
        == with_c3.conditions["C1"].compile_valid.high
    )


def test_bootstrap_bounds_are_the_seeded_nearest_rank_percentiles() -> None:
    """The interval is ordered[24] and ordered[974] of 1,000 seeded draws.

    Eight cases with means 1, 1, 1, 0.5, 0.5, 0, 0, 0 give a spread wide
    enough that another seed or another pair of percentiles cannot land on
    the same two numbers: seed 99 gives 0.25 and 0.8125 here, and the 10th
    and 90th percentiles of this seed give 0.3125 and 0.6875.
    """
    means = (1.0, 1.0, 1.0, 0.5, 0.5, 0.0, 0.0, 0.0)
    outcomes: list[ItemOutcomeV1] = []
    for index, mean in enumerate(means):
        case_id = f"case-{index:02d}"
        strong = round(mean * 2)
        for slot in range(2):
            outcomes.append(
                _item(
                    "C1",
                    case_id,
                    f"{case_id}-{slot}",
                    (
                        OutcomeV1.STRONG_EXACT
                        if slot < strong
                        else OutcomeV1.SILENT_WRONG
                    ),
                )
            )

    summary = _summarize(outcomes)
    rate = summary.conditions["C1"].strong_exact

    assert summary.bootstrap["seed"] == 17
    assert summary.bootstrap["resamples"] == BOOTSTRAP_RESAMPLES
    assert rate.value == 0.5
    assert rate.low == 0.1875
    assert rate.high == 0.75
    assert rate.resamples_used == BOOTSTRAP_RESAMPLES


def test_new_case_id_changes_the_case_universe() -> None:
    """The shared-vector invariant is scoped to an unchanged case set."""
    base = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-2", "i2", OutcomeV1.SILENT_WRONG),
    ]
    widened = base + [_item("C3", "case-3", "i3", OutcomeV1.STRONG_EXACT)]

    assert _summarize(base).bootstrap["cases"] == 2
    assert _summarize(widened).bootstrap["cases"] == 3


def test_comparison_turns_conclusive_at_ten_discordant_cases() -> None:
    """Below ten discordant cases the paired comparison says so."""
    nine = _summarize(_paired(9)).comparisons[0]
    ten = _summarize(_paired(10)).comparisons[0]

    assert nine.first == "C4"
    assert nine.second == "C2"
    assert nine.discordant_cases == 9
    assert nine.inconclusive is True
    assert ten.discordant_cases == 10
    assert ten.inconclusive is False
    assert (
        nine.first_better_cases + nine.second_better_cases
        == nine.discordant_cases
    )
    assert nine.difference.value == pytest.approx(0.75)
    assert nine.difference.low is not None
    assert nine.difference.high is not None
    assert nine.difference.low <= 0.75 <= nine.difference.high


def test_comparison_without_shared_cases_reports_no_difference() -> None:
    """Two conditions run on disjoint cases have nothing to pair."""
    outcomes = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C2", "case-2", "i2", OutcomeV1.STRONG_EXACT),
    ]

    comparison = _summarize(outcomes).comparisons[0]

    assert comparison.difference.value is None
    assert comparison.difference.resamples_used == 0
    assert comparison.discordant_cases == 0
    assert comparison.inconclusive is True


def test_missing_condition_is_reported_not_compared() -> None:
    """A condition that was not run yields a reason, not a comparison."""
    outcomes = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C2", "case-1", "i2", OutcomeV1.STRONG_EXACT),
    ]

    summary = _summarize(outcomes)

    assert len(summary.comparisons) == 1
    assert summary.comparisons[0].first == "C2"
    assert summary.comparisons[0].second == "C1"
    assert summary.not_measured["C4-C2"] == "condition_not_run"
    assert summary.not_measured["C4-C3"] == "condition_not_run"


def test_default_not_measured_and_caller_overrides() -> None:
    """Caller reasons merge on top of the always-present defaults."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    summary = _summarize(outcomes, not_measured={"C3": "no_typed_mutation"})

    assert summary.not_measured["false_ready"] == "no_non_ready_gold"
    assert summary.not_measured["slot_match"] == "no_non_ready_gold"
    assert summary.not_measured["repair_at_1"] == "not_run"
    assert summary.not_measured["C3"] == "no_typed_mutation"


def test_cost_uses_recorded_prices_and_counts_missing_usage() -> None:
    """Cost comes from recorded tokens and the run manifest's prices."""
    outcomes = [
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.STRONG_EXACT,
            prompt_tokens=1000,
            completion_tokens=500,
        ),
        _item(
            "C1",
            "case-2",
            "i2",
            OutcomeV1.STRONG_EXACT,
            prompt_tokens=1000,
            completion_tokens=500,
        ),
    ]
    partial = outcomes + [
        _item(
            "C1",
            "case-3",
            "i3",
            OutcomeV1.STRONG_EXACT,
            completion_tokens=500,
        )
    ]

    priced = _summarize(outcomes, usd_per_million_tokens=_PRICES)
    missing = _summarize(partial, usd_per_million_tokens=_PRICES)
    unpriced = _summarize(outcomes)

    assert priced.conditions["C1"].usage.cost_usd == 0.000689
    assert priced.conditions["C1"].usage.cost_per_item_usd == 0.0003445
    assert priced.conditions["C1"].usage.cost_is_lower_bound is False
    assert missing.conditions["C1"].usage.usage_missing == 1
    assert missing.conditions["C1"].usage.prompt_tokens == 2000
    assert missing.conditions["C1"].usage.completion_tokens == 1000
    assert missing.conditions["C1"].usage.cost_is_lower_bound is True
    assert unpriced.conditions["C1"].usage.cost_usd is None
    assert unpriced.conditions["C1"].usage.cost_per_item_usd is None
    assert unpriced.conditions["C1"].usage.cost_is_lower_bound is False
    assert "it is a lower bound" in render_markdown(missing)
    assert "it is a lower bound" not in render_markdown(priced)


def test_cost_column_prints_the_per_item_figure() -> None:
    """The column is the protocol's cost per item, not the total."""
    outcomes = [
        _item(
            "C1",
            f"case-{index}",
            f"i{index}",
            OutcomeV1.STRONG_EXACT,
            prompt_tokens=1000,
            completion_tokens=500,
        )
        for index in range(2)
    ]

    summary = _summarize(outcomes, usd_per_million_tokens=_PRICES)
    usage = summary.conditions["C1"].usage
    rendered = render_markdown(summary)
    row = next(
        line for line in rendered.splitlines() if line.startswith("| C1 |")
    )

    assert usage.cost_per_item_usd is not None
    assert "| Cost USD/item |" in rendered
    assert f"| {usage.cost_per_item_usd:.6f} |" in row
    assert f"{usage.cost_usd:.6f}" not in row


def test_executable_rate_prints_the_count_it_rests_on() -> None:
    """A rate over executed items says how many there were."""
    outcomes = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-2", "i2", OutcomeV1.SILENT_WRONG),
        _item("C1", "case-3", "i3", OutcomeV1.INVALID),
    ]
    executed = outcomes[:2]

    rendered = render_markdown(_summarize(outcomes))
    row = next(
        line for line in rendered.splitlines() if line.startswith("| C1 |")
    )
    full = render_markdown(_summarize(executed))

    assert "| 0.500 (1/2) [" in row
    assert (
        "Intervals drawn from fewer than 1,000 resamples skip draws whose"
        " denominator is zero: C1 silent-wrong (exec) "
    ) in rendered
    assert "Intervals drawn from fewer than" not in full


def test_comparisons_below_the_discordant_rule_say_so() -> None:
    """Too few cases make every verdict inconclusive before any data."""
    few = render_markdown(
        _summarize(
            [
                _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
                _item("C2", "case-1", "i2", OutcomeV1.SILENT_WRONG),
            ]
        )
    )
    enough = render_markdown(_summarize(_paired(9)))

    assert (
        "With 1 case no comparison can reach 10 discordant cases, so every"
        " verdict is inconclusive by construction."
    ) in few
    assert "by construction" not in enough


def test_provider_cost_is_carried_next_to_the_estimate() -> None:
    """The provider's own figure sits beside the derived estimate."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    carried = _summarize(
        outcomes, provider_reported_usd=0.0431, charged_usd_upper_bound=0.06
    )
    bare = _summarize(outcomes)

    assert carried.provider_reported_usd == 0.0431
    assert carried.charged_usd_upper_bound == 0.06
    assert "Provider reported USD: 0.0431." in render_markdown(carried)
    assert "Charged upper bound: 0.0600." in render_markdown(carried)
    assert bare.provider_reported_usd is None
    assert bare.charged_usd_upper_bound is None
    assert "Provider reported USD" not in render_markdown(bare)


@pytest.mark.parametrize(
    "recorded",
    [
        {"provider_reported_usd": 0.5},
        {"charged_usd_upper_bound": 0.6},
        {"provider_reported_usd": 1e-05},
    ],
)
def test_half_recorded_cost_reads_as_a_measurement(
    recorded: dict[str, float],
) -> None:
    """One recorded figure never prints a Python None or an exponent."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    rendered = render_markdown(_summarize(outcomes, **recorded))
    footnote = next(
        line
        for line in rendered.splitlines()
        if line.startswith("Provider reported USD:")
    )

    assert "None" not in footnote
    assert "e-05" not in footnote
    assert "n/a" in footnote


def test_shortcut_is_compile_valid_and_executed_but_never_exact() -> None:
    """A shortcut ran, so it counts as compile valid and as executed."""
    outcomes = [
        _item("C1", "case-1", "i1", OutcomeV1.SHORTCUT),
        _item("C1", "case-2", "i2", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-3", "i3", OutcomeV1.SILENT_WRONG),
    ]

    summary = _summarize(outcomes)
    condition = summary.conditions["C1"]

    assert condition.outcomes[OutcomeV1.SHORTCUT.value] == 1
    assert condition.compile_valid.value == 1.0
    assert condition.strong_exact.value == pytest.approx(1 / 3, abs=1e-6)
    assert condition.silent_wrong_of_executable.value == pytest.approx(
        1 / 3, abs=1e-6
    )
    assert "(1/3)" in render_markdown(summary)


def test_non_ready_gold_leaves_every_ready_number_alone() -> None:
    """Non-ready cases are their own universe with their own vectors."""
    ready = [
        _item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT),
        _item("C1", "case-2", "i2", OutcomeV1.SILENT_WRONG),
        _item("C1", "case-3", "i3", OutcomeV1.ABSTAINED),
    ]
    non_ready = [
        _item(
            "C1",
            "ask-1",
            "i4",
            OutcomeV1.FALSE_READY,
            gold_status="needs_clarification",
            status_match=False,
            slot_match=False,
        ),
        _item(
            "C1",
            "ask-1",
            "i5",
            OutcomeV1.ABSTAINED,
            gold_status="needs_clarification",
            status_match=True,
            slot_match=True,
        ),
        _item(
            "C1",
            "never-1",
            "i6",
            OutcomeV1.ABSTAINED,
            gold_status="not_expressible",
            status_match=True,
        ),
    ]

    alone = _summarize(ready)
    mixed = _summarize(ready + non_ready)
    before, after = alone.conditions["C1"], mixed.conditions["C1"]

    for name in (
        "compile_valid",
        "strong_exact",
        "silent_wrong_all",
        "silent_wrong_of_executable",
        "over_abstention",
    ):
        assert getattr(after, name) == getattr(before, name), name
    assert (before.false_ready, before.slot_match) == (None, None)
    assert after.false_ready is not None
    assert after.false_ready.value == 0.25
    assert after.slot_match is not None and after.slot_match.value == 0.5
    assert after.outcomes[OutcomeV1.FALSE_READY.value] == 1
    assert mixed.bootstrap["cases"] == alone.bootstrap["cases"] == 3
    assert mixed.bootstrap["non_ready_cases"] == 2
    assert mixed.case_count == 5
    assert "false_ready" in alone.not_measured
    assert "false_ready" not in mixed.not_measured
    assert "slot_match" not in mixed.not_measured
    assert "## Non-ready gold" not in render_markdown(alone)
    assert "| C1 | 0.250" in render_markdown(mixed)


def test_render_markdown_prints_settings_and_spend_deterministically() -> None:
    """Both blocks render from the summary alone, the same way every time."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]
    reported = _summarize(
        outcomes, effective_settings=_settings(), spend=_spend()
    )
    bare = _summarize(outcomes)

    rendered = render_markdown(reported)
    without = render_markdown(bare)

    keys = [
        line.split(" | ")[0].removeprefix("| ")
        for line in rendered.splitlines()
        if line.startswith("| ")
    ]

    assert rendered == render_markdown(reported)
    assert "## Run settings" in rendered
    assert [key for key in keys if key in EffectiveSettingsV1.model_fields] == (
        list(EffectiveSettingsV1.model_fields)
    )
    assert "| requested_model | vendor/model-a |" in rendered
    assert "| served_model_changed | false |" in rendered
    assert "| system_fingerprints | - |" in rendered
    assert "| thinking | honoured |" in rendered
    assert "| seed | uncontrolled |" in rendered
    assert "| seed_requested | 17 |" in rendered
    assert "| served_models_distinct | 1 |" in rendered
    assert "## Spend" in rendered
    assert "Price-derived USD: 0.0007." in rendered
    assert "Provider reported USD: 0.0431." in rendered
    assert "Charged upper bound: 0.0600." in rendered
    assert rendered.count("Provider reported USD") == 1
    assert len(rendered.splitlines()) < 70
    assert "## Run settings" not in without
    assert "## Spend" not in without


def _sections(rendered: str) -> dict[str, list[str]]:
    """Groups every rendered line under the heading it falls beneath."""
    sections: dict[str, list[str]] = {"": []}
    heading = ""
    for line in rendered.splitlines():
        if line.startswith("## "):
            heading = line.removeprefix("## ")
            sections[heading] = []
        else:
            sections[heading].append(line)
    return sections


def test_every_rendered_table_stands_under_its_own_heading() -> None:
    """No section may file another section's table under its own name."""
    reported = _summarize(
        _paired(12), effective_settings=_settings(), spend=_spend()
    )

    sections = _sections(render_markdown(reported))

    assert list(sections) == [
        "",
        "Conditions",
        "Comparisons",
        "Run settings",
        "Spend",
        "Notes",
    ]
    assert any(line.startswith("| C2 |") for line in sections["Conditions"])
    assert any(
        line.startswith("| C4 - C2 |") for line in sections["Comparisons"]
    )
    assert not any("C4 - C2" in line for line in sections["Spend"])
    assert not any("C4 - C2" in line for line in sections["Run settings"])
    assert any(
        line.startswith("| requested_model |")
        for line in sections["Run settings"]
    )
    assert any(line.startswith("Not measured: ") for line in sections["Notes"])
    assert not any(line.startswith("| ") for line in sections["Spend"])


def test_effective_settings_rejects_unbounded_values() -> None:
    """A published provenance block cannot grow with what a router says."""
    with pytest.raises(ValidationError, match="at most 8 items"):
        _settings(served_models=tuple(f"vendor/m-{n}" for n in range(9)))
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        _settings(reasoning_tokens_total=-1)

    with pytest.raises(ValidationError, match="cannot drop a listed value"):
        _settings(
            served_models=("a", "b"),
            served_models_distinct=1,
            served_model_changed=True,
        )

    accepted = _settings(
        served_models=("a", "b"),
        served_models_distinct=2,
        served_model_changed=True,
    )

    assert accepted.served_models == ("a", "b")


def test_provider_metadata_cannot_escape_its_table_cell() -> None:
    """A served model id is data, not a row of the report it is printed in."""
    hostile = 'vendor/a\n| injected | row |\n<script>alert("x")'
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    rendered = render_markdown(
        _summarize(
            outcomes,
            effective_settings=_settings(
                served_models=(hostile, ""),
                served_models_distinct=2,
                served_model_changed=True,
            ),
        )
    )
    rows = [
        line for line in rendered.splitlines() if line.startswith("| served_")
    ]

    assert "| injected | row |" not in rendered
    assert "<script>" not in rendered
    assert len(rows) == 3
    assert rows[0].count("|") == 3


@pytest.mark.parametrize(
    "missing,sentence",
    [
        (1, "usage was missing for 1 item."),
        (3, "usage was missing for 3 items."),
    ],
)
def test_spend_reports_its_lower_bound_in_words(
    missing: int, sentence: str
) -> None:
    """The derived figure says so whenever recorded usage was incomplete."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    bounded = render_markdown(
        _summarize(
            outcomes,
            spend=_spend(
                price_derived_is_lower_bound=True, usage_missing=missing
            ),
        )
    )
    exact = render_markdown(_summarize(outcomes, spend=_spend()))

    assert sentence in bounded
    assert "lower bound: usage was missing" not in exact


def test_spend_names_a_retry_as_a_reason_it_understates() -> None:
    """Tokens an abandoned attempt spent are absent from every census."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    retried = render_markdown(
        _summarize(
            outcomes,
            spend=_spend(price_derived_is_lower_bound=True, retried_items=2),
        )
    )
    both = render_markdown(
        _summarize(
            outcomes,
            spend=_spend(
                price_derived_is_lower_bound=True,
                usage_missing=1,
                retried_items=1,
            ),
        )
    )

    assert "lower bound: 2 items spent tokens on a retry." in retried
    assert "usage was missing" not in retried
    assert (
        "lower bound: usage was missing for 1 item and 1 item spent tokens"
        " on a retry." in both
    )


def test_spend_flags_a_derived_figure_above_the_recorded_charge() -> None:
    """Prices and a charge that disagree are reported, not averaged."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    over = render_markdown(
        _summarize(
            outcomes,
            spend=_spend(
                price_derived_usd=0.09,
                charged_usd_upper_bound=0.06,
                derived_above_charged=True,
            ),
        )
    )
    within = render_markdown(_summarize(outcomes, spend=_spend()))

    assert "above the charged upper bound" in over
    assert "above the charged upper bound" not in within


def test_a_sub_cent_cost_never_rounds_away_to_nothing() -> None:
    """A run too cheap for four decimals still reports what it cost."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    rendered = render_markdown(
        _summarize(outcomes, spend=_spend(price_derived_usd=0.00004))
    )

    assert "Price-derived USD: 0.000040." in rendered
    assert "Price-derived USD: 0.0000." not in rendered


def test_spend_without_recorded_prices_reports_no_derived_figure() -> None:
    """A run whose prices were never recorded reports no derived cost."""
    outcomes = [_item("C1", "case-1", "i1", OutcomeV1.STRONG_EXACT)]

    rendered = render_markdown(
        _summarize(
            outcomes,
            spend=_spend(
                price_derived_usd=None,
                provider_reported_usd=None,
                usage_missing=1,
            ),
        )
    )

    assert "Price-derived USD: n/a." in rendered
    assert "Provider reported USD: n/a." in rendered
    assert "Charged upper bound: 0.0600." in rendered


def test_bounded_codes_cannot_become_object_keys() -> None:
    """A code that could not be a JSON key is refused at the item."""
    hostile = 'bad"key\n<script>'

    with pytest.raises(ValidationError, match="A-Za-z0-9"):
        _item("C1", "case-1", "i1", OutcomeV1.MALFORMED, error_code=hostile)
    with pytest.raises(ValidationError, match="A-Za-z0-9"):
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.MALFORMED,
            provider_error_code=hostile,
        )

    accepted = _item(
        "C1",
        "case-1",
        "i1",
        OutcomeV1.PROVIDER_FAILED,
        error_code="http_error",
        provider_error_code="402",
    )

    assert accepted.error_code == "http_error"


def test_retrieved_gold_fields_cannot_exceed_gold_fields() -> None:
    """An impossible retrieval names its item instead of breaking a rate."""
    with pytest.raises(ValidationError, match="item i9 retrieved 3 gold"):
        _item(
            "C2",
            "case-1",
            "i9",
            OutcomeV1.STRONG_EXACT,
            gold_field_count=1,
            retrieved_gold_field_count=3,
        )


def test_latency_percentiles_exclude_provider_failures() -> None:
    """One socket timeout cannot masquerade as a latency result."""
    outcomes = [
        _item(
            "C1",
            f"case-{index}",
            f"i{index}",
            OutcomeV1.STRONG_EXACT,
            latency_ms=latency,
        )
        for index, latency in enumerate((10.0, 20.0, 30.0, 40.0))
    ] + [
        _item(
            "C1",
            "case-4",
            "i4",
            OutcomeV1.PROVIDER_FAILED,
            latency_ms=120000.0,
        )
    ]
    failed_only = [
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.PROVIDER_FAILED,
            latency_ms=120000.0,
        )
    ]

    usage = _summarize(outcomes).conditions["C1"].usage
    empty = _summarize(failed_only)
    rows = [
        line
        for line in render_markdown(empty).splitlines()
        if line.startswith("| C1 |")
    ]

    assert usage.latency_ms_p50 == 20.0
    assert usage.latency_ms_p95 == 40.0
    assert usage.latency_items == 4
    assert usage.latency_failed_items == 1
    assert "1 provider failure is excluded" in render_markdown(
        _summarize(outcomes)
    )
    assert empty.conditions["C1"].usage.latency_items == 0
    assert empty.conditions["C1"].usage.latency_ms_p50 == 0.0
    assert empty.conditions["C1"].usage.latency_ms_p95 == 0.0
    assert rows[0].endswith("| n/a | n/a |")


def test_gold_field_recall_only_for_lexical_conditions() -> None:
    """Only conditions shown ranked context over gold fields report recall.

    A condition whose every item has no gold field to retrieve is excluded
    from both rates, which leaves the whole record absent.
    """
    outcomes = [
        _item(
            "C2",
            "case-1",
            "i1",
            OutcomeV1.STRONG_EXACT,
            gold_field_count=2,
            retrieved_gold_field_count=1,
            retrieved_field_count=8,
        ),
        _item(
            "C2",
            "case-1",
            "i2",
            OutcomeV1.STRONG_EXACT,
            gold_field_count=2,
            retrieved_gold_field_count=1,
            retrieved_field_count=12,
        ),
        _item("C1", "case-1", "i3", OutcomeV1.STRONG_EXACT),
        _item(
            "C4",
            "case-1",
            "i4",
            OutcomeV1.STRONG_EXACT,
            gold_field_count=0,
            retrieved_gold_field_count=0,
            retrieved_field_count=8,
        ),
    ]

    summary = _summarize(outcomes)
    recall = summary.conditions["C2"].gold_field_recall

    assert recall is not None
    assert recall.mean_recall == 0.5
    assert recall.full_coverage == 0.0
    assert recall.k_min == 8
    assert recall.k_max == 12
    assert summary.conditions["C1"].gold_field_recall is None
    assert summary.conditions["C4"].gold_field_recall is None
    assert "0.500 full 0.000 at k<=12" in render_markdown(summary)


def test_markdown_has_one_row_per_condition_and_no_model_text() -> None:
    """The report is built from the summary, so model text cannot leak."""
    hostile = 'tcp && "|<script>|"'
    outcomes = [
        _item(
            "C1",
            "case-1",
            "i1",
            OutcomeV1.SILENT_WRONG,
            candidate_filter=hostile,
        ),
        _item("C1", "case-2", "i2", OutcomeV1.STRONG_EXACT),
        _item("C2", "case-1", "i3", OutcomeV1.STRONG_EXACT),
        _item("C2", "case-2", "i4", OutcomeV1.STRONG_EXACT),
    ]

    rendered = render_markdown(_summarize(outcomes))
    lines = rendered.splitlines()

    assert hostile not in rendered
    assert "<script>" not in rendered
    assert len(lines) < 40
    assert len([line for line in lines if line.startswith("| C1 |")]) == 1
    assert len([line for line in lines if line.startswith("| C2 |")]) == 1
    assert "inconclusive (fewer than 10 discordant cases)" in rendered
    assert "seed 17, nearest-rank 2.5 and 97.5 percentiles," in rendered
    assert "Compile valid means C1 and C2 were accepted" in rendered
    assert any(line.startswith("Not measured: ") for line in lines)
    assert rendered.endswith("\n")


def test_empty_outcomes_are_rejected() -> None:
    """An empty sequence has no case universe to draw from."""
    with pytest.raises(ValueError, match="at least one item outcome"):
        _summarize([])
