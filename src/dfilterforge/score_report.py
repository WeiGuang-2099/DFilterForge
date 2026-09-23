"""Rendering one scored run as the Markdown report this repository ships.

The report is built from a :class:`~dfilterforge.score_summary.ScoreSummaryV1`
and from nothing else, so no model answer and no captured error text can
reach it. The one class of value that is both published here and chosen by
a provider is a served model id, a provider name and a system fingerprint,
and those pass through :func:`_render_cell` first.

This module reads the aggregation module and is never read by it, so the
numbers and the way they are printed stay separable.
"""

from __future__ import annotations

import re
from typing import cast

from dfilterforge.score_summary import BOOTSTRAP_RESAMPLES
from dfilterforge.score_summary import BOOTSTRAP_SEED
from dfilterforge.score_summary import CONDITION_ORDER
from dfilterforge.score_summary import ConditionSummaryV1
from dfilterforge.score_summary import HIGH_PERCENTILE
from dfilterforge.score_summary import LOW_PERCENTILE
from dfilterforge.score_summary import MIN_DISCORDANT_CASES
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import RateV1
from dfilterforge.score_summary import RecallV1
from dfilterforge.score_summary import ScoreSummaryV1
from dfilterforge.score_summary import SpendV1

_CONDITION_HEADER = (
    "| Condition | Items | Compile valid | Strong exact |"
    " Silent-wrong (all) | Silent-wrong (exec) | Over-abstention |"
    " Provider failed | Malformed | Gold-field recall | Cost USD/item |"
    " Latency p50 ms |"
)
_CONDITION_RULE = (
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    " ---: | ---: | ---: |"
)
_COMPARISON_HEADER = (
    "| Comparison | Metric | Difference | First better | Second better |"
    " Discordant | Verdict |"
)
_COMPARISON_RULE = "| --- | --- | ---: | ---: | ---: | ---: | --- |"
_INCONCLUSIVE = (
    f"inconclusive (fewer than {MIN_DISCORDANT_CASES} discordant cases)"
)
_COMPILE_VALID_NOTE = (
    "Compile valid means C1 and C2 were accepted and run by pinned tshark"
    " only, so an accepted name outside the frozen catalog still counts as"
    " valid; C3 and C4 additionally bind the frozen catalog and check"
    " types, operators and values."
)
_COST_NOTE = (
    "Cost USD/item is derived from recorded token counts and the prices in"
    " the run manifest; it is a lower bound where usage was missing."
)
_CONDITIONS_HEADING = "## Conditions"
_COMPARISONS_HEADING = "## Comparisons"
_SETTINGS_HEADING = "## Run settings"
_SETTINGS_HEADER = "| Setting | Value |"
_SETTINGS_RULE = "| --- | --- |"
_SPEND_HEADING = "## Spend"
_NOTES_HEADING = "## Notes"
# The published row order of the run-settings table. It is written out
# rather than read from the contract at run time so the report cannot
# reorder itself under a field reordering; a test requires it to name
# exactly the fields EffectiveSettingsV1 declares, in that order.
_SETTING_FIELDS: tuple[str, ...] = (
    "requested_model",
    "served_models",
    "served_models_distinct",
    "served_model_changed",
    "providers",
    "providers_distinct",
    "provider_changed",
    "system_fingerprints",
    "system_fingerprints_distinct",
    "reasoning_tokens_total",
    "items_with_reasoning",
    "thinking",
    "thinking_evidence_items",
    "seed_requested",
    "seed",
    "temperature",
    "max_output_tokens",
    "json_mode",
    "provider_order",
    "allow_fallbacks",
    "timeout_seconds",
)
_UNSAFE_CELL = re.compile(r"[^A-Za-z0-9 ._/:@-]")
_MAX_CELL_CHARS = 64
_ABSENT_CELL = "-"


def _render_rate(rate: RateV1, count: str = "") -> str:
    """Renders a rate and its interval to three decimals, or n/a.

    A count, when given, is printed after the value and before the
    interval.
    """
    suffix = f" {count}" if count else ""
    if rate.value is None:
        return f"n/a{suffix}"
    interval = (
        f" [{rate.low:.3f}, {rate.high:.3f}]"
        if rate.low is not None and rate.high is not None
        else ""
    )
    return f"{rate.value:.3f}{suffix}{interval}"


def _render_executable_rate(condition: ConditionSummaryV1) -> str:
    """Renders the executable-only silent-wrong rate with its item count.

    Its denominator is the executed items alone, which can be one item in
    a condition that mostly failed to compile, so the count it rests on is
    printed beside the rate instead of being left for the reader to derive.
    """
    silent = condition.outcomes[OutcomeV1.SILENT_WRONG.value]
    executable = silent + condition.outcomes[OutcomeV1.STRONG_EXACT.value]
    return _render_rate(
        condition.silent_wrong_of_executable, f"({silent}/{executable})"
    )


def _render_recall(recall: RecallV1 | None) -> str:
    """Renders gold-field coverage, or n/a for the no-context conditions."""
    if recall is None:
        return "n/a"
    return (
        f"{recall.mean_recall:.3f} full {recall.full_coverage:.3f}"
        f" at k<={recall.k_max}"
    )


def _condition_rows(summary: ScoreSummaryV1) -> list[str]:
    """Renders one table row per condition present, in protocol order."""
    rows: list[str] = []
    for label in CONDITION_ORDER:
        condition = summary.conditions.get(label)
        if condition is None:
            continue
        usage = condition.usage
        per_item = usage.cost_per_item_usd
        cost = "n/a" if per_item is None else f"{per_item:.6f}"
        latency = (
            "n/a" if usage.latency_items == 0 else f"{usage.latency_ms_p50:.0f}"
        )
        rows.append(
            f"| {condition.condition} | {condition.items}"
            f" | {_render_rate(condition.compile_valid)}"
            f" | {_render_rate(condition.strong_exact)}"
            f" | {_render_rate(condition.silent_wrong_all)}"
            f" | {_render_executable_rate(condition)}"
            f" | {_render_rate(condition.over_abstention)}"
            f" | {condition.outcomes[OutcomeV1.PROVIDER_FAILED.value]}"
            f" | {condition.outcomes[OutcomeV1.MALFORMED.value]}"
            f" | {_render_recall(condition.gold_field_recall)}"
            f" | {cost} | {latency} |"
        )
    return rows


def _render_usd(value: float | None) -> str:
    """Renders a run-level cost, or n/a when none was recorded.

    Four decimals are enough for a charge in dollars, but a cost derived
    from a few thousand tokens can be smaller than that, and a spend this
    repository publishes must never round to a figure that reads as no
    spend at all. Anything under a hundredth of a cent gets six.
    """
    if value is None:
        return "n/a"
    return f"{value:.6f}" if 0 < value < 0.0001 else f"{value:.4f}"


def _render_cell(value: str) -> str:
    """Renders one recorded identifier as a cell it cannot escape from.

    Provider metadata is bounded in length but has no vocabulary, so a
    served model id could otherwise carry a line break, a column
    delimiter or markup into a file this repository publishes. Only the
    characters a model id, a provider slug and a fingerprint are made of
    survive; every other one becomes a question mark.
    """
    safe = _UNSAFE_CELL.sub("?", value)[:_MAX_CELL_CHARS]
    return safe or _ABSENT_CELL


def _render_setting(value: object) -> str:
    """Renders one recorded setting as a single bounded table cell."""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, tuple):
        entries = cast("tuple[object, ...]", value)
        return (
            ", ".join(_render_cell(str(entry)) for entry in entries)
            or _ABSENT_CELL
        )
    return _render_cell(str(value))


def _settings_lines(summary: ScoreSummaryV1) -> list[str]:
    """Renders one row per recorded setting, or nothing without them."""
    settings = summary.effective_settings
    if settings is None:
        return []
    lines = ["", _SETTINGS_HEADING, "", _SETTINGS_HEADER, _SETTINGS_RULE]
    for name in _SETTING_FIELDS:
        rendered = _render_setting(getattr(settings, name))
        lines.append(f"| {name} | {rendered} |")
    return lines


def _lower_bound_reasons(spend: SpendV1) -> list[str]:
    """Names every recorded reason the derived figure understates."""
    reasons: list[str] = []
    if spend.usage_missing:
        missing = spend.usage_missing
        noun = "item" if missing == 1 else "items"
        reasons.append(f"usage was missing for {missing} {noun}")
    if spend.retried_items:
        retried = spend.retried_items
        noun = "item" if retried == 1 else "items"
        reasons.append(f"{retried} {noun} spent tokens on a retry")
    return reasons


def _spend_lines(summary: ScoreSummaryV1) -> list[str]:
    """Renders the derived figure beside the two recorded charges."""
    spend = summary.spend
    if spend is None:
        return []
    lines = [
        "",
        _SPEND_HEADING,
        "",
        (
            f"Price-derived USD: {_render_usd(spend.price_derived_usd)}."
            " Provider reported USD:"
            f" {_render_usd(spend.provider_reported_usd)}. Charged upper"
            f" bound: {_render_usd(spend.charged_usd_upper_bound)}."
        ),
    ]
    reasons = _lower_bound_reasons(spend)
    if spend.price_derived_is_lower_bound and reasons:
        lines.append(
            "Price-derived cost is a lower bound: "
            + " and ".join(reasons)
            + "."
        )
    if spend.derived_above_charged:
        lines.append(
            "Price-derived cost is above the charged upper bound, so the"
            " recorded prices and the recorded charge disagree."
        )
    return lines


def _footnotes(summary: ScoreSummaryV1) -> list[str]:
    """Renders the fixed footnote block below the condition table.

    The two recorded charges appear here only when no Spend section
    follows, so a summary that carries one never prints them twice.
    """
    lines = [_COMPILE_VALID_NOTE]
    conditions = summary.conditions.values()
    failed = sum(item.usage.latency_failed_items for item in conditions)
    if failed:
        subject = "failure is" if failed == 1 else "failures are"
        lines.append(
            f"Latency p50 covers completed items only; {failed} provider"
            f" {subject} excluded and counted in the Provider failed"
            " column."
        )
    if any(item.usage.cost_is_lower_bound for item in conditions):
        lines.append(_COST_NOTE)
    thin = _thin_intervals(summary)
    if thin:
        lines.append(
            f"Intervals drawn from fewer than {BOOTSTRAP_RESAMPLES:,}"
            " resamples skip draws whose denominator is zero: "
            + "; ".join(thin)
            + "."
        )
    if summary.spend is None and (
        summary.provider_reported_usd is not None
        or summary.charged_usd_upper_bound is not None
    ):
        lines.append(
            "Provider reported USD:"
            f" {_render_usd(summary.provider_reported_usd)}. Charged upper"
            f" bound: {_render_usd(summary.charged_usd_upper_bound)}."
        )
    return lines


def _thin_intervals(summary: ScoreSummaryV1) -> list[str]:
    """Names every printed interval drawn from fewer than all resamples."""
    thin: list[str] = []
    for label in CONDITION_ORDER:
        condition = summary.conditions.get(label)
        if condition is None:
            continue
        rates = (
            ("compile valid", condition.compile_valid),
            ("strong exact", condition.strong_exact),
            ("silent-wrong (all)", condition.silent_wrong_all),
            ("silent-wrong (exec)", condition.silent_wrong_of_executable),
            ("over-abstention", condition.over_abstention),
        )
        for name, rate in rates:
            if rate.low is None or rate.resamples_used >= BOOTSTRAP_RESAMPLES:
                continue
            thin.append(f"{label} {name} {rate.resamples_used:,}")
    return thin


def _comparison_lines(summary: ScoreSummaryV1) -> list[str]:
    """Renders the comparison table, or nothing when no pair was run."""
    if not summary.comparisons:
        return []
    lines = [
        "",
        _COMPARISONS_HEADING,
        "",
        _COMPARISON_HEADER,
        _COMPARISON_RULE,
    ]
    for comparison in summary.comparisons:
        verdict = _INCONCLUSIVE if comparison.inconclusive else "conclusive"
        lines.append(
            f"| {comparison.first} - {comparison.second} | strong exact"
            f" | {_render_rate(comparison.difference)}"
            f" | {comparison.first_better_cases}"
            f" | {comparison.second_better_cases}"
            f" | {comparison.discordant_cases} | {verdict} |"
        )
    cases = summary.bootstrap["cases"]
    if cases < MIN_DISCORDANT_CASES:
        noun = "case" if cases == 1 else "cases"
        lines.append("")
        lines.append(
            f"With {cases} {noun} no comparison can reach"
            f" {MIN_DISCORDANT_CASES} discordant cases, so every verdict is"
            " inconclusive by construction."
        )
    return lines


def render_markdown(summary: ScoreSummaryV1) -> str:
    """Renders the summary as Markdown that cannot contain model text.

    Args:
        summary: The aggregated run summary.

    Returns:
        At most seventy lines of Markdown ending in a newline.

    Every table is published under a heading of its own, so no section
    can file another section's table under its own name in a rendered
    document or in a table of contents.
    """
    lines = [
        "# Score summary",
        "",
        (
            f"Model: {summary.model_id}. Split: {summary.split}."
            f" Run: {summary.run}. Cases: {summary.case_count},"
            f" items: {summary.item_count}."
        ),
        (
            f"Gold hash: {summary.gold_hash[:12]}. Bootstrap:"
            f" {BOOTSTRAP_RESAMPLES:,} case-level resamples, seed"
            f" {BOOTSTRAP_SEED}, nearest-rank"
            f" {LOW_PERCENTILE * 100:.1f} and"
            f" {HIGH_PERCENTILE * 100:.1f} percentiles,"
            " index vectors shared by every metric, drawn from"
            f" {summary.bootstrap['cases']} cases."
        ),
        "",
        _CONDITIONS_HEADING,
        "",
        _CONDITION_HEADER,
        _CONDITION_RULE,
    ]
    lines.extend(_condition_rows(summary))
    lines.append("")
    lines.extend(_footnotes(summary))
    lines.extend(_comparison_lines(summary))
    lines.extend(_settings_lines(summary))
    lines.extend(_spend_lines(summary))
    lines.append("")
    lines.append(_NOTES_HEADING)
    lines.append("")
    lines.append(
        "Not measured: "
        + "; ".join(
            f"{key} ({summary.not_measured[key]})"
            for key in sorted(summary.not_measured)
        )
    )
    lines.append("")
    lines.append("Files: summary.json, outcomes.jsonl, receipts/.")
    return "\n".join(lines) + "\n"
