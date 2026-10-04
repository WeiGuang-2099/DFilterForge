"""Pure aggregation of a repair round into its published numbers.

``repair-summary/1.0`` is one base pass's round and ``repair-pool/1.0`` the
rounds of several models on one split. This module defines both and derives
them from values already read; it reads nothing from disk and executes
nothing, so every number is testable by hand.
:mod:`dfilterforge.repair_round` reads and checks the committed runs.

repair@1 is the protocol's ratio estimator, the one silent-wrong over
compile-valid items uses (:func:`dfilterforge.score_summary.ratio_rate`):
each ready case's repaired share of its C4 items, summed over the cases,
over the same sum of its triggered share, with the interval from the base
pass's own ready-case vectors (:func:`dfilterforge.score_summary.draw_indices`
over its sorted ready cases). An item is repaired only when its arm outcome
is strong exact. The silent-wrong and invalid parts use the same formula
over their own items. Each pair of arms is compared on the case shares:
the difference is the ratio estimator over their differences, and the
cases on which they differ are counted as discordant. A pool sums every
model's shares case by case, so each drawn case brings every model's cells,
and counts discordant cells.

A summary holds every ready case of the base pass with its C4 item count
and every triggered item with its outcome in each arm run, so a pool is
derived from committed summaries alone. An arm run the gate stopped is
reported as not run: the summary names it and why and reports the other
arms and their comparison, and such a round is never pooled. Diagnostics
are reported and never become outcomes: transitions from the base outcome,
answers equal to the base's, card kinds and card values an answer reuses.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
import hashlib
from typing import Annotated, cast, Literal, NamedTuple

from pydantic import Field
from pydantic import model_validator

from dfilterforge.completions import RepairPlanV1
from dfilterforge.counterexample import FramesCardV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import GenerationError
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.pair_report import transitions
from dfilterforge.pair_report import TransitionV1
from dfilterforge.score_summary import BOOTSTRAP_RESAMPLES
from dfilterforge.score_summary import BOOTSTRAP_SEED
from dfilterforge.score_summary import discordance
from dfilterforge.score_summary import draw_indices
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import MIN_DISCORDANT_CASES
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import RateV1
from dfilterforge.score_summary import ratio_rate

ArmName = Literal["resample", "bare", "counterexample"]
ARMS: tuple[ArmName, ...] = ("resample", "bare", "counterexample")
# Counterexample against bare is the primary comparison.
ARM_PAIRS: tuple[tuple[ArmName, ArmName], ...] = (
    ("counterexample", "bare"),
    ("counterexample", "resample"),
    ("bare", "resample"),
)
Trigger = Literal["silent_wrong", "invalid"]
# Why an arm was not run: its run stopped at the first-answer gate because
# the provider kept on thinking, as scripts/model_run.py records it.
NotRunReason = Literal["thinking_not_honoured"]

_Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_REUSING = frozenset({OutcomeV1.STRONG_EXACT, OutcomeV1.SHORTCUT})
_VERDICT_KEYS = frozenset({"frame", "answer_matched", "should_match"})
_ValueKey = tuple[str, int | str]


class RoundError(DFilterForgeError, RuntimeError):
    """A refused repair round or pool, with a stable public code.

    The codes are ``repair_arms_incomplete``, ``repair_arm_mismatch``,
    ``repair_items_mismatch``, ``repair_prompt_mismatch``,
    ``repair_settings_mismatch``, ``repair_arm_unscored``,
    ``repair_plan_changed``, ``repair_plan_unreadable``, ``base_unscored``,
    ``repair_not_run_invalid``, ``repair_pool_bases_invalid``,
    ``repair_pool_unsummarized``, ``repair_pool_mismatch`` and
    ``repair_pool_not_run``. A message names a run, an arm or an item id,
    never model text.
    """


class RepairNotRunV1(FrozenModel):
    """The arms of a round recorded as not run, as ``repair/not_run.json``.

    An arm run the gate stopped is over: it is never published or moved to
    another provider, and its prompt set may stay committed as a seed. At
    least one arm of the round runs.
    """

    schema_version: Literal["repair-not-run/1.0"] = "repair-not-run/1.0"
    arms: dict[ArmName, NotRunReason] = Field(min_length=1, max_length=2)


class RepairCaseV1(FrozenModel):
    """One ready case of the base pass: its C4 items, and how many triggered."""

    case_id: str
    ready_items: int = Field(ge=1)
    triggered_items: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "RepairCaseV1":
        """Triggers no more items than the case has."""
        if self.triggered_items > self.ready_items:
            raise ValueError("a case triggers at most its ready items")
        return self


class RepairComparisonV1(FrozenModel):
    """Two arms' repaired shares, paired on every case.

    ``unit`` is ``cases`` for one model and ``cells``, one model's case,
    for a pool. ``difference`` is the first arm's repair@1 minus the
    second's on the same vectors.
    """

    first: ArmName
    second: ArmName
    unit: Literal["cases", "cells"]
    difference: RateV1
    first_better: int = Field(ge=0)
    second_better: int = Field(ge=0)
    discordant: int = Field(ge=0)
    inconclusive: bool


class RepairArmV1(FrozenModel):
    """One arm run of a round: counts, repair@1 and diagnostics.

    ``outcomes`` holds one zero-filled key per outcome over the triggered
    items. ``answer_unchanged`` counts answers whose text equals the base
    pass's, and ``card_value_reuse``, for the counterexample arm only,
    strong-exact or shortcut answers that hold a predicate value equal to
    one their frames card shows for that field. Neither is an outcome.
    """

    arm: ArmName
    run: str
    run_manifest_sha256: _Sha256
    outcomes_sha256: _Sha256
    outcomes: dict[str, int]
    repaired: int = Field(ge=0)
    shortcut: int = Field(ge=0)
    repair_at_1: RateV1
    repair_at_1_silent_wrong: RateV1
    repair_at_1_invalid: RateV1
    transitions: tuple[TransitionV1, ...]
    answer_unchanged: int = Field(ge=0)
    card_value_reuse: int | None = Field(default=None, ge=0)
    latency_ms_p50: float = Field(ge=0)
    latency_ms_p95: float = Field(ge=0)
    charged_usd_upper_bound: float = Field(ge=0)
    provider_reported_usd: float | None = Field(default=None, ge=0)


class RepairItemOutcomesV1(FrozenModel):
    """One triggered item: its plan entry and its outcome in every arm run.

    ``base_outcome`` is the one the plan was triggered by and
    ``base_outcome_now`` the base pass's outcome in ``scored/`` today,
    which a later correction may have changed.
    """

    item_id: str
    case_id: str
    base_outcome: Trigger
    base_outcome_now: OutcomeV1
    card_kind: Literal["frames", "error", "none"]
    card_sha256: _Sha256 | None = None
    outcomes: dict[ArmName, OutcomeV1]


class RepairSummaryV1(FrozenModel):
    """One base pass's repair round, as ``repair/summary.json`` holds it."""

    schema_version: Literal["repair-summary/1.0"] = "repair-summary/1.0"
    split: Literal["dev", "test"]
    base_run: str
    model_id: str
    base_run_manifest_sha256: _Sha256
    base_outcomes_sha256: _Sha256
    plan_sha256: _Sha256
    gold_hash: str
    feedback_probe: str
    bootstrap: dict[str, int]
    triggered_items: int = Field(ge=1)
    triggered_cases: int = Field(ge=1)
    by_base_outcome: dict[str, int]
    card_kinds: dict[str, int]
    cases: tuple[RepairCaseV1, ...] = Field(min_length=1)
    arms: tuple[RepairArmV1, ...]
    comparisons: tuple[RepairComparisonV1, ...]
    items: tuple[RepairItemOutcomesV1, ...] = Field(min_length=1)
    base_outcome_changed: tuple[str, ...] = ()
    arms_not_run: dict[ArmName, NotRunReason] = Field(
        default_factory=dict[ArmName, NotRunReason]
    )

    @model_validator(mode="after")
    def validate_round(self) -> "RepairSummaryV1":
        """Ties the items to the cases and the arms run to their order.

        A pool reads only the cases and the items, so a summary whose case
        counts do not describe its items is refused rather than pooled.
        """
        run = tuple(arm for arm in ARMS if arm not in self.arms_not_run)
        if not run or tuple(arm.arm for arm in self.arms) != run:
            raise ValueError("a summary lists every arm run, in order")
        if any(set(item.outcomes) != set(run) for item in self.items):
            raise ValueError("an item has an outcome in every arm run")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("a summary lists each item once")
        counts = Counter(item.case_id for item in self.items)
        cases = {case.case_id: case for case in self.cases}
        if len(cases) != len(self.cases) or not set(counts) <= set(cases):
            raise ValueError("every item is in one listed ready case")
        if any(
            case.triggered_items != counts[key] for key, case in cases.items()
        ):
            raise ValueError("each case counts its triggered items")
        return self


class PoolBaseV1(FrozenModel):
    """One base pass a pool reads, pinned by its summary's digest."""

    run: str
    model_id: str
    summary_sha256: _Sha256
    triggered_items: int = Field(ge=1)
    triggered_cases: int = Field(ge=1)


class PoolArmV1(FrozenModel):
    """One arm pooled over every base's triggered items."""

    arm: ArmName
    triggered_items: int = Field(ge=1)
    repaired: int = Field(ge=0)
    repair_at_1: RateV1


class RepairPoolV1(FrozenModel):
    """Several models' rounds on one split, as ``repair-pool/<split>.json``."""

    schema_version: Literal["repair-pool/1.0"] = "repair-pool/1.0"
    split: Literal["dev", "test"]
    bases: tuple[PoolBaseV1, ...] = Field(min_length=1)
    bootstrap: dict[str, int]
    arms: tuple[PoolArmV1, ...]
    comparisons: tuple[RepairComparisonV1, ...]


class RoundBase(NamedTuple):
    """What a summary reads of the base pass.

    ``outcomes`` are its C4 outcomes as the plan's trigger read them, and
    they alone give the ready cases and their item counts; ``now`` is each
    C4 item's outcome in ``scored/`` today, and ``answers`` each stored
    answer, None for a provider failure.
    """

    model_id: str
    gold_hash: str
    outcomes: Mapping[str, ItemOutcomeV1]
    now: Mapping[str, OutcomeV1]
    answers: Mapping[str, str | None]


class ArmResult(NamedTuple):
    """One published, scored arm run, as a summary reads it."""

    run: str
    manifest_sha256: str
    outcomes_sha256: str
    outcomes: Mapping[str, OutcomeV1]
    answers: Mapping[str, str | None]
    output_contract: OutputContractV1
    latency_ms: tuple[float, float]
    charged_usd_upper_bound: float
    provider_reported_usd: float | None


_ItemTest = Callable[[RepairItemOutcomesV1], bool]


class _Universe(NamedTuple):
    """The sorted ready case ids and the seeded vectors drawn over them."""

    case_ids: tuple[str, ...]
    vectors: tuple[tuple[int, ...], ...]


class _Cells(NamedTuple):
    """One model's ready cases and triggered items, as a summary holds them."""

    cases: tuple[RepairCaseV1, ...]
    items: tuple[RepairItemOutcomesV1, ...]

    def shares(self, chosen: _ItemTest) -> dict[str, float]:
        """Each ready case's share of its C4 items that ``chosen`` admits.

        Only triggered items can be admitted, and every ready C4 item of
        the case is in the denominator.
        """
        counts = Counter(item.case_id for item in self.items if chosen(item))
        return {
            case.case_id: counts[case.case_id] / case.ready_items
            for case in self.cases
        }


def _universe(case_ids: Iterable[str]) -> _Universe:
    """Sorts a case universe and draws its seeded vectors."""
    ordered = tuple(sorted(case_ids))
    return _Universe(ordered, draw_indices(len(ordered)))


def _bootstrap(cases: int) -> dict[str, int]:
    """Records how the intervals were drawn, as a score summary does."""
    return {
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "cases": cases,
        "min_discordant_cases": MIN_DISCORDANT_CASES,
    }


def _summed(shares: Iterable[Mapping[str, float]]) -> dict[str, float]:
    """Adds every model's case shares case by case."""
    total: dict[str, float] = {}
    for share in shares:
        for case_id, value in share.items():
            total[case_id] = total.get(case_id, 0.0) + value
    return total


def _triggered(trigger: Trigger | None = None) -> _ItemTest:
    """Admits every triggered item, or those of one base outcome."""
    return lambda item: trigger is None or item.base_outcome == trigger


def _repaired(arm: ArmName, trigger: Trigger | None = None) -> _ItemTest:
    """Admits the triggered items an arm made strong exact."""
    return lambda item: (
        item.outcomes[arm] is OutcomeV1.STRONG_EXACT
        and (trigger is None or item.base_outcome == trigger)
    )


def _rate(
    models: Sequence[_Cells],
    universe: _Universe,
    numerator: _ItemTest,
    denominator: _ItemTest,
) -> RateV1:
    """The summed case shares of one test over those of another."""
    return ratio_rate(
        _summed(model.shares(numerator) for model in models),
        _summed(model.shares(denominator) for model in models),
        universe.vectors,
        universe.case_ids,
    )


def _comparison(
    models: Sequence[_Cells],
    universe: _Universe,
    pair: tuple[ArmName, ArmName],
    unit: Literal["cases", "cells"],
) -> RepairComparisonV1:
    """Compares two arms' repaired shares, paired on every case and model."""
    first, second = pair
    differences: list[dict[str, float]] = []
    cells: dict[str, float] = {}
    for index, model in enumerate(models):
        ahead = model.shares(_repaired(first))
        behind = model.shares(_repaired(second))
        difference = {key: ahead[key] - behind[key] for key in ahead}
        differences.append(difference)
        cells.update(
            {f"{index}/{key}": value for key, value in difference.items()}
        )
    counts = discordance(cells)
    return RepairComparisonV1(
        first=first,
        second=second,
        unit=unit,
        difference=ratio_rate(
            _summed(differences),
            _summed(model.shares(_triggered()) for model in models),
            universe.vectors,
            universe.case_ids,
        ),
        first_better=counts.first_better,
        second_better=counts.second_better,
        discordant=counts.discordant,
        inconclusive=counts.inconclusive,
    )


def _value_keys(field: str, value: object) -> set[_ValueKey]:
    """The comparable (field, value) pairs one shown or held value gives.

    A boolean reads as 0 or 1 and a whole float as an integer, as tshark
    compares them; a list gives each element; any other value gives none.
    """
    keys: set[_ValueKey] = set()
    values: tuple[object, ...] = (
        tuple(cast(Iterable[object], value))
        if isinstance(value, (tuple, list))
        else (value,)
    )
    for one in values:
        if isinstance(one, (bool, int)):
            keys.add((field, int(one)))
        elif isinstance(one, float) and one.is_integer():
            keys.add((field, int(one)))
        elif isinstance(one, str):
            keys.add((field, one))
    return keys


def _shown(card: str) -> set[_ValueKey]:
    """Every field value a frames card shows, its verdict keys left out."""
    keys: set[_ValueKey] = set()
    for frame in FramesCardV1.model_validate_json(card).frames:
        shown = frame.model_dump(mode="json", by_alias=True, exclude_none=True)
        for field, value in shown.items():
            if field not in _VERDICT_KEYS:
                keys |= _value_keys(field, value)
    return keys


def _held(contract: OutputContractV1, text: str | None) -> set[_ValueKey]:
    """Every predicate value a ready typed-IR answer holds, by field."""
    if text is None:
        return set()
    try:
        parsed = parse_response(contract, text)
    except GenerationError:
        return set()
    if not isinstance(parsed, GenerationResultV1) or parsed.intent_ir is None:
        return set()
    keys: set[_ValueKey] = set()
    for _, predicate in walk_predicates(parsed.intent_ir.expression):
        keys |= _value_keys(predicate.field, predicate.value)
    return keys


def _card_value_reuse(plan: RepairPlanV1, result: ArmResult) -> int:
    """Counts strong-exact or shortcut answers holding a value their card shows.

    Only a frames card shows values. A reused address or ephemeral port is
    already a shortcut; this counts a value of every shown field.
    """
    return sum(
        1
        for item in plan.items
        if item.card is not None
        and item.card_kind == "frames"
        and result.outcomes[item.item_id] in _REUSING
        and _shown(item.card)
        & _held(result.output_contract, result.answers[item.item_id])
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def _arm_summary(
    arm: ArmName,
    result: ArmResult,
    plan: RepairPlanV1,
    base: RoundBase,
    cells: _Cells,
    universe: _Universe,
) -> RepairArmV1:
    """Reduces one arm run to its counts, rates and diagnostics."""
    counts = {outcome.value: 0 for outcome in OutcomeV1}
    for item in plan.items:
        counts[result.outcomes[item.item_id].value] += 1
    rate, silent_wrong, invalid = (
        _rate([cells], universe, _repaired(arm, part), _triggered(part))
        for part in (None, "silent_wrong", "invalid")
    )
    return RepairArmV1(
        arm=arm,
        run=result.run,
        run_manifest_sha256=result.manifest_sha256,
        outcomes_sha256=result.outcomes_sha256,
        outcomes=counts,
        repaired=counts[OutcomeV1.STRONG_EXACT.value],
        shortcut=counts[OutcomeV1.SHORTCUT.value],
        repair_at_1=rate,
        repair_at_1_silent_wrong=silent_wrong,
        repair_at_1_invalid=invalid,
        transitions=transitions(
            (OutcomeV1(item.base_outcome), result.outcomes[item.item_id])
            for item in plan.items
        ),
        answer_unchanged=sum(
            1
            for item in plan.items
            if result.answers[item.item_id] is not None
            and result.answers[item.item_id] == base.answers[item.item_id]
        ),
        card_value_reuse=(
            _card_value_reuse(plan, result) if arm == "counterexample" else None
        ),
        latency_ms_p50=result.latency_ms[0],
        latency_ms_p95=result.latency_ms[1],
        charged_usd_upper_bound=result.charged_usd_upper_bound,
        provider_reported_usd=result.provider_reported_usd,
    )


def _cells(
    plan: RepairPlanV1, base: RoundBase, arms: Mapping[ArmName, ArmResult]
) -> _Cells:
    """Lists the base's ready cases and the plan's items with their outcomes."""
    ready = Counter(
        outcome.case_id
        for outcome in base.outcomes.values()
        if outcome.gold_status == "ready"
    )
    triggered = Counter(
        base.outcomes[item.item_id].case_id for item in plan.items
    )
    return _Cells(
        cases=tuple(
            RepairCaseV1(
                case_id=case_id,
                ready_items=ready[case_id],
                triggered_items=triggered[case_id],
            )
            for case_id in sorted(ready)
        ),
        items=tuple(
            RepairItemOutcomesV1(
                item_id=item.item_id,
                case_id=base.outcomes[item.item_id].case_id,
                base_outcome=item.base_outcome,
                base_outcome_now=base.now[item.item_id],
                card_kind=item.card_kind,
                card_sha256=(
                    None
                    if item.card is None
                    else hashlib.sha256(item.card.encode("utf-8")).hexdigest()
                ),
                outcomes={
                    arm: arms[arm].outcomes[item.item_id]
                    for arm in ARMS
                    if arm in arms
                },
            )
            for item in plan.items
        ),
    )


def summarize_round(
    plan: RepairPlanV1,
    plan_sha256: str,
    base: RoundBase,
    arms: Mapping[ArmName, ArmResult],
    not_run: Mapping[ArmName, NotRunReason] | None = None,
) -> RepairSummaryV1:
    """Reduces a checked round to its published summary.

    Args:
        plan: The round's plan; every item is a C4 item of ``base``.
        plan_sha256: The digest of the plan's committed bytes.
        base: What the summary reads of the base pass.
        arms: Every arm run's published, scored run; each scores every item
            of the plan.
        not_run: Every other arm, with why it was not run.

    Returns:
        repair@1 per arm run with its silent-wrong and invalid parts, the
        comparisons of every two arms run, the diagnostics and every
        triggered item's outcomes.

    Raises:
        ValidationError: When an item of the plan is not a ready C4 item
            of the base pass, or the arms run and not run are not the three.
    """
    cells = _cells(plan, base, arms)
    universe = _universe(case.case_id for case in cells.cases)
    return RepairSummaryV1(
        split=plan.split,
        base_run=plan.base_run,
        model_id=base.model_id,
        base_run_manifest_sha256=plan.base_run_manifest_sha256,
        base_outcomes_sha256=plan.base_outcomes_sha256,
        plan_sha256=plan_sha256,
        gold_hash=base.gold_hash,
        feedback_probe=plan.feedback_probe,
        bootstrap=_bootstrap(len(universe.case_ids)),
        triggered_items=len(plan.items),
        triggered_cases=sum(1 for case in cells.cases if case.triggered_items),
        by_base_outcome={
            trigger: sum(1 for i in plan.items if i.base_outcome == trigger)
            for trigger in ("invalid", "silent_wrong")
        },
        card_kinds={
            kind: sum(1 for i in plan.items if i.card_kind == kind)
            for kind in ("error", "frames", "none")
        },
        cases=cells.cases,
        arms=tuple(
            _arm_summary(arm, arms[arm], plan, base, cells, universe)
            for arm in ARMS
            if arm in arms
        ),
        comparisons=tuple(
            _comparison([cells], universe, pair, "cases")
            for pair in ARM_PAIRS
            if set(pair) <= set(arms)
        ),
        items=cells.items,
        base_outcome_changed=tuple(
            item.item_id
            for item in cells.items
            if item.base_outcome_now.value != item.base_outcome
        ),
        arms_not_run=dict(not_run or {}),
    )


def pool_summaries(
    split: Literal["dev", "test"],
    summaries: Sequence[tuple[RepairSummaryV1, str]],
) -> RepairPoolV1:
    """Pools several models' rounds on one split's ready cases.

    Args:
        split: The split every base pass is on.
        summaries: Each base's summary and the digest of its committed
            bytes, in the order the pool lists them.

    Returns:
        repair@1 per arm over every model's triggered items, each drawn
        case bringing every model's cells, and the arm comparisons over
        discordant cells.

    Raises:
        RoundError: With ``repair_pool_mismatch`` when a summary is of
            another split, a model appears twice, or the bases do not share
            one set of ready cases, and ``repair_pool_not_run`` when a
            base's round has an arm not run, so its cells cannot be paired
            in every comparison.
    """
    if any(summary.split != split for summary, _ in summaries):
        raise RoundError("repair_pool_mismatch", f"A base is not on {split}")
    for summary, _ in summaries:
        if summary.arms_not_run:
            raise RoundError(
                "repair_pool_not_run",
                f"{summary.base_run} has an arm not run and is not pooled",
            )
    models = [summary.model_id for summary, _ in summaries]
    if len(set(models)) != len(models):
        raise RoundError("repair_pool_mismatch", "A model appears twice")
    universes = {
        frozenset(case.case_id for case in summary.cases)
        for summary, _ in summaries
    }
    if len(universes) != 1:
        raise RoundError(
            "repair_pool_mismatch", "The bases do not share their ready cases"
        )
    cells = [_Cells(summary.cases, summary.items) for summary, _ in summaries]
    universe = _universe(universes.pop())
    return RepairPoolV1(
        split=split,
        bases=tuple(
            PoolBaseV1(
                run=summary.base_run,
                model_id=summary.model_id,
                summary_sha256=digest,
                triggered_items=summary.triggered_items,
                triggered_cases=summary.triggered_cases,
            )
            for summary, digest in summaries
        ),
        bootstrap=_bootstrap(len(universe.case_ids)),
        arms=tuple(
            PoolArmV1(
                arm=arm,
                triggered_items=sum(len(model.items) for model in cells),
                repaired=sum(
                    sum(map(_repaired(arm), model.items)) for model in cells
                ),
                repair_at_1=_rate(
                    cells, universe, _repaired(arm), _triggered()
                ),
            )
            for arm in ARMS
        ),
        comparisons=tuple(
            _comparison(cells, universe, pair, "cells") for pair in ARM_PAIRS
        ),
    )
