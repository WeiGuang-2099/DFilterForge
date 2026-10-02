"""Rendering a repair round and a repair pool as Markdown reports.

Each report is built from a
:class:`~dfilterforge.repair_summary.RepairSummaryV1` or a
:class:`~dfilterforge.repair_summary.RepairPoolV1` and from nothing else,
so no answer text and no card can reach it; the one recorded
identifier chosen outside this repository, a model id, passes through
:func:`_cell` first. This module reads the aggregation module and is never
read by it.
"""

from __future__ import annotations

import re

from dfilterforge.repair_summary import ArmName
from dfilterforge.repair_summary import ARMS
from dfilterforge.repair_summary import RepairComparisonV1
from dfilterforge.repair_summary import RepairPoolV1
from dfilterforge.repair_summary import RepairSummaryV1
from dfilterforge.score_summary import MIN_DISCORDANT_CASES
from dfilterforge.score_summary import RateV1

_UNSAFE_CELL = re.compile(r"[^A-Za-z0-9 ._/:@-]")
_MAX_CELL_CHARS = 64
_ABSENT = "-"


def _cell(value: str) -> str:
    """Renders one recorded identifier as a cell it cannot escape from."""
    return _UNSAFE_CELL.sub("?", value)[:_MAX_CELL_CHARS] or _ABSENT


def _rate(rate: RateV1) -> str:
    """Renders a rate and its interval to three decimals, or n/a."""
    if rate.value is None:
        return "n/a"
    if rate.low is None or rate.high is None:
        return f"{rate.value:.3f}"
    return f"{rate.value:.3f} [{rate.low:.3f}, {rate.high:.3f}]"


def _bootstrap_line(bootstrap: dict[str, int], drawn: str) -> str:
    """Says how the intervals were drawn."""
    return (
        f"Bootstrap: {bootstrap['resamples']:,} case-level resamples, seed"
        f" {bootstrap['seed']}, nearest-rank 2.5 and 97.5 percentiles,"
        f" drawn from {bootstrap['cases']} ready cases{drawn}."
    )


def _comparison_rows(
    comparisons: tuple[RepairComparisonV1, ...],
) -> list[str]:
    """Renders the comparisons table, the primary comparison first."""
    lines = [
        "| Comparison | Difference | First better | Second better |"
        " Discordant | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for comparison in comparisons:
        verdict = (
            f"inconclusive (fewer than {MIN_DISCORDANT_CASES} discordant"
            f" {comparison.unit})"
            if comparison.inconclusive
            else "conclusive"
        )
        lines.append(
            f"| {comparison.first} - {comparison.second}"
            f" | {_rate(comparison.difference)} | {comparison.first_better}"
            f" | {comparison.second_better} | {comparison.discordant}"
            f" | {verdict} |"
        )
    return lines


def _arm_rows(summary: RepairSummaryV1) -> list[str]:
    """Renders one row per arm of a round."""
    lines = [
        "| Arm | Run | repair@1 | Silent-wrong part | Invalid part |"
        " Repaired | Shortcut | Answer unchanged | Card value reuse |"
        " Latency p50 ms | Charged USD | Provider USD |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        " ---: | ---: |",
    ]
    for arm in summary.arms:
        reuse = (
            _ABSENT if arm.card_value_reuse is None else arm.card_value_reuse
        )
        reported = (
            _ABSENT
            if arm.provider_reported_usd is None
            else f"{arm.provider_reported_usd:.6f}"
        )
        lines.append(
            f"| {arm.arm} | {arm.run} | {_rate(arm.repair_at_1)}"
            f" | {_rate(arm.repair_at_1_silent_wrong)}"
            f" | {_rate(arm.repair_at_1_invalid)}"
            f" | {arm.repaired}/{summary.triggered_items} | {arm.shortcut}"
            f" | {arm.answer_unchanged} | {reuse} | {arm.latency_ms_p50:.0f}"
            f" | {arm.charged_usd_upper_bound:.6f} | {reported} |"
        )
    return lines


def _transition_rows(summary: RepairSummaryV1) -> list[str]:
    """Renders every arm's transitions from the base outcome."""
    lines = [
        "| Arm | Base outcome | Arm outcome | Items |",
        "| --- | --- | --- | ---: |",
    ]
    for arm in summary.arms:
        lines.extend(
            f"| {arm.arm} | {step.first.value} | {step.second.value}"
            f" | {step.items} |"
            for step in arm.transitions
        )
    return lines


def _item_rows(summary: RepairSummaryV1) -> list[str]:
    """Renders every triggered item's outcome in each arm run."""
    arms: list[ArmName] = [arm.arm for arm in summary.arms]
    lines = [
        "| Item | Case | Base outcome | Base outcome now | Card |"
        + "".join(f" {arm} |" for arm in arms),
        "| --- | --- | --- | --- | --- |" + " --- |" * len(arms),
    ]
    for item in summary.items:
        lines.append(
            f"| {item.item_id} | {item.case_id} | {item.base_outcome}"
            f" | {item.base_outcome_now.value} | {item.card_kind} |"
            + "".join(f" {item.outcomes[arm].value} |" for arm in arms)
        )
    return lines


def render_summary(summary: RepairSummaryV1) -> str:
    """Renders one round's summary as the Markdown report committed with it.

    Args:
        summary: The round's summary.

    Returns:
        The report, ending in one newline.
    """
    kinds = summary.card_kinds
    by_outcome = summary.by_base_outcome
    changed = ", ".join(summary.base_outcome_changed) or "none"
    not_run = (
        ", ".join(
            f"{arm}, stopped at the gate ({summary.arms_not_run[arm]})"
            for arm in ARMS
            if arm in summary.arms_not_run
        )
        or "none"
    )
    lines = [
        "# Repair summary",
        "",
        f"Model: {_cell(summary.model_id)}. Split: {summary.split}. Base run:"
        f" {summary.base_run}. Feedback probe: {summary.feedback_probe}.",
        f"Triggered: {summary.triggered_items} items in"
        f" {summary.triggered_cases} cases ({by_outcome['silent_wrong']}"
        f" silent-wrong, {by_outcome['invalid']} invalid). Cards:"
        f" {kinds['frames']} frames, {kinds['error']} error,"
        f" {kinds['none']} none.",
        f"Base manifest {summary.base_run_manifest_sha256[:12]}, base"
        f" outcomes {summary.base_outcomes_sha256[:12]}, plan"
        f" {summary.plan_sha256[:12]}, gold hash {summary.gold_hash[:12]}.",
        _bootstrap_line(summary.bootstrap, " of the base pass"),
        "",
        "## Arms",
        "",
        *_arm_rows(summary),
        "",
        f"Arms not run: {not_run}.",
        "",
        "repair@1 is the triggered items made strong exact over the triggered"
        " items, as summed case shares of each case's C4 items. A shortcut,"
        " a provider failure or any other outcome is not repaired. Answer"
        " unchanged and card value reuse are diagnostics, never outcomes.",
        "",
        "## Comparisons",
        "",
        *_comparison_rows(summary.comparisons),
        "",
        "## Transitions",
        "",
        *_transition_rows(summary),
        "",
        "## Items",
        "",
        *_item_rows(summary),
        "",
        f"Base outcome changed since the plan: {changed}.",
    ]
    return "\n".join(lines) + "\n"


def render_pool(pool: RepairPoolV1) -> str:
    """Renders a pool of rounds as the Markdown report committed with it.

    Args:
        pool: The pooled rounds.

    Returns:
        The report, ending in one newline.
    """
    lines = [
        "# Repair pool",
        "",
        f"Split: {pool.split}. Bases: {len(pool.bases)}. Each drawn case"
        " brings every model's cells.",
        _bootstrap_line(pool.bootstrap, " shared by every base"),
        "",
        "## Bases",
        "",
        "| Run | Model | Triggered items | Triggered cases | Summary |",
        "| --- | --- | ---: | ---: | --- |",
        *(
            f"| {base.run} | {_cell(base.model_id)} | {base.triggered_items}"
            f" | {base.triggered_cases} | {base.summary_sha256[:12]} |"
            for base in pool.bases
        ),
        "",
        "## Arms",
        "",
        "| Arm | repair@1 | Repaired |",
        "| --- | ---: | ---: |",
        *(
            f"| {arm.arm} | {_rate(arm.repair_at_1)}"
            f" | {arm.repaired}/{arm.triggered_items} |"
            for arm in pool.arms
        ),
        "",
        "## Comparisons",
        "",
        *_comparison_rows(pool.comparisons),
    ]
    return "\n".join(lines) + "\n"
