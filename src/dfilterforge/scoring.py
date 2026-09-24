"""Offline scoring of stored completions against regenerated gold.

Nothing here contacts a network; the only executable boundary is tshark
through live.evaluate_live. Gold is verified before a single model answer is
read, the committed prompts are re-prepared so the item-to-case join is
provably the one the model saw, and only a failure attributable to the
candidate is counted against it.

Reading the run directory and writing the scored tree live one module away,
in :mod:`dfilterforge.run_store`; this module owns the verdicts.
"""

# The scoring entry points thread run identity through every helper.
# pylint: disable=too-many-arguments,too-many-positional-arguments

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, NamedTuple, TypeAlias, TypedDict

from pydantic import Field

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.catalog_runtime import tshark_types
from dfilterforge.compiler import CompileError
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.field_catalog import CatalogError
from dfilterforge.generation import condition_label
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import GenerationError
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.live import evaluate_live
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.live import packet_set_hash
from dfilterforge.model_cases import ModelNonReadyCaseV1
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import GoldCase
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.run_store import check_manifest
from dfilterforge.run_store import check_prepare
from dfilterforge.run_store import check_prompts
from dfilterforge.run_store import check_splits
from dfilterforge.run_store import compare
from dfilterforge.run_store import load_run
from dfilterforge.run_store import render
from dfilterforge.run_store import SCORED_NAME
from dfilterforge.run_store import ScoringError
from dfilterforge.run_store import selected_cases
from dfilterforge.run_store import summarize_run
from dfilterforge.run_store import write_scored
from dfilterforge.runner import RunnerError
from dfilterforge.runner import TsharkRunner
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.shortcuts import find_shortcuts
from dfilterforge.shortcuts import references
from dfilterforge.shortcuts import ShortcutHitV1

# Gold is verified before any model answer is read, so once scoring starts
# only the candidate can still raise one of these codes.
_MODEL_ERROR_CODES: dict[type[DFilterForgeError], frozenset[str]] = {
    CatalogError: frozenset(
        {
            "unknown_field",
            "ambiguous_field",
            "unsupported_type",
            "unsupported_operator",
            "type_mismatch",
        }
    ),
    CompileError: frozenset({"invalid_value"}),
    RunnerError: frozenset(
        {
            "filter_invalid",
            "filter_too_large",
            "filter_rejected",
            "filter_unknown_field",
        }
    ),
}
# A resource bound is reachable from either side, so a candidate is only
# charged with one once the same gold case still runs clean.
_CANDIDATE_RESOURCE_CODES = frozenset(
    {"timeout", "output_limit", "frame_limit"}
)
# The abstention channel is derived from the parsed status itself, so a
# fourth generation status raises here instead of being misfiled as an
# over-abstention and corrupting the protocol's false-ready split.
_ABSTENTIONS: dict[
    GenerationStatus, Literal["needs_clarification", "not_expressible"]
] = {
    GenerationStatus.NEEDS_CLARIFICATION: "needs_clarification",
    GenerationStatus.NOT_EXPRESSIBLE: "not_expressible",
}
# With neither a run manifest nor a committed prepare manifest there is no
# recorded timestamp at all. This fixed placeholder reaches the receipts and
# nothing else, and the receipt comparison normalizes created_at away.
_PLACEHOLDER_CREATED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)
# A control pass answers the committed prompts from gold instead of from a
# provider, so the scorer, the gold and the prompts themselves are exercised
# against real tshark before anything is paid for.
ControlMode: TypeAlias = Literal["reference", "mutation"]
_CONTROL_DIRECTORIES: dict[ControlMode, str] = {
    "reference": "control-reference",
    "mutation": "control-mutation",
}
# Gold records one authored near-wrong filter per case and no near-wrong
# typed target, so the typed conditions have nothing to answer under the
# mutation control and are reported as skipped rather than dropped silently.
_NO_TYPED_MUTATION = "no_typed_mutation"
# The mutation control answers non-ready gold with a ready filter, so the
# false-ready channel is exercised the way a wrong filter exercises the
# silent-wrong one.
_FALSE_READY_CONTROL_FILTER = "ip"
_CONTROL_QUESTION = "Which value do you mean?"


class ScoreReportV1(FrozenModel):
    """What one scoring pass wrote, or what it found already committed."""

    schema_version: Literal["score-report/1.0"] = "score-report/1.0"
    output_dir: Path
    checked: bool
    items: int = Field(ge=0)
    outcomes: dict[str, int]
    summary_sha256: str
    differences: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Execution:
    """The run identity every live execution of one pass shares."""

    capture_root: Path
    run_id: str
    created_at: datetime
    code_revision: str
    runner: TsharkRunner


class _ItemFields(TypedDict):
    """The outcome fields every verdict carries, whatever the verdict."""

    gold_status: Literal["ready", "needs_clarification", "not_expressible"]
    condition: ConditionLabel
    item_id: str
    case_id: str
    finish_reason: str | None
    gold_field_count: int
    retrieved_field_count: int
    retrieved_gold_field_count: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float


def _item_fields(
    prompt: PreparedPromptV1,
    completion: CompletionV1,
    case: GoldCase,
    label: ConditionLabel,
) -> _ItemFields:
    """Collects the fields that do not depend on the verdict.

    Non-ready gold has no target fields, so its gold field count is zero.
    """
    gold_fields: set[str] = (
        set()
        if isinstance(case, ModelNonReadyCaseV1)
        else {
            predicate.field
            for _, predicate in walk_predicates(
                case.spec.canonical_ir.expression
            )
        }
    )
    shown = {field.abbreviation for field in prompt.retrieved_fields}
    return _ItemFields(
        gold_status=(
            case.status if isinstance(case, ModelNonReadyCaseV1) else "ready"
        ),
        condition=label,
        item_id=prompt.item_id,
        case_id=case.case_id,
        finish_reason=completion.finish_reason,
        gold_field_count=len(gold_fields),
        retrieved_field_count=len(prompt.retrieved_fields),
        retrieved_gold_field_count=(
            None
            if prompt.retrieval is RetrievalV1.NONE
            else len(gold_fields & shown)
        ),
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
    )


def _verify_case(
    case: ModelGoldCaseV1, context: _Execution
) -> LiveEnvironmentV1 | None:
    """Runs one case's canonical IR and returns its environment when exact."""
    receipt, environment = evaluate_live(
        case.spec,
        case.spec.canonical_ir,
        context.capture_root,
        run_id=context.run_id,
        created_at=context.created_at,
        code_revision=context.code_revision,
        runner=context.runner,
    )
    if not all(probe.exact for probe in receipt.probes):
        return None
    return environment


def _case_is_healthy(case: ModelGoldCaseV1, context: _Execution) -> bool:
    """Reports whether the same gold case still runs clean right now."""
    recheck = replace(context, run_id=f"{context.run_id}-recheck")
    try:
        return _verify_case(case, recheck) is not None
    except DFilterForgeError:
        return False


def _shortcuts(
    candidate: IntentIrV1 | str, request: str
) -> tuple[tuple[ShortcutHitV1, ...], int]:
    """Returns the shortcut rules a candidate breaks and its OR count."""
    found = references(candidate)
    return (
        find_shortcuts(found, request, tshark_types(found.fields)),
        found.disjunctions,
    )


class _StatusFields(TypedDict, total=False):
    """How an answer's status and slots compare with non-ready gold."""

    status_match: bool
    slot_match: bool


def _status_fields(
    case: GoldCase,
    status: GenerationStatus | None,
    slots: tuple[MissingSlot, ...] = (),
) -> _StatusFields:
    """Compares an answer's status and slots with non-ready gold.

    Ready gold gets neither field. For non-ready gold, ``status`` is None
    when there was no parsed answer, which matches nothing. Slot match is
    set for needs_clarification gold only: the answer must ask for
    clarification and name at least one gold slot.
    """
    if not isinstance(case, ModelNonReadyCaseV1):
        return _StatusFields()
    fields = _StatusFields(status_match=status == case.status)
    if case.status == GenerationStatus.NEEDS_CLARIFICATION:
        fields["slot_match"] = status == case.status and bool(
            set(slots) & set(case.missing_slots)
        )
    return fields


def _attributable_code(
    error: DFilterForgeError, case: ModelGoldCaseV1, context: _Execution
) -> str | None:
    """Returns the code to charge the candidate, or None to stop scoring.

    A resource bound is reachable from the reference side too, so it is
    charged to the candidate only once the same gold case reruns clean.
    """
    if isinstance(error, RunnerError) and (
        error.code in _CANDIDATE_RESOURCE_CODES
    ):
        return error.code if _case_is_healthy(case, context) else None
    for error_type, codes in _MODEL_ERROR_CODES.items():
        if isinstance(error, error_type) and error.code in codes:
            return error.code
    return None


# pylint: disable-next=too-many-locals
def score_item(
    prompt: PreparedPromptV1,
    completion: CompletionV1,
    case: GoldCase,
    capture_root: Path,
    *,
    run_id: str,
    created_at: datetime,
    code_revision: str,
    model_hash: str,
    runner: TsharkRunner,
    request: str,
) -> tuple[ItemOutcomeV1, EvaluationReceiptV1 | None, IntentIrV1 | None]:
    """Classifies one stored completion into exactly one protocol outcome.

    An executed candidate that matches every probe but breaks a shortcut
    rule is ``shortcut``, never strong exact; a silent-wrong one keeps its
    outcome and records the rules it breaks. A ready answer to non-ready
    gold is ``false_ready`` and is never executed; an abstention on
    non-ready gold records whether its status and slots match the gold.

    Args:
        prompt: The committed prompt the model actually answered.
        completion: The stored raw answer or sanitized provider failure.
        case: The gold case this item routes to, already verified.
        capture_root: Directory holding the regenerated probe captures.
        run_id: Run identifier recorded on the receipt.
        created_at: Run timestamp recorded on the receipt.
        code_revision: Revision recorded on the receipt.
        model_hash: Content hash of the recorded request settings.
        runner: The shared bounded tshark runner.
        request: The request text the model saw, which grounds literals.

    Returns:
        The scored outcome, the receipt for an executed candidate, and the
        ready typed IR for a typed-contract item.

    Raises:
        ScoringError: With code ``item_aborted`` when the failure is not
            attributable to the candidate.
    """
    label = condition_label(prompt.output_contract, prompt.retrieval)
    fields = _item_fields(prompt, completion, case, label)
    context = _Execution(
        capture_root, run_id, created_at, code_revision, runner
    )
    if completion.status is CompletionStatusV1.FAILED:
        return (
            ItemOutcomeV1(
                **fields,
                outcome=OutcomeV1.PROVIDER_FAILED,
                error_code=completion.error_code,
                http_status=completion.http_status,
                provider_error_code=completion.provider_error_code,
                **_status_fields(case, None),
            ),
            None,
            None,
        )
    try:
        parsed = parse_response(
            prompt.output_contract, completion.response_text or ""
        )
    except GenerationError as error:
        outcome = ItemOutcomeV1(
            **fields,
            outcome=OutcomeV1.MALFORMED,
            error_code=error.code,
            **_status_fields(case, None),
        )
        return outcome, None, None
    if parsed.status is not GenerationStatus.READY:
        outcome = ItemOutcomeV1(
            **fields,
            outcome=OutcomeV1.ABSTAINED,
            abstention_status=_ABSTENTIONS[parsed.status],
            **_status_fields(case, parsed.status, parsed.missing_slots),
        )
        return outcome, None, None
    filter_text: str | None = None
    ready_ir: IntentIrV1 | None = None
    candidate: IntentIrV1 | str
    if isinstance(parsed, DirectFilterResultV1):
        assert parsed.display_filter is not None
        filter_text = parsed.display_filter
        candidate = filter_text
    else:
        assert parsed.intent_ir is not None
        ready_ir = parsed.intent_ir
        candidate = ready_ir
    if isinstance(case, ModelNonReadyCaseV1):
        outcome = ItemOutcomeV1(
            **fields,
            outcome=OutcomeV1.FALSE_READY,
            candidate_filter=filter_text,
            **_status_fields(case, parsed.status),
        )
        return outcome, None, ready_ir
    try:
        receipt, _ = evaluate_live(
            case.spec,
            candidate,
            capture_root,
            run_id=run_id,
            created_at=created_at,
            code_revision=code_revision,
            runner=runner,
            model_hash=model_hash,
            prompt_hash=content_sha256(prompt),
        )
    except DFilterForgeError as error:
        code = _attributable_code(error, case, context)
        if code is None:
            raise ScoringError(
                "item_aborted", f"{label} {prompt.item_id}: {error.code}"
            ) from error
        outcome = ItemOutcomeV1(
            **fields,
            outcome=OutcomeV1.INVALID,
            error_code=code,
            candidate_filter=filter_text,
        )
        return outcome, None, ready_ir
    exact = tuple(probe.exact for probe in receipt.probes)
    hits, disjunctions = _shortcuts(candidate, request)
    verdict = OutcomeV1.SILENT_WRONG
    if all(exact):
        verdict = OutcomeV1.SHORTCUT if hits else OutcomeV1.STRONG_EXACT
    outcome = ItemOutcomeV1(
        **fields,
        outcome=verdict,
        candidate_filter=filter_text,
        probe_exact=exact,
        packet_set_hash=packet_set_hash(receipt),
        shortcuts=hits,
        disjunctions=disjunctions,
    )
    return outcome, receipt, ready_ir


def verify_gold(
    cases: Sequence[ModelGoldCaseV1],
    capture_root: Path,
    *,
    run_id: str,
    created_at: datetime,
    code_revision: str,
    runner: TsharkRunner,
) -> LiveEnvironmentV1:
    """Proves every selected case before a single model answer is read.

    A reference label mismatch is caught here, so it can never be charged
    to a model.

    Args:
        cases: The selected gold cases, in the order to verify them.
        capture_root: Directory holding the regenerated probe captures.
        run_id: Run identifier; the gold pass suffixes it with ``-gold``.
        created_at: Run timestamp recorded on the gold receipts.
        code_revision: Revision recorded on the gold receipts.
        runner: The shared bounded tshark runner.

    Returns:
        The measured execution environment, identical for every case.

    Raises:
        ScoringError: With code ``gold_invalid`` naming the offending case.
    """
    for case in cases:
        for gold in (case.spec.reference_filter, case.spec.canonical_ir):
            if _shortcuts(gold, case.spec.intent)[0]:
                raise ScoringError(
                    "gold_invalid", f"{case.case_id}: gold uses a shortcut"
                )
    context = _Execution(
        capture_root, f"{run_id}-gold", created_at, code_revision, runner
    )
    environment: LiveEnvironmentV1 | None = None
    for case in cases:
        if not any(probe.expected_frames for probe in case.spec.probes):
            raise ScoringError(
                "gold_invalid",
                f"{case.case_id}: every probe label set is empty",
            )
        try:
            measured = _verify_case(case, context)
        except DFilterForgeError as error:
            raise ScoringError(
                "gold_invalid", f"{case.case_id}: {error.code}"
            ) from error
        if measured is None:
            raise ScoringError(
                "gold_invalid", f"{case.case_id}: canonical IR is not exact"
            )
        environment = measured
    assert environment is not None
    return environment


def _non_ready_control(
    output_contract: OutputContractV1,
    case: ModelNonReadyCaseV1,
    mode: ControlMode,
) -> str | None:
    """Answers non-ready gold: its own status, or a ready filter."""
    if mode == "mutation":
        if output_contract is not OutputContractV1.DISPLAY_FILTER:
            return None
        return canonical_json(
            DirectFilterResultV1(
                status=GenerationStatus.READY,
                display_filter=_FALSE_READY_CONTROL_FILTER,
            )
        )
    status = GenerationStatus(case.status)
    question = (
        _CONTROL_QUESTION
        if status is GenerationStatus.NEEDS_CLARIFICATION
        else None
    )
    envelope: FrozenModel = (
        DirectFilterResultV1(
            status=status,
            clarifying_question=question,
            missing_slots=case.missing_slots,
        )
        if output_contract is OutputContractV1.DISPLAY_FILTER
        else GenerationResultV1(
            status=status,
            clarifying_question=question,
            missing_slots=case.missing_slots,
        )
    )
    return canonical_json(envelope)


def _control_completion(
    prompt: PreparedPromptV1, case: GoldCase, mode: ControlMode
) -> CompletionV1 | None:
    """Answers one committed prompt from the gold case it routes to.

    The envelope is built from the response contract itself rather than
    from a literal, so a later change to either envelope cannot leave this
    path emitting a shape the parser would reject. Non-ready gold is
    answered with its own status and slots under the reference control
    and with a ready filter under the mutation control.

    Args:
        prompt: The committed prompt to answer.
        case: The gold case the prompt's item routes to.
        mode: Whether to answer with the reference or with the mutation.

    Returns:
        The synthesized completion, or None when this contract has no
        answer in this mode, because gold holds no typed mutation.
    """
    if isinstance(case, ModelNonReadyCaseV1):
        response = _non_ready_control(prompt.output_contract, case, mode)
        if response is None:
            return None
    elif prompt.output_contract is OutputContractV1.DISPLAY_FILTER:
        response = canonical_json(
            DirectFilterResultV1(
                status=GenerationStatus.READY,
                display_filter=(
                    case.spec.reference_filter
                    if mode == "reference"
                    else case.mutation_filter
                ),
            )
        )
    elif mode == "mutation":
        return None
    else:
        response = canonical_json(
            GenerationResultV1(
                status=GenerationStatus.READY, intent_ir=case.spec.canonical_ir
            )
        )
    return CompletionV1(
        item_id=prompt.item_id,
        status=CompletionStatusV1.COMPLETED,
        response_text=response,
        latency_ms=0.0,
    )


def _control_batch(
    prepared: PreparedBatchV1,
    cases_by_item: Mapping[str, GoldCase],
    mode: ControlMode,
) -> CompletionBatchV1 | None:
    """Answers one whole prepared condition from gold, in prepared order.

    Args:
        prepared: The committed prompts of exactly one condition.
        cases_by_item: The item-to-case routing, already checked.
        mode: Whether to answer with the reference or with the mutation.

    Returns:
        The synthesized batch, or None when any prompt of the condition
        has no answer in this mode.
    """
    answers: list[CompletionV1] = []
    for prompt in prepared.prompts:
        answer = _control_completion(
            prompt, cases_by_item[prompt.item_id], mode
        )
        if answer is None:
            return None
        answers.append(answer)
    return CompletionBatchV1(
        output_contract=prepared.output_contract,
        retrieval=prepared.retrieval,
        settings=RequestSettingsV1(model_id=f"control-{mode}"),
        completions=tuple(answers),
    )


class _ControlPlan(NamedTuple):
    """The conditions a control pass scores, and the ones it cannot."""

    prepared: dict[ConditionLabel, tuple[PreparedBatchV1, str]]
    completions: dict[ConditionLabel, CompletionBatchV1]
    not_measured: dict[str, str]


def _control_plan(
    prepared: Mapping[ConditionLabel, tuple[PreparedBatchV1, str]],
    routes: Mapping[str, GoldCase],
    mode: ControlMode,
) -> _ControlPlan:
    """Answers every committed condition that this control mode can answer.

    Args:
        prepared: Every committed condition of the run.
        routes: The item-to-case routing, already checked.
        mode: Whether to answer with the reference or with the mutation.

    Returns:
        The conditions to score, their synthesized answers, and the
        reason recorded for each condition that was skipped.

    Raises:
        ScoringError: With code ``run_layout_invalid`` when no committed
            condition can be answered in this mode at all.
    """
    scored: dict[ConditionLabel, tuple[PreparedBatchV1, str]] = {}
    answered: dict[ConditionLabel, CompletionBatchV1] = {}
    skipped: dict[str, str] = {}
    for label, (batch, digest) in prepared.items():
        control = _control_batch(batch, routes, mode)
        if control is None:
            skipped[label] = _NO_TYPED_MUTATION
            continue
        scored[label] = (batch, digest)
        answered[label] = control
    if not answered:
        raise ScoringError(
            "run_layout_invalid",
            "No condition can be scored under this control mode",
        )
    return _ControlPlan(scored, answered, skipped)


# pylint: disable-next=too-many-locals
def _score_items(
    prepared: Mapping[ConditionLabel, tuple[PreparedBatchV1, str]],
    completions: Mapping[ConditionLabel, CompletionBatchV1],
    routes: Mapping[str, GoldCase],
    context: _Execution,
    requests: Mapping[str, str],
    *,
    model_hash: str | None = None,
) -> tuple[list[ItemOutcomeV1], dict[str, FrozenModel]]:
    """Scores every prompt in prepared order with one shared runner.

    ``requests`` maps each item to the request text its model saw.

    ``model_hash`` names the answer source on every receipt. It is the
    content hash of the recorded request settings unless a caller pins it,
    which is what keeps a control pass from publishing a synthesized
    settings object as though a provider had been asked for one.
    """
    outcomes: list[ItemOutcomeV1] = []
    files: dict[str, FrozenModel] = {}
    for label, (batch, _) in prepared.items():
        recorded = {
            item.item_id: item for item in completions[label].completions
        }
        answered_by = (
            content_sha256(completions[label].settings)
            if model_hash is None
            else model_hash
        )
        for prompt in batch.prompts:
            outcome, receipt, intent = score_item(
                prompt,
                recorded[prompt.item_id],
                routes[prompt.item_id],
                context.capture_root,
                run_id=context.run_id,
                created_at=context.created_at,
                code_revision=context.code_revision,
                model_hash=answered_by,
                runner=context.runner,
                request=requests[prompt.item_id],
            )
            outcomes.append(outcome)
            if receipt is not None:
                files[f"receipts/{label}/{prompt.item_id}.json"] = receipt
            if intent is not None:
                files[f"intents/{label}/{prompt.item_id}.json"] = intent
    return outcomes, files


def _run_created_at(
    manifest: RunManifestV1 | None, prepare: PrepareManifestV1 | None
) -> datetime:
    """Returns the timestamp the run directory recorded for itself.

    A control pass is taken before any request is sent, so the directory it
    reads holds no run manifest. The committed prepare manifest is then the
    clock its receipts sit on, and only a directory that committed neither
    falls back to the placeholder.
    """
    if manifest is not None:
        return manifest.created_at
    if prepare is not None:
        return prepare.created_at
    return _PLACEHOLDER_CREATED_AT


def _check_control_pin(
    split: str,
    manifest: RunManifestV1 | None,
    prepare: PrepareManifestV1 | None,
) -> None:
    """Keeps an unpinned control pass on the development split.

    A control pass reads no stored answer, so a directory holding nothing
    but ``prepared/`` is enough to run the whole path and to publish every
    gold specification it touches. Without a manifest the split is only a
    claim the prompts make about themselves; both manifest types pin it to
    a reviewed literal, so a directory that committed neither is limited to
    the split no held-out answer key can be published from.

    Raises:
        ScoringError: With code ``split_violation``.
    """
    if manifest is None and prepare is None and split != "dev":
        raise ScoringError(
            "split_violation",
            "an unpinned control pass is limited to the dev split",
        )


def _control_prompts(
    scored_conditions: Mapping[ConditionLabel, tuple[PreparedBatchV1, str]],
) -> list[PreparedPromptV1]:
    """Lists the prompts of the conditions a control mode can answer."""
    return [
        prompt
        for batch, _ in scored_conditions.values()
        for prompt in batch.prompts
    ]


# pylint: disable-next=too-many-locals
def score_run(
    run_dir: Path,
    *,
    code_revision: str,
    check: bool = False,
    control: ControlMode | None = None,
    split_dir: Path | None = None,
    runner: TsharkRunner | None = None,
) -> ScoreReportV1:
    """Scores one run into a deterministic ``scored`` or control directory.

    Args:
        run_dir: The run directory holding prepared/, an optional
            completions/ that is never read under ``control``, an optional
            prepare.json and an optional run_manifest.json.
        code_revision: Revision recorded on every receipt.
        check: Compare against the committed tree instead of writing it.
        control: Answer the committed prompts from gold instead of from
            the stored completions, writing to ``control-reference`` or
            ``control-mutation``. Every other check is unchanged, which is
            the point: the control pass exercises the same path.
        split_dir: Where to regenerate the split; a temporary directory is
            used when this is None.
        runner: The bounded tshark runner to share across every execution.

    Returns:
        What was written, or what differs from the committed tree.

    Raises:
        ScoringError: For any layout, manifest, prompt, split or gold
            failure, and for a failure not attributable to a candidate.
    """
    loaded = load_run(run_dir, with_completions=control is None)
    manifest, prepare = loaded.manifest, loaded.prepare
    prepared, completions = loaded.prepared, loaded.completions
    if prepare is not None:
        check_prepare(prepare, prepared)
    if manifest is not None:
        # A control pass reads no stored answer, so it has no recorded
        # settings to cross-check; every other manifest claim about the
        # committed prompts is checked exactly as it always is.
        check_manifest(manifest, prepared, completions)
    split = check_splits(prepared, manifest, prepare)
    if control is not None:
        _check_control_pin(split, manifest, prepare)
    prompts = [
        prompt for batch, _ in prepared.values() for prompt in batch.prompts
    ]
    active_runner = runner if runner is not None else TsharkRunner()
    created_at = _run_created_at(manifest, prepare)
    scored_conditions = prepared
    not_measured: dict[str, str] = {}
    with ExitStack() as stack:
        base = (
            split_dir
            if split_dir is not None
            else Path(
                stack.enter_context(
                    TemporaryDirectory(prefix="dfilterforge-score-")
                )
            )
        )
        artifacts = generate_model_split(base)
        routes, selected, non_ready = selected_cases(
            prompts, artifacts.gold, split
        )
        check_prompts(
            prepared, {item.item_id: item for item in artifacts.inputs}
        )
        if control is not None:
            scored_conditions, completions, not_measured = _control_plan(
                prepared, routes, control
            )
            # The gold preflight, the published specifications and the
            # gold hash have to cover exactly the cases the scored
            # conditions reach. Leaving them wider would publish an answer
            # key for cases no outcome in the same summary was drawn from.
            routes, selected, non_ready = selected_cases(
                _control_prompts(scored_conditions), artifacts.gold, split
            )
        captures = base / "captures"
        environment = verify_gold(
            selected,
            captures,
            run_id=run_dir.name,
            created_at=created_at,
            code_revision=code_revision,
            runner=active_runner,
        )
        context = _Execution(
            captures, run_dir.name, created_at, code_revision, active_runner
        )
        outcomes, files = _score_items(
            scored_conditions,
            completions,
            routes,
            context,
            {item.item_id: item.intent for item in artifacts.inputs},
            model_hash=(
                None
                if control is None
                else content_sha256({"control": control})
            ),
        )
    summary = summarize_run(
        outcomes,
        scored_conditions,
        completions,
        selected,
        # A gold-derived answer costs nothing, so a control pass reports
        # no price, no charge and no served provenance, even when the run
        # directory holds the manifest of a paid run.
        None if control is not None else manifest,
        run=run_dir.name,
        split=split,
        synthesized=control is not None,
        not_measured=not_measured,
        non_ready=non_ready,
    )
    rendered = render(
        summary,
        outcomes,
        files,
        selected,
        code_revision=code_revision,
        environment=environment,
        non_ready=non_ready,
    )
    counts = {outcome.value: 0 for outcome in OutcomeV1}
    for item in outcomes:
        counts[item.outcome.value] += 1
    name = SCORED_NAME if control is None else _CONTROL_DIRECTORIES[control]
    target = run_dir / name
    differences = compare(target, rendered) if check else ()
    if not check:
        target = write_scored(run_dir, rendered, name=name)
    return ScoreReportV1(
        output_dir=target,
        checked=check,
        items=len(outcomes),
        outcomes=counts,
        summary_sha256=content_sha256(summary),
        differences=differences,
    )
