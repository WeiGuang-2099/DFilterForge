"""Repair plans: the triggered C4 items of one scored pass and their cards.

A repair round continues every C4 item whose counted outcome in its base
pass is silent-wrong or invalid, whatever its finish reason. This module
reads that trigger set from the committed scored outcomes and builds each
item's card with :class:`dfilterforge.counterexample.CardBuilder` on its
split's unscored feedback probe, offline, in the lab container. The result
is ``repair/plan.json`` beside the pass: canonical JSON with no timestamp
and no revision, so ``--check`` derives it again and compares bytes.

The base pass is read as scoring reads it, with every digest checked, and
must be complete and scored; each triggered answer, parsed again by the
scorer's parser, must equal the intent the scorer committed for it. The
scored probes' captures are deleted from the regenerated split before the
first card is built, so a card can only come from the feedback probe, and
on test the feedback labels must be the ones the freeze record quotes.

No module that builds prompts, calls a model or scores imports this one.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from typing import Literal, NamedTuple

from pydantic import Field
from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import RepairItemV1
from dfilterforge.completions import RepairPlanV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.counterexample import card_json
from dfilterforge.counterexample import CardBuilder
from dfilterforge.counterexample import CounterexampleCardV1
from dfilterforge.counterexample import FramesCardV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import GenerationError
from dfilterforge.generation import parse_response
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.held_out import load_record
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import FEEDBACK_PROBE_IDS
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import GoldCase
from dfilterforge.model_split import ModelSplit
from dfilterforge.run_store import check_manifest
from dfilterforge.run_store import check_prepare
from dfilterforge.run_store import check_prompts
from dfilterforge.run_store import check_splits
from dfilterforge.run_store import load_run
from dfilterforge.run_store import MANIFEST_NAME
from dfilterforge.run_store import MAX_RUN_FILE_BYTES
from dfilterforge.run_store import SCORED_NAME
from dfilterforge.run_store import selected_cases
from dfilterforge.runner import TsharkRunner
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1

PLAN_PATH = Path("repair") / "plan.json"
REPAIR_CONDITION: ConditionLabel = "C4"
# A gold or scorer correction keeps the pass's first outcomes here, and the
# trigger set is the one those outcomes give.
ORIGINAL_SCORED_NAME = "scored-original"
CardKind = Literal["frames", "error", "none"]
Trigger = Literal["silent_wrong", "invalid"]
_TRIGGERS: Mapping[OutcomeV1, Trigger] = {
    OutcomeV1.SILENT_WRONG: "silent_wrong",
    OutcomeV1.INVALID: "invalid",
}
_CARD_KINDS: tuple[CardKind, ...] = ("error", "frames", "none")
_OUTCOMES_NAME = "outcomes.jsonl"


class RepairError(DFilterForgeError, RuntimeError):
    """A refused repair plan, with a stable public code.

    The codes are ``base_incomplete``, ``base_condition_missing``,
    ``base_unscored``, ``outcomes_mismatch``, ``intent_mismatch`` and
    ``feedback_labels_mismatch``. A message names a file, an item id or a
    case id, never model text.
    """


class RepairReportV1(FrozenModel):
    """What one repair pass wrote, or how the committed files compare.

    ``stage`` is how far the round has come: ``plan`` when no arm run
    exists beside the base pass, ``prompts`` when the three arms' prompt
    sets are committed but not yet answered, and ``summary`` once all
    three are published and scored. ``arm_runs`` maps each arm to the run
    it was read from, and ``summary_sha256`` is the digest of the summary
    written or derived, both empty before that stage.
    """

    schema_version: Literal["repair-report/1.0"] = "repair-report/1.0"
    plan_path: Path
    checked: bool
    code_revision: str
    base_run: str
    items: int = Field(ge=0)
    card_kinds: dict[str, int]
    plan_sha256: str
    stage: Literal["plan", "prompts", "summary"] = "plan"
    arm_runs: dict[str, str] = Field(default_factory=dict)
    summary_sha256: str | None = None
    differences: tuple[str, ...] = ()


class BasePass(NamedTuple):
    """The parts of a complete, scored base pass a plan is built from.

    ``outcomes`` are the C4 outcomes the trigger is read from: those of
    ``scored-original/`` once a correction kept them, else ``scored/``.
    """

    manifest: RunManifestV1
    manifest_sha256: str
    split: ModelSplit
    prompts: PreparedBatchV1
    prompts_sha256: str
    answers: Mapping[str, CompletionV1]
    outcomes: Mapping[str, ItemOutcomeV1]
    outcomes_sha256: str


def read_bounded(path: Path) -> bytes | None:
    """Reads one bounded regular file, or returns None when it is absent.

    Raises:
        OSError: When the path is a symlink, not a regular file, over
            ``MAX_RUN_FILE_BYTES`` or unreadable.
    """
    if not os.path.lexists(path):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise OSError("not a regular file")
        data = source.read(MAX_RUN_FILE_BYTES + 1)
    if len(data) > MAX_RUN_FILE_BYTES:
        raise OSError("file exceeds its byte limit")
    return data


def _required(path: Path, code: str, message: str) -> bytes:
    """Reads a file the plan needs, refusing with ``code`` otherwise."""
    try:
        data = read_bounded(path)
    except OSError:
        data = None
    if data is None:
        raise RepairError(code, message)
    return data


def _read_outcomes(
    run_dir: Path, prompts: PreparedBatchV1
) -> tuple[dict[str, ItemOutcomeV1], str]:
    """Reads the base pass's C4 outcomes and the digest of their file.

    Raises:
        RepairError: With ``base_unscored`` when no readable outcome file
            covers exactly the committed C4 prompts once each.
    """
    original = run_dir / ORIGINAL_SCORED_NAME
    tree = original if original.is_dir() else run_dir / SCORED_NAME
    name = f"{tree.name}/{_OUTCOMES_NAME}"
    raw = _required(
        tree / _OUTCOMES_NAME, "base_unscored", f"{name} cannot be read"
    )
    outcomes: dict[str, ItemOutcomeV1] = {}
    for line in raw.split(b"\n"):
        if not line:
            continue
        try:
            outcome = ItemOutcomeV1.model_validate_json(line)
        except ValidationError:
            raise RepairError(
                "base_unscored", f"{name} holds an unreadable line"
            ) from None
        if outcome.condition != REPAIR_CONDITION:
            continue
        if outcome.item_id in outcomes:
            raise RepairError(
                "base_unscored", f"{name} scores {outcome.item_id} twice"
            )
        outcomes[outcome.item_id] = outcome
    if set(outcomes) != {prompt.item_id for prompt in prompts.prompts}:
        raise RepairError(
            "base_unscored", f"{name} does not score the C4 prompts"
        )
    return outcomes, hashlib.sha256(raw).hexdigest()


def read_base(run_dir: Path) -> BasePass:
    """Reads a complete, scored base pass, checking every digest.

    Args:
        run_dir: The base pass's published directory.

    Returns:
        Its manifest, C4 prompts and answers, and the C4 outcomes the
        trigger is read from, each with the digest of the bytes read.

    Raises:
        RepairError: When the pass is incomplete, prepared no C4 or is not
            scored.
        ScoringError: For any layout, manifest or split failure.
    """
    raw = _required(
        run_dir / MANIFEST_NAME, "base_incomplete", "The pass has no manifest"
    )
    loaded = load_run(run_dir)
    try:
        recorded = RunManifestV1.model_validate_json(raw)
    except ValidationError:
        recorded = None
    # The digest the plan records must be of the manifest that was checked.
    if (
        loaded.manifest is None
        or loaded.manifest != recorded
        or loaded.manifest.status != "complete"
    ):
        raise RepairError("base_incomplete", "The pass is not complete")
    if loaded.prepare is not None:
        check_prepare(loaded.prepare, loaded.prepared)
    check_manifest(loaded.manifest, loaded.prepared, loaded.completions)
    check_splits(loaded.prepared, loaded.manifest, loaded.prepare)
    if REPAIR_CONDITION not in loaded.prepared:
        raise RepairError(
            "base_condition_missing", "The pass did not prepare C4"
        )
    prompts, prompts_sha256 = loaded.prepared[REPAIR_CONDITION]
    outcomes, outcomes_sha256 = _read_outcomes(run_dir, prompts)
    return BasePass(
        manifest=loaded.manifest,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        # check_splits tied every prompt to the manifest's split.
        split=loaded.manifest.prepare.split,
        prompts=prompts,
        prompts_sha256=prompts_sha256,
        answers={
            answer.item_id: answer
            for answer in loaded.completions[REPAIR_CONDITION].completions
        },
        outcomes=outcomes,
        outcomes_sha256=outcomes_sha256,
    )


def triggers(base: BasePass) -> tuple[tuple[str, Trigger], ...]:
    """Lists the triggered C4 items of a base pass and what triggered each.

    Args:
        base: The base pass, with the outcomes the trigger is read from.

    Returns:
        Each silent-wrong or invalid C4 item's id and outcome, in prepare
        order.
    """
    triggered: list[tuple[str, Trigger]] = []
    for prompt in base.prompts.prompts:
        trigger = _TRIGGERS.get(base.outcomes[prompt.item_id].outcome)
        if trigger is not None:
            triggered.append((prompt.item_id, trigger))
    return tuple(triggered)


def ready_intent(
    run_dir: Path, prompt: PreparedPromptV1, completion: CompletionV1
) -> IntentIrV1:
    """Parses a triggered answer and ties it to the scorer's committed intent.

    Args:
        run_dir: The base pass's published directory.
        prompt: The item's committed C4 prompt.
        completion: The item's stored answer.

    Returns:
        The ready typed IR the answer parses to.

    Raises:
        RepairError: With ``outcomes_mismatch`` when the stored answer is not
            a ready typed IR, and ``intent_mismatch`` when it differs from
            ``scored/intents/C4/<item>.json``.
    """
    item_id = prompt.item_id
    parsed = None
    if completion.status is CompletionStatusV1.COMPLETED:
        try:
            parsed = parse_response(
                prompt.output_contract, completion.response_text or ""
            )
        except GenerationError:
            parsed = None
    if (
        not isinstance(parsed, GenerationResultV1)
        or parsed.status is not GenerationStatus.READY
        or parsed.intent_ir is None
    ):
        raise RepairError(
            "outcomes_mismatch", f"{item_id}: the triggered answer is not ready"
        )
    intents = run_dir / SCORED_NAME / "intents" / REPAIR_CONDITION
    committed = _required(
        intents / f"{item_id}.json",
        "intent_mismatch",
        f"{item_id}: no committed intent",
    )
    if committed != (canonical_json(parsed.intent_ir) + "\n").encode("utf-8"):
        raise RepairError(
            "intent_mismatch", f"{item_id}: the answer is not the scored intent"
        )
    return parsed.intent_ir


def _check_frozen_labels(split: str, digest: str) -> None:
    """Requires the test feedback labels the freeze record quotes.

    Raises:
        RepairError: With ``feedback_labels_mismatch`` on test when the
            record is absent or quotes another digest.
        HeldOutError: When the committed record is unusable.
    """
    if split != "test":
        return
    record = load_record()
    if record is None or record.digests.get("feedback_labels") != digest:
        raise RepairError(
            "feedback_labels_mismatch",
            "The test feedback labels are not the frozen ones",
        )


def _plan_item(
    item_id: str,
    trigger: Trigger,
    card: CounterexampleCardV1 | None,
) -> RepairItemV1:
    """Records one triggered item with its card's kind and canonical text."""
    if card is None:
        return RepairItemV1(
            item_id=item_id, base_outcome=trigger, card_kind="none"
        )
    return RepairItemV1(
        item_id=item_id,
        base_outcome=trigger,
        card_kind="frames" if isinstance(card, FramesCardV1) else "error",
        card=card_json(card),
    )


def _plan_items(
    run_dir: Path,
    base: BasePass,
    routes: Mapping[str, GoldCase],
    builder: CardBuilder,
) -> tuple[RepairItemV1, ...]:
    """Builds the card of each triggered item, in prepare order.

    Raises:
        RepairError: With ``outcomes_mismatch`` when an outcome was scored
            on another case than its item routes to.
    """
    items: list[RepairItemV1] = []
    for prompt in base.prompts.prompts:
        outcome = base.outcomes[prompt.item_id]
        case_id = routes[prompt.item_id].case_id
        if outcome.case_id != case_id:
            raise RepairError(
                "outcomes_mismatch",
                f"{prompt.item_id}: scored on a case other than {case_id}",
            )
        trigger = _TRIGGERS.get(outcome.outcome)
        if trigger is None:
            continue
        answer = ready_intent(run_dir, prompt, base.answers[prompt.item_id])
        card = builder.card(case_id, answer)
        items.append(_plan_item(prompt.item_id, trigger, card))
    return tuple(items)


def build_plan(
    run_dir: Path, *, runner: TsharkRunner | None = None
) -> RepairPlanV1:
    """Derives the repair plan of one complete, scored base pass.

    Args:
        run_dir: The base pass's published directory.
        runner: The bounded tshark runner that builds every card.

    Returns:
        The triggered C4 items in prepare order, each with its card.

    Raises:
        RepairError: When the base pass cannot be planned, as its codes say.
        ScoringError: For a layout, manifest, split or prompt failure.
        CounterexampleError: When a card cannot be built.
    """
    base = read_base(run_dir)
    with TemporaryDirectory(prefix="dfilterforge-repair-") as temporary:
        artifacts = generate_model_split(Path(temporary))
        feedback = generate_feedback_probes(artifacts)
        # The feedback copies are written; no card may read a scored probe.
        for capture in artifacts.capture_paths:
            capture.unlink()
        routes, _, _ = selected_cases(
            base.prompts.prompts, artifacts.gold, base.split
        )
        check_prompts(
            {REPAIR_CONDITION: (base.prompts, base.prompts_sha256)},
            {item.item_id: item for item in artifacts.inputs},
        )
        labels_sha256 = feedback_labels_sha256(feedback, base.split)
        _check_frozen_labels(base.split, labels_sha256)
        items = _plan_items(
            run_dir, base, routes, CardBuilder(feedback, runner)
        )
    return RepairPlanV1.model_validate(
        {
            "split": base.split,
            "base_run": base.manifest.run_id,
            "base_run_manifest_sha256": base.manifest_sha256,
            "base_outcomes_sha256": base.outcomes_sha256,
            "feedback_labels_sha256": labels_sha256,
            "feedback_probe": FEEDBACK_PROBE_IDS[base.split],
            "items": items,
        }
    )


def plan_bytes(plan: RepairPlanV1) -> bytes:
    """Encodes a plan as committed: canonical JSON and one newline."""
    return (canonical_json(plan) + "\n").encode("utf-8")


def write_whole(path: Path, payload: bytes) -> None:
    """Replaces one file whole, so no torn file survives a failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.partial")
    staging.write_bytes(payload)
    os.replace(staging, path)


def committed_differs(path: Path, rendered: bytes) -> bool:
    """Reports whether a committed file is missing or other than ``rendered``.

    A file that cannot be read as a bounded regular file differs.
    """
    try:
        committed = read_bounded(path)
    except OSError:
        committed = None
    return committed != rendered


def plan_report(
    plan: RepairPlanV1,
    run_dir: Path,
    *,
    check: bool,
    code_revision: str,
    differences: tuple[str, ...] = (),
) -> RepairReportV1:
    """Reports a plan written, checked or read beside its base pass.

    Args:
        plan: The plan.
        run_dir: The base pass's published directory.
        check: Whether the committed plan was compared rather than written.
        code_revision: The revision this pass ran at.
        differences: The committed files found to differ.

    Returns:
        The plan stage's report; ``plan_sha256`` is the digest of the
        plan's canonical bytes.
    """
    kinds = {kind: 0 for kind in _CARD_KINDS}
    for item in plan.items:
        kinds[item.card_kind] += 1
    return RepairReportV1(
        plan_path=run_dir / PLAN_PATH,
        checked=check,
        code_revision=code_revision,
        base_run=plan.base_run,
        items=len(plan.items),
        card_kinds=kinds,
        plan_sha256=hashlib.sha256(plan_bytes(plan)).hexdigest(),
        differences=differences,
    )


def plan_run(
    run_dir: Path,
    *,
    code_revision: str,
    check: bool = False,
    runner: TsharkRunner | None = None,
) -> tuple[RepairPlanV1, RepairReportV1]:
    """Writes a base pass's repair plan, or checks the committed one.

    Args:
        run_dir: The base pass's published directory.
        code_revision: The revision this pass ran at; it is reported and
            never written into the plan.
        check: Compare with the committed plan instead of writing it.
        runner: The bounded tshark runner that builds every card.

    Returns:
        The plan derived now, and what was written or whether the
        committed plan differs from it.

    Raises:
        RepairError: When the base pass cannot be planned.
    """
    plan = build_plan(run_dir, runner=runner)
    rendered = plan_bytes(plan)
    target = run_dir / PLAN_PATH
    differences: tuple[str, ...] = ()
    if check:
        if committed_differs(target, rendered):
            differences = (PLAN_PATH.as_posix(),)
    else:
        write_whole(target, rendered)
    return plan, plan_report(
        plan,
        run_dir,
        check=check,
        code_revision=code_revision,
        differences=differences,
    )


def repair_run(
    run_dir: Path,
    *,
    code_revision: str,
    check: bool = False,
    runner: TsharkRunner | None = None,
) -> RepairReportV1:
    """Writes a base pass's repair plan, or checks the committed one.

    This is the plan stage alone; :func:`dfilterforge.repair_round.round_run`
    adds the arm runs once they exist.

    Args:
        run_dir: The base pass's published directory.
        code_revision: The revision this pass ran at; it is reported and
            never written into the plan.
        check: Compare with the committed plan instead of writing it.
        runner: The bounded tshark runner that builds every card.

    Returns:
        What was written, or whether the committed plan differs.

    Raises:
        RepairError: When the base pass cannot be planned.
    """
    return plan_run(
        run_dir, code_revision=code_revision, check=check, runner=runner
    )[1]
