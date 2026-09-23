"""Behavioral tests for offline scoring of stored completions."""

from __future__ import annotations

from collections.abc import Callable, Collection, Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, TypeAlias

import pytest

from dfilterforge import scoring as scoring_module
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.compiler import CompileError
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import OpenRouterOptionsV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import TokenPricesV1
from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.field_catalog import CatalogError
from dfilterforge.generation import ConditionLabel
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.live import LiveError
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.runner import RunnerError
from dfilterforge.runner import TsharkRunner
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import ScoreSummaryV1
from dfilterforge.scoring import score_item
from dfilterforge.scoring import score_run
from dfilterforge.scoring import ScoringError
from dfilterforge.scoring import verify_gold

_CREATED_AT = datetime(2026, 9, 18, tzinfo=timezone.utc)
_DEV_PROBES = ("semantic-11", "semantic-17", "semantic-23")
_REFERENCE = "tcp && ip.ttl <= 1"
_INTENT = "Keep only TCP packets whose IPv4 TTL is 1 or lower."
_ASSUMPTIONS = ("Interpret the request at packet scope.",)
_MODEL_ID = "vendor/model-a"
_RUNNER = TsharkRunner()
_CONDITION_INPUTS: dict[
    ConditionLabel, tuple[OutputContractV1, RetrievalV1]
] = {
    "C1": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    "C2": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    "C3": (OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    "C4": (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
}
_UNATTRIBUTABLE: list[tuple[type[Exception], str]] = [
    (LiveError, "reference_label_mismatch"),
    (LiveError, "capture_hash_mismatch"),
    (RunnerError, "capture_unreadable"),
    (RunnerError, "tshark_failed"),
    (RunnerError, "tshark_unavailable"),
    (CatalogError, "catalog_unavailable"),
]
_ATTRIBUTABLE: list[tuple[type[Exception], str]] = [
    (CatalogError, "unknown_field"),
    (CatalogError, "ambiguous_field"),
    (CatalogError, "unsupported_type"),
    (CatalogError, "unsupported_operator"),
    (CatalogError, "type_mismatch"),
    (CompileError, "invalid_value"),
    (RunnerError, "filter_invalid"),
    (RunnerError, "filter_too_large"),
    (RunnerError, "filter_rejected"),
    (RunnerError, "filter_unknown_field"),
]

_Call = tuple[SemanticSpecV1, IntentIrV1 | str, dict[str, Any]]


def _canonical_ir() -> IntentIrV1:
    """Returns the typed target shared by the hand-built gold case."""
    return IntentIrV1(
        expression=All(
            children=(
                Predicate(field="tcp", operator=Operator.EXISTS),
                Predicate(field="ip.ttl", operator=Operator.LE, value=1),
            )
        )
    )


def _case(
    *,
    case_id: str = "tcp-expiring-ttl",
    expected: tuple[tuple[int, ...], ...] = ((1, 2), (3,), (4, 5)),
) -> ModelGoldCaseV1:
    """Builds one dev gold case without touching the generated split."""
    spec = SemanticSpecV1(
        task_id=case_id,
        intent=_INTENT,
        canonical_ir=_canonical_ir(),
        reference_filter=_REFERENCE,
        probes=tuple(
            ProbeExpectationV1(
                probe_id=probe_id,
                capture_sha256="0" * 64,
                expected_frames=frames,
            )
            for probe_id, frames in zip(_DEV_PROBES, expected)
        ),
        split="dev",
        provenance="hand built for scoring tests",
        license="MIT",
        review_status="reviewed",
    )
    return ModelGoldCaseV1(
        case_id=case_id, spec=spec, mutation_filter="ip.ttl <= 1"
    )


def _environment() -> LiveEnvironmentV1:
    """Returns the environment the fake live boundary reports."""
    return LiveEnvironmentV1(
        tshark_version="4.6.8",
        executable_sha256="measured-by-live-boundary",
        runner_source_sha256="measured-by-live-boundary",
        runner_limits_hash="measured-by-live-boundary",
        catalog_hash="measured-by-live-boundary",
        catalog_profile_hash="measured-by-live-boundary",
        python_version="3.12.3",
        platform_machine="x86_64",
    )


def _miss(frames: tuple[int, ...]) -> tuple[int, ...]:
    """Returns a packet set that can never equal ``frames``."""
    return frames[1:] if frames else (1,)


def _install_live(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: Callable[[IntentIrV1 | str], None] | None = None,
    inexact: Collection[str] = (),
    gold_inexact: bool = False,
) -> list[_Call]:
    """Replaces the live boundary with a recorder that executes nothing."""
    calls: list[_Call] = []

    def fake_evaluate_live(
        spec: SemanticSpecV1,
        candidate: IntentIrV1 | str,
        capture_root: Path,
        **kwargs: Any,
    ) -> tuple[EvaluationReceiptV1, LiveEnvironmentV1]:
        del capture_root
        calls.append((spec, candidate, kwargs))
        if fail is not None:
            fail(candidate)
        if candidate == spec.canonical_ir:
            missing: Collection[str] = _DEV_PROBES[:1] if gold_inexact else ()
        else:
            missing = inexact
        probes = tuple(
            evaluate_probe(
                probe.probe_id,
                probe.expected_frames,
                (
                    _miss(probe.expected_frames)
                    if probe.probe_id in missing
                    else probe.expected_frames
                ),
                1.5,
            )
            for probe in spec.probes
        )
        receipt = EvaluationReceiptV1(
            run_id=kwargs["run_id"],
            created_at=kwargs["created_at"],
            code_revision=kwargs["code_revision"],
            environment_hash=_environment().environment_hash(),
            data_hash=content_sha256(spec),
            model_hash=kwargs.get("model_hash"),
            prompt_hash=kwargs.get("prompt_hash"),
            candidate_filter=(
                candidate if isinstance(candidate, str) else _REFERENCE
            ),
            reference_filter=spec.reference_filter,
            probes=probes,
            metrics=aggregate_metrics(probes),
        )
        return receipt, _environment()

    monkeypatch.setattr(scoring_module, "evaluate_live", fake_evaluate_live)
    return calls


def _prompt(
    output_contract: OutputContractV1,
    retrieval: RetrievalV1 = RetrievalV1.NONE,
    *,
    item_id: str = "mei-0001",
) -> PreparedPromptV1:
    """Prepares one committed prompt exactly as the preparation step would."""
    batch = prepare_batch(
        [
            GenerationInputV1(
                item_id=item_id,
                intent=_INTENT,
                user_assumptions=_ASSUMPTIONS,
                retrieved_fields=(
                    () if retrieval is RetrievalV1.LEXICAL else None
                ),
                split="dev",
            )
        ],
        output_contract=output_contract,
        retrieval=retrieval,
    )
    return batch.prompts[0]


def _completion(item_id: str = "mei-0001", **overrides: Any) -> CompletionV1:
    """Builds one stored completion with test-friendly defaults."""
    values: dict[str, Any] = {
        "item_id": item_id,
        "status": CompletionStatusV1.COMPLETED,
        "latency_ms": 120.0,
        "prompt_tokens": 400,
        "completion_tokens": 40,
        "finish_reason": "stop",
    }
    values.update(overrides)
    return CompletionV1(**values)


def _filter_reply(display_filter: str | None = _REFERENCE, **extra: Any) -> str:
    """Renders one direct-filter response envelope."""
    payload: dict[str, Any] = {
        "schema_version": "direct-filter/1.0",
        "status": "ready",
        "assumptions": [],
        "clarifying_question": None,
        "missing_slots": [],
        "display_filter": display_filter,
    }
    payload.update(extra)
    return canonical_json(payload)


def _ir_reply(intent: IntentIrV1 | None = None, **extra: Any) -> str:
    """Renders one typed-IR response envelope."""
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "ready",
        "assumptions": [],
        "clarifying_question": None,
        "missing_slots": [],
        "intent_ir": intent if intent is not None else _canonical_ir(),
    }
    payload.update(extra)
    return canonical_json(payload)


def _score(
    prompt: PreparedPromptV1,
    completion: CompletionV1,
    *,
    case: ModelGoldCaseV1 | None = None,
    model_hash: str = "model-settings-hash",
) -> tuple[ItemOutcomeV1, EvaluationReceiptV1 | None, IntentIrV1 | None]:
    """Scores one item with fixed run identity."""
    return score_item(
        prompt,
        completion,
        case if case is not None else _case(),
        Path("captures"),
        run_id="dev-0001",
        created_at=_CREATED_AT,
        code_revision="revision",
        model_hash=model_hash,
        runner=_RUNNER,
    )


def test_failed_completion_is_provider_failed_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure is never the model producing a wrong answer."""
    calls = _install_live(monkeypatch)
    completion = _completion(
        status=CompletionStatusV1.FAILED,
        response_text=None,
        error_code="http_error",
        http_status=429,
        provider_error_code="429",
    )

    outcome, receipt, intent = _score(
        _prompt(OutputContractV1.DISPLAY_FILTER), completion
    )

    assert outcome.outcome is OutcomeV1.PROVIDER_FAILED
    assert outcome.error_code == "http_error"
    assert outcome.http_status == 429
    assert outcome.provider_error_code == "429"
    assert receipt is None and intent is None
    assert calls == []


@pytest.mark.parametrize(
    "output_contract,response_text",
    [
        (OutputContractV1.DISPLAY_FILTER, "not json"),
        (OutputContractV1.DISPLAY_FILTER, _filter_reply("tcp\n&& ip")),
        (
            OutputContractV1.TYPED_IR,
            canonical_json(
                {
                    "schema_version": "1.0",
                    "status": "ready",
                    "intent_ir": {"scope": "packet", "extra": 1},
                }
            ),
        ),
    ],
)
def test_unparseable_response_is_malformed_without_execution(
    monkeypatch: pytest.MonkeyPatch,
    output_contract: OutputContractV1,
    response_text: str,
) -> None:
    """A reply that misses its contract is malformed, not invalid."""
    calls = _install_live(monkeypatch)

    outcome, receipt, intent = _score(
        _prompt(output_contract), _completion(response_text=response_text)
    )

    assert outcome.outcome is OutcomeV1.MALFORMED
    assert outcome.error_code == "response_invalid"
    assert receipt is None and intent is None
    assert calls == []


@pytest.mark.parametrize(
    "status,extra",
    [
        (
            "needs_clarification",
            {"clarifying_question": "Which port?", "missing_slots": ["port"]},
        ),
        ("not_expressible", {}),
    ],
)
def test_typed_abstention_is_abstained_without_execution(
    monkeypatch: pytest.MonkeyPatch, status: str, extra: dict[str, Any]
) -> None:
    """A typed abstention is recorded on its own channel."""
    calls = _install_live(monkeypatch)
    response_text = _ir_reply(status=status, intent_ir=None, **extra)

    outcome, receipt, intent = _score(
        _prompt(OutputContractV1.TYPED_IR),
        _completion(response_text=response_text),
    )

    assert outcome.outcome is OutcomeV1.ABSTAINED
    assert outcome.abstention_status == status
    assert receipt is None and intent is None
    assert calls == []


def test_display_filter_abstention_is_abstained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both output contracts share one abstention channel."""
    calls = _install_live(monkeypatch)
    response_text = _filter_reply(
        None,
        status="needs_clarification",
        clarifying_question="Which direction?",
        missing_slots=["direction"],
    )

    outcome, receipt, _ = _score(
        _prompt(OutputContractV1.DISPLAY_FILTER),
        _completion(response_text=response_text),
    )

    assert outcome.outcome is OutcomeV1.ABSTAINED
    assert outcome.abstention_status == "needs_clarification"
    assert receipt is None
    assert calls == []


@pytest.mark.parametrize("error_type,code", _ATTRIBUTABLE)
def test_model_attributable_errors_are_invalid(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception], code: str
) -> None:
    """Only a candidate-attributable rejection counts against the model."""

    def fail(candidate: IntentIrV1 | str) -> None:
        del candidate
        raise error_type(code, "bounded message")

    calls = _install_live(monkeypatch, fail=fail)

    outcome, receipt, intent = _score(
        _prompt(OutputContractV1.DISPLAY_FILTER),
        _completion(response_text=_filter_reply()),
    )
    typed_outcome, _, typed_intent = _score(
        _prompt(OutputContractV1.TYPED_IR, item_id="mei-0002"),
        _completion("mei-0002", response_text=_ir_reply()),
    )

    assert outcome.outcome is OutcomeV1.INVALID
    assert outcome.error_code == code
    assert outcome.candidate_filter == _REFERENCE
    assert receipt is None and intent is None
    assert typed_outcome.outcome is OutcomeV1.INVALID
    assert typed_outcome.candidate_filter is None
    assert typed_intent == _canonical_ir()
    assert len(calls) == 2


@pytest.mark.parametrize("code", ["timeout", "output_limit", "frame_limit"])
def test_candidate_resource_failure_is_invalid_when_gold_reverifies(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """One pathological filter cannot make a paid run unscoreable."""

    def fail(candidate: IntentIrV1 | str) -> None:
        if isinstance(candidate, str):
            raise RunnerError(code, "bounded message")

    calls = _install_live(monkeypatch, fail=fail)

    outcome, receipt, _ = _score(
        _prompt(OutputContractV1.DISPLAY_FILTER),
        _completion(response_text=_filter_reply()),
    )

    assert outcome.outcome is OutcomeV1.INVALID
    assert outcome.error_code == code
    assert outcome.candidate_filter == _REFERENCE
    assert receipt is None
    assert len(calls) == 2
    assert calls[1][1] == _canonical_ir()
    assert calls[1][2]["run_id"] == "dev-0001-recheck"


def test_resource_failure_aborts_when_the_reference_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A harness-side time limit still stops scoring."""

    def fail(candidate: IntentIrV1 | str) -> None:
        del candidate
        raise RunnerError("timeout", "bounded message")

    _install_live(monkeypatch, fail=fail)

    with pytest.raises(ScoringError) as error:
        _score(
            _prompt(OutputContractV1.DISPLAY_FILTER),
            _completion(response_text=_filter_reply()),
        )

    assert error.value.code == "item_aborted"
    assert str(error.value) == "C1 mei-0001: timeout"


@pytest.mark.parametrize("error_type,code", _UNATTRIBUTABLE)
def test_unattributable_errors_stop_scoring(
    monkeypatch: pytest.MonkeyPatch, error_type: type[Exception], code: str
) -> None:
    """A reference, capture or catalog failure is never charged to a model."""

    def fail(candidate: IntentIrV1 | str) -> None:
        del candidate
        raise error_type(code, "bounded message")

    _install_live(monkeypatch, fail=fail)

    with pytest.raises(ScoringError) as error:
        _score(
            _prompt(OutputContractV1.DISPLAY_FILTER),
            _completion(response_text=_filter_reply()),
        )

    assert error.value.code == "item_aborted"
    assert str(error.value) == f"C1 mei-0001: {code}"
    assert _REFERENCE not in str(error.value)


def test_receipt_probes_decide_strong_exact_or_silent_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exactness on every probe is what separates the two verdicts."""
    _install_live(monkeypatch)

    exact_outcome, exact_receipt, _ = _score(
        _prompt(OutputContractV1.DISPLAY_FILTER),
        _completion(response_text=_filter_reply()),
    )

    _install_live(monkeypatch, inexact=("semantic-17",))
    wrong_outcome, wrong_receipt, _ = _score(
        _prompt(OutputContractV1.DISPLAY_FILTER),
        _completion(response_text=_filter_reply()),
    )

    assert exact_outcome.outcome is OutcomeV1.STRONG_EXACT
    assert exact_outcome.probe_exact == (True, True, True)
    assert exact_outcome.packet_set_hash is not None
    assert exact_receipt is not None
    assert wrong_outcome.outcome is OutcomeV1.SILENT_WRONG
    assert wrong_outcome.probe_exact == (True, False, True)
    assert wrong_outcome.packet_set_hash is not None
    assert wrong_receipt is not None


def test_display_filter_goes_in_unchanged_and_typed_ir_as_ir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model's own text reaches the oracle without rewriting."""
    calls = _install_live(monkeypatch)
    settings = RequestSettingsV1(model_id=_MODEL_ID)
    model_hash = content_sha256(settings)
    raw = _prompt(OutputContractV1.DISPLAY_FILTER)
    typed = _prompt(OutputContractV1.TYPED_IR, item_id="mei-0002")

    _score(
        raw, _completion(response_text=_filter_reply()), model_hash=model_hash
    )
    _score(
        typed,
        _completion("mei-0002", response_text=_ir_reply()),
        model_hash=model_hash,
    )

    assert calls[0][1] == _REFERENCE
    assert calls[0][2]["prompt_hash"] == content_sha256(raw)
    assert calls[0][2]["model_hash"] == model_hash
    assert calls[1][1] == _canonical_ir()
    assert calls[1][2]["prompt_hash"] == content_sha256(typed)
    assert calls[1][2]["model_hash"] == model_hash


def test_gold_preflight_rejects_inexact_canonical_and_all_empty_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gold is proved before a single model answer is read."""
    _install_live(monkeypatch)
    empty = _case(case_id="empty-labels", expected=((), (), ()))

    with pytest.raises(ScoringError) as blank:
        verify_gold(
            [empty],
            Path("captures"),
            run_id="dev-0001",
            created_at=_CREATED_AT,
            code_revision="revision",
            runner=_RUNNER,
        )

    _install_live(monkeypatch, gold_inexact=True)
    with pytest.raises(ScoringError) as drifted:
        verify_gold(
            [_case()],
            Path("captures"),
            run_id="dev-0001",
            created_at=_CREATED_AT,
            code_revision="revision",
            runner=_RUNNER,
        )

    assert blank.value.code == "gold_invalid"
    assert str(blank.value) == "empty-labels: every probe label set is empty"
    assert drifted.value.code == "gold_invalid"
    assert str(drifted.value) == "tcp-expiring-ttl: canonical IR is not exact"


def test_gold_preflight_reports_an_execution_failure_by_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gold-side execution failure names the case and its code."""

    def fail(candidate: IntentIrV1 | str) -> None:
        del candidate
        raise LiveError("reference_label_mismatch", "bounded message")

    _install_live(monkeypatch, fail=fail)

    with pytest.raises(ScoringError) as error:
        verify_gold(
            [_case()],
            Path("captures"),
            run_id="dev-0001",
            created_at=_CREATED_AT,
            code_revision="revision",
            runner=_RUNNER,
        )

    assert error.value.code == "gold_invalid"
    assert str(error.value) == "tcp-expiring-ttl: reference_label_mismatch"


def _write_json(path: Path, value: object) -> None:
    """Writes one committed contract as canonical JSON with an LF ending."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((canonical_json(value) + "\n").encode("utf-8"))


def _reply_for(output_contract: OutputContractV1, case: ModelGoldCaseV1) -> str:
    """Derives one answering reply from the gold case the item routes to."""
    if output_contract is OutputContractV1.DISPLAY_FILTER:
        return _filter_reply(case.spec.reference_filter)
    return _ir_reply(case.spec.canonical_ir)


def _run_dir(
    tmp_path: Path,
    labels: Sequence[ConditionLabel] = ("C1", "C3"),
    *,
    malformed: Collection[str] = (),
    provenance: Callable[[str], dict[str, Any]] | None = None,
    settings: RequestSettingsV1 | None = None,
    stored: bool = True,
    split: str = "dev",
    keep: Mapping[ConditionLabel, int] | None = None,
    prompt_version: int | None = None,
) -> Path:
    """Builds a run directory from one split and gold-derived replies.

    With ``stored`` false only ``prepared/`` is written, which is the
    layout a control pass is asked to score. ``keep`` truncates the item
    list of the named conditions, which is how a run whose conditions
    cover different items is built. ``prompt_version`` prepares every
    condition with that system prompt version, as an older run was.
    """
    artifacts = generate_model_split(tmp_path / "source")
    everything = [item for item in artifacts.inputs if item.split == split]
    cases = {case.case_id: case for case in artifacts.gold.cases}
    run_dir = tmp_path / f"{split}-0001"
    for label in labels:
        output_contract, retrieval = _CONDITION_INPUTS[label]
        items = (
            everything
            if keep is None or label not in keep
            else everything[: keep[label]]
        )
        batch = prepare_batch(
            [
                GenerationInputV1(
                    item_id=item.item_id,
                    intent=item.intent,
                    user_assumptions=item.user_assumptions,
                    retrieved_fields=(
                        () if retrieval is RetrievalV1.LEXICAL else None
                    ),
                    split=item.split,
                )
                for item in items
            ],
            output_contract=output_contract,
            retrieval=retrieval,
            prompt_version=prompt_version,
        )
        recorded = CompletionBatchV1(
            output_contract=output_contract,
            retrieval=retrieval,
            settings=(
                RequestSettingsV1(model_id=_MODEL_ID)
                if settings is None
                else settings
            ),
            completions=tuple(
                _completion(
                    item.item_id,
                    response_text=(
                        "not json"
                        if item.item_id in malformed
                        else _reply_for(
                            output_contract,
                            cases[artifacts.gold.item_to_case[item.item_id]],
                        )
                    ),
                    **({} if provenance is None else provenance(item.item_id)),
                )
                for item in items
            ),
        )
        _write_json(run_dir / "prepared" / f"{label}.json", batch)
        if stored:
            _write_json(run_dir / "completions" / f"{label}.json", recorded)
    return run_dir


def _dev_item_ids(run_dir: Path) -> tuple[str, ...]:
    """Reads the committed prompt ids back out of one prepared file."""
    document = json.loads(
        (run_dir / "prepared" / "C1.json").read_text(encoding="utf-8")
    )
    return tuple(prompt["item_id"] for prompt in document["prompts"])


def _prepare_manifest(
    run_dir: Path,
    labels: Sequence[ConditionLabel] = ("C1", "C3"),
    *,
    tweak_sha: ConditionLabel | None = None,
    drop_item: str | None = None,
    prompt_count: int = 16,
    mislabel: ConditionLabel | None = None,
    created_at: datetime = _CREATED_AT,
) -> PrepareManifestV1:
    """Builds the prepare manifest that describes the committed prompts."""
    item_ids = [
        item_id for item_id in _dev_item_ids(run_dir) if item_id != drop_item
    ]
    conditions: list[PreparedConditionV1] = []
    for label in labels:
        output_contract, retrieval = _CONDITION_INPUTS[label]
        if label == mislabel:
            output_contract, retrieval = _CONDITION_INPUTS[
                "C4" if label != "C4" else "C1"
            ]
        path = run_dir / "prepared" / f"{label}.json"
        digest = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.exists()
            else "a" * 64
        )
        if label == tweak_sha:
            digest = ("0" if digest[0] != "0" else "1") + digest[1:]
        conditions.append(
            PreparedConditionV1(
                label=label,
                output_contract=output_contract,
                retrieval=retrieval,
                path=f"prepared/{label}.json",
                sha256=digest,
                system_prompt_sha256="1" * 64,
                prompt_count=prompt_count,
            )
        )
    return PrepareManifestV1(
        prepare_id="prep-0001",
        created_at=created_at,
        source_revision="revision",
        source_files={"model_inputs.jsonl": "2" * 64},
        split="dev",
        item_ids=tuple(item_ids),
        model_inputs_sha256="3" * 64,
        catalog=CatalogIdentityV1(
            file_name="fields.sqlite3.gz",
            file_sha256="4" * 64,
            sqlite_sha256="5" * 64,
            catalog_hash="6" * 64,
            tshark_version="4.6.8",
        ),
        top_k=8,
        conditions=tuple(conditions),
    )


def _write_prepare(
    run_dir: Path,
    labels: Sequence[ConditionLabel] = ("C1", "C3"),
    **overrides: Any,
) -> PrepareManifestV1:
    """Commits prepare.json beside the prompts, as the freeze step does."""
    prepare = _prepare_manifest(run_dir, labels, **overrides)
    _write_json(run_dir / "prepare.json", prepare)
    return prepare


def _write_manifest(
    run_dir: Path,
    labels: Sequence[ConditionLabel] = ("C1", "C3"),
    *,
    tweak_sha: ConditionLabel | None = None,
    drop_item: str | None = None,
    prompt_count: int = 16,
    mislabel: ConditionLabel | None = None,
    prices: TokenPricesV1 | None = None,
    provider_reported_usd: float | None = None,
    charged_usd_upper_bound: float = 0.06,
    settings: RequestSettingsV1 | None = None,
    retried: Collection[str] = (),
    run_labels: Sequence[ConditionLabel] | None = None,
    completed: int | None = None,
) -> None:
    """Writes a run manifest that describes the committed prompt files.

    ``run_labels`` and ``completed`` move the run-side census away from the
    prepare-side description, which is how a manifest that describes the
    committed prompts but miscounts what was called is built. The census a
    condition reports always counts its own attempt keys, because that is
    a contract invariant; ``completed`` shortens both together, so the
    disagreement is with the committed prompts and not inside one record.
    """
    census = _dev_item_ids(run_dir)
    if completed is not None:
        census = census[:completed]
    prepare = _prepare_manifest(
        run_dir,
        labels,
        tweak_sha=tweak_sha,
        drop_item=drop_item,
        prompt_count=prompt_count,
        mislabel=mislabel,
    )
    manifest = RunManifestV1(
        run_id=run_dir.name,
        created_at=_CREATED_AT,
        prepare=prepare,
        prepare_sha256="7" * 64,
        endpoint_host="openrouter.ai",
        settings=(
            RequestSettingsV1(model_id=_MODEL_ID)
            if settings is None
            else settings
        ),
        prices=prices,
        max_attempts=3,
        min_interval_seconds=1.0,
        invocations=(
            InvocationV1(
                source_revision="revision",
                source_files={"scripts/model_run.py": "8" * 64},
                started_at=_CREATED_AT,
                finished_at=_CREATED_AT,
                max_usd=5.0,
                requests_sent=32,
            ),
        ),
        status="complete",
        charged_usd_upper_bound=charged_usd_upper_bound,
        provider_reported_usd=provider_reported_usd,
        conditions=tuple(
            ConditionRunV1(
                label=label,
                attempts_path=f"attempts/{label}.jsonl",
                attempts_sha256="9" * 64,
                completions_path=f"completions/{label}.json",
                completions_sha256="a" * 64,
                attempts={
                    item_id: 2 if item_id in retried else 1
                    for item_id in census
                },
                completed=len(census),
                failed=0,
                pending=0,
            )
            for label in (labels if run_labels is None else run_labels)
        ),
    )
    _write_json(run_dir / "run_manifest.json", manifest)


def test_score_run_writes_sorted_outcomes_summary_receipts_intents_and_specs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pass writes every committed artifact of a scored run."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, malformed=("mei-0001",))

    report = score_run(run_dir, code_revision="revision")

    scored = run_dir / "scored"
    assert report.output_dir == scored
    assert not report.checked
    assert report.items == 32
    assert report.outcomes[OutcomeV1.MALFORMED.value] == 2
    assert report.outcomes[OutcomeV1.STRONG_EXACT.value] == 30
    lines = (scored / "outcomes.jsonl").read_text("utf-8").splitlines()
    keys = [
        (json.loads(line)["condition"], json.loads(line)["item_id"])
        for line in lines
    ]
    assert keys == sorted(keys) and len(keys) == 32
    summary = ScoreSummaryV1.model_validate_json(
        (scored / "summary.json").read_bytes()
    )
    assert summary.case_count == 8 and summary.item_count == 32
    assert summary.conditions["C1"].usage.cost_usd is None
    assert (scored / "summary.md").read_text("utf-8").startswith("# Score")
    receipts = sorted(
        path.stem for path in (scored / "receipts" / "C1").glob("*")
    )
    intents = sorted(
        path.stem for path in (scored / "intents" / "C3").glob("*")
    )
    assert len(receipts) == 15 and "mei-0001" not in receipts
    assert len(intents) == 15 and "mei-0001" not in intents
    assert not (scored / "intents" / "C1").exists()
    assert len(sorted((scored / "specs").glob("*.json"))) == 8
    assert not (run_dir / ".scored.partial").exists()


def _joined(lines: Sequence[str]) -> bytes:
    """Encodes committed JSON Lines, one record per LF-terminated line."""
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


@contextmanager
def _edited(path: Path, payload: bytes) -> Generator[None, None, None]:
    """Temporarily replaces one committed file's bytes."""
    original = path.read_bytes()
    path.write_bytes(payload)
    try:
        yield
    finally:
        path.write_bytes(original)


def test_check_writes_nothing_and_names_changed_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checking reports differences without touching the committed tree."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    split_dir = tmp_path / "split"
    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    scored = run_dir / "scored"
    before = {
        path: path.stat().st_mtime_ns for path in sorted(scored.rglob("*"))
    }

    clean = score_run(
        run_dir, code_revision="revision", check=True, split_dir=split_dir
    )

    assert clean.checked and clean.differences == ()
    assert {
        path: path.stat().st_mtime_ns for path in sorted(scored.rglob("*"))
    } == before
    outcomes = scored / "outcomes.jsonl"
    rewritten: list[str] = []
    for line in outcomes.read_text("utf-8").splitlines():
        record: dict[str, Any] = json.loads(line)
        if (record["condition"], record["item_id"]) == ("C1", "mei-0003"):
            record["outcome"] = "silent_wrong"
        rewritten.append(canonical_json(record))
    drifted = _joined(rewritten)
    with _edited(outcomes, drifted):
        report = score_run(
            run_dir, code_revision="revision", check=True, split_dir=split_dir
        )
        assert report.differences == ("outcomes:C1/mei-0003",)
    summary = scored / "summary.md"
    with _edited(summary, summary.read_bytes() + b" "):
        report = score_run(
            run_dir, code_revision="revision", check=True, split_dir=split_dir
        )
        assert report.differences == ("summary.md",)


def test_check_covers_receipts_intents_and_specs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed receipts, intents and specs are under the guard too."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    split_dir = tmp_path / "split"
    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    scored = run_dir / "scored"

    def differences() -> tuple[str, ...]:
        return score_run(
            run_dir, code_revision="revision", check=True, split_dir=split_dir
        ).differences

    intent = scored / "intents" / "C3" / "mei-0001.json"
    with _edited(intent, intent.read_bytes() + b" "):
        assert differences() == ("intents:C3/mei-0001",)
    spec = scored / "specs" / "tcp-expiring-ttl.json"
    with _edited(spec, spec.read_bytes() + b" "):
        assert differences() == ("specs:tcp-expiring-ttl",)
    receipt = scored / "receipts" / "C1" / "mei-0001.json"
    document: dict[str, Any] = json.loads(receipt.read_text("utf-8"))
    tampered = json.loads(json.dumps(document))
    tampered["probes"][0]["candidate_frames"] = []
    with _edited(receipt, json.dumps(tampered).encode("utf-8")):
        assert differences() == ("receipts:C1/mei-0001",)
    jittered = json.loads(json.dumps(document))
    jittered["created_at"] = "2001-01-01T00:00:00Z"
    jittered["code_revision"] = "another-revision"
    jittered["metrics"]["p50_runtime_ms"] = 99.0
    jittered["metrics"]["p95_runtime_ms"] = 99.0
    for probe in jittered["probes"]:
        probe["runtime_ms"] = 99.0
    with _edited(receipt, json.dumps(jittered).encode("utf-8")):
        assert differences() == ()
    manifest = scored / "score_manifest.json"
    with _edited(manifest, b"{}\n"):
        assert differences() == ()


def test_prompt_drift_stops_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed prompt that cannot be rebuilt stops the whole run."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    path = run_dir / "prepared" / "C1.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    document["prompts"][0]["messages"][0]["content"] += "\nExtra guidance."
    _write_json(path, document)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "prompt_mismatch"
    assert str(error.value) == "C1 mei-0001"


def test_a_run_prepared_before_a_prompt_change_still_scores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every committed prompt rebuilds under the version that made it."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1", "C3"), prompt_version=1)

    result = score_run(
        run_dir, code_revision="revision", split_dir=tmp_path / "s"
    )

    assert result.items == 32


def test_a_condition_mixing_prompt_versions_stops_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One condition's prompts must all come from one prompt version."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C3",))
    path = run_dir / "prepared" / "C3.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    first = prepare_batch(
        [
            GenerationInputV1(
                item_id="mei-0002",
                intent=_INTENT,
                user_assumptions=_ASSUMPTIONS,
                split="dev",
            )
        ],
        output_contract=OutputContractV1.TYPED_IR,
        retrieval=RetrievalV1.NONE,
        prompt_version=1,
    )
    system = document["prompts"][1]["messages"][0]
    assert document["prompts"][1]["item_id"] == "mei-0002"
    assert system["content"] != first.prompts[0].messages[0].content
    system["content"] = first.prompts[0].messages[0].content
    _write_json(path, document)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "prompt_mismatch"
    assert str(error.value) == "C3 mei-0002"


def test_completion_items_must_match_prepared_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scoring refuses a completion batch that does not cover the prompts."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    path = run_dir / "completions" / "C1.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    document["completions"] = document["completions"][:-1]
    _write_json(path, document)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "items_mismatch"


def test_mixed_model_ids_stop_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two conditions answered by two models are not one measurement."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    path = run_dir / "completions" / "C3.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    document["settings"]["model_id"] = "vendor/model-b"
    _write_json(path, document)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "model_mismatch"


@pytest.mark.parametrize("split", [None, "test"])
def test_mixed_or_missing_splits_stop_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, split: str | None
) -> None:
    """Every committed prompt must carry the same declared split."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    path = run_dir / "prepared" / "C1.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    document["prompts"][0]["split"] = split
    _write_json(path, document)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "split_violation"


@pytest.mark.parametrize("mislabelled", ["prepared", "completions"])
def test_wrong_condition_file_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mislabelled: str
) -> None:
    """A batch stored under another label is refused before any execution."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1", "C2"))
    source = run_dir / mislabelled / "C2.json"
    source.replace(run_dir / mislabelled / "C1.json")

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "condition_mismatch"


def test_a_manifest_and_its_prompts_must_agree_on_the_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest cannot claim a split the committed prompts do not carry."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    path = run_dir / "prepared" / "C1.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    for prompt in document["prompts"]:
        prompt["split"] = "test"
    _write_json(path, document)
    _write_manifest(run_dir, ("C1",))

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "split_violation"
    assert str(error.value) == "prompts and manifest disagree on the split"


def test_checking_an_unscored_run_names_every_committed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory that was never scored differs in every committed file."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))

    report = score_run(
        run_dir,
        code_revision="revision",
        check=True,
        split_dir=tmp_path / "split",
    )

    assert report.checked and not (run_dir / "scored").exists()
    assert "summary.json" in report.differences
    assert "summary.md" in report.differences
    assert "outcomes:C1/mei-0001" in report.differences
    assert "receipts:C1/mei-0001" in report.differences
    assert "specs:tcp-expiring-ttl" in report.differences
    assert len(report.differences) == 42


def test_unreadable_committed_lines_and_receipts_still_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A committed file that no longer parses is a difference, not a crash."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    split_dir = tmp_path / "split"
    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    scored = run_dir / "scored"
    outcomes = scored / "outcomes.jsonl"
    kept = outcomes.read_text("utf-8").splitlines()[1:]
    broken = _joined(["not json", *kept])
    text = scored / "receipts" / "C1" / "mei-0002.json"
    array = scored / "receipts" / "C1" / "mei-0003.json"

    with _edited(outcomes, broken), _edited(text, b"not json"):
        with _edited(array, b"[]"):
            differences = score_run(
                run_dir,
                code_revision="revision",
                check=True,
                split_dir=split_dir,
            ).differences

    assert "outcomes:line-1" in differences
    assert "outcomes:C1/mei-0001" in differences
    assert "receipts:C1/mei-0002" in differences
    assert "receipts:C1/mei-0003" in differences

    stale = scored / "receipts" / "C1" / "mei-9999.json"
    stale.write_bytes(b"not json")
    try:
        report = score_run(
            run_dir, code_revision="revision", check=True, split_dir=split_dir
        )
    finally:
        stale.unlink()

    assert report.differences == ("receipts:C1/mei-9999",)


@pytest.mark.parametrize("shuffle", [True, False])
def test_check_proves_the_outcome_file_byte_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shuffle: bool
) -> None:
    """One LF-terminated line per item, sorted, with no duplicate."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    split_dir = tmp_path / "split"
    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    outcomes = run_dir / "scored" / "outcomes.jsonl"
    lines = outcomes.read_text("utf-8").splitlines()
    relaid = list(reversed(lines)) if shuffle else [lines[0], *lines]

    with _edited(outcomes, _joined(relaid)):
        report = score_run(
            run_dir, code_revision="revision", check=True, split_dir=split_dir
        )

    assert report.differences == ("outcomes.jsonl",)


def test_unknown_item_id_stops_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An item that routes to no gold case cannot be scored."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    for name in ("prepared", "completions"):
        path = run_dir / name / "C1.json"
        _write_json(
            path,
            json.loads(
                path.read_text("utf-8").replace("mei-0001", "mei-9999", 1)
            ),
        )

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "split_violation"


def test_manifest_must_describe_the_committed_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest is only evidence when it names the files it describes."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    split_dir = tmp_path / "split"

    _write_manifest(run_dir, tweak_sha="C1")
    with pytest.raises(ScoringError) as drifted:
        score_run(run_dir, code_revision="revision", split_dir=split_dir)

    _write_manifest(run_dir, drop_item="mei-0004")
    with pytest.raises(ScoringError) as missing:
        score_run(run_dir, code_revision="revision", split_dir=split_dir)

    _write_manifest(run_dir)
    report = score_run(run_dir, code_revision="revision", split_dir=split_dir)

    assert drifted.value.code == "manifest_mismatch"
    assert (
        str(drifted.value)
        == "C1: manifest does not describe the committed prompts"
    )
    assert missing.value.code == "manifest_mismatch"
    assert report.items == 32


def test_manifest_naming_an_uncommitted_condition_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A condition cannot vanish from a published summary without a signal."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    _write_manifest(run_dir, ("C1", "C3"))
    (run_dir / "prepared" / "C3.json").unlink()
    (run_dir / "completions" / "C3.json").unlink()

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "manifest_mismatch"
    assert str(error.value) == "C3: manifest and committed prompts disagree"


@pytest.mark.parametrize(
    "overrides", [{"prompt_count": 15}, {"mislabel": "C1"}]
)
def test_manifest_prompt_count_and_condition_shape_are_cross_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    """A manifest that miscounts or mistypes a condition is not evidence."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    _write_manifest(run_dir, ("C1",), **overrides)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "manifest_mismatch"
    assert (
        str(error.value)
        == "C1: manifest does not describe the committed prompts"
    )


@pytest.mark.parametrize(
    "overrides, message",
    [
        (
            {"run_labels": ("C1", "C4")},
            "C4: manifest and committed prompts disagree",
        ),
        (
            {"completed": 15},
            "C1: manifest does not describe the committed prompts",
        ),
    ],
)
def test_the_manifest_call_census_is_cross_checked_as_well(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
    message: str,
) -> None:
    """A manifest that describes the prompts can still miscount the calls."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    _write_manifest(run_dir, ("C1",), **overrides)

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "manifest_mismatch"
    assert str(error.value) == message


def test_manifest_prices_and_provider_cost_reach_the_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cost is reported from the manifest, or not reported at all."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    split_dir = tmp_path / "split"
    _write_manifest(
        run_dir,
        prices=TokenPricesV1(
            usd_per_million_input=0.117,
            usd_per_million_output=0.455,
            source="openrouter 2026-09-17",
        ),
        provider_reported_usd=0.0431,
        charged_usd_upper_bound=0.06,
    )

    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    priced = ScoreSummaryV1.model_validate_json(
        (run_dir / "scored" / "summary.json").read_bytes()
    )

    (run_dir / "run_manifest.json").unlink()
    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    unpriced = ScoreSummaryV1.model_validate_json(
        (run_dir / "scored" / "summary.json").read_bytes()
    )

    assert priced.conditions["C1"].usage.cost_usd is not None
    assert priced.provider_reported_usd == 0.0431
    assert priced.charged_usd_upper_bound == 0.06
    assert unpriced.conditions["C1"].usage.cost_usd is None
    assert unpriced.provider_reported_usd is None
    assert unpriced.charged_usd_upper_bound is None


_TOKEN_PRICES = TokenPricesV1(
    usd_per_million_input=0.117,
    usd_per_million_output=0.455,
    source="openrouter 2026-09-17",
)


def _scored(run_dir: Path, split_dir: Path) -> ScoreSummaryV1:
    """Scores one run directory and reads back the summary it committed."""
    score_run(run_dir, code_revision="revision", split_dir=split_dir)
    return ScoreSummaryV1.model_validate_json(
        (run_dir / "scored" / "summary.json").read_bytes()
    )


def _answered(**fields: Any) -> Callable[[str], dict[str, Any]]:
    """Returns provenance every recorded completion of a run carries."""
    return lambda item_id: dict(fields)


def test_effective_settings_reports_thinking_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A control counts as honoured only where every reply reports it."""
    _install_live(monkeypatch)
    run_dir = _run_dir(
        tmp_path,
        ("C1",),
        provenance=_answered(
            reasoning_tokens=0,
            reasoning_present=False,
            response_model=_MODEL_ID,
            provider="alibaba",
            system_fingerprint="fp_44709d6fcb",
        ),
    )
    _write_manifest(run_dir, ("C1",))

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.thinking == "honoured"
    assert settings.thinking_evidence_items == 16
    assert settings.reasoning_tokens_total == 0
    assert settings.items_with_reasoning == 0
    assert settings.requested_model == _MODEL_ID
    assert settings.served_models == (_MODEL_ID,)
    assert settings.served_model_changed is False
    assert settings.providers == ("alibaba",)
    assert settings.system_fingerprints == ("fp_44709d6fcb",)
    assert settings.seed_requested == 17
    assert settings.seed == "uncontrolled"
    assert settings.temperature == 0.0
    assert settings.max_output_tokens == 2048
    assert settings.json_mode is True
    assert settings.provider_order == ()
    assert settings.allow_fallbacks is None
    assert settings.timeout_seconds == 120.0


def test_effective_settings_reports_thinking_not_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One reply that reasoned is enough to report the switch ignored."""
    _install_live(monkeypatch)
    run_dir = _run_dir(
        tmp_path,
        ("C1",),
        provenance=lambda item_id: {
            "reasoning_tokens": 3 if item_id == "mei-0001" else 0,
            "reasoning_present": item_id == "mei-0001",
        },
    )
    _write_manifest(run_dir, ("C1",))

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.thinking == "not_honoured"
    assert settings.reasoning_tokens_total == 3
    assert settings.items_with_reasoning == 1
    assert settings.thinking_evidence_items == 16


def test_effective_settings_reports_thinking_uncontrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that reports nothing about reasoning controls nothing."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    _write_manifest(run_dir, ("C1",))

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.thinking == "uncontrolled"
    assert settings.thinking_evidence_items == 0
    assert settings.reasoning_tokens_total == 0
    assert settings.items_with_reasoning == 0
    assert settings.served_models == ()
    assert settings.providers == ()


def test_effective_settings_flags_a_changed_served_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run that silently routed elsewhere cannot report one model id."""
    _install_live(monkeypatch)
    run_dir = _run_dir(
        tmp_path,
        ("C1",),
        provenance=lambda item_id: {
            "response_model": (
                "vendor/model-a-turbo" if item_id == "mei-0001" else _MODEL_ID
            ),
            "provider": "novita" if item_id == "mei-0001" else "alibaba",
        },
    )
    _write_manifest(run_dir, ("C1",))

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.requested_model == _MODEL_ID
    assert settings.served_models == (_MODEL_ID, "vendor/model-a-turbo")
    assert settings.served_models_distinct == 2
    assert settings.served_model_changed is True
    assert settings.providers == ("alibaba", "novita")
    assert settings.providers_distinct == 2
    assert settings.provider_changed is True


def test_effective_settings_flags_one_consistent_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model served for every request is still not the model requested."""
    _install_live(monkeypatch)
    pinned = RequestSettingsV1(
        model_id=_MODEL_ID,
        openrouter=OpenRouterOptionsV1(provider_order=("alibaba",)),
    )
    run_dir = _run_dir(
        tmp_path,
        ("C1",),
        provenance=_answered(response_model="served/other", provider="novita"),
        settings=pinned,
    )
    _write_manifest(run_dir, ("C1",), settings=pinned)

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.served_models == ("served/other",)
    assert settings.served_models_distinct == 1
    assert settings.served_model_changed is True
    assert settings.providers == ("novita",)
    assert settings.provider_order == ("alibaba",)
    assert settings.provider_changed is True


@pytest.mark.parametrize(
    ("route", "served", "changed"),
    [
        ("deepinfra", "DeepInfra", False),
        ("deepinfra/fp8", "DeepInfra", False),
        ("google-ai-studio", "Google AI Studio", False),
        ("deepinfra", "Novita", True),
    ],
)
def test_effective_settings_matches_a_pinned_slug_to_its_display_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    served: str,
    changed: bool,
) -> None:
    """The router pins by slug but names the provider that answered."""
    _install_live(monkeypatch)
    pinned = RequestSettingsV1(
        model_id=_MODEL_ID,
        openrouter=OpenRouterOptionsV1(provider_order=(route,)),
    )
    run_dir = _run_dir(
        tmp_path,
        ("C1",),
        provenance=_answered(response_model=_MODEL_ID, provider=served),
        settings=pinned,
    )
    _write_manifest(run_dir, ("C1",), settings=pinned)

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.providers == (served,)
    assert settings.providers_distinct == 1
    assert settings.provider_changed is changed


def test_effective_settings_counts_the_values_it_could_not_print(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A router that answered with nine model ids says nine."""
    _install_live(monkeypatch)
    run_dir = _run_dir(
        tmp_path,
        ("C1",),
        provenance=lambda item_id: {
            "response_model": f"served/m-{item_id[-1]}",
            "system_fingerprint": f"fp_{item_id[-1]}",
        },
    )
    _write_manifest(run_dir, ("C1",))

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert len(settings.served_models) == 8
    assert settings.served_models_distinct == 10
    assert len(settings.system_fingerprints) == 8
    assert settings.system_fingerprints_distinct == 10


def test_a_reasoning_flag_alone_is_counted_as_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verdict drawn from a reading never publishes no reading at all."""
    _install_live(monkeypatch)
    run_dir = _run_dir(
        tmp_path, ("C1",), provenance=_answered(reasoning_present=True)
    )
    _write_manifest(run_dir, ("C1",))

    settings = _scored(run_dir, tmp_path / "split").effective_settings

    assert settings is not None
    assert settings.thinking == "not_honoured"
    assert settings.thinking_evidence_items == 16
    assert settings.items_with_reasoning == 16
    assert settings.reasoning_tokens_total == 0


def test_manifest_settings_must_be_the_settings_that_were_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest is only evidence of a request the client actually sent."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    split_dir = tmp_path / "split"

    _write_manifest(
        run_dir, ("C1",), settings=RequestSettingsV1(model_id="vendor/other")
    )
    with pytest.raises(ScoringError) as swapped:
        score_run(run_dir, code_revision="revision", split_dir=split_dir)

    _write_manifest(
        run_dir,
        ("C1",),
        settings=RequestSettingsV1(model_id=_MODEL_ID, temperature=1.9),
    )
    with pytest.raises(ScoringError) as heated:
        score_run(run_dir, code_revision="revision", split_dir=split_dir)

    _write_manifest(run_dir, ("C1",))
    report = score_run(run_dir, code_revision="revision", split_dir=split_dir)

    assert swapped.value.code == "manifest_mismatch"
    assert (
        str(swapped.value) == "C1: manifest settings are not the recorded ones"
    )
    assert heated.value.code == "manifest_mismatch"
    assert report.items == 16


def test_spend_marks_a_lower_bound_when_usage_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tokens a provider never reported were still spent."""
    _install_live(monkeypatch)
    partial = _run_dir(
        tmp_path / "partial",
        ("C1",),
        provenance=lambda item_id: (
            {"prompt_tokens": None} if item_id == "mei-0001" else {}
        ),
    )
    _write_manifest(partial, ("C1",), prices=_TOKEN_PRICES)
    whole = _run_dir(tmp_path / "whole", ("C1",))
    _write_manifest(whole, ("C1",), prices=_TOKEN_PRICES)

    bounded = _scored(partial, tmp_path / "partial-split")
    exact = _scored(whole, tmp_path / "whole-split")
    report = (partial / "scored" / "summary.md").read_text("utf-8")
    clean = (whole / "scored" / "summary.md").read_text("utf-8")

    assert bounded.spend is not None and exact.spend is not None
    assert bounded.spend.usage_missing == 1
    assert bounded.spend.price_derived_is_lower_bound is True
    assert bounded.spend.price_derived_usd == 0.000975
    assert "usage was missing for 1 item." in report
    assert exact.spend.usage_missing == 0
    assert exact.spend.price_derived_is_lower_bound is False
    assert "usage was missing" not in clean


def test_spend_marks_a_lower_bound_when_an_item_was_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An abandoned attempt left no completion record but spent tokens."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    split_dir = tmp_path / "split"
    _write_manifest(
        run_dir, ("C1",), prices=_TOKEN_PRICES, retried=("mei-0002",)
    )

    retried = _scored(run_dir, split_dir)
    report = (run_dir / "scored" / "summary.md").read_text("utf-8")

    _write_manifest(run_dir, ("C1",), prices=_TOKEN_PRICES)
    once = _scored(run_dir, split_dir)

    assert retried.spend is not None and once.spend is not None
    assert retried.spend.retried_items == 1
    assert retried.spend.usage_missing == 0
    assert retried.spend.price_derived_is_lower_bound is True
    assert "1 item spent tokens on a retry." in report
    assert once.spend.retried_items == 0
    assert once.spend.price_derived_is_lower_bound is False


def test_spend_flags_a_derived_figure_above_the_recorded_charge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recorded prices and a recorded charge that disagree are reported."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    split_dir = tmp_path / "split"
    _write_manifest(
        run_dir,
        ("C1",),
        prices=_TOKEN_PRICES,
        charged_usd_upper_bound=0.0001,
    )

    over = _scored(run_dir, split_dir)
    report = (run_dir / "scored" / "summary.md").read_text("utf-8")

    _write_manifest(run_dir, ("C1",), prices=_TOKEN_PRICES)
    within = _scored(run_dir, split_dir)

    assert over.spend is not None and within.spend is not None
    assert over.spend.derived_above_charged is True
    assert "above the charged upper bound" in report
    assert within.spend.derived_above_charged is False


def test_spend_carries_the_manifest_charges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The provider's own figure is reported beside the derived one."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    split_dir = tmp_path / "split"
    _write_manifest(
        run_dir,
        ("C1",),
        prices=_TOKEN_PRICES,
        provider_reported_usd=0.0431,
        charged_usd_upper_bound=0.06,
    )

    charged = _scored(run_dir, split_dir)
    stable = score_run(
        run_dir, code_revision="revision", check=True, split_dir=split_dir
    )

    _write_manifest(run_dir, ("C1",), prices=_TOKEN_PRICES)
    quiet = _scored(run_dir, split_dir)

    (run_dir / "run_manifest.json").unlink()
    bare = _scored(run_dir, split_dir)

    assert charged.spend is not None
    assert charged.spend.price_derived_usd == 0.00104
    assert charged.spend.price_derived_usd == (
        charged.conditions["C1"].usage.cost_usd
    )
    assert charged.spend.provider_reported_usd == 0.0431
    assert charged.spend.charged_usd_upper_bound == 0.06
    assert stable.differences == ()
    assert quiet.spend is not None
    assert quiet.spend.provider_reported_usd is None
    assert quiet.spend.charged_usd_upper_bound == 0.06
    assert bare.spend is None
    assert bare.effective_settings is None
    assert "## Spend" not in (run_dir / "scored" / "summary.md").read_text(
        "utf-8"
    )


def test_oversized_run_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run file above the byte ceiling is never read."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    (run_dir / "prepared" / "C1.json").write_bytes(b"x" * (33 * 1024 * 1024))

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "run_layout_invalid"
    assert str(error.value) == "C1.json is not a readable run file"


@pytest.mark.skipif(sys.platform != "linux", reason="requires POSIX symlinks")
@pytest.mark.parametrize("dangling", [False, True])
def test_symlinked_prepared_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dangling: bool
) -> None:
    """A symlinked prompt file is refused rather than followed or dropped."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    path = run_dir / "prepared" / "C1.json"
    real = run_dir / "real.json"
    path.replace(real)
    path.symlink_to(real)
    if dangling:
        real.unlink()

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "run_layout_invalid"
    assert str(error.value) == "C1.json is not a readable run file"


def test_a_stray_file_in_prepared_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the four named condition files may live in prepared/."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))
    (run_dir / "prepared" / "notes.json").write_bytes(b"{}\n")

    with pytest.raises(ScoringError) as error:
        score_run(run_dir, code_revision="revision", split_dir=tmp_path / "s")

    assert error.value.code == "run_layout_invalid"
    assert (
        str(error.value) == "prepared holds a file that is not a condition file"
    )


def test_missing_run_directory_and_missing_completions_are_layout_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent directory or completion file stops before any execution."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",))

    with pytest.raises(ScoringError) as absent:
        score_run(tmp_path / "nowhere", code_revision="revision")

    (run_dir / "completions" / "C1.json").unlink()
    with pytest.raises(ScoringError) as incomplete:
        score_run(run_dir, code_revision="revision")

    empty = tmp_path / "dev-0002"
    (empty / "prepared").mkdir(parents=True)
    with pytest.raises(ScoringError) as bare:
        score_run(empty, code_revision="revision")

    unprepared = tmp_path / "dev-0003"
    unprepared.mkdir()
    with pytest.raises(ScoringError) as missing:
        score_run(unprepared, code_revision="revision")

    assert absent.value.code == "run_layout_invalid"
    assert incomplete.value.code == "run_layout_invalid"
    assert bare.value.code == "run_layout_invalid"
    assert str(bare.value) == "prepared holds no condition file"
    assert missing.value.code == "run_layout_invalid"
    assert str(missing.value) == "prepared is not a readable directory"


_IMPORT_CHECK = """
import sys
import dfilterforge.scoring
loaded = {"http.client", "ssl", "dfilterforge.model_client"} & set(sys.modules)
print(sorted(loaded))
"""


def test_scoring_never_imports_the_network_client() -> None:
    """The scoring path cannot reach the HTTP client at all."""
    loaded = subprocess.run(
        [sys.executable, "-c", _IMPORT_CHECK],
        capture_output=True,
        check=True,
        text=True,
        timeout=120,
    )

    assert loaded.stdout.strip() == "[]"


def test_score_report_counts_every_outcome_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The report census always carries one key per protocol outcome."""
    _install_live(monkeypatch, inexact=("semantic-11",))
    run_dir = _run_dir(tmp_path, ("C1",))

    report = score_run(
        run_dir, code_revision="revision", split_dir=tmp_path / "split"
    )

    assert set(report.outcomes) == {outcome.value for outcome in OutcomeV1}
    assert report.outcomes[OutcomeV1.SILENT_WRONG.value] == 16
    assert report.items == 16
    assert report.summary_sha256


_CONTROL_LABELS: tuple[ConditionLabel, ...] = ("C1", "C2", "C3", "C4")
# The key set A11 froze for the display-filter envelope. Asserting it as a
# literal is what proves the control envelope is generated from the response
# model rather than from a hand-written dict that A11 already invalidated.
_DIRECT_FILTER_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "assumptions",
        "clarifying_question",
        "missing_slots",
        "display_filter",
    }
)
_ControlCompletion: TypeAlias = Callable[
    [PreparedPromptV1, ModelGoldCaseV1, str], CompletionV1 | None
]
_ControlBatch: TypeAlias = Callable[
    [PreparedBatchV1, dict[str, ModelGoldCaseV1], str],
    CompletionBatchV1 | None,
]
_control_completion: _ControlCompletion = getattr(
    scoring_module, "_control_completion"
)
_control_batch: _ControlBatch = getattr(scoring_module, "_control_batch")


def _dev_conditions(
    root: Path, labels: Sequence[ConditionLabel] = _CONTROL_LABELS
) -> tuple[dict[ConditionLabel, PreparedBatchV1], dict[str, ModelGoldCaseV1]]:
    """Prepares the named conditions over the dev split and routes them."""
    artifacts = generate_model_split(root)
    items = [item for item in artifacts.inputs if item.split == "dev"]
    cases = {case.case_id: case for case in artifacts.gold.cases}
    routes = {
        item.item_id: cases[artifacts.gold.item_to_case[item.item_id]]
        for item in items
    }
    batches: dict[ConditionLabel, PreparedBatchV1] = {}
    for label in labels:
        output_contract, retrieval = _CONDITION_INPUTS[label]
        batches[label] = prepare_batch(
            [
                GenerationInputV1(
                    item_id=item.item_id,
                    intent=item.intent,
                    user_assumptions=item.user_assumptions,
                    retrieved_fields=(
                        () if retrieval is RetrievalV1.LEXICAL else None
                    ),
                    split=item.split,
                )
                for item in items
            ],
            output_contract=output_contract,
            retrieval=retrieval,
        )
    return batches, routes


def test_reference_control_outputs_parse_under_their_contracts(
    tmp_path: Path,
) -> None:
    """Every gold-derived reference answer parses ready under its contract."""
    batches, routes = _dev_conditions(tmp_path / "source")

    answered = 0
    for batch in batches.values():
        for prompt in batch.prompts:
            case = routes[prompt.item_id]
            answer = _control_completion(prompt, case, "reference")
            assert answer is not None
            parsed = parse_response(
                prompt.output_contract, answer.response_text or ""
            )
            assert parsed.status is GenerationStatus.READY
            if isinstance(parsed, DirectFilterResultV1):
                assert parsed.display_filter == case.spec.reference_filter
            else:
                assert parsed.intent_ir == case.spec.canonical_ir
            answered += 1

    assert answered == 64


def test_control_envelopes_carry_every_contract_key(tmp_path: Path) -> None:
    """The envelope is the response model's own shape, not a literal."""
    batches, routes = _dev_conditions(tmp_path / "source", ("C1",))
    prompt = batches["C1"].prompts[0]

    answer = _control_completion(prompt, routes[prompt.item_id], "reference")

    assert answer is not None
    envelope: dict[str, Any] = json.loads(answer.response_text or "")
    assert set(envelope) == _DIRECT_FILTER_KEYS
    assert set(DirectFilterResultV1.model_fields) == _DIRECT_FILTER_KEYS
    assert envelope["status"] == "ready"


def test_mutation_control_uses_mutation_filters_and_skips_typed_conditions(
    tmp_path: Path,
) -> None:
    """Gold records a near-wrong filter per case and no near-wrong IR."""
    batches, routes = _dev_conditions(tmp_path / "source")

    direct = _control_batch(batches["C1"], routes, "mutation")

    assert direct is not None
    assert len(direct.completions) == 16
    for answer in direct.completions:
        envelope: dict[str, Any] = json.loads(answer.response_text or "")
        mutation = routes[answer.item_id].mutation_filter
        assert envelope["display_filter"] == mutation
    assert _control_batch(batches["C3"], routes, "mutation") is None
    assert _control_batch(batches["C4"], routes, "mutation") is None


def test_control_does_not_read_completions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run directory with no stored answers at all still scores."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, stored=False)

    report = score_run(
        run_dir,
        code_revision="revision",
        control="reference",
        split_dir=tmp_path / "split",
    )

    assert not (run_dir / "completions").exists()
    assert report.output_dir == run_dir / "control-reference"
    assert not (run_dir / "scored").exists()
    assert report.items == 32
    assert report.outcomes[OutcomeV1.STRONG_EXACT.value] == 32


def test_control_batch_settings_carry_the_control_model_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The synthesized batch names the control, and so does the summary."""
    batches, routes = _dev_conditions(tmp_path / "source", ("C1",))
    reference = _control_batch(batches["C1"], routes, "reference")
    mutation = _control_batch(batches["C1"], routes, "mutation")
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path / "run", stored=False)

    score_run(
        run_dir,
        code_revision="revision",
        control="mutation",
        split_dir=tmp_path / "split",
    )
    summary = ScoreSummaryV1.model_validate_json(
        (run_dir / "control-mutation" / "summary.json").read_bytes()
    )

    assert reference is not None and mutation is not None
    assert reference.settings.model_id == "control-reference"
    assert mutation.settings.model_id == "control-mutation"
    assert summary.model_id == "control-mutation"
    assert set(summary.conditions) == {"C1"}
    assert summary.not_measured["C3"] == "no_typed_mutation"
    assert set(summary.batch_hashes) == {"prepared/C1"}


def test_control_ignores_manifest_prices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A free control pass can never be reported with a paid run's money."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path)
    _write_manifest(
        run_dir,
        prices=_TOKEN_PRICES,
        provider_reported_usd=0.0431,
        charged_usd_upper_bound=0.06,
    )

    score_run(
        run_dir,
        code_revision="revision",
        control="reference",
        split_dir=tmp_path / "split",
    )
    summary = ScoreSummaryV1.model_validate_json(
        (run_dir / "control-reference" / "summary.json").read_bytes()
    )

    assert summary.conditions["C1"].usage.cost_usd is None
    assert summary.conditions["C1"].usage.cost_per_item_usd is None
    assert summary.provider_reported_usd is None
    assert summary.charged_usd_upper_bound is None
    assert summary.spend is None
    assert summary.effective_settings is None


def test_a_control_mode_with_nothing_to_answer_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typed-only run has no mutation to score, and says so."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C3",), stored=False)

    with pytest.raises(ScoringError) as error:
        score_run(
            run_dir,
            code_revision="revision",
            control="mutation",
            split_dir=tmp_path / "split",
        )

    assert error.value.code == "run_layout_invalid"
    assert str(error.value) == (
        "No condition can be scored under this control mode"
    )


def test_an_unpinned_control_pass_refuses_a_held_out_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory with no manifest at all cannot publish a held-out key.

    A control pass reads no stored answer, so nothing but ``prepared/``
    is needed to run the whole path and write every gold specification it
    touches. Without a manifest the split is the prompts' own claim, and
    the only split a run can claim for itself is the development one.
    """
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",), stored=False, split="test")

    with pytest.raises(ScoringError) as error:
        score_run(
            run_dir,
            code_revision="revision",
            control="reference",
            split_dir=tmp_path / "split",
        )

    assert error.value.code == "split_violation"
    assert str(error.value) == (
        "an unpinned control pass is limited to the dev split"
    )
    assert not (run_dir / "control-reference").exists()
    assert not (run_dir / "split" / "captures").exists()


def test_a_committed_prepare_manifest_pins_the_split_and_the_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The frozen prompts carry their own provenance before any run."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",), stored=False)
    prepare = _write_prepare(
        run_dir,
        ("C1",),
        created_at=datetime(2026, 9, 17, 11, 30, tzinfo=timezone.utc),
    )

    report = score_run(
        run_dir,
        code_revision="revision",
        control="reference",
        split_dir=tmp_path / "split",
    )

    receipt: dict[str, Any] = json.loads(
        (report.output_dir / "receipts" / "C1" / "mei-0001.json").read_text(
            "utf-8"
        )
    )
    assert prepare.split == "dev"
    assert report.items == 16
    assert receipt["created_at"].startswith("2026-09-17T11:30")


def test_a_prepare_manifest_refuses_relabelled_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relabelling the prompts cannot widen the split the manifest pinned."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",), stored=False)
    path = run_dir / "prepared" / "C1.json"
    document: dict[str, Any] = json.loads(path.read_text("utf-8"))
    for prompt in document["prompts"]:
        prompt["split"] = "test"
    _write_json(path, document)
    _write_prepare(run_dir, ("C1",))

    with pytest.raises(ScoringError) as error:
        score_run(
            run_dir,
            code_revision="revision",
            control="reference",
            split_dir=tmp_path / "split",
        )

    assert error.value.code == "split_violation"
    assert str(error.value) == "prompts and manifest disagree on the split"


def test_a_prepare_manifest_cross_checks_the_committed_prompt_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prompt file that drifted from its recorded hash is not scored."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1",), stored=False)
    _write_prepare(run_dir, ("C1",), tweak_sha="C1")

    with pytest.raises(ScoringError) as error:
        score_run(
            run_dir,
            code_revision="revision",
            control="reference",
            split_dir=tmp_path / "split",
        )

    assert error.value.code == "manifest_mismatch"
    assert (
        str(error.value)
        == "C1: manifest does not describe the committed prompts"
    )


def test_control_publishes_only_the_cases_its_conditions_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dropped condition takes its gold out of the published answer key."""
    _install_live(monkeypatch)
    run_dir = _run_dir(tmp_path, ("C1", "C3"), stored=False, keep={"C1": 4})
    gold = generate_model_split(tmp_path / "expected").gold
    scored_items = _dev_item_ids(run_dir)
    expected = sorted({gold.item_to_case[item] for item in scored_items})

    report = score_run(
        run_dir,
        code_revision="revision",
        control="mutation",
        split_dir=tmp_path / "split",
    )

    summary = ScoreSummaryV1.model_validate_json(
        (report.output_dir / "summary.json").read_bytes()
    )
    published = sorted(
        path.stem for path in (report.output_dir / "specs").glob("*.json")
    )
    assert len(scored_items) == 4 and report.items == 4
    assert summary.not_measured["C3"] == "no_typed_mutation"
    assert published == expected and len(published) < len(gold.cases)
    assert summary.case_count == len(published)
