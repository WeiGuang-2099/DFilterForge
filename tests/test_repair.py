"""Repair plans: the schema, the refusals and the feedback-only rule.

Most tests replace the card builder with a table, so the trigger set, the
order, the digests and every refusal are checked without tshark; the
tests marked POSIX-only score a pass and build its cards with the pinned
tshark, as the lab command does.
"""

from collections.abc import Callable, Mapping
import dataclasses
from datetime import datetime
from datetime import timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Literal

from pydantic import ValidationError
import pytest

from dfilterforge import held_out as held_out_module
from dfilterforge import repair as repair_module
from dfilterforge.canonical import canonical_json
from dfilterforge.cli import main
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import REPAIR_CARD_MAX_BYTES
from dfilterforge.completions import REPAIR_FEEDBACK_PROBES
from dfilterforge.completions import RepairItemV1
from dfilterforge.completions import RepairPlanV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.counterexample import card_json
from dfilterforge.counterexample import CARD_MAX_BYTES
from dfilterforge.counterexample import CardBuilder
from dfilterforge.counterexample import CounterexampleCardV1
from dfilterforge.counterexample import CounterexampleError
from dfilterforge.counterexample import ErrorCardV1
from dfilterforge.counterexample import FrameFactV1
from dfilterforge.counterexample import FramesCardV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import GenerationError
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.model_feedback import feedback_labels_sha256
from dfilterforge.model_feedback import FEEDBACK_PROBE_IDS
from dfilterforge.model_feedback import FeedbackProbes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.model_split import ModelSplitArtifacts
from dfilterforge.model_split import MUTANT_WAIVERS
from dfilterforge.mutants import single_site_mutants
from dfilterforge.repair import build_plan
from dfilterforge.repair import plan_bytes
from dfilterforge.repair import PLAN_PATH
from dfilterforge.repair import repair_run
from dfilterforge.repair import RepairError
from dfilterforge.run_store import ScoringError
from dfilterforge.runner import TsharkRunner
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.scoring import score_run

_POSIX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)
_CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)
_SETTINGS = RequestSettingsV1(model_id="vendor/model-a")
_RUNS = {"dev": "dev-model-a-2026-10-01", "test": "test-model-a-2026-10-01"}
_UNKNOWN_FIELD_IR = IntentIrV1(
    expression=Predicate(field="ip.ttll", operator=Operator.LE, value=1)
)
# An answer the fake builder treats as one the feedback probe cannot tell
# from its labels.
_BLIND_IR = IntentIrV1(
    expression=Predicate(field="frame.len", operator=Operator.GE, value=1)
)
_ERROR_CARD = ErrorCardV1(error="unknown_field", field="ip.ttll")
_FRAMES_CARD = FramesCardV1(
    frames=(
        FrameFactV1.model_validate(
            {
                "frame": 3,
                "answer_matched": True,
                "should_match": False,
                "ip.src": "192.0.2.129",
                "ip.dst": "198.51.100.1",
                "ip.ttl": 64,
                "ip.dsfield.ecn": 0,
                "udp.srcport": 41129,
                "udp.dstport": 53,
            }
        ),
    )
)
_NOT_EXPRESSIBLE = canonical_json(
    GenerationResultV1(status=GenerationStatus.NOT_EXPRESSIBLE)
)
_LABELS: dict[ConditionLabel, tuple[OutputContractV1, RetrievalV1]] = {
    "C3": (OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    "C4": (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
}


def _ir_reply(intent: IntentIrV1) -> str:
    """Renders one ready typed-IR answer."""
    return canonical_json(
        GenerationResultV1(status=GenerationStatus.READY, intent_ir=intent)
    )


def _write(path: Path, value: object) -> bytes:
    """Writes one contract as canonical JSON with an LF ending."""
    payload = (canonical_json(value) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


@pytest.fixture(name="source", scope="module")
def fixture_source(
    tmp_path_factory: pytest.TempPathFactory,
) -> ModelSplitArtifacts:
    """The split the plan regenerates, for item ids and gold routing."""
    return generate_model_split(tmp_path_factory.mktemp("source"))


def _items(
    source: ModelSplitArtifacts, split: str, count: int | None = None
) -> list[ModelInputItemV1]:
    """The split's items in numbering order, the first ``count`` of them."""
    items = [item for item in source.inputs if item.split == split]
    return items if count is None else items[:count]


def _default_reply(source: ModelSplitArtifacts, item_id: str) -> str:
    """Answers ready gold with its canonical IR and abstains otherwise."""
    case_id = source.gold.item_to_case[item_id]
    for case in source.gold.cases:
        if case.case_id == case_id:
            return _ir_reply(case.spec.canonical_ir)
    return _NOT_EXPRESSIBLE


# pylint: disable-next=too-many-arguments,too-many-locals
def _write_base(
    root: Path,
    source: ModelSplitArtifacts,
    *,
    split: Literal["dev", "test"] = "dev",
    count: int | None = None,
    replies: Mapping[str, str | None] | None = None,
    label: ConditionLabel = "C4",
    status: Literal["complete", "incomplete"] = "complete",
    reverse: bool = False,
) -> Path:
    """Writes a published one-condition pass, unscored.

    A null reply is a provider failure. ``reverse`` writes the prompts in
    descending item order, so prepare order is not numbering order.
    """
    items = _items(source, split, count)
    if reverse:
        items.reverse()
    output_contract, retrieval = _LABELS[label]
    run_dir = root / _RUNS[split]
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
    )
    chosen = dict(replies or {})
    answers: list[CompletionV1] = []
    for item in items:
        reply = chosen.get(item.item_id, _default_reply(source, item.item_id))
        answers.append(
            CompletionV1(
                item_id=item.item_id,
                status=CompletionStatusV1.FAILED,
                error_code="timeout",
                latency_ms=1.0,
            )
            if reply is None
            else CompletionV1(
                item_id=item.item_id,
                status=CompletionStatusV1.COMPLETED,
                response_text=reply,
                latency_ms=1.0,
                prompt_tokens=10,
                completion_tokens=5,
                finish_reason="stop",
            )
        )
    prepared = _write(run_dir / "prepared" / f"{label}.json", batch)
    _write(
        run_dir / "completions" / f"{label}.json",
        CompletionBatchV1(
            output_contract=output_contract,
            retrieval=retrieval,
            settings=_SETTINGS,
            completions=tuple(answers),
        ),
    )
    prepare = PrepareManifestV1(
        prepare_id="prep-0001",
        created_at=_CREATED_AT,
        source_revision="revision",
        source_files={"scripts/model_run.py": "1" * 64},
        split=split,
        item_ids=tuple(item.item_id for item in items),
        model_inputs_sha256="2" * 64,
        catalog=CatalogIdentityV1(
            file_name="catalog.sqlite3",
            file_sha256="3" * 64,
            sqlite_sha256="3" * 64,
            catalog_hash="4" * 64,
            tshark_version="4.6.8",
        ),
        top_k=16,
        conditions=(
            PreparedConditionV1(
                label=label,
                output_contract=output_contract,
                retrieval=retrieval,
                path=f"prepared/{label}.json",
                sha256=hashlib.sha256(prepared).hexdigest(),
                system_prompt_sha256="5" * 64,
                prompt_count=len(items),
            ),
        ),
    )
    _write(run_dir / "prepare.json", prepare)
    _write(
        run_dir / "run_manifest.json",
        RunManifestV1(
            run_id=run_dir.name,
            created_at=_CREATED_AT,
            prepare=prepare,
            prepare_sha256="6" * 64,
            endpoint_host="openrouter.ai",
            settings=_SETTINGS,
            max_attempts=3,
            min_interval_seconds=1.0,
            invocations=(
                InvocationV1(
                    source_revision="revision",
                    source_files={"scripts/model_run.py": "1" * 64},
                    started_at=_CREATED_AT,
                    finished_at=_CREATED_AT,
                    max_usd=0.05,
                    requests_sent=len(items),
                ),
            ),
            status=status,
            charged_usd_upper_bound=0.01,
            conditions=(
                ConditionRunV1(
                    label=label,
                    attempts_path=f"attempts/{label}.jsonl",
                    attempts_sha256="7" * 64,
                    completions_path=f"completions/{label}.json",
                    completions_sha256="8" * 64,
                    attempts={item.item_id: 1 for item in items},
                    completed=len(items),
                    failed=0,
                    pending=0,
                ),
            ),
        ),
    )
    return run_dir


def _ready_ir(response_text: str | None) -> IntentIrV1 | None:
    """The ready typed IR an answer parses to, as the scorer reads it."""
    if response_text is None:
        return None
    try:
        parsed = parse_response(OutputContractV1.TYPED_IR, response_text)
    except GenerationError:
        return None
    if not isinstance(parsed, GenerationResultV1):
        return None
    return parsed.intent_ir


def _write_scored(
    run_dir: Path,
    source: ModelSplitArtifacts,
    verdicts: Mapping[str, OutcomeV1],
    *,
    tree: str = "scored",
    cases: Mapping[str, str] | None = None,
) -> bytes:
    """Writes a scored tree as the scorer lays it out, with given verdicts.

    An item with no verdict is strong exact on ready gold and abstained on
    non-ready gold; every ready answer's intent is written, as scoring
    does.
    """
    batch = PreparedBatchV1.model_validate_json(
        (run_dir / "prepared" / "C4.json").read_bytes()
    )
    recorded = CompletionBatchV1.model_validate_json(
        (run_dir / "completions" / "C4.json").read_bytes()
    )
    answers = {item.item_id: item for item in recorded.completions}
    ready = {case.case_id for case in source.gold.cases}
    intents = run_dir / "scored" / "intents" / "C4"
    lines: list[str] = []
    for prompt in sorted(batch.prompts, key=lambda prompt: prompt.item_id):
        case_id = source.gold.item_to_case[prompt.item_id]
        default = (
            OutcomeV1.STRONG_EXACT if case_id in ready else OutcomeV1.ABSTAINED
        )
        outcome = ItemOutcomeV1(
            condition="C4",
            item_id=prompt.item_id,
            case_id=(cases or {}).get(prompt.item_id, case_id),
            outcome=verdicts.get(prompt.item_id, default),
            gold_field_count=1,
            latency_ms=1.0,
        )
        lines.append(canonical_json(outcome) + "\n")
        intent = _ready_ir(answers[prompt.item_id].response_text)
        if intent is not None:
            _write(intents / f"{prompt.item_id}.json", intent)
    payload = "".join(lines).encode("utf-8")
    (run_dir / tree).mkdir(parents=True, exist_ok=True)
    (run_dir / tree / "outcomes.jsonl").write_bytes(payload)
    return payload


def _fake_card(candidate: IntentIrV1 | str) -> CounterexampleCardV1 | None:
    """An error card for the unknown field, none for the blind answer."""
    if candidate == _UNKNOWN_FIELD_IR:
        return _ERROR_CARD
    if candidate == _BLIND_IR:
        return None
    return _FRAMES_CARD


class _Spy:
    """Records what the fake builder saw and answers from a fixed table."""

    def __init__(self) -> None:
        self.splits: list[ModelSplitArtifacts] = []
        self.cards: list[tuple[str, IntentIrV1 | str]] = []
        self.feedback: list[FeedbackProbes] = []
        self.answer: Callable[
            [IntentIrV1 | str], CounterexampleCardV1 | None
        ] = _fake_card


@pytest.fixture(name="spy")
def fixture_spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    """Replaces the card builder and watches the regenerated split."""
    spy = _Spy()
    generate = repair_module.generate_model_split

    def generate_and_keep(output_dir: Path) -> ModelSplitArtifacts:
        artifacts = generate(output_dir)
        spy.splits.append(artifacts)
        return artifacts

    class FakeBuilder:
        """Builds cards from the table, never from a scored capture."""

        def __init__(
            self, feedback: FeedbackProbes, runner: TsharkRunner | None = None
        ) -> None:
            del runner
            spy.feedback.append(feedback)

        def card(
            self, case_id: str, candidate: IntentIrV1 | str
        ) -> CounterexampleCardV1 | None:
            assert not any(
                path.exists() for path in spy.splits[-1].capture_paths
            )
            assert all(
                probe.capture_path.is_file()
                for probe in spy.feedback[-1].probes
            )
            card = spy.answer(candidate)
            spy.cards.append((case_id, candidate))
            return card

    monkeypatch.setattr(
        repair_module, "generate_model_split", generate_and_keep
    )
    monkeypatch.setattr(repair_module, "CardBuilder", FakeBuilder)
    return spy


def _refusal(run_dir: Path) -> DFilterForgeError:
    """Builds a plan that must be refused and returns the refusal."""
    with pytest.raises(DFilterForgeError) as error:
        build_plan(run_dir)
    return error.value


def _mutant(source: ModelSplitArtifacts, case_id: str) -> IntentIrV1:
    """The first single-site mutant of a case that no waiver keeps."""
    waived = {(waiver.case_id, waiver.edit) for waiver in MUTANT_WAIVERS}
    (case,) = [case for case in source.gold.cases if case.case_id == case_id]
    return next(
        mutant.intent
        for mutant in single_site_mutants(case.spec.canonical_ir)
        if (case_id, mutant.edit) not in waived
    )


def _ready_items(source: ModelSplitArtifacts, split: str) -> list[str]:
    """The split's item ids that route to ready gold, in numbering order."""
    ready = {case.case_id for case in source.gold.cases}
    return [
        item.item_id
        for item in _items(source, split)
        if source.gold.item_to_case[item.item_id] in ready
    ]


def test_the_plan_schema_names_each_splits_own_feedback_probe() -> None:
    assert dict(REPAIR_FEEDBACK_PROBES) == dict(FEEDBACK_PROBE_IDS)
    assert REPAIR_CARD_MAX_BYTES == CARD_MAX_BYTES


def _plan(**overrides: Any) -> dict[str, Any]:
    """A valid plan document with one item of each card kind."""
    values: dict[str, Any] = {
        "schema_version": "repair-plan/1.0",
        "split": "dev",
        "base_run": "dev-qwen3-32b-2026-09-26",
        "base_run_manifest_sha256": "a" * 64,
        "base_outcomes_sha256": "b" * 64,
        "feedback_labels_sha256": "c" * 64,
        "feedback_probe": "semantic-29",
        "items": [
            {
                "item_id": "mei-0001",
                "base_outcome": "silent_wrong",
                "card_kind": "frames",
                "card": card_json(_FRAMES_CARD),
            },
            {
                "item_id": "mei-0003",
                "base_outcome": "invalid",
                "card_kind": "error",
                "card": card_json(_ERROR_CARD),
            },
            {
                "item_id": "mei-0004",
                "base_outcome": "silent_wrong",
                "card_kind": "none",
                "card": None,
            },
        ],
    }
    values.update(overrides)
    return values


def test_a_plan_round_trips_as_canonical_json() -> None:
    plan = RepairPlanV1.model_validate(_plan())

    encoded = canonical_json(plan)

    assert RepairPlanV1.model_validate_json(encoded) == plan
    assert plan_bytes(plan) == (encoded + "\n").encode("utf-8")
    assert "created_at" not in encoded and "revision" not in encoded
    assert RepairPlanV1.model_validate(_plan(items=[])).items == ()


@pytest.mark.parametrize(
    "item",
    [
        {"card_kind": "frames", "card": None},
        {"card_kind": "none", "card": card_json(_ERROR_CARD)},
        {"card_kind": "error", "card": card_json(_FRAMES_CARD)},
        {"card_kind": "frames", "card": card_json(_ERROR_CARD)},
        {"card_kind": "error", "card": '{"error": "unknown_field"}'},
        {"card_kind": "error", "card": '{"field":"a","error":"x"}'},
        {"card_kind": "error", "card": '["error"]'},
        {"card_kind": "error", "card": '{"error":NaN}'},
        {"card_kind": "error", "card": '{"error":"a","error":"b"}'},
        {"card_kind": "error", "card": "not json"},
        {"card_kind": "error", "card": '{"error":"x","note":"y"}'},
        {
            "card_kind": "error",
            "card": canonical_json({"error": "x" * REPAIR_CARD_MAX_BYTES}),
        },
        {"item_id": "mei-1"},
        {"item_id": "item-0001"},
        {"base_outcome": "shortcut"},
        {"base_outcome": "strong_exact"},
        {"card_kind": "trace"},
        {"extra": "field"},
    ],
)
def test_an_item_must_hold_a_bounded_card_of_its_kind(
    item: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "item_id": "mei-0001",
        "base_outcome": "invalid",
        "card_kind": "error",
        "card": card_json(_ERROR_CARD),
    }
    values.update(item)

    with pytest.raises(ValidationError):
        RepairItemV1.model_validate(values)


def test_a_card_at_the_byte_cap_is_accepted() -> None:
    padding = REPAIR_CARD_MAX_BYTES - len(canonical_json({"error": ""}))
    card = canonical_json({"error": "x" * padding})

    item = RepairItemV1(
        item_id="mei-0001",
        base_outcome="invalid",
        card_kind="error",
        card=card,
    )

    assert len((item.card or "").encode("utf-8")) == REPAIR_CARD_MAX_BYTES


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_run": "test-qwen3-32b-2026-09-26"},
        {"base_run": "dev-qwen3-32b"},
        {"base_run": "dev-Qwen3-2026-09-26"},
        {"base_run": "dev-" + "a" * 33 + "-2026-09-26"},
        {"feedback_probe": "semantic-35"},
        {"split": "test", "base_run": "test-qwen3-32b-2026-09-26"},
        {"split": "train"},
        {"base_outcomes_sha256": "B" * 64},
        {"schema_version": "repair-plan/1.1"},
        {"created_at": "2026-10-01T00:00:00Z"},
    ],
)
def test_a_plan_pins_its_split_base_and_probe(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        RepairPlanV1.model_validate(_plan(**overrides))


def test_a_plan_lists_each_item_once() -> None:
    items = _plan()["items"]

    with pytest.raises(ValidationError):
        RepairPlanV1.model_validate(_plan(items=[items[0], items[0]]))


def test_a_plan_lists_the_triggered_items_in_prepare_order(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    ready = _ready_items(source, "dev")
    replies = {
        ready[0]: _ir_reply(_BLIND_IR),
        ready[2]: _ir_reply(_UNKNOWN_FIELD_IR),
        ready[3]: _ir_reply(_BLIND_IR),
        ready[5]: _ir_reply(_BLIND_IR),
        ready[6]: _ir_reply(_BLIND_IR),
        ready[7]: None,
    }
    verdicts = {
        ready[0]: OutcomeV1.SILENT_WRONG,
        ready[2]: OutcomeV1.INVALID,
        ready[3]: OutcomeV1.SHORTCUT,
        ready[5]: OutcomeV1.SILENT_WRONG,
        ready[6]: OutcomeV1.STRONG_EXACT,
        ready[7]: OutcomeV1.PROVIDER_FAILED,
    }
    run_dir = _write_base(tmp_path, source, replies=replies, reverse=True)
    outcomes = _write_scored(run_dir, source, verdicts)

    plan = build_plan(run_dir)

    assert [
        (item.item_id, item.base_outcome, item.card_kind) for item in plan.items
    ] == [
        (ready[5], "silent_wrong", "none"),
        (ready[2], "invalid", "error"),
        (ready[0], "silent_wrong", "none"),
    ]
    assert plan.items[1].card == card_json(_ERROR_CARD)
    assert plan.split == "dev"
    assert plan.base_run == run_dir.name
    assert plan.feedback_probe == "semantic-29"
    assert (
        plan.base_run_manifest_sha256
        == hashlib.sha256(
            (run_dir / "run_manifest.json").read_bytes()
        ).hexdigest()
    )
    assert plan.base_outcomes_sha256 == hashlib.sha256(outcomes).hexdigest()
    assert plan.feedback_labels_sha256 == feedback_labels_sha256(
        spy.feedback[0], "dev"
    )
    # The builder saw only the triggered answers, each on its own case.
    assert spy.cards == [
        (source.gold.item_to_case[ready[5]], _BLIND_IR),
        (source.gold.item_to_case[ready[2]], _UNKNOWN_FIELD_IR),
        (source.gold.item_to_case[ready[0]], _BLIND_IR),
    ]
    assert build_plan(run_dir) == plan


def test_a_frames_card_is_kept_as_its_canonical_text(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    ready = _ready_items(source, "dev")
    run_dir = _write_base(
        tmp_path, source, replies={ready[1]: _ir_reply(_mutant_of(source))}
    )
    _write_scored(run_dir, source, {ready[1]: OutcomeV1.SILENT_WRONG})

    (item,) = build_plan(run_dir).items

    assert item.card_kind == "frames"
    assert item.card == card_json(_FRAMES_CARD)
    assert len(spy.cards) == 1


def _mutant_of(source: ModelSplitArtifacts) -> IntentIrV1:
    """A mutant of the second dev ready item's case."""
    return _mutant(
        source, source.gold.item_to_case[_ready_items(source, "dev")[1]]
    )


def test_non_ready_gold_and_other_outcomes_never_trigger(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    ready = set(_ready_items(source, "dev"))
    others = [item.item_id for item in _items(source, "dev")]
    non_ready = [item_id for item_id in others if item_id not in ready]
    replies = {non_ready[0]: _ir_reply(_BLIND_IR)}
    verdicts = {
        non_ready[0]: OutcomeV1.FALSE_READY,
        non_ready[1]: OutcomeV1.MALFORMED,
    }
    run_dir = _write_base(tmp_path, source, replies=replies)
    _write_scored(run_dir, source, verdicts)

    plan = build_plan(run_dir)

    assert plan.items == ()
    assert not spy.cards
    report = repair_run(run_dir, code_revision="rev")
    assert report.items == 0
    assert report.card_kinds == {"error": 0, "frames": 0, "none": 0}


def test_the_original_outcomes_decide_after_a_correction(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    ready = _ready_items(source, "dev")
    replies = {item_id: _ir_reply(_BLIND_IR) for item_id in ready[:2]}
    run_dir = _write_base(tmp_path, source, replies=replies)
    _write_scored(run_dir, source, {ready[0]: OutcomeV1.SILENT_WRONG})
    original = _write_scored(
        run_dir,
        source,
        {ready[1]: OutcomeV1.SILENT_WRONG},
        tree="scored-original",
    )

    plan = build_plan(run_dir)

    assert [item.item_id for item in plan.items] == [ready[1]]
    assert plan.base_outcomes_sha256 == hashlib.sha256(original).hexdigest()
    assert len(spy.cards) == 1


def test_an_incomplete_or_unpublished_pass_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    incomplete = _write_base(
        tmp_path / "incomplete", source, count=4, status="incomplete"
    )
    _write_scored(incomplete, source, {})
    missing = _write_base(tmp_path / "missing", source, count=4)
    _write_scored(missing, source, {})
    (missing / "run_manifest.json").unlink()
    linked = _write_base(tmp_path / "linked", source, count=4)
    _write_scored(linked, source, {})
    manifest = linked / "run_manifest.json"
    moved = manifest.with_name("manifest-copy.json")
    manifest.rename(moved)
    manifest.symlink_to(moved)

    assert isinstance(_refusal(incomplete), RepairError)
    assert _refusal(incomplete).code == "base_incomplete"
    assert _refusal(missing).code == "base_incomplete"
    assert _refusal(linked).code == "base_incomplete"
    assert not spy.cards


def test_a_pass_without_c4_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    run_dir = _write_base(tmp_path, source, count=4, label="C3")

    assert _refusal(run_dir).code == "base_condition_missing"
    assert not spy.cards


def test_a_pass_whose_layout_or_digests_fail_is_refused_as_scoring_is(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    run_dir = _write_base(tmp_path, source, count=4)
    _write_scored(run_dir, source, {})
    prompts = run_dir / "prepared" / "C4.json"
    prompts.write_bytes(prompts.read_bytes().replace(b"\n", b" \n"))

    error = _refusal(run_dir)

    assert isinstance(error, ScoringError)
    assert error.code == "manifest_mismatch"
    assert not spy.cards


def _scored_base(
    root: Path, source: ModelSplitArtifacts
) -> tuple[Path, list[str]]:
    """A dev pass whose first ready item is silent-wrong, scored."""
    ready = _ready_items(source, "dev")
    run_dir = _write_base(
        root, source, count=8, replies={ready[0]: _ir_reply(_BLIND_IR)}
    )
    _write_scored(run_dir, source, {ready[0]: OutcomeV1.SILENT_WRONG})
    return run_dir, ready


def test_a_pass_whose_prompts_are_not_the_frozen_ones_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    """Consistent digests do not admit a prompt the code does not rebuild.

    The base is written from a split whose triggered item asks something
    else, and its prepare and run manifests are derived from those bytes,
    so every digest agrees and only the prompt check can refuse it.
    """
    triggered = _ready_items(source, "dev")[0]
    edited = dataclasses.replace(
        source,
        inputs=tuple(
            (
                item.model_copy(update={"intent": f"{item.intent} Please."})
                if item.item_id == triggered
                else item
            )
            for item in source.inputs
        ),
    )
    run_dir, _ = _scored_base(tmp_path, edited)

    error = _refusal(run_dir)

    assert isinstance(error, ScoringError)
    assert error.code == "prompt_mismatch"
    assert str(error) == f"C4 {triggered}"
    assert not spy.cards
    assert not (run_dir / PLAN_PATH).exists()


@pytest.mark.parametrize(
    "damage",
    ["missing", "short", "twice", "unreadable", "directory", "symlink"],
)
def test_a_pass_whose_c4_outcomes_are_not_all_scored_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy, damage: str
) -> None:
    run_dir, _ = _scored_base(tmp_path, source)
    outcomes = run_dir / "scored" / "outcomes.jsonl"
    lines = outcomes.read_bytes().splitlines(keepends=True)
    if damage == "missing":
        outcomes.unlink()
    elif damage == "short":
        outcomes.write_bytes(b"".join(lines[1:]))
    elif damage == "twice":
        outcomes.write_bytes(b"".join([*lines, lines[0]]))
    elif damage == "unreadable":
        outcomes.write_bytes(b"".join([*lines, b"{not json}\n"]))
    elif damage == "directory":
        outcomes.unlink()
        outcomes.mkdir()
    else:
        copy = outcomes.with_name("outcomes-copy.jsonl")
        outcomes.rename(copy)
        outcomes.symlink_to(copy)

    assert _refusal(run_dir).code == "base_unscored"
    assert not spy.cards


def test_outcomes_of_another_condition_do_not_score_c4(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    run_dir, _ = _scored_base(tmp_path, source)
    outcomes = run_dir / "scored" / "outcomes.jsonl"
    outcomes.write_bytes(outcomes.read_bytes().replace(b'"C4"', b'"C3"'))

    assert _refusal(run_dir).code == "base_unscored"
    assert not spy.cards


@pytest.mark.parametrize("damage", ["edited", "missing"])
def test_an_answer_that_is_not_the_scored_intent_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy, damage: str
) -> None:
    run_dir, ready = _scored_base(tmp_path, source)
    intent = run_dir / "scored" / "intents" / "C4" / f"{ready[0]}.json"
    if damage == "edited":
        _write(intent, _UNKNOWN_FIELD_IR)
    else:
        intent.unlink()

    assert _refusal(run_dir).code == "intent_mismatch"
    assert not spy.cards


def test_a_triggered_item_without_a_ready_answer_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    ready = _ready_items(source, "dev")
    run_dir = _write_base(
        tmp_path, source, count=8, replies={ready[0]: "not json"}
    )
    _write_scored(run_dir, source, {ready[0]: OutcomeV1.INVALID})

    assert _refusal(run_dir).code == "outcomes_mismatch"
    assert not spy.cards


def test_an_item_scored_on_another_case_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    ready = _ready_items(source, "dev")
    run_dir = _write_base(tmp_path, source, count=8)
    _write_scored(run_dir, source, {}, cases={ready[3]: "some-other-case"})

    assert _refusal(run_dir).code == "outcomes_mismatch"
    assert not spy.cards


def _record_with(tmp_path: Path, feedback_labels: str | None) -> Path:
    """A copy of the committed freeze record with other feedback labels."""
    document = json.loads(held_out_module.RECORD_PATH.read_bytes())
    if feedback_labels is None:
        del document["digests"]["feedback_labels"]
    else:
        document["digests"]["feedback_labels"] = feedback_labels
    path = tmp_path / "held_out_freeze.json"
    path.write_text(canonical_json(document), encoding="utf-8")
    return path


def test_test_feedback_labels_must_be_the_frozen_ones(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _ready_items(source, "test")
    run_dir = _write_base(
        tmp_path / "base",
        source,
        split="test",
        count=4,
        replies={ready[1]: _ir_reply(_BLIND_IR)},
    )
    _write_scored(run_dir, source, {ready[1]: OutcomeV1.SILENT_WRONG})

    plan = build_plan(run_dir)
    record = held_out_module.load_record()
    assert record is not None
    assert plan.feedback_labels_sha256 == record.digests["feedback_labels"]
    assert plan.feedback_probe == "semantic-35"
    assert [item.item_id for item in plan.items] == [ready[1]]
    built = len(spy.cards)

    for labels in ("0" * 64, None):
        monkeypatch.setattr(
            held_out_module, "RECORD_PATH", _record_with(tmp_path, labels)
        )
        assert _refusal(run_dir).code == "feedback_labels_mismatch"
    monkeypatch.setattr(
        held_out_module, "RECORD_PATH", tmp_path / "no-such-record.json"
    )
    assert _refusal(run_dir).code == "feedback_labels_mismatch"
    assert len(spy.cards) == built


def test_dev_feedback_labels_need_no_freeze_record(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir, ready = _scored_base(tmp_path, source)
    monkeypatch.setattr(
        held_out_module, "RECORD_PATH", tmp_path / "no-such-record.json"
    )

    plan = build_plan(run_dir)

    assert [item.item_id for item in plan.items] == [ready[0]]
    assert len(spy.cards) == 1


def test_repair_writes_the_plan_and_check_compares_bytes(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    run_dir, _ = _scored_base(tmp_path, source)
    target = run_dir / PLAN_PATH

    missing = repair_run(run_dir, code_revision="rev", check=True)
    written = repair_run(run_dir, code_revision="rev")
    committed = target.read_bytes()
    checked = repair_run(run_dir, code_revision="rev", check=True)
    target.write_bytes(committed.replace(b"\n", b""))
    edited = repair_run(run_dir, code_revision="rev", check=True)

    assert missing.differences == ("repair/plan.json",)
    assert written.checked is False and written.differences == ()
    assert written.plan_sha256 == hashlib.sha256(committed).hexdigest()
    assert committed == plan_bytes(build_plan(run_dir))
    assert written.card_kinds == {"error": 0, "frames": 0, "none": 1}
    assert written.items == 1 and written.base_run == run_dir.name
    assert checked.checked is True and checked.differences == ()
    assert checked.plan_sha256 == written.plan_sha256
    assert edited.differences == ("repair/plan.json",)
    # A check never writes.
    assert target.read_bytes() == committed.replace(b"\n", b"")
    assert not list(target.parent.glob(".*partial"))
    assert len(spy.cards) == 5


def test_the_cli_writes_checks_and_refuses_with_exit_codes(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir, _ = _scored_base(tmp_path, source)
    args = ["repair", "--run-dir", str(run_dir), "--code-revision", "rev"]

    assert main(args) == 0
    written = json.loads(capsys.readouterr().out)
    assert main([*args, "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    (run_dir / PLAN_PATH).write_bytes(b"{}\n")
    assert main([*args, "--check"]) == 1
    differs = json.loads(capsys.readouterr().out)
    (run_dir / "scored" / "outcomes.jsonl").unlink()
    assert main(args) == 2
    refused = json.loads(capsys.readouterr().err)

    assert written["schema_version"] == "repair-report/1.0"
    assert written["code_revision"] == "rev"
    assert written["plan_sha256"] == checked["plan_sha256"]
    assert checked["differences"] == []
    assert differs["differences"] == ["repair/plan.json"]
    assert refused["error"]["code"] == "base_unscored"
    assert len(spy.cards) == 3


def test_a_card_failure_stops_the_plan_without_writing(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    run_dir, _ = _scored_base(tmp_path, source)

    def fail(candidate: IntentIrV1 | str) -> CounterexampleCardV1 | None:
        del candidate
        raise CounterexampleError("card_aborted", "No frame disagrees")

    spy.answer = fail

    with pytest.raises(CounterexampleError) as error:
        repair_run(run_dir, code_revision="rev")
    assert error.value.code == "card_aborted"
    assert not (run_dir / PLAN_PATH).exists()
    assert not spy.cards


# --- With the pinned tshark: a scored pass and its real cards. ---


def _real_replies(
    source: ModelSplitArtifacts,
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Answers that reach every outcome a plan reads, and what each is."""
    ready = _ready_items(source, "dev")
    non_ready = [
        item.item_id
        for item in _items(source, "dev")
        if item.item_id not in set(ready)
    ]
    mutant_case = source.gold.item_to_case[ready[1]]
    replies: dict[str, str | None] = {
        ready[1]: _ir_reply(_mutant(source, mutant_case)),
        ready[4]: _ir_reply(_UNKNOWN_FIELD_IR),
        ready[6]: "not json",
        ready[7]: None,
        non_ready[0]: _ir_reply(_UNKNOWN_FIELD_IR),
    }
    roles = {
        ready[1]: "silent_wrong",
        ready[4]: "invalid",
        ready[6]: "malformed",
        ready[7]: "provider_failed",
        non_ready[0]: "false_ready",
    }
    return replies, roles


@pytest.fixture(name="scored", scope="module")
def fixture_scored(
    tmp_path_factory: pytest.TempPathFactory, source: ModelSplitArtifacts
) -> Path:
    """A whole dev C4 pass, scored once with the pinned tshark."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Runner requires a Linux container")
    replies, _ = _real_replies(source)
    run_dir = _write_base(
        tmp_path_factory.mktemp("scored"), source, replies=replies
    )
    score_run(run_dir, code_revision="unit-test")
    return run_dir


@_POSIX_ONLY
def test_a_scored_pass_gets_real_cards_for_its_triggered_items(
    scored: Path, source: ModelSplitArtifacts, tmp_path: Path
) -> None:
    _, roles = _real_replies(source)
    lines = (scored / "scored" / "outcomes.jsonl").read_text("utf-8")
    outcomes = {
        line["item_id"]: line["outcome"]
        for line in map(json.loads, lines.splitlines())
    }
    run_dir = tmp_path / scored.name
    shutil.copytree(scored, run_dir)

    report = repair_run(run_dir, code_revision="unit-test")
    plan = RepairPlanV1.model_validate_json((run_dir / PLAN_PATH).read_bytes())
    checked = repair_run(run_dir, code_revision="unit-test", check=True)

    assert {item_id: outcomes[item_id] for item_id in roles} == roles
    assert [
        (item.item_id, item.base_outcome, item.card_kind) for item in plan.items
    ] == [
        (item_id, role, "frames" if role == "silent_wrong" else "error")
        for item_id, role in roles.items()
        if role in {"silent_wrong", "invalid"}
    ]
    frames, error = plan.items
    card = FramesCardV1.model_validate_json(frames.card or "")
    assert 1 <= len(card.frames) <= 3
    assert len((frames.card or "").encode("utf-8")) <= CARD_MAX_BYTES
    assert error.card == card_json(_ERROR_CARD)
    assert report.card_kinds == {"error": 1, "frames": 1, "none": 0}
    assert checked.differences == ()
    assert plan_bytes(build_plan(run_dir)) == (run_dir / PLAN_PATH).read_bytes()


@_POSIX_ONLY
def test_the_plan_is_built_from_the_feedback_probe_alone(
    scored: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / scored.name
    shutil.copytree(scored, run_dir)
    expected = plan_bytes(build_plan(run_dir))
    generate = repair_module.generate_model_split
    splits: list[ModelSplitArtifacts] = []
    seen: list[tuple[bool, ...]] = []

    def generate_and_keep(output_dir: Path) -> ModelSplitArtifacts:
        artifacts = generate(output_dir)
        splits.append(artifacts)
        return artifacts

    class Watched(CardBuilder):
        """Notes whether a scored capture exists when a card is built."""

        def card(
            self, case_id: str, candidate: IntentIrV1 | str
        ) -> CounterexampleCardV1 | None:
            seen.append(
                tuple(path.exists() for path in splits[-1].capture_paths)
            )
            return super().card(case_id, candidate)

    monkeypatch.setattr(
        repair_module, "generate_model_split", generate_and_keep
    )
    monkeypatch.setattr(repair_module, "CardBuilder", Watched)

    assert plan_bytes(build_plan(run_dir)) == expected
    assert len(seen) == 2 and len(splits[-1].capture_paths) == 6
    assert not any(any(flags) for flags in seen)
