"""Reading and checking a repair round's committed runs.

A repair round sends each triggered item of a base pass's plan once in each
of three arms, as ordinary C4 runs named after the base run with ``-res``,
``-bare`` or ``-cx`` before its date; the one re-run an outage allows adds
``-r2`` after the tag and replaces its arm, and the first run it replaces
has its prompts checked all the same. :func:`round_run` is the
``dfilterforge repair`` command. It writes or checks the plan and, once arm
runs exist beside the base pass, requires all three and checks each one
against the committed plan, which from then on is the round's record and
is never derived again:

- one C4 condition on the base's split and prepared inputs, named after its
  arm, over the plan's items in plan order;
- every prompt the one its arm builds: the base prompt itself for the
  resample, that prompt continued by the counted answer and the follow-up
  for bare, and the same with the item's card for counterexample;
- once published, the base's request settings, prices, endpoint host,
  attempt limit and pacing, a complete run and a scored tree that scores
  every item on the case the base pass scored it on.

A base pass with a provider move registered in :data:`PROVIDER_MOVES` has
its arm runs held to the move's provider order and prices instead of its
own, every other setting unchanged, and, when the move carries a tag,
named with that tag after the arm tag and prepared under the arm's
registered first run id.

An arm run the gate stopped is reported as not run: ``repair --not-run
ARM`` records it in ``repair/not_run.json``, after which that arm may stay
an unpublished prompt set or be absent and is never published, and the
other arms are checked and summarized without it.

With every arm run published and scored it writes or checks
``repair/summary.json`` and ``repair/summary.md``, which
:mod:`dfilterforge.repair_summary` derives and
:mod:`dfilterforge.repair_report` prints. :func:`pool_run` does the same for
``repair-pool/<split>.json`` from the committed summaries of several bases.

``score --check`` rebuilds only a prompt's first turn, so the counted
answer and follow-up of a second turn are checked here alone, and only in
runs named as arms of a base pass with a committed plan;
:func:`unchecked_second_turns` lists every other committed run that holds
one, which CI refuses.

Only the plan stage executes anything; the rest reads committed files, and
no answer text reaches a report or an error message. No module that builds
prompts, calls a model or scores imports this one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Literal, NamedTuple

from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.completions import RepairItemV1
from dfilterforge.completions import RepairPlanV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import TokenPricesV1
from dfilterforge.generation import follow_up_prompt
from dfilterforge.generation import GenerationError
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.pair_report import PairError
from dfilterforge.pair_report import read_pass
from dfilterforge.repair import BasePass
from dfilterforge.repair import committed_differs
from dfilterforge.repair import plan_bytes
from dfilterforge.repair import PLAN_PATH
from dfilterforge.repair import plan_report
from dfilterforge.repair import plan_run
from dfilterforge.repair import read_base
from dfilterforge.repair import read_bounded
from dfilterforge.repair import ready_intent
from dfilterforge.repair import REPAIR_CONDITION
from dfilterforge.repair import RepairReportV1
from dfilterforge.repair import triggers
from dfilterforge.repair import write_whole
from dfilterforge.repair_report import render_pool
from dfilterforge.repair_report import render_summary
from dfilterforge.repair_summary import ArmName
from dfilterforge.repair_summary import ArmResult
from dfilterforge.repair_summary import ARMS
from dfilterforge.repair_summary import NotRunReason
from dfilterforge.repair_summary import pool_summaries
from dfilterforge.repair_summary import RepairNotRunV1
from dfilterforge.repair_summary import RepairPoolV1
from dfilterforge.repair_summary import RepairSummaryV1
from dfilterforge.repair_summary import RoundBase
from dfilterforge.repair_summary import RoundError
from dfilterforge.repair_summary import summarize_round
from dfilterforge.run_store import check_prepare
from dfilterforge.run_store import check_splits
from dfilterforge.run_store import load_run
from dfilterforge.run_store import MANIFEST_NAME
from dfilterforge.runner import TsharkRunner

# The tag each arm's run id carries before its base pass's date, and the
# one re-run tag, as scripts/model_run.py names them; a test ties the two.
ARM_TAGS: Mapping[ArmName, str] = MappingProxyType(
    {"resample": "res", "bare": "bare", "counterexample": "cx"}
)
ARM_RERUN = "r2"
SUMMARY_PATH = Path("repair") / "summary.json"
NOT_RUN_PATH = Path("repair") / "not_run.json"
SUMMARY_REPORT_PATH = Path("repair") / "summary.md"
POOL_DIR = "repair-pool"

_DATE_LENGTH = 10
_GATE_STOP: NotRunReason = "thinking_not_honoured"
_RESULT_DIR = re.compile(
    r"(dev|test)-[a-z0-9][a-z0-9.-]{0,31}-[0-9]{4}-[0-9]{2}-[0-9]{2}"
)
# What a run manifest records about how its requests were sent and priced.
_CALL_CONFIG = (
    "settings",
    "prices",
    "endpoint_host",
    "max_attempts",
    "min_interval_seconds",
)


class ProviderMove(NamedTuple):
    """A registered move of a base pass's arm runs to another provider.

    Attributes:
        tag: The tag the moved arm run ids carry after the arm tag, or None
            when they keep the registered ids.
        provider_order: The provider order the moved arm runs send.
        prices: The prices the moved arm runs record.
    """

    tag: str | None
    provider_order: tuple[str, ...]
    prices: TokenPricesV1


# The prices object of the committed config, its source string verbatim:
# docs/decisions/evidence/bakeoff/configs/
# deepseek-v4-pro-0813_nextbit_enabled-false.json.
_NEXTBIT_PRICES = TokenPricesV1(
    usd_per_million_input=1.056,
    usd_per_million_output=3.168,
    source=(
        "OpenRouter endpoints API for deepseek/deepseek-v4-pro-0813, slug"
        " nextbit matches nextbit/fp8 (NextBit, fp8), fetched"
        " 2026-09-26T10:05:28Z"
    ),
)
# Owner ruling OD5, 2026-10-04, in the repair note: the frontier slot's arm
# runs move from DeepInfra to NextBit, under new ids on dev (OD6) and the
# registered ids on test (OD8). scripts/repair_arms.py holds the same
# moves, and tests tie both to the committed config.
PROVIDER_MOVES: Mapping[str, ProviderMove] = MappingProxyType(
    {
        "dev-deepseek-v4-pro-0813-2026-09-26": ProviderMove(
            "nb", ("nextbit",), _NEXTBIT_PRICES
        ),
        "test-deepseek-v4-pro-0813-2026-09-26": ProviderMove(
            None, ("nextbit",), _NEXTBIT_PRICES
        ),
    }
)


class PoolReportV1(FrozenModel):
    """What one pool pass wrote, or how the committed pool compares."""

    schema_version: Literal["repair-pool-report/1.0"] = "repair-pool-report/1.0"
    pool_path: Path
    checked: bool
    code_revision: str
    bases: tuple[str, ...]
    pool_sha256: str
    differences: tuple[str, ...] = ()


class _ArmRun(NamedTuple):
    """One arm run whose prompts were checked against the base and plan."""

    arm: ArmName
    run_dir: Path
    prompts: PreparedBatchV1
    manifest: RunManifestV1 | None


def registered_run_ids(base_run: str, arm: ArmName) -> tuple[str, str]:
    """Names one arm's run and its one re-run as the protocol registers them.

    They are the only names follow-up builds an arm's prompt set under.

    Args:
        base_run: The base pass's run id, ending in its date.
        arm: The arm.

    Returns:
        The arm's run id and the run id of its re-run.
    """
    stem, date = base_run[: -_DATE_LENGTH - 1], base_run[-_DATE_LENGTH:]
    tagged = f"{stem}-{ARM_TAGS[arm]}"
    return f"{tagged}-{date}", f"{tagged}-{ARM_RERUN}-{date}"


def arm_run_ids(base_run: str, arm: ArmName) -> tuple[str, str]:
    """Names one arm's run and its one re-run after the base run.

    They are the registered names, unless the base has a provider move
    with a tag, whose runs carry that tag after the arm tag.

    Args:
        base_run: The base pass's run id, ending in its date.
        arm: The arm.

    Returns:
        The arm's run id and the run id of its re-run.
    """
    move = PROVIDER_MOVES.get(base_run)
    if move is None or move.tag is None:
        return registered_run_ids(base_run, arm)
    stem, date = base_run[: -_DATE_LENGTH - 1], base_run[-_DATE_LENGTH:]
    tagged = f"{stem}-{ARM_TAGS[arm]}-{move.tag}"
    return f"{tagged}-{date}", f"{tagged}-{ARM_RERUN}-{date}"


def _not_run(
    run_dir: Path, named: Sequence[ArmName], check: bool
) -> dict[ArmName, NotRunReason]:
    """The arms a round records as not run: those named now, or the file's.

    Raises:
        RoundError: With ``repair_not_run_invalid`` when arms are named in
            a check or all three are named, or when the committed record is
            not a canonical record.
    """
    if named:
        if check or set(named) == set(ARMS):
            raise RoundError(
                "repair_not_run_invalid",
                "Name one or two arms not run, and only outside a check",
            )
        return {arm: _GATE_STOP for arm in ARMS if arm in named}
    try:
        data = read_bounded(run_dir / NOT_RUN_PATH)
        record = (
            None if data is None else RepairNotRunV1.model_validate_json(data)
        )
    except (OSError, ValidationError):
        data, record = b"", None
    if data is not None and (record is None or data != _encoded(record)):
        raise RoundError(
            "repair_not_run_invalid",
            f"{run_dir.name}: {NOT_RUN_PATH.as_posix()} is not its record",
        )
    return {} if record is None else dict(record.arms)


def _locate(
    base_dir: Path, not_run: Mapping[ArmName, NotRunReason]
) -> dict[ArmName, Path]:
    """Finds the arm runs beside a base pass, a re-run before its first run.

    Once any arm has a run, or some arm is recorded as not run, every other
    arm must have one; an arm not run may keep its unpublished prompt set.

    Raises:
        RoundError: With ``repair_arms_incomplete`` when an arm that is not
            recorded as not run has no run while the round has begun.
    """
    found: dict[ArmName, Path] = {}
    for arm in ARMS:
        first, rerun = arm_run_ids(base_dir.name, arm)
        for name in (rerun, first):
            path = base_dir.parent / name
            if os.path.lexists(path):
                found[arm] = path
                break
    missing = [arm for arm in ARMS if arm not in found and arm not in not_run]
    if (found or not_run) and missing:
        raise RoundError(
            "repair_arms_incomplete",
            f"{base_dir.name}: no {', '.join(missing)} arm run",
        )
    return found


def _in_order(item_ids: Sequence[str], order: Sequence[str]) -> bool:
    """Reports whether every id is in ``order``, once each and in its order."""
    remaining = iter(order)
    # Each membership test consumes ``remaining`` up to the id it finds.
    return all(item_id in remaining for item_id in item_ids)


def _committed_plan(
    run_dir: Path, base: BasePass, check: bool
) -> tuple[RepairPlanV1, tuple[str, ...]]:
    """Reads the plan a round's arms were prepared from and checks its base.

    Once an arm run exists the committed plan is the round's record. A gold
    correction may since have moved the base's outcomes, the feedback labels
    or a card, but the arms were prepared from these bytes and the
    triggered set stays the plan's, so the plan is never derived again.
    What must still hold is checked: it is a plan of this pass, its items
    are ready C4 items of the pass in prepare order, each with a ready
    answer equal to its scored intent, and while the outcomes the trigger
    reads are the ones the plan recorded, its items are exactly their
    trigger set. Outcomes a correction moved are reported by the summary.

    Args:
        run_dir: The base pass's published directory.
        base: The base pass, read as the plan stage reads it.
        check: Compare the committed bytes instead of requiring them.

    Returns:
        The plan, and ``repair/plan.json`` when its committed bytes are not
        its canonical encoding.

    Raises:
        RoundError: With ``repair_plan_unreadable`` when no committed plan
            can be read, and ``repair_plan_changed`` when it does not fit
            the pass, or, outside a check, is not in its canonical bytes.
        RepairError: When a planned answer is not its scored intent.
    """
    try:
        raw = read_bounded(run_dir / PLAN_PATH)
        plan = None if raw is None else RepairPlanV1.model_validate_json(raw)
    except (OSError, ValidationError):
        raw, plan = None, None
    if raw is None or plan is None:
        raise RoundError(
            "repair_plan_unreadable",
            f"{run_dir.name}: arm runs exist, and no committed plan reads",
        )
    planned = tuple((item.item_id, item.base_outcome) for item in plan.items)
    ready = [
        prompt.item_id
        for prompt in base.prompts.prompts
        if base.outcomes[prompt.item_id].gold_status == "ready"
    ]
    if (
        (plan.split, plan.base_run, plan.base_run_manifest_sha256)
        != (base.split, base.manifest.run_id, base.manifest_sha256)
        or not _in_order([item_id for item_id, _ in planned], ready)
        or (
            plan.base_outcomes_sha256 == base.outcomes_sha256
            and planned != triggers(base)
        )
    ):
        raise RoundError(
            "repair_plan_changed",
            f"{plan.base_run}: the committed plan is not one this pass gives",
        )
    first = {prompt.item_id: prompt for prompt in base.prompts.prompts}
    for item_id, _ in planned:
        ready_intent(run_dir, first[item_id], base.answers[item_id])
    if raw == plan_bytes(plan):
        return plan, ()
    if not check:
        raise RoundError(
            "repair_plan_changed",
            f"{plan.base_run}: arm runs exist, and the committed plan is not"
            " in its canonical bytes",
        )
    return plan, (PLAN_PATH.as_posix(),)


def _arm_prompt(
    arm: ArmName, prompt: PreparedPromptV1, answer: str, item: RepairItemV1
) -> PreparedPromptV1 | None:
    """Builds the prompt an arm sends for one item, or None if none can be."""
    if arm == "resample":
        return prompt
    try:
        return follow_up_prompt(
            prompt, answer, item.card if arm == "counterexample" else None
        )
    except GenerationError:
        return None


def _check_prompts(run: _ArmRun, plan: RepairPlanV1, base: BasePass) -> None:
    """Requires an arm's prompts to be the plan's items, each as its arm builds.

    Raises:
        RoundError: With ``repair_items_mismatch`` when the run holds other
            items or another order than the plan, and
            ``repair_prompt_mismatch`` when a prompt is not the one its arm
            builds from the base prompt, the counted answer and the card.
    """
    name = run.run_dir.name
    if [prompt.item_id for prompt in run.prompts.prompts] != [
        item.item_id for item in plan.items
    ]:
        raise RoundError(
            "repair_items_mismatch",
            f"{name} does not hold the plan's items in plan order",
        )
    first = {prompt.item_id: prompt for prompt in base.prompts.prompts}
    for prompt, item in zip(run.prompts.prompts, plan.items, strict=True):
        answer = base.answers[item.item_id].response_text or ""
        if prompt != _arm_prompt(run.arm, first[item.item_id], answer, item):
            raise RoundError(
                "repair_prompt_mismatch",
                f"{name} {item.item_id}: not the {run.arm} arm's prompt",
            )


def _check_arm(
    arm: ArmName, path: Path, plan: RepairPlanV1, base: BasePass
) -> _ArmRun:
    """Requires one arm run's prompts to be its arm of this plan and base.

    Raises:
        RoundError: With ``repair_arm_mismatch`` when the run is not a C4
            run of the base's split and prepared inputs named after itself,
            a moved run prepared under its arm's registered first run id
            aside, and as :func:`_check_prompts` says.
        ScoringError: For any layout or prepare manifest failure.
    """
    name = path.name
    if path.is_symlink() or not path.is_dir():
        raise RoundError(
            "repair_arm_mismatch", f"{name} is not a run directory"
        )
    loaded = load_run(path, with_completions=False)
    manifest = loaded.manifest
    prepare = manifest.prepare if manifest is not None else loaded.prepare
    if prepare is None:
        raise RoundError("repair_arm_mismatch", f"{name} has no prepare record")
    check_prepare(prepare, loaded.prepared)
    if loaded.prepare is not None:
        check_prepare(loaded.prepare, loaded.prepared)
    split = check_splits(loaded.prepared, manifest, loaded.prepare)
    source = base.manifest.prepare
    # Follow-up builds only under the registered names, so a run a move
    # named otherwise is prepared under its arm's registered first id.
    registered = registered_run_ids(plan.base_run, arm)
    prepared_as = {name}
    if name in arm_run_ids(plan.base_run, arm) and name not in registered:
        prepared_as.add(registered[0])
    run_ids = {name}
    if manifest is not None:
        run_ids.add(manifest.run_id)
    if (
        set(loaded.prepared) != {REPAIR_CONDITION}
        or split != plan.split
        or run_ids != {name}
        or prepare.prepare_id not in prepared_as
        or (prepare.model_inputs_sha256, prepare.catalog, prepare.top_k)
        != (source.model_inputs_sha256, source.catalog, source.top_k)
    ):
        raise RoundError(
            "repair_arm_mismatch",
            f"{name} is not a C4 {arm} arm of {plan.base_run}",
        )
    run = _ArmRun(arm, path, loaded.prepared[REPAIR_CONDITION][0], manifest)
    _check_prompts(run, plan, base)
    return run


def _sent_as(
    base: RunManifestV1, move: ProviderMove | None
) -> dict[str, object]:
    """What an arm run of a base pass must record about how it was sent.

    It is the base's call config, except that a registered move replaces
    the provider order in its settings and its prices. A base sent without
    OpenRouter options has no provider order to replace, so no settings
    an arm run records match it.
    """
    sent = {setting: getattr(base, setting) for setting in _CALL_CONFIG}
    if move is not None:
        routes = base.settings.openrouter
        sent["settings"] = (
            None
            if routes is None
            else base.settings.model_copy(
                update={
                    "openrouter": routes.model_copy(
                        update={"provider_order": move.provider_order}
                    )
                }
            )
        )
        sent["prices"] = move.prices
    return sent


def _read_arm(run: _ArmRun, plan: RepairPlanV1, base: BasePass) -> ArmResult:
    """Reads one published arm run's scored outcomes and stored answers.

    Raises:
        RoundError: With ``repair_settings_mismatch`` when the run was not
            sent as the base pass was or, for a base with a registered
            provider move, with the move's provider order and prices and
            the base's other settings, host, attempt limit and pacing;
            ``repair_arms_incomplete`` when it is not complete,
            ``repair_arm_unscored`` when its scored tree does not score its
            prompts, and ``repair_items_mismatch`` when an item was scored
            on another case than in the base pass.
        ScoringError: For any layout, manifest or split failure.
    """
    name = run.run_dir.name
    manifest = run.manifest
    assert manifest is not None
    move = PROVIDER_MOVES.get(plan.base_run)
    if any(
        getattr(manifest, setting) != sent
        for setting, sent in _sent_as(base.manifest, move).items()
    ):
        raise RoundError(
            "repair_settings_mismatch",
            f"{name} was not sent with {plan.base_run}'s settings"
            + ("" if move is None else " as its registered move sends them"),
        )
    if manifest.status != "complete":
        raise RoundError("repair_arms_incomplete", f"{name} is not complete")
    try:
        scored = read_pass(run.run_dir)
        raw = read_bounded(run.run_dir / MANIFEST_NAME) or b""
    except (PairError, OSError):
        raise RoundError(
            "repair_arm_unscored", f"{name} is not scored"
        ) from None
    condition = scored.conditions[REPAIR_CONDITION]
    outcomes = {outcome.item_id: outcome for outcome in condition.outcomes}
    for item in plan.items:
        scored_on = outcomes[item.item_id]
        expected = base.outcomes[item.item_id]
        if (scored_on.case_id, scored_on.gold_status) != (
            expected.case_id,
            expected.gold_status,
        ):
            raise RoundError(
                "repair_items_mismatch",
                f"{name} {item.item_id}: scored on another case",
            )
    usage = scored.summary.conditions[REPAIR_CONDITION].usage
    return ArmResult(
        run=name,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        outcomes_sha256=scored.outcomes_sha256,
        outcomes={key: value.outcome for key, value in outcomes.items()},
        answers=condition.answers,
        output_contract=run.prompts.output_contract,
        latency_ms=(usage.latency_ms_p50, usage.latency_ms_p95),
        charged_usd_upper_bound=manifest.charged_usd_upper_bound,
        provider_reported_usd=manifest.provider_reported_usd,
    )


def _counted_arms(
    arms: Mapping[ArmName, Path],
    plan: RepairPlanV1,
    base: BasePass,
    not_run: Mapping[ArmName, NotRunReason],
) -> list[_ArmRun]:
    """Checks every arm run's prompts and returns those of the arms run.

    Raises:
        RoundError: With ``repair_arm_mismatch`` when an arm recorded as not
            run was published, and as :func:`_check_arm` says.
    """
    runs = [_check_arm(arm, path, plan, base) for arm, path in arms.items()]
    for run in runs:
        # A re-run replaces its arm's first run, whose prompts were sent
        # all the same and may be committed beside it.
        first = run.run_dir.parent / arm_run_ids(plan.base_run, run.arm)[0]
        if run.run_dir != first and os.path.lexists(first):
            _check_arm(run.arm, first, plan, base)
        if run.arm in not_run and run.manifest is not None:
            raise RoundError(
                "repair_arm_mismatch",
                f"{run.run_dir.name} is published, and the round records"
                f" its {run.arm} arm as not run",
            )
    return [run for run in runs if run.arm not in not_run]


def _encoded(value: FrozenModel) -> bytes:
    """Encodes a contract as committed: canonical JSON and one newline."""
    return (canonical_json(value) + "\n").encode("utf-8")


def _settle(
    root: Path, rendered: Mapping[Path, bytes], check: bool
) -> tuple[str, ...]:
    """Writes each rendered file under ``root``, or lists those that differ."""
    differences: list[str] = []
    for path, payload in rendered.items():
        if not check:
            write_whole(root / path, payload)
        elif committed_differs(root / path, payload):
            differences.append(path.as_posix())
    return tuple(differences)


def _summarize(
    run_dir: Path,
    plan: RepairPlanV1,
    base: BasePass,
    runs: Sequence[_ArmRun],
    not_run: Mapping[ArmName, NotRunReason],
) -> RepairSummaryV1:
    """Reads the base's scored tree and every arm run's, and summarizes them.

    Raises:
        RoundError: With ``base_unscored`` when the base pass's own scored
            tree cannot be read, and as :func:`_read_arm` says.
    """
    try:
        current = read_pass(run_dir)
    except PairError:
        raise RoundError(
            "base_unscored", f"{plan.base_run} has no usable scored tree"
        ) from None
    results: dict[ArmName, ArmResult] = {
        run.arm: _read_arm(run, plan, base) for run in runs
    }
    return summarize_round(
        plan,
        hashlib.sha256(plan_bytes(plan)).hexdigest(),
        RoundBase(
            model_id=base.manifest.settings.model_id,
            gold_hash=current.summary.gold_hash,
            outcomes=base.outcomes,
            now={
                outcome.item_id: outcome.outcome
                for outcome in current.conditions[REPAIR_CONDITION].outcomes
            },
            answers={
                item_id: answer.response_text
                for item_id, answer in base.answers.items()
            },
        ),
        results,
        not_run,
    )


def round_run(
    run_dir: Path,
    *,
    code_revision: str,
    check: bool = False,
    runner: TsharkRunner | None = None,
    not_run: Sequence[ArmName] = (),
) -> RepairReportV1:
    """Writes or checks a base pass's plan and, once its arms ran, its summary.

    With no arm run beside the pass this is the plan stage alone, which
    derives the plan again. Once any arm run exists, every arm not
    recorded as not run must have one, and the committed plan is read,
    checked against the pass and never rewritten (:func:`_committed_plan`);
    every arm's prompts are checked against it. Once every arm run is
    published and scored, the summary is written or checked.

    Args:
        run_dir: The base pass's published directory, beside its arm runs.
        code_revision: The revision this pass ran at; it is reported and
            never written into any file.
        check: Compare with the committed files instead of writing them.
        runner: The bounded tshark runner that builds every card.
        not_run: Arms whose runs the gate stopped, recorded in
            ``repair/not_run.json`` once the other arms check; a check
            reads the committed record instead.

    Returns:
        What was written, or which committed files differ.

    Raises:
        RoundError: When the round cannot be checked, as its codes say.
        RepairError: When the base pass cannot be planned.
        ScoringError: For any layout, manifest or split failure.
    """
    gated = _not_run(run_dir, not_run, check)
    arms = _locate(run_dir.absolute(), gated)
    if not arms:
        return plan_run(
            run_dir, code_revision=code_revision, check=check, runner=runner
        )[1]
    base = read_base(run_dir)
    plan, differences = _committed_plan(run_dir, base, check)
    runs = _counted_arms(arms, plan, base, gated)
    if not_run:
        write_whole(
            run_dir / NOT_RUN_PATH, _encoded(RepairNotRunV1(arms=gated))
        )
    report = plan_report(
        plan,
        run_dir,
        differences=differences,
        code_revision=code_revision,
        check=check,
    ).model_copy(
        update={
            "arm_runs": {arm: path.name for arm, path in arms.items()},
            "arms_not_run": gated,
            "stage": "prompts",
        }
    )
    published = [run.manifest is not None for run in runs]
    if not any(published):
        return report
    if not all(published):
        raise RoundError(
            "repair_arms_incomplete",
            f"{plan.base_run}: only some arm runs are published",
        )
    summary = _summarize(run_dir, plan, base, runs, gated)
    rendered = {
        SUMMARY_PATH: _encoded(summary),
        SUMMARY_REPORT_PATH: render_summary(summary).encode("utf-8"),
    }
    return report.model_copy(
        update={
            "stage": "summary",
            "summary_sha256": hashlib.sha256(
                rendered[SUMMARY_PATH]
            ).hexdigest(),
            "differences": report.differences
            + _settle(run_dir, rendered, check),
        }
    )


def _holds_second_turn(run_dir: Path) -> bool:
    """Reports whether a run's prompt sets hold a second turn or are unread."""
    for path in sorted((run_dir / "prepared").glob("*.json")):
        try:
            data = read_bounded(path)
            batch = (
                None
                if data is None
                else PreparedBatchV1.model_validate_json(data)
            )
        except (OSError, ValidationError):
            batch = None
        if batch is None or any(
            len(prompt.messages) > 2 for prompt in batch.prompts
        ):
            return True
    return False


def unchecked_second_turns(results_dir: Path) -> tuple[str, ...]:
    """Lists the committed runs whose second turns no repair check reaches.

    ``score --check`` rebuilds only the system and user messages of a
    prompt (:func:`dfilterforge.run_store.check_prompts`). The counted
    answer and the follow-up after them are checked by ``repair --check``
    alone, which reaches the arm runs, first runs and re-runs alike, named
    after a base pass with a committed ``repair/plan.json``. Any other run
    with a prompt of more than two messages is listed, and so is one with a
    prompt set that cannot be read as one.

    Args:
        results_dir: The directory holding every committed run.

    Returns:
        The listed runs' directory names, sorted.
    """
    checked: set[str] = set()
    for plan in results_dir.glob(f"*/{PLAN_PATH.as_posix()}"):
        for arm in ARMS:
            checked.update(arm_run_ids(plan.parent.parent.name, arm))
    return tuple(
        run_dir.name
        for run_dir in sorted(results_dir.iterdir())
        if run_dir.name not in checked
        and (run_dir / "prepared").is_dir()
        and _holds_second_turn(run_dir)
    )


def _committed_bases(target: Path) -> tuple[str, ...]:
    """Reads which bases a committed pool names, for a check of it.

    Raises:
        RoundError: With ``repair_pool_bases_invalid`` when the committed
            pool cannot be read.
    """
    try:
        data = read_bounded(target)
        committed = (
            None if data is None else RepairPoolV1.model_validate_json(data)
        )
    except (OSError, ValidationError):
        committed = None
    if committed is None:
        raise RoundError(
            "repair_pool_bases_invalid",
            f"{target.name} cannot be read to name its bases",
        )
    return tuple(base.run for base in committed.bases)


def _read_summary(
    results_dir: Path, run: str, split: str
) -> tuple[RepairSummaryV1, str]:
    """Reads one base's committed summary and the digest of its bytes.

    Raises:
        RoundError: With ``repair_pool_unsummarized`` when it cannot be
            read, and ``repair_pool_mismatch`` when it is another pass's.
    """
    try:
        data = read_bounded(results_dir / run / SUMMARY_PATH)
        summary = (
            None if data is None else RepairSummaryV1.model_validate_json(data)
        )
    except (OSError, ValidationError):
        data, summary = None, None
    if data is None or summary is None:
        raise RoundError(
            "repair_pool_unsummarized", f"{run} has no usable repair summary"
        )
    if (summary.base_run, summary.split) != (run, split):
        raise RoundError(
            "repair_pool_mismatch", f"{run}'s summary is another pass's"
        )
    return summary, hashlib.sha256(data).hexdigest()


def pool_run(
    results_dir: Path,
    split: Literal["dev", "test"],
    bases: Sequence[str] = (),
    *,
    code_revision: str,
    check: bool = False,
) -> PoolReportV1:
    """Writes or checks ``repair-pool/<split>.json`` and its report.

    Args:
        results_dir: The directory holding every base pass.
        split: The split pooled.
        bases: The base passes' run ids; a check with none takes those the
            committed pool names.
        code_revision: The revision this pass ran at; it is reported and
            never written into any file.
        check: Compare with the committed files instead of writing them.

    Returns:
        What was written, or which committed files differ.

    Raises:
        RoundError: When the bases cannot be pooled, as its codes say.
    """
    rendered_path = Path(POOL_DIR) / f"{split}.json"
    named = tuple(bases)
    if not named and check:
        named = _committed_bases(results_dir / rendered_path)
    if (
        not named
        or len(set(named)) != len(named)
        or any(
            _RESULT_DIR.fullmatch(run) is None
            or not run.startswith(f"{split}-")
            for run in named
        )
    ):
        raise RoundError(
            "repair_pool_bases_invalid",
            f"Name one or more distinct {split} base passes",
        )
    runs = tuple(sorted(named))
    pooled = pool_summaries(
        split, [_read_summary(results_dir, run, split) for run in runs]
    )
    rendered = {
        rendered_path: _encoded(pooled),
        rendered_path.with_suffix(".md"): render_pool(pooled).encode("utf-8"),
    }
    return PoolReportV1(
        pool_path=results_dir / rendered_path,
        checked=check,
        code_revision=code_revision,
        bases=runs,
        pool_sha256=hashlib.sha256(rendered[rendered_path]).hexdigest(),
        differences=_settle(results_dir, rendered, check),
    )
