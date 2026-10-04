"""A paired reading of two scored passes over the same items.

The A/A paragraph of ``docs/protocol.md`` reads a pass against its rerun:
per condition, the changed answers, the outcome transitions and the flipped
cases, the ready cases whose strong-exact case mean differs. A comparison
with ``MIN_DISCORDANT_CASES`` or more discordant cases is within rerun noise
when its net count is at most twice the square root of its two conditions'
mean flipped cases, and not replicated when the rerun reverses its sign.

:func:`transitions` is the one count of outcome transitions, so a repair
round reads each arm against its base pass the same way. :func:`pair_runs`
reads two published, scored passes as scoring reads them, with every digest
checked, and :func:`read_pass` reads one, so a repair round reads its arm
runs the same way. A pair requires the same split, conditions, items and
gold; the comparisons it reads against the noise are the ones each pass's
committed summary holds. Nothing here executes a capture, and no answer
text reaches a report or an error message: answers are only compared.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import math
import os
from pathlib import Path
import stat
from typing import Literal, NamedTuple

from pydantic import Field
from pydantic import ValidationError

from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.run_store import check_manifest
from dfilterforge.run_store import check_prepare
from dfilterforge.run_store import check_splits
from dfilterforge.run_store import load_run
from dfilterforge.run_store import MAX_RUN_FILE_BYTES
from dfilterforge.run_store import SCORED_NAME
from dfilterforge.score_summary import case_means
from dfilterforge.score_summary import COMPARISONS
from dfilterforge.score_summary import ComparisonV1
from dfilterforge.score_summary import CONDITION_ORDER
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import discordance
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import ScoreSummaryV1

_OUTCOME_ORDER: Mapping[OutcomeV1, int] = {
    outcome: index for index, outcome in enumerate(OutcomeV1)
}
# What a run manifest records about how its requests were sent.
_CALL_CONFIG = (
    "settings",
    "endpoint_host",
    "max_attempts",
    "min_interval_seconds",
)
_BOUND_DIGITS = 6
_OUTCOMES_NAME = "outcomes.jsonl"
_SUMMARY_NAME = "summary.json"


class PairError(DFilterForgeError, RuntimeError):
    """A refused pair, with a stable public code.

    The codes are ``pair_unpublished``, ``pair_unscored`` and
    ``pair_mismatch``. A message names a run directory, a condition, an
    item id or a file, never model text.
    """


class TransitionV1(FrozenModel):
    """How many items went from one outcome in the first pass to another."""

    first: OutcomeV1
    second: OutcomeV1
    items: int = Field(ge=1)


class PairConditionV1(FrozenModel):
    """What changed in one condition between the two passes.

    ``changed_answers`` counts the items whose stored answer text differs;
    an item that stored no text, a provider failure, counts as changed only
    when the other pass stored some. ``transitions`` lists every pair of
    first and second outcomes that occurs, unchanged ones included, in
    :class:`OutcomeV1` order. ``first_better_cases`` and
    ``second_better_cases`` split the flipped cases by the pass they favour.
    """

    condition: ConditionLabel
    items: int = Field(ge=1)
    prompts_identical: bool
    changed_answers: int = Field(ge=0)
    changed_outcomes: int = Field(ge=0)
    changed_outcome_items: tuple[str, ...]
    transitions: tuple[TransitionV1, ...]
    ready_cases: int = Field(ge=0)
    flipped_cases: int = Field(ge=0)
    first_better_cases: int = Field(ge=0)
    second_better_cases: int = Field(ge=0)
    flipped_case_ids: tuple[str, ...]


class NoiseReadingV1(FrozenModel):
    """One pass's condition comparison read against the pair's noise.

    ``net_cases`` is first-better minus second-better cases.
    ``within_noise`` is None for an inconclusive comparison, because the
    protocol reads noise only from ``MIN_DISCORDANT_CASES`` cases up.
    """

    net_cases: int
    discordant_cases: int = Field(ge=0)
    within_noise: bool | None


class PairComparisonV1(FrozenModel):
    """A condition comparison of both passes and the pair's noise bound.

    ``noise_bound`` is twice the square root of the two conditions' mean
    flipped cases. ``sign_reversed`` says whether the second pass's net
    count has the opposite sign of the first's.
    """

    first: ConditionLabel
    second: ConditionLabel
    noise_bound: float = Field(ge=0)
    first_pass: NoiseReadingV1
    second_pass: NoiseReadingV1
    sign_reversed: bool


class PairPassV1(FrozenModel):
    """Which pass a side of the pair is, and the outcomes it was read from."""

    run: str
    model_id: str
    outcomes_sha256: str


class PairReportV1(FrozenModel):
    """A pair of scored passes over the same items, condition by condition.

    ``settings_identical`` says whether the two run manifests record the
    same request settings, endpoint host, attempt limit and pacing; an A/A
    pair needs it true and every condition's prompts identical.
    """

    schema_version: Literal["pair-report/1.0"] = "pair-report/1.0"
    split: str
    gold_hash: str
    first: PairPassV1
    second: PairPassV1
    settings_identical: bool
    conditions: tuple[PairConditionV1, ...]
    comparisons: tuple[PairComparisonV1, ...] = ()


class ConditionPass(NamedTuple):
    """One condition of one pass, as a pair reads it.

    ``answers`` maps each item to its stored text, None when it stored
    none; ``prompts_sha256`` is the prepared batch file's digest.
    """

    outcomes: Sequence[ItemOutcomeV1]
    answers: Mapping[str, str | None]
    prompts_sha256: str


class ScoredPass(NamedTuple):
    """The parts of a published, scored pass a pair or a round reads."""

    manifest: RunManifestV1
    split: str
    conditions: dict[ConditionLabel, ConditionPass]
    outcomes_sha256: str
    summary: ScoreSummaryV1


def transitions(
    pairs: Iterable[tuple[OutcomeV1, OutcomeV1]],
) -> tuple[TransitionV1, ...]:
    """Counts each pair of first and second outcomes that occurs.

    Args:
        pairs: One (first outcome, second outcome) pair per item.

    Returns:
        One transition per distinct pair, in :class:`OutcomeV1` order of
        the first outcome, then of the second.
    """
    counts = Counter(pairs)
    return tuple(
        TransitionV1(first=first, second=second, items=counts[first, second])
        for first, second in sorted(
            counts,
            key=lambda pair: (_OUTCOME_ORDER[pair[0]], _OUTCOME_ORDER[pair[1]]),
        )
    )


def _strong_exact_means(items: Sequence[ItemOutcomeV1]) -> dict[str, float]:
    """Averages the strong-exact indicator inside each ready case."""
    return case_means(
        [
            (item.case_id, float(item.outcome is OutcomeV1.STRONG_EXACT))
            for item in items
            if item.gold_status == "ready"
        ]
    )


def _by_item(
    condition: ConditionLabel, outcomes: Sequence[ItemOutcomeV1]
) -> dict[str, ItemOutcomeV1]:
    """Keys one side's outcomes by item id, refusing a repeated item."""
    keyed = {outcome.item_id: outcome for outcome in outcomes}
    if len(keyed) != len(outcomes):
        raise PairError(
            "pair_mismatch", f"{condition}: an item is scored twice"
        )
    return keyed


def pair_condition(
    condition: ConditionLabel, first: ConditionPass, second: ConditionPass
) -> PairConditionV1:
    """Reads what changed in one condition between two passes.

    Args:
        condition: The condition both sides belong to.
        first: The first pass's side; its answers must cover its items.
        second: The second pass's side, over the same items.

    Returns:
        The changed answers, the outcome transitions and the flipped cases.

    Raises:
        PairError: With ``pair_mismatch`` when the two sides score
            different items, or score an item on different gold.
    """
    first_items = _by_item(condition, first.outcomes)
    second_items = _by_item(condition, second.outcomes)
    if set(first_items) != set(second_items):
        raise PairError(
            "pair_mismatch", f"{condition}: the passes scored different items"
        )
    item_ids = sorted(first_items)
    for item_id in item_ids:
        before, after = first_items[item_id], second_items[item_id]
        if (before.case_id, before.gold_status) != (
            after.case_id,
            after.gold_status,
        ):
            raise PairError(
                "pair_mismatch", f"{condition} {item_id}: scored on other gold"
            )
    first_means = _strong_exact_means(first.outcomes)
    second_means = _strong_exact_means(second.outcomes)
    # The same items on the same gold give both sides the same ready cases.
    flipped = {
        case_id: first_means[case_id] - second_means[case_id]
        for case_id in sorted(first_means)
        if first_means[case_id] != second_means[case_id]
    }
    counts = discordance(flipped)
    changed = tuple(
        item_id
        for item_id in item_ids
        if first_items[item_id].outcome is not second_items[item_id].outcome
    )
    return PairConditionV1(
        condition=condition,
        items=len(item_ids),
        prompts_identical=first.prompts_sha256 == second.prompts_sha256,
        changed_answers=sum(
            first.answers[item_id] != second.answers[item_id]
            for item_id in item_ids
        ),
        changed_outcomes=len(changed),
        changed_outcome_items=changed,
        transitions=transitions(
            (first_items[item_id].outcome, second_items[item_id].outcome)
            for item_id in item_ids
        ),
        ready_cases=len(first_means),
        flipped_cases=counts.discordant,
        first_better_cases=counts.first_better,
        second_better_cases=counts.second_better,
        flipped_case_ids=tuple(flipped),
    )


def _reading(comparison: ComparisonV1, flipped_sum: int) -> NoiseReadingV1:
    """Reads one pass's comparison against the pair's flipped cases.

    ``|net| <= 2 * sqrt(sum / 2)`` is compared exactly as
    ``net**2 <= 2 * sum``, so no rounding decides a reading.
    """
    net = comparison.first_better_cases - comparison.second_better_cases
    return NoiseReadingV1(
        net_cases=net,
        discordant_cases=comparison.discordant_cases,
        within_noise=(
            None if comparison.inconclusive else net * net <= 2 * flipped_sum
        ),
    )


def noise_reading(
    first: ComparisonV1,
    second: ComparisonV1,
    flipped: Mapping[ConditionLabel, int],
) -> PairComparisonV1:
    """Reads one condition comparison of both passes against rerun noise.

    Args:
        first: The comparison as the first pass's summary holds it.
        second: The same comparison in the second pass's summary.
        flipped: Condition to the pair's flipped cases in it; it must cover
            both conditions of the comparison.

    Returns:
        The noise bound, each pass's net count against it, and whether the
        second pass reverses the first's sign.

    Raises:
        ValueError: When the two comparisons are of different conditions.
    """
    if (first.first, first.second) != (second.first, second.second):
        raise ValueError("the two comparisons are of different conditions")
    flipped_sum = flipped[first.first] + flipped[first.second]
    first_pass = _reading(first, flipped_sum)
    second_pass = _reading(second, flipped_sum)
    return PairComparisonV1(
        first=first.first,
        second=first.second,
        noise_bound=round(2 * math.sqrt(flipped_sum / 2), _BOUND_DIGITS),
        first_pass=first_pass,
        second_pass=second_pass,
        sign_reversed=first_pass.net_cases * second_pass.net_cases < 0,
    )


def _read_scored(run_dir: Path, name: str) -> bytes:
    """Reads one bounded regular file of a pass's scored tree.

    Raises:
        PairError: With ``pair_unscored`` when the file is absent, a
            symlink, not a regular file, over ``MAX_RUN_FILE_BYTES`` or
            unreadable.
    """
    path = run_dir / SCORED_NAME / name
    data = None
    try:
        if stat.S_ISREG(os.lstat(path).st_mode):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0))
            with os.fdopen(descriptor, "rb") as source:
                if stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    data = source.read(MAX_RUN_FILE_BYTES + 1)
    except OSError:
        data = None
    if data is None or len(data) > MAX_RUN_FILE_BYTES:
        raise PairError(
            "pair_unscored",
            f"{run_dir.name}: {SCORED_NAME}/{name} cannot be read",
        )
    return data


def _read_outcomes(
    run_dir: Path, prepared: Mapping[ConditionLabel, frozenset[str]]
) -> tuple[dict[ConditionLabel, list[ItemOutcomeV1]], str]:
    """Reads a pass's scored outcomes and the digest of their file.

    Raises:
        PairError: With ``pair_unscored`` when the file cannot be read, a
            line does not validate, or the outcomes do not score each
            prepared item exactly once.
    """
    raw = _read_scored(run_dir, _OUTCOMES_NAME)
    lines = [line for line in raw.split(b"\n") if line]
    keyed: dict[tuple[str, str], ItemOutcomeV1] = {}
    try:
        for line in lines:
            outcome = ItemOutcomeV1.model_validate_json(line)
            keyed[outcome.condition, outcome.item_id] = outcome
    except ValidationError:
        keyed.clear()
    expected = {
        (label, item) for label, ids in prepared.items() for item in ids
    }
    if len(keyed) != len(lines) or set(keyed) != expected:
        raise PairError(
            "pair_unscored",
            f"{run_dir.name}: {SCORED_NAME}/{_OUTCOMES_NAME} does not score"
            " each prompt once",
        )
    grouped: dict[ConditionLabel, list[ItemOutcomeV1]] = {
        label: [] for label in prepared
    }
    for outcome in keyed.values():
        grouped[outcome.condition].append(outcome)
    return grouped, hashlib.sha256(raw).hexdigest()


def _answers(batch: CompletionBatchV1) -> dict[str, str | None]:
    """Maps each item to the answer text it stored, None for a failure."""
    return {
        completion.item_id: (
            completion.response_text
            if completion.status is CompletionStatusV1.COMPLETED
            else None
        )
        for completion in batch.completions
    }


def read_pass(run_dir: Path) -> ScoredPass:
    """Reads a published, scored pass, checking every digest as scoring does.

    Args:
        run_dir: The pass's published directory.

    Returns:
        Its run manifest and split, each condition's outcomes, stored
        answers and prompt digest, the digest of its outcome file and its
        committed summary.

    Raises:
        PairError: When the pass has no run manifest or is not scored.
        ScoringError: For any layout, manifest or split failure.
    """
    loaded = load_run(run_dir)
    if loaded.manifest is None:
        raise PairError("pair_unpublished", f"{run_dir.name}: no run manifest")
    if loaded.prepare is not None:
        check_prepare(loaded.prepare, loaded.prepared)
    check_manifest(loaded.manifest, loaded.prepared, loaded.completions)
    split = check_splits(loaded.prepared, loaded.manifest, loaded.prepare)
    outcomes, outcomes_sha256 = _read_outcomes(
        run_dir,
        {
            label: frozenset(prompt.item_id for prompt in batch.prompts)
            for label, (batch, _) in loaded.prepared.items()
        },
    )
    try:
        summary = ScoreSummaryV1.model_validate_json(
            _read_scored(run_dir, _SUMMARY_NAME)
        )
    except ValidationError:
        summary = None
    # Scoring names a summary after its run directory.
    if summary is None or (summary.run, summary.split) != (run_dir.name, split):
        raise PairError(
            "pair_unscored",
            f"{run_dir.name}: {SCORED_NAME}/{_SUMMARY_NAME} is not its summary",
        )
    return ScoredPass(
        manifest=loaded.manifest,
        split=split,
        conditions={
            label: ConditionPass(
                outcomes=outcomes[label],
                answers=_answers(loaded.completions[label]),
                prompts_sha256=digest,
            )
            for label, (_, digest) in loaded.prepared.items()
        },
        outcomes_sha256=outcomes_sha256,
        summary=summary,
    )


def pair_runs(first_dir: Path, second_dir: Path) -> PairReportV1:
    """Reports a pair of published, scored passes over the same items.

    Args:
        first_dir: The first pass's published directory, such as pass A.
        second_dir: The second pass's, such as its rerun.

    Returns:
        Per condition, the changed answers, the outcome transitions and
        the flipped cases, and each condition comparison both summaries
        hold read against the pair's rerun noise.

    Raises:
        PairError: When either pass is unpublished or unscored, or the two
            differ in split, conditions, items or gold.
        ScoringError: For any layout, manifest or split failure.
    """
    first = read_pass(first_dir)
    second = read_pass(second_dir)
    if first.split != second.split:
        raise PairError("pair_mismatch", "The passes are of different splits")
    if set(first.conditions) != set(second.conditions):
        raise PairError(
            "pair_mismatch", "The passes prepared different conditions"
        )
    if first.summary.gold_hash != second.summary.gold_hash:
        raise PairError(
            "pair_mismatch", "The passes were scored against different gold"
        )
    conditions = tuple(
        pair_condition(label, first.conditions[label], second.conditions[label])
        for label in CONDITION_ORDER
        if label in first.conditions
    )
    flipped: dict[ConditionLabel, int] = {
        item.condition: item.flipped_cases for item in conditions
    }
    first_comparisons = {
        (item.first, item.second): item for item in first.summary.comparisons
    }
    second_comparisons = {
        (item.first, item.second): item for item in second.summary.comparisons
    }
    return PairReportV1(
        split=first.split,
        gold_hash=first.summary.gold_hash,
        first=PairPassV1(
            run=first.manifest.run_id,
            model_id=first.manifest.settings.model_id,
            outcomes_sha256=first.outcomes_sha256,
        ),
        second=PairPassV1(
            run=second.manifest.run_id,
            model_id=second.manifest.settings.model_id,
            outcomes_sha256=second.outcomes_sha256,
        ),
        settings_identical=all(
            getattr(first.manifest, name) == getattr(second.manifest, name)
            for name in _CALL_CONFIG
        ),
        conditions=conditions,
        comparisons=tuple(
            noise_reading(
                first_comparisons[pair], second_comparisons[pair], flipped
            )
            for pair in COMPARISONS
            if pair in first_comparisons
            and pair in second_comparisons
            and set(pair) <= set(flipped)
        ),
    )
