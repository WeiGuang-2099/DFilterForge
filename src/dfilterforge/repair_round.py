"""Reading and checking a repair round's committed runs.

A repair round sends each triggered item of a base pass's plan once in each
of three arms, as ordinary C4 runs named after the base run with ``-res``,
``-bare`` or ``-cx`` before its date; the one re-run an outage allows adds
``-r2`` after the tag and replaces its arm. :func:`round_run` is the
``dfilterforge repair`` command. It writes or checks the plan and, once arm
runs exist beside the base pass, requires all three and checks each one:

- one C4 condition on the base's split and prepared inputs, named after its
  arm, over the plan's items in plan order;
- every prompt the one its arm builds: the base prompt itself for the
  resample, that prompt continued by the counted answer and the follow-up
  for bare, and the same with the item's card for counterexample;
- once published, the base's request settings, prices, endpoint host,
  attempt limit and pacing, a complete run and a scored tree that scores
  every item on the case the base pass scored it on.

With all three published and scored it writes or checks
``repair/summary.json`` and ``repair/summary.md``, which
:mod:`dfilterforge.repair_summary` derives and
:mod:`dfilterforge.repair_report` prints. :func:`pool_run` does the same for
``repair-pool/<split>.json`` from the committed summaries of several bases.

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
from dfilterforge.repair import plan_run
from dfilterforge.repair import read_base
from dfilterforge.repair import read_bounded
from dfilterforge.repair import REPAIR_CONDITION
from dfilterforge.repair import RepairReportV1
from dfilterforge.repair import write_whole
from dfilterforge.repair_report import render_pool
from dfilterforge.repair_report import render_summary
from dfilterforge.repair_summary import ArmName
from dfilterforge.repair_summary import ArmResult
from dfilterforge.repair_summary import ARMS
from dfilterforge.repair_summary import pool_summaries
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
SUMMARY_REPORT_PATH = Path("repair") / "summary.md"
POOL_DIR = "repair-pool"

_DATE_LENGTH = 10
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


def arm_run_ids(base_run: str, arm: ArmName) -> tuple[str, str]:
    """Names one arm's run and its one re-run after the base run.

    Args:
        base_run: The base pass's run id, ending in its date.
        arm: The arm.

    Returns:
        The arm's run id and the run id of its re-run.
    """
    stem, date = base_run[: -_DATE_LENGTH - 1], base_run[-_DATE_LENGTH:]
    tagged = f"{stem}-{ARM_TAGS[arm]}"
    return f"{tagged}-{date}", f"{tagged}-{ARM_RERUN}-{date}"


def _locate(base_dir: Path) -> dict[ArmName, Path]:
    """Finds the arm runs beside a base pass, a re-run before its first run.

    Raises:
        RoundError: With ``repair_arms_incomplete`` when some arm has a run
            and another has none.
    """
    found: dict[ArmName, Path] = {}
    for arm in ARMS:
        first, rerun = arm_run_ids(base_dir.name, arm)
        for name in (rerun, first):
            path = base_dir.parent / name
            if os.path.lexists(path):
                found[arm] = path
                break
    if found and len(found) != len(ARMS):
        missing = ", ".join(arm for arm in ARMS if arm not in found)
        raise RoundError(
            "repair_arms_incomplete", f"{base_dir.name}: no {missing} arm run"
        )
    return found


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
            and as :func:`_check_prompts` says.
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
    names = {prepare.prepare_id, name}
    if manifest is not None:
        names.add(manifest.run_id)
    if (
        set(loaded.prepared) != {REPAIR_CONDITION}
        or split != plan.split
        or names != {name}
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


def _read_arm(run: _ArmRun, plan: RepairPlanV1, base: BasePass) -> ArmResult:
    """Reads one published arm run's scored outcomes and stored answers.

    Raises:
        RoundError: With ``repair_settings_mismatch`` when the run was not
            sent as the base pass was, ``repair_arms_incomplete`` when it
            is not complete, ``repair_arm_unscored`` when its scored tree
            does not score its prompts, and ``repair_items_mismatch`` when
            an item was scored on another case than in the base pass.
        ScoringError: For any layout, manifest or split failure.
    """
    name = run.run_dir.name
    manifest = run.manifest
    assert manifest is not None
    if any(
        getattr(manifest, setting) != getattr(base.manifest, setting)
        for setting in _CALL_CONFIG
    ):
        raise RoundError(
            "repair_settings_mismatch",
            f"{name} was not sent with {plan.base_run}'s settings",
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
    run_dir: Path, plan: RepairPlanV1, base: BasePass, runs: Sequence[_ArmRun]
) -> RepairSummaryV1:
    """Reads the base's scored tree and every arm's, and summarizes them.

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
    )


def round_run(
    run_dir: Path,
    *,
    code_revision: str,
    check: bool = False,
    runner: TsharkRunner | None = None,
) -> RepairReportV1:
    """Writes or checks a base pass's plan and, once its arms ran, its summary.

    With no arm run beside the pass this is the plan stage alone. Once any
    arm run exists, all three must, the committed plan must be the one
    derived now and is never rewritten, and every arm's prompts are
    checked. Once all three are published and scored, the summary is
    written or checked.

    Args:
        run_dir: The base pass's published directory, beside its arm runs.
        code_revision: The revision this pass ran at; it is reported and
            never written into any file.
        check: Compare with the committed files instead of writing them.
        runner: The bounded tshark runner that builds every card.

    Returns:
        What was written, or which committed files differ.

    Raises:
        RoundError: When the round cannot be checked, as its codes say.
        RepairError: When the base pass cannot be planned.
        ScoringError: For any layout, manifest or split failure.
    """
    arms = _locate(run_dir.absolute())
    plan, report = plan_run(
        run_dir,
        code_revision=code_revision,
        check=check or bool(arms),
        runner=runner,
    )
    if not arms:
        return report
    if report.differences and not check:
        raise RoundError(
            "repair_plan_changed",
            f"{plan.base_run}: arm runs exist, and the committed plan is not"
            " the one derived now",
        )
    base = read_base(run_dir)
    runs = [_check_arm(arm, arms[arm], plan, base) for arm in ARMS]
    stage: dict[str, object] = {
        "checked": check,
        "arm_runs": {run.arm: run.run_dir.name for run in runs},
        "stage": "prompts",
    }
    published = [run.manifest is not None for run in runs]
    if not any(published):
        return report.model_copy(update=stage)
    if not all(published):
        raise RoundError(
            "repair_arms_incomplete",
            f"{plan.base_run}: only some arm runs are published",
        )
    summary = _summarize(run_dir, plan, base, runs)
    rendered = {
        SUMMARY_PATH: _encoded(summary),
        SUMMARY_REPORT_PATH: render_summary(summary).encode("utf-8"),
    }
    return report.model_copy(
        update=stage
        | {
            "stage": "summary",
            "summary_sha256": hashlib.sha256(
                rendered[SUMMARY_PATH]
            ).hexdigest(),
            "differences": report.differences
            + _settle(run_dir, rendered, check),
        }
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
