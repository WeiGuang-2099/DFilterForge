"""Pure aggregation of scored items into the protocol's per-condition metrics.

This module executes nothing and reads nothing from disk; it is the only
place where paraphrase averaging, case-level rates and the seeded bootstrap
are defined. A bootstrap interval is reproducible only for an unchanged case
universe: the index vectors are drawn from the number of distinct case_id
values in the whole outcome sequence, so adding a condition that covers a
case no other condition covers changes every interval in the summary.
``bootstrap.cases`` is recorded next to the numbers for exactly that reason.

How the result is printed lives in :mod:`dfilterforge.score_report`, which
reads this module and is never read by it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
import math
import random
import re
from typing import Literal, TypeAlias

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from dfilterforge.intent_ir import FrozenModel

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 17
MIN_DISCORDANT_CASES = 10
MAX_EFFECTIVE_VALUES = 8
LOW_PERCENTILE = 0.025
HIGH_PERCENTILE = 0.975

ConditionLabel = Literal["C1", "C2", "C3", "C4"]
ThinkingState: TypeAlias = Literal["honoured", "not_honoured", "uncontrolled"]
CONDITION_ORDER: tuple[ConditionLabel, ...] = ("C1", "C2", "C3", "C4")
COMPARISONS: tuple[tuple[ConditionLabel, ConditionLabel], ...] = (
    ("C4", "C2"),
    ("C2", "C1"),
    ("C4", "C3"),
)

_RATE_DIGITS = 6
_COST_DIGITS = 8
_BUDGET_EXHAUSTED = "budget_exhausted"
_EMPTY_CONTENT = "empty_content"
_LENGTH_FINISH = "length"
_FINISH_REASONS: frozenset[str] = frozenset(
    {
        "stop",
        "length",
        "content_filter",
        "tool_calls",
        "function_call",
        "error",
    }
)
_OTHER_FINISH_REASON = "other"
_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class OutcomeV1(StrEnum):
    """The six mutually exclusive verdicts one scored item can receive."""

    PROVIDER_FAILED = "provider_failed"
    MALFORMED = "malformed"
    ABSTAINED = "abstained"
    INVALID = "invalid"
    SILENT_WRONG = "silent_wrong"
    STRONG_EXACT = "strong_exact"


_EXECUTABLE = frozenset({OutcomeV1.SILENT_WRONG, OutcomeV1.STRONG_EXACT})
_STRONG_EXACT = frozenset({OutcomeV1.STRONG_EXACT})
_SILENT_WRONG = frozenset({OutcomeV1.SILENT_WRONG})
_ABSTAINED = frozenset({OutcomeV1.ABSTAINED})


class ItemOutcomeV1(FrozenModel):
    """One scored generation, already judged against gold.

    ``candidate_filter`` is the only field that can hold model text; it is
    never rendered into Markdown, because the report module reads a
    :class:`ScoreSummaryV1` and nothing else.

    ``error_code`` and ``provider_error_code`` become object keys in the
    summary this repository publishes, so both are bounded here by the same
    pattern the completion contract applies, rather than trusting the
    caller to have applied it; ``http_status`` is bounded by the 100 to 999
    integer range. The pattern is deliberately duplicated because this
    module stays free of the completion contract. The only other validator
    is the cross-field check that a case cannot retrieve more gold fields
    than it has, which names the offending ``item_id`` instead of failing
    later inside an aggregate.
    """

    schema_version: Literal["item-outcome/1.0"] = "item-outcome/1.0"
    condition: ConditionLabel
    item_id: str
    case_id: str
    outcome: OutcomeV1
    error_code: str | None = None
    http_status: int | None = Field(default=None, ge=100, le=999, strict=True)
    provider_error_code: str | None = None
    abstention_status: (
        Literal["needs_clarification", "not_expressible"] | None
    ) = None
    finish_reason: str | None = None
    candidate_filter: str | None = None
    probe_exact: tuple[bool, ...] = ()
    packet_set_hash: str | None = None
    gold_field_count: int = Field(ge=0)
    retrieved_field_count: int = Field(default=0, ge=0)
    retrieved_gold_field_count: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)

    @field_validator("error_code", "provider_error_code")
    @classmethod
    def _bounded_code(cls, value: str | None) -> str | None:
        """Rejects a code that could not be a key in a published file."""
        if value is not None and not _CODE_PATTERN.fullmatch(value):
            raise ValueError("code must match ^[A-Za-z0-9_.-]{1,64}$")
        return value

    @model_validator(mode="after")
    def _retrieval_fits_the_gold_set(self) -> ItemOutcomeV1:
        """Rejects retrieving more gold fields than the case has."""
        hits = self.retrieved_gold_field_count
        if hits is not None and hits > self.gold_field_count:
            raise ValueError(
                f"item {self.item_id} retrieved {hits} gold fields of"
                f" {self.gold_field_count}"
            )
        return self


class RateV1(FrozenModel):
    """A case-level rate with its seeded bootstrap interval."""

    value: float | None
    low: float | None = None
    high: float | None = None
    resamples_used: int = Field(default=0, ge=0, le=BOOTSTRAP_RESAMPLES)


class UsageV1(FrozenModel):
    """Token, cost and latency accounting for one condition."""

    usage_missing: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    cost_usd: float | None = None
    cost_per_item_usd: float | None = None
    cost_is_lower_bound: bool = False
    latency_items: int = Field(ge=0)
    latency_failed_items: int = Field(ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)


class RecallV1(FrozenModel):
    """Gold-field coverage of the ranked context shown to the model."""

    k_min: int = Field(ge=0)
    k_max: int = Field(ge=0)
    mean_recall: float = Field(ge=0, le=1)
    full_coverage: float = Field(ge=0, le=1)


class ConditionSummaryV1(FrozenModel):
    """Every reported number for one of the four conditions.

    ``outcomes`` always holds one zero-filled key per :class:`OutcomeV1`
    value. ``error_codes`` is the complete per-code census, and
    ``failure_details`` is a pure refinement of it that keeps an HTTP 402
    apart from a 429; an item with neither a status nor a provider code
    contributes to ``error_codes`` alone. ``finish_reasons`` is bucketed
    because the provider's finish reason is bounded in length but has no
    vocabulary, and an unbucketed count would let a broken or hostile
    provider choose object keys in a file this repository publishes.
    """

    condition: ConditionLabel
    items: int = Field(ge=1)
    cases: int = Field(ge=1)
    outcomes: dict[str, int]
    error_codes: dict[str, int]
    failure_details: dict[str, int]
    finish_reasons: dict[str, int]
    compile_valid: RateV1
    strong_exact: RateV1
    silent_wrong_all: RateV1
    silent_wrong_of_executable: RateV1
    over_abstention: RateV1
    gold_field_recall: RecallV1 | None = None
    usage: UsageV1


class ComparisonV1(FrozenModel):
    """A paired case-level comparison between two conditions."""

    first: ConditionLabel
    second: ConditionLabel
    metric: Literal["strong_exact"] = "strong_exact"
    difference: RateV1
    first_better_cases: int = Field(ge=0)
    second_better_cases: int = Field(ge=0)
    discordant_cases: int = Field(ge=0)
    inconclusive: bool


class EffectiveSettingsV1(FrozenModel):
    """What the endpoint served, beside what the run asked it for.

    Every served value is collected from the records a provider actually
    answered, so a run that silently routed to another provider, or that
    ignored the thinking switch, cannot read the same as one that did
    not. The two changed flags compare what was served against what was
    asked for, not merely against each other: a run that was served one
    substituted model id for every single request reports the
    substitution rather than reporting no change. ``seed`` is always
    ``uncontrolled``: no reply echoes a seed, so the requested value is
    reported as a request and nothing more.

    The served lists are bounded because they hold provider-chosen
    strings. The derivation truncates and publishes the matching
    ``_distinct`` count beside the list, so a router that answered with
    nine model ids reports nine and prints eight rather than looking
    like one that answered with eight.
    """

    requested_model: str
    served_models: tuple[str, ...] = Field(max_length=MAX_EFFECTIVE_VALUES)
    served_models_distinct: int = Field(ge=0)
    served_model_changed: bool
    providers: tuple[str, ...] = Field(max_length=MAX_EFFECTIVE_VALUES)
    providers_distinct: int = Field(ge=0)
    provider_changed: bool
    system_fingerprints: tuple[str, ...] = Field(
        max_length=MAX_EFFECTIVE_VALUES
    )
    system_fingerprints_distinct: int = Field(ge=0)
    reasoning_tokens_total: int = Field(ge=0)
    items_with_reasoning: int = Field(ge=0)
    thinking: ThinkingState
    thinking_evidence_items: int = Field(ge=0)
    seed_requested: int | None = None
    seed: Literal["uncontrolled"] = "uncontrolled"
    temperature: float
    max_output_tokens: int = Field(ge=1)
    json_mode: bool
    provider_order: tuple[str, ...] = ()
    allow_fallbacks: bool | None = None
    timeout_seconds: float

    @model_validator(mode="after")
    def validate_distinct_counts(self) -> "EffectiveSettingsV1":
        """Requires every count to cover the list it was truncated from."""
        for values, count in (
            (self.served_models, self.served_models_distinct),
            (self.providers, self.providers_distinct),
            (self.system_fingerprints, self.system_fingerprints_distinct),
        ):
            if count < len(values):
                raise ValueError("a distinct count cannot drop a listed value")
        return self


class SpendV1(FrozenModel):
    """What the run cost, derived and as the provider reported it.

    ``price_derived_usd`` applies the prices recorded with the run to the
    run's whole recorded token census, by the same formula and over the
    same census as the per-condition figures, and is absent when no
    prices were recorded. That census covers the one final reply each
    item kept, so the derived figure understates the run for two
    reasons, not one: an item that recorded no usage contributes no
    tokens, and an item that was retried contributes only its last
    attempt. Both set ``price_derived_is_lower_bound``.

    ``derived_above_charged`` is the one reconciliation this record can
    perform on its own. A derived figure above the charge recorded with
    the run means the recorded prices and the recorded charge disagree,
    and neither reads as the cost of the run until that is settled.
    """

    price_derived_usd: float | None = Field(default=None, ge=0.0)
    price_derived_is_lower_bound: bool = False
    usage_missing: int = Field(ge=0)
    retried_items: int = Field(ge=0)
    provider_reported_usd: float | None = Field(default=None, ge=0.0)
    charged_usd_upper_bound: float | None = Field(default=None, ge=0.0)
    derived_above_charged: bool = False


class ScoreSummaryV1(FrozenModel):
    """The whole reported result of one scored run."""

    schema_version: Literal["score-summary/1.0"] = "score-summary/1.0"
    run: str
    model_id: str
    split: str
    case_count: int = Field(ge=1)
    item_count: int = Field(ge=1)
    gold_hash: str
    capture_hashes: dict[str, str]
    batch_hashes: dict[str, str]
    bootstrap: dict[str, int]
    conditions: dict[str, ConditionSummaryV1]
    comparisons: tuple[ComparisonV1, ...] = ()
    provider_reported_usd: float | None = Field(default=None, ge=0)
    charged_usd_upper_bound: float | None = Field(default=None, ge=0)
    effective_settings: EffectiveSettingsV1 | None = None
    spend: SpendV1 | None = None
    not_measured: dict[str, str]


_DEFAULT_NOT_MEASURED: dict[str, str] = {
    "false_ready": "no_non_ready_gold",
    "slot_match": "no_non_ready_gold",
    "repair_at_1": "not_run",
}


def _draw_indices(n: int) -> tuple[tuple[int, ...], ...]:
    """Draws the resample index vectors shared by every reported number.

    The vectors depend only on ``n``, so the same seed reproduces the same
    intervals if and only if the case universe is unchanged. Reusing one
    set of vectors for every metric, condition and comparison is what makes
    the comparisons paired and keeps an existing condition's interval
    unchanged when a later condition covering the same case ids is added.

    Args:
        n: The number of distinct case ids in the whole outcome sequence.

    Returns:
        ``BOOTSTRAP_RESAMPLES`` vectors of ``n`` case indices each.
    """
    rng = random.Random(BOOTSTRAP_SEED)
    return tuple(
        tuple(int(rng.random() * n) for _ in range(n))
        for _ in range(BOOTSTRAP_RESAMPLES)
    )


def _nearest_rank(ordered: Sequence[float], percentile: float) -> float:
    """Returns a nearest-rank percentile of an already sorted sequence."""
    rank = math.ceil(percentile * len(ordered)) - 1
    return ordered[min(len(ordered) - 1, max(0, rank))]


def _bounds(statistics: list[float]) -> tuple[float | None, float | None, int]:
    """Returns the 2.5 and 97.5 percentiles of the surviving resamples."""
    if not statistics:
        return (None, None, 0)
    ordered = sorted(statistics)
    return (
        round(_nearest_rank(ordered, LOW_PERCENTILE), _RATE_DIGITS),
        round(_nearest_rank(ordered, HIGH_PERCENTILE), _RATE_DIGITS),
        len(ordered),
    )


def _case_means(pairs: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Averages per-item values inside each case."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for case_id, value in pairs:
        totals[case_id] = totals.get(case_id, 0.0) + value
        counts[case_id] = counts.get(case_id, 0) + 1
    return {key: total / counts[key] for key, total in totals.items()}


def _case_values(
    items: Sequence[ItemOutcomeV1], wanted: frozenset[OutcomeV1]
) -> dict[str, float]:
    """Averages an outcome indicator inside each case.

    Every item of a case is in that case's denominator, including provider
    failures, malformed replies and abstentions.
    """
    return _case_means(
        [
            (item.case_id, 1.0 if item.outcome in wanted else 0.0)
            for item in items
        ]
    )


def _interval(
    values: Mapping[str, float],
    vectors: tuple[tuple[int, ...], ...],
    case_ids: tuple[str, ...],
) -> tuple[float | None, float | None, int]:
    """Bootstraps the mean of per-case values over the shared vectors."""
    statistics: list[float] = []
    for vector in vectors:
        drawn = [
            values[case_ids[index]]
            for index in vector
            if case_ids[index] in values
        ]
        if drawn:
            statistics.append(sum(drawn) / len(drawn))
    return _bounds(statistics)


def _rate(
    values: Mapping[str, float],
    vectors: tuple[tuple[int, ...], ...],
    case_ids: tuple[str, ...],
) -> RateV1:
    """Averages per-case values and attaches their bootstrap interval."""
    if not values:
        return RateV1(value=None)
    low, high, used = _interval(values, vectors, case_ids)
    return RateV1(
        value=round(sum(values.values()) / len(values), _RATE_DIGITS),
        low=low,
        high=high,
        resamples_used=used,
    )


def _ratio_rate(
    numerators: Mapping[str, float],
    denominators: Mapping[str, float],
    vectors: tuple[tuple[int, ...], ...],
    case_ids: tuple[str, ...],
) -> RateV1:
    """Divides summed case means, skipping resamples with no denominator."""
    statistics: list[float] = []
    for vector in vectors:
        numerator = 0.0
        denominator = 0.0
        for index in vector:
            case_id = case_ids[index]
            if case_id in denominators:
                numerator += numerators.get(case_id, 0.0)
                denominator += denominators[case_id]
        if denominator > 0:
            statistics.append(numerator / denominator)
    low, high, used = _bounds(statistics)
    total = sum(denominators.values())
    value = (
        None
        if total <= 0
        else round(sum(numerators.values()) / total, _RATE_DIGITS)
    )
    return RateV1(value=value, low=low, high=high, resamples_used=used)


def _outcome_counts(items: Sequence[ItemOutcomeV1]) -> dict[str, int]:
    """Counts every outcome, keeping all six keys present."""
    counts = {outcome.value: 0 for outcome in OutcomeV1}
    for item in items:
        counts[item.outcome.value] += 1
    return counts


def _error_codes(items: Sequence[ItemOutcomeV1]) -> dict[str, int]:
    """Counts error codes and flags budget exhaustion separately."""
    counts: dict[str, int] = {}
    for item in items:
        if item.error_code is None:
            continue
        counts[item.error_code] = counts.get(item.error_code, 0) + 1
        if (
            item.outcome is OutcomeV1.PROVIDER_FAILED
            and item.error_code == _EMPTY_CONTENT
            and item.finish_reason == _LENGTH_FINISH
        ):
            counts[_BUDGET_EXHAUSTED] = counts.get(_BUDGET_EXHAUSTED, 0) + 1
    return counts


def _failure_details(items: Sequence[ItemOutcomeV1]) -> dict[str, int]:
    """Refines each error code by HTTP status and provider error code."""
    counts: dict[str, int] = {}
    for item in items:
        if item.error_code is None:
            continue
        keys: list[str] = []
        if item.http_status is not None:
            keys.append(f"{item.error_code}:http_{item.http_status}")
        if item.provider_error_code is not None:
            keys.append(
                f"{item.error_code}:provider_{item.provider_error_code}"
            )
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _finish_reasons(items: Sequence[ItemOutcomeV1]) -> dict[str, int]:
    """Counts finish reasons, bucketing anything off the known list."""
    counts: dict[str, int] = {}
    for item in items:
        if item.finish_reason is None:
            continue
        key = (
            item.finish_reason
            if item.finish_reason in _FINISH_REASONS
            else _OTHER_FINISH_REASON
        )
        counts[key] = counts.get(key, 0) + 1
    return counts


def _recall(items: Sequence[ItemOutcomeV1]) -> RecallV1 | None:
    """Averages gold-field coverage inside each case, or returns None."""
    measured = [
        item for item in items if item.retrieved_gold_field_count is not None
    ]
    if not measured:
        return None
    recall_pairs: list[tuple[str, float]] = []
    cover_pairs: list[tuple[str, float]] = []
    for item in measured:
        hits = item.retrieved_gold_field_count
        if hits is None or item.gold_field_count == 0:
            continue
        recall_pairs.append((item.case_id, hits / item.gold_field_count))
        cover_pairs.append(
            (item.case_id, 1.0 if hits == item.gold_field_count else 0.0)
        )
    if not recall_pairs:
        return None
    recalls = _case_means(recall_pairs)
    covered = _case_means(cover_pairs)
    widths = [item.retrieved_field_count for item in items]
    return RecallV1(
        k_min=min(widths),
        k_max=max(widths),
        mean_recall=round(sum(recalls.values()) / len(recalls), _RATE_DIGITS),
        full_coverage=round(sum(covered.values()) / len(covered), _RATE_DIGITS),
    )


def token_census(items: Sequence[ItemOutcomeV1]) -> tuple[int, int, int]:
    """Sums the recorded tokens and counts the items that recorded none.

    An item counts only when both token fields are present, because a
    provider that omits its usage block omits the whole block.

    Args:
        items: The scored items to census, in any order.

    Returns:
        Prompt tokens, completion tokens, and the number of items whose
        usage was missing.
    """
    complete = [
        item
        for item in items
        if item.prompt_tokens is not None and item.completion_tokens is not None
    ]
    return (
        sum(item.prompt_tokens or 0 for item in complete),
        sum(item.completion_tokens or 0 for item in complete),
        len(items) - len(complete),
    )


def derived_cost(
    prompt_tokens: int,
    completion_tokens: int,
    prices: tuple[float, float] | None,
) -> float | None:
    """Derives one USD figure from recorded tokens and recorded prices.

    This is the only definition of the price formula, so a per-condition
    figure and a whole-run figure can never drift apart.

    Args:
        prompt_tokens: Recorded input tokens.
        completion_tokens: Recorded output tokens.
        prices: Input and output USD per million tokens, or None when the
            run recorded no prices.

    Returns:
        The derived cost, or None when no prices were recorded.
    """
    if prices is None:
        return None
    return round(
        prompt_tokens / 1e6 * prices[0] + completion_tokens / 1e6 * prices[1],
        _COST_DIGITS,
    )


def _usage(
    items: Sequence[ItemOutcomeV1], prices: tuple[float, float] | None
) -> UsageV1:
    """Sums recorded tokens, derives cost and splits latency from failures.

    The percentiles cover completed items only: a provider failure records
    the client's socket bound, so a single timeout would otherwise dominate
    a sixteen-item condition and read as a latency result.
    """
    prompt_tokens, completion_tokens, missing = token_census(items)
    cost_usd = derived_cost(prompt_tokens, completion_tokens, prices)
    cost_per_item = (
        None if cost_usd is None else round(cost_usd / len(items), _COST_DIGITS)
    )
    latencies = sorted(
        item.latency_ms
        for item in items
        if item.outcome is not OutcomeV1.PROVIDER_FAILED
    )
    return UsageV1(
        usage_missing=missing,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        cost_per_item_usd=cost_per_item,
        cost_is_lower_bound=cost_usd is not None and missing > 0,
        latency_items=len(latencies),
        latency_failed_items=len(items) - len(latencies),
        latency_ms_p50=_nearest_rank(latencies, 0.50) if latencies else 0.0,
        latency_ms_p95=_nearest_rank(latencies, 0.95) if latencies else 0.0,
    )


def _condition_summary(
    condition: ConditionLabel,
    items: Sequence[ItemOutcomeV1],
    vectors: tuple[tuple[int, ...], ...],
    case_ids: tuple[str, ...],
    prices: tuple[float, float] | None,
) -> ConditionSummaryV1:
    """Reduces one condition's items to its reported numbers."""
    executable = _case_values(items, _EXECUTABLE)
    strong = _case_values(items, _STRONG_EXACT)
    silent = _case_values(items, _SILENT_WRONG)
    abstained = _case_values(items, _ABSTAINED)
    return ConditionSummaryV1(
        condition=condition,
        items=len(items),
        cases=len({item.case_id for item in items}),
        outcomes=_outcome_counts(items),
        error_codes=_error_codes(items),
        failure_details=_failure_details(items),
        finish_reasons=_finish_reasons(items),
        compile_valid=_rate(executable, vectors, case_ids),
        strong_exact=_rate(strong, vectors, case_ids),
        silent_wrong_all=_rate(silent, vectors, case_ids),
        silent_wrong_of_executable=_ratio_rate(
            silent, executable, vectors, case_ids
        ),
        over_abstention=_rate(abstained, vectors, case_ids),
        gold_field_recall=_recall(items),
        usage=_usage(items, prices),
    )


def _compare(
    pair: tuple[ConditionLabel, ConditionLabel],
    grouped: Mapping[ConditionLabel, Sequence[ItemOutcomeV1]],
    vectors: tuple[tuple[int, ...], ...],
    case_ids: tuple[str, ...],
) -> ComparisonV1:
    """Compares strong-exact case means over the cases both conditions cover."""
    first, second = pair
    first_values = _case_values(grouped[first], _STRONG_EXACT)
    second_values = _case_values(grouped[second], _STRONG_EXACT)
    shared = sorted(set(first_values) & set(second_values))
    differences = {
        case_id: first_values[case_id] - second_values[case_id]
        for case_id in shared
    }
    first_better = sum(1 for value in differences.values() if value > 0)
    second_better = sum(1 for value in differences.values() if value < 0)
    discordant = first_better + second_better
    return ComparisonV1(
        first=first,
        second=second,
        difference=_rate(differences, vectors, case_ids),
        first_better_cases=first_better,
        second_better_cases=second_better,
        discordant_cases=discordant,
        inconclusive=discordant < MIN_DISCORDANT_CASES,
    )


def _comparisons(
    grouped: Mapping[ConditionLabel, Sequence[ItemOutcomeV1]],
    vectors: tuple[tuple[int, ...], ...],
    case_ids: tuple[str, ...],
) -> tuple[tuple[ComparisonV1, ...], dict[str, str]]:
    """Builds every runnable comparison and reports the missing pairs."""
    comparisons: list[ComparisonV1] = []
    missing: dict[str, str] = {}
    for pair in COMPARISONS:
        if pair[0] not in grouped or pair[1] not in grouped:
            missing[f"{pair[0]}-{pair[1]}"] = "condition_not_run"
            continue
        comparisons.append(_compare(pair, grouped, vectors, case_ids))
    return tuple(comparisons), missing


# pylint: disable-next=too-many-arguments,too-many-locals
def summarize(
    outcomes: Sequence[ItemOutcomeV1],
    *,
    run: str,
    model_id: str,
    split: str,
    gold_hash: str,
    capture_hashes: Mapping[str, str],
    batch_hashes: Mapping[str, str],
    usd_per_million_tokens: tuple[float, float] | None = None,
    provider_reported_usd: float | None = None,
    charged_usd_upper_bound: float | None = None,
    effective_settings: EffectiveSettingsV1 | None = None,
    spend: SpendV1 | None = None,
    not_measured: Mapping[str, str] | None = None,
) -> ScoreSummaryV1:
    """Aggregates scored items into the protocol's reported summary.

    Args:
        outcomes: Every scored item of the run, in any order.
        run: The run identifier recorded beside the numbers.
        model_id: The requested model identifier.
        split: The evaluation split the items came from.
        gold_hash: Content hash of the gold set the items were scored on.
        capture_hashes: Capture file name to content hash.
        batch_hashes: Prepared batch name to content hash.
        usd_per_million_tokens: Input and output prices from the run
            manifest, or None to leave cost unreported.
        provider_reported_usd: The provider's own cost figure, if recorded.
        charged_usd_upper_bound: The run's charged upper bound, if recorded.
        effective_settings: What the endpoint served, derived by the
            caller from the stored completions and the run manifest, or
            None when the run recorded neither.
        spend: The reconciled spend, derived by the caller, or None when
            the run recorded no manifest. Neither block is computed here,
            so this module stays free of the completion contract.
        not_measured: Extra skipped metrics merged over the defaults.

    Returns:
        The frozen summary for the whole run.

    Raises:
        ValueError: If ``outcomes`` is empty.
    """
    if not outcomes:
        raise ValueError("at least one item outcome is required")
    case_ids = tuple(sorted({item.case_id for item in outcomes}))
    vectors = _draw_indices(len(case_ids))
    grouped: dict[ConditionLabel, list[ItemOutcomeV1]] = {}
    for item in outcomes:
        grouped.setdefault(item.condition, []).append(item)
    conditions = {
        label: _condition_summary(
            label,
            grouped[label],
            vectors,
            case_ids,
            usd_per_million_tokens,
        )
        for label in CONDITION_ORDER
        if label in grouped
    }
    comparisons, missing = _comparisons(grouped, vectors, case_ids)
    reasons = dict(_DEFAULT_NOT_MEASURED)
    reasons.update(missing)
    reasons.update(not_measured or {})
    return ScoreSummaryV1(
        run=run,
        model_id=model_id,
        split=split,
        case_count=len(case_ids),
        item_count=len(outcomes),
        gold_hash=gold_hash,
        capture_hashes=dict(capture_hashes),
        batch_hashes=dict(batch_hashes),
        bootstrap={
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "cases": len(case_ids),
            "min_discordant_cases": MIN_DISCORDANT_CASES,
        },
        conditions=conditions,
        comparisons=comparisons,
        provider_reported_usd=provider_reported_usd,
        charged_usd_upper_bound=charged_usd_upper_bound,
        effective_settings=effective_settings,
        spend=spend,
        not_measured=reasons,
    )
