"""Repair plans and rounds: schemas, refusals, numbers and the probe rule.

Most tests replace the card builder with a table, so the trigger set, the
order, the digests and every refusal are checked without tshark; the
tests marked POSIX-only score a pass and build its cards with the pinned
tshark, as the lab command does. A round's arm runs are written beside a
base pass as the follow-up, call, publish and score steps lay them out,
with outcomes chosen so that every reported number is counted by hand.
"""

from collections.abc import Callable, Mapping, Sequence
import dataclasses
from datetime import datetime
from datetime import timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from typing import Any, cast, Literal

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
from dfilterforge.completions import TokenPricesV1
from dfilterforge.counterexample import card_json
from dfilterforge.counterexample import CARD_MAX_BYTES
from dfilterforge.counterexample import CardBuilder
from dfilterforge.counterexample import CounterexampleCardV1
from dfilterforge.counterexample import CounterexampleError
from dfilterforge.counterexample import ErrorCardV1
from dfilterforge.counterexample import FrameFactV1
from dfilterforge.counterexample import FramesCardV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import follow_up_prompt
from dfilterforge.generation import GenerationError
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
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
from dfilterforge.repair_report import render_summary
from dfilterforge.repair_round import ARM_RERUN
from dfilterforge.repair_round import arm_run_ids
from dfilterforge.repair_round import ARM_TAGS
from dfilterforge.repair_round import pool_run
from dfilterforge.repair_round import round_run
from dfilterforge.repair_round import SUMMARY_PATH
from dfilterforge.repair_round import SUMMARY_REPORT_PATH
from dfilterforge.repair_summary import ArmResult
from dfilterforge.repair_summary import ARMS
from dfilterforge.repair_summary import pool_summaries
from dfilterforge.repair_summary import RepairCaseV1
from dfilterforge.repair_summary import RepairPoolV1
from dfilterforge.repair_summary import RepairSummaryV1
from dfilterforge.repair_summary import RoundBase
from dfilterforge.repair_summary import RoundError
from dfilterforge.repair_summary import summarize_round
from dfilterforge.run_store import ScoringError
from dfilterforge.runner import TsharkRunner
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import draw_indices
from dfilterforge.score_summary import GoldStatus
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import ratio_rate
from dfilterforge.score_summary import summarize
from dfilterforge.scoring import score_run

_POSIX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)
_CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)
_SETTINGS = RequestSettingsV1(model_id="vendor/model-a")
_GOLD_HASH = "9" * 64
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
    non-ready gold, and each carries its gold status; every ready answer's
    intent is written, and ``scored/`` gets the summary of its outcomes,
    as scoring does.
    """
    batch = PreparedBatchV1.model_validate_json(
        (run_dir / "prepared" / "C4.json").read_bytes()
    )
    recorded = CompletionBatchV1.model_validate_json(
        (run_dir / "completions" / "C4.json").read_bytes()
    )
    answers = {item.item_id: item for item in recorded.completions}
    statuses: dict[str, GoldStatus] = {
        case.case_id: case.status for case in source.gold.non_ready
    }
    intents = run_dir / "scored" / "intents" / "C4"
    outcomes: list[ItemOutcomeV1] = []
    for prompt in sorted(batch.prompts, key=lambda prompt: prompt.item_id):
        case_id = source.gold.item_to_case[prompt.item_id]
        status = statuses.get(case_id, "ready")
        default = (
            OutcomeV1.STRONG_EXACT if status == "ready" else OutcomeV1.ABSTAINED
        )
        outcomes.append(
            ItemOutcomeV1(
                condition="C4",
                item_id=prompt.item_id,
                case_id=(cases or {}).get(prompt.item_id, case_id),
                outcome=verdicts.get(prompt.item_id, default),
                gold_field_count=1,
                latency_ms=1.0,
                gold_status=status,
            )
        )
        intent = _ready_ir(answers[prompt.item_id].response_text)
        if intent is not None:
            _write(intents / f"{prompt.item_id}.json", intent)
    payload = "".join(canonical_json(item) + "\n" for item in outcomes)
    (run_dir / tree).mkdir(parents=True, exist_ok=True)
    (run_dir / tree / "outcomes.jsonl").write_bytes(payload.encode("utf-8"))
    if tree == "scored":
        _write(
            run_dir / tree / "summary.json",
            summarize(
                outcomes,
                run=run_dir.name,
                model_id=recorded.settings.model_id,
                split=batch.prompts[0].split or "dev",
                gold_hash=_GOLD_HASH,
                capture_hashes={},
                batch_hashes={},
            ),
        )
    return payload.encode("utf-8")


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


# --- A repair round: three arm runs beside the base pass. ---

_SE = OutcomeV1.STRONG_EXACT
_SW = OutcomeV1.SILENT_WRONG
_INV = OutcomeV1.INVALID
_SC = OutcomeV1.SHORTCUT
_PF = OutcomeV1.PROVIDER_FAILED
_MAL = OutcomeV1.MALFORMED


def _predicate_ir(field: str, operator: Operator, value: int) -> IntentIrV1:
    """One single-predicate typed IR."""
    return IntentIrV1(
        expression=Predicate(field=field, operator=operator, value=value)
    )


_TTL_IR = _predicate_ir("ip.ttl", Operator.LE, 2)
# _FRAMES_CARD shows ip.ttl 64 and udp.dstport 53, and never ip.ttl 1.
_SHOWN_TTL = _ir_reply(_predicate_ir("ip.ttl", Operator.EQ, 64))
_SHOWN_PORT = _ir_reply(_predicate_ir("udp.dstport", Operator.EQ, 53))
_UNSHOWN = _ir_reply(_predicate_ir("ip.ttl", Operator.LE, 1))
# The base pass's triggered answers and outcomes, in prepare order. The
# fake builder gives _TTL_IR a frames card, the unknown field an error
# card and the blind answer none.
_ROUND_BASE: dict[str, tuple[IntentIrV1, OutcomeV1]] = {
    "mei-0001": (_TTL_IR, _SW),
    "mei-0002": (_UNKNOWN_FIELD_IR, _INV),
    "mei-0003": (_BLIND_IR, _SW),
    "mei-0005": (_TTL_IR, _SW),
    "mei-0007": (_UNKNOWN_FIELD_IR, _INV),
    "mei-0009": (_TTL_IR, _SW),
    "mei-0010": (_TTL_IR, _SW),
}
# Every dev ready case has two paraphrases, so a case's share of its C4
# items is a half per item: T is tcp 1, udp 0.5, ack 0.5, dns 0.5 and
# fin 1, 3.5 in all, over 12 ready cases.
_ROUND_CASES = {
    "mei-0001": "tcp-expiring-ttl",
    "mei-0002": "tcp-expiring-ttl",
    "mei-0003": "udp-expiring-ttl",
    "mei-0005": "ack-to-https",
    "mei-0007": "dns-a-queries",
    "mei-0009": "fin-or-dns-response",
    "mei-0010": "fin-or-dns-response",
}
_DEV_READY_CASES = (
    "aaaa-or-nxdomain",
    "ack-to-https",
    "dns-a-queries",
    "dns-error-responses",
    "ecn-syn-or-expiring",
    "fin-or-dns-response",
    "private-destination",
    "reset-or-fin",
    "tcp-expiring-ttl",
    "udp-expiring-ttl",
    "udp-nondns-private-destination",
    "udp-normal-ttl",
)
# Stands for the base pass's own answer text.
_SAME = "the base answer"
_Table = Mapping[str, tuple[str | None, OutcomeV1]]
# Each arm's answer and outcome per item. Repaired: resample mei-0001
# (0.5 of 3.5); bare mei-0001, -0002 and -0007 (1.5); counterexample
# mei-0001, -0002, -0003, -0005 and -0009 (2.5).
_ROUND_ARMS: dict[str, _Table] = {
    "resample": {
        "mei-0001": (_SHOWN_TTL, _SE),
        "mei-0002": (_SAME, _INV),
        "mei-0003": (_SAME, _SW),
        "mei-0005": (_SAME, _SW),
        "mei-0007": (_SAME, _INV),
        "mei-0009": (_SAME, _SW),
        "mei-0010": (_SAME, _SW),
    },
    "bare": {
        "mei-0001": (_UNSHOWN, _SE),
        "mei-0002": (_UNSHOWN, _SE),
        "mei-0003": (_SHOWN_TTL, _SC),
        "mei-0005": (_SAME, _SW),
        "mei-0007": (_UNSHOWN, _SE),
        "mei-0009": (None, _PF),
        "mei-0010": ("not json", _MAL),
    },
    # Card values are reused by mei-0001 and mei-0009 only: mei-0002 has
    # an error card, mei-0003 none, and mei-0010 is not strong exact.
    "counterexample": {
        "mei-0001": (_SHOWN_TTL, _SE),
        "mei-0002": (_SHOWN_TTL, _SE),
        "mei-0003": (_SHOWN_TTL, _SE),
        "mei-0005": (_UNSHOWN, _SE),
        "mei-0007": (_SAME, _INV),
        "mei-0009": (_SHOWN_PORT, _SE),
        "mei-0010": (_SHOWN_TTL, _SW),
    },
}
_ARM_RUNS = {
    "resample": "dev-model-a-res-2026-10-01",
    "bare": "dev-model-a-bare-2026-10-01",
    "counterexample": "dev-model-a-cx-2026-10-01",
}


def _round_base(root: Path, source: ModelSplitArtifacts) -> Path:
    """Writes the scored dev base pass and its plan, from the fake builder."""
    run_dir = _write_base(
        root,
        source,
        replies={item: _ir_reply(ir) for item, (ir, _) in _ROUND_BASE.items()},
    )
    _write_scored(
        run_dir,
        source,
        {item: outcome for item, (_, outcome) in _ROUND_BASE.items()},
    )
    repair_run(run_dir, code_revision="rev")
    return run_dir


def _base_texts(base_dir: Path) -> dict[str, str | None]:
    """The base pass's stored C4 answers."""
    recorded = CompletionBatchV1.model_validate_json(
        (base_dir / "completions" / "C4.json").read_bytes()
    )
    return {item.item_id: item.response_text for item in recorded.completions}


def _arm_prompts(base_dir: Path, arm: str) -> list[PreparedPromptV1]:
    """The prompts follow-up writes for one arm of the committed plan."""
    plan = RepairPlanV1.model_validate_json((base_dir / PLAN_PATH).read_bytes())
    first = {
        prompt.item_id: prompt
        for prompt in PreparedBatchV1.model_validate_json(
            (base_dir / "prepared" / "C4.json").read_bytes()
        ).prompts
    }
    texts = _base_texts(base_dir)
    return [
        (
            first[item.item_id]
            if arm == "resample"
            else follow_up_prompt(
                first[item.item_id],
                texts[item.item_id] or "",
                item.card if arm == "counterexample" else None,
            )
        )
        for item in plan.items
    ]


def _arm_answer(item_id: str, text: str | None) -> CompletionV1:
    """Stores one arm answer, or a provider failure when it has no text."""
    if text is None:
        return CompletionV1(
            item_id=item_id,
            status=CompletionStatusV1.FAILED,
            error_code="timeout",
            latency_ms=2.0,
        )
    return CompletionV1(
        item_id=item_id,
        status=CompletionStatusV1.COMPLETED,
        response_text=text,
        latency_ms=2.0,
        prompt_tokens=20,
        completion_tokens=5,
        finish_reason="stop",
    )


def _arm_prepare(
    base_dir: Path,
    run_dir: Path,
    prompts: Sequence[PreparedPromptV1],
    prepare: Mapping[str, object] | None,
) -> PrepareManifestV1:
    """Writes an arm's prompt set and the prepare record follow-up gives it."""
    payload = _write(
        run_dir / "prepared" / "C4.json",
        PreparedBatchV1(
            output_contract=OutputContractV1.TYPED_IR,
            retrieval=RetrievalV1.LEXICAL,
            prompts=tuple(prompts),
        ),
    )
    source_prepare = PrepareManifestV1.model_validate_json(
        (base_dir / "prepare.json").read_bytes()
    )
    record = PrepareManifestV1.model_validate(
        {
            **source_prepare.model_dump(),
            "prepare_id": run_dir.name,
            "item_ids": [prompt.item_id for prompt in prompts],
            "conditions": [
                {
                    "label": "C4",
                    "output_contract": OutputContractV1.TYPED_IR,
                    "retrieval": RetrievalV1.LEXICAL,
                    "path": "prepared/C4.json",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "system_prompt_sha256": "5" * 64,
                    "prompt_count": len(prompts),
                }
            ],
            **(prepare or {}),
        }
    )
    _write(run_dir / "prepare.json", record)
    return record


def _arm_manifest(
    run_dir: Path,
    record: PrepareManifestV1,
    answers: Sequence[CompletionV1],
    settings: RequestSettingsV1,
    manifest: Mapping[str, object] | None,
) -> None:
    """Writes the run manifest a complete arm call publishes."""
    failed = sum(answer.response_text is None for answer in answers)
    _write(
        run_dir / "run_manifest.json",
        RunManifestV1.model_validate(
            {
                "run_id": run_dir.name,
                "created_at": _CREATED_AT,
                "prepare": record,
                "prepare_sha256": "6" * 64,
                "endpoint_host": "openrouter.ai",
                "settings": settings,
                "max_attempts": 3,
                "min_interval_seconds": 1.0,
                "invocations": [
                    InvocationV1(
                        source_revision="revision",
                        source_files={"scripts/model_run.py": "1" * 64},
                        started_at=_CREATED_AT,
                        finished_at=_CREATED_AT,
                        max_usd=0.05,
                        requests_sent=len(answers),
                    )
                ],
                "status": "complete",
                "charged_usd_upper_bound": 0.002,
                "provider_reported_usd": 0.001,
                "conditions": [
                    ConditionRunV1(
                        label="C4",
                        attempts_path="attempts/C4.jsonl",
                        attempts_sha256="7" * 64,
                        completions_path="completions/C4.json",
                        completions_sha256="8" * 64,
                        attempts={answer.item_id: 1 for answer in answers},
                        completed=len(answers) - failed,
                        failed=failed,
                        pending=0,
                    )
                ],
                **(manifest or {}),
            }
        ),
    )


def _arm_scored(
    run_dir: Path,
    source: ModelSplitArtifacts,
    outcomes: Mapping[str, OutcomeV1],
    moved: str | None,
) -> None:
    """Writes an arm's scored tree with the given outcomes."""
    scored = [
        ItemOutcomeV1(
            condition="C4",
            item_id=item_id,
            case_id=(
                "another-case"
                if item_id == moved
                else source.gold.item_to_case[item_id]
            ),
            outcome=outcome,
            gold_field_count=1,
            latency_ms=2.0,
        )
        for item_id, outcome in sorted(outcomes.items())
    ]
    (run_dir / "scored").mkdir(parents=True)
    (run_dir / "scored" / "outcomes.jsonl").write_bytes(
        "".join(canonical_json(item) + "\n" for item in scored).encode()
    )
    _write(
        run_dir / "scored" / "summary.json",
        summarize(
            scored,
            run=run_dir.name,
            model_id=_SETTINGS.model_id,
            split="dev",
            gold_hash=_GOLD_HASH,
            capture_hashes={},
            batch_hashes={},
        ),
    )


# pylint: disable-next=too-many-arguments
def _write_arm(
    base_dir: Path,
    source: ModelSplitArtifacts,
    arm: str,
    *,
    name: str | None = None,
    prompts: Sequence[PreparedPromptV1] | None = None,
    published: bool = True,
    scored: bool = True,
    settings: RequestSettingsV1 = _SETTINGS,
    manifest: Mapping[str, object] | None = None,
    prepare: Mapping[str, object] | None = None,
    moved: str | None = None,
) -> Path:
    """Writes one arm run beside the base pass, as far as it has come.

    It is the prompt set follow-up writes, then what publish copies, then
    the scored tree with the arm's outcomes from _ROUND_ARMS. ``moved``
    names an item scored on another case.
    """
    run_dir = base_dir.parent / (name or _ARM_RUNS[arm])
    chosen = list(
        prompts if prompts is not None else _arm_prompts(base_dir, arm)
    )
    record = _arm_prepare(base_dir, run_dir, chosen, prepare)
    if not published:
        return run_dir
    table = _ROUND_ARMS[arm]
    texts = _base_texts(base_dir)
    answers = [
        _arm_answer(
            prompt.item_id,
            (
                texts[prompt.item_id]
                if table[prompt.item_id][0] == _SAME
                else table[prompt.item_id][0]
            ),
        )
        for prompt in chosen
    ]
    _write(
        run_dir / "completions" / "C4.json",
        CompletionBatchV1(
            output_contract=OutputContractV1.TYPED_IR,
            retrieval=RetrievalV1.LEXICAL,
            settings=settings,
            completions=tuple(answers),
        ),
    )
    _arm_manifest(run_dir, record, answers, settings, manifest)
    if scored:
        _arm_scored(
            run_dir,
            source,
            {prompt.item_id: table[prompt.item_id][1] for prompt in chosen},
            moved,
        )
    return run_dir


def _round(root: Path, source: ModelSplitArtifacts) -> Path:
    """A base pass, its plan and its three published, scored arm runs."""
    base_dir = _round_base(root / "results", source)
    for arm in _ARM_RUNS:
        _write_arm(base_dir, source, arm)
    return base_dir


def _summary(base_dir: Path) -> RepairSummaryV1:
    """The round's committed summary."""
    return RepairSummaryV1.model_validate_json(
        (base_dir / SUMMARY_PATH).read_bytes()
    )


def _round_refusal(base_dir: Path, check: bool = False) -> RoundError:
    """Runs a round that must be refused, and returns the refusal."""
    with pytest.raises(RoundError) as error:
        round_run(base_dir, code_revision="rev", check=check)
    assert not (base_dir / SUMMARY_PATH).exists()
    return error.value


def _dev_shares(items: Sequence[str]) -> dict[str, float]:
    """Each dev ready case's share of its two items among ``items``."""
    counted = {case_id: 0.0 for case_id in _DEV_READY_CASES}
    for item_id in items:
        counted[_ROUND_CASES[item_id]] += 0.5
    return counted


def _repaired_by(arm: str) -> list[str]:
    """The items an arm of _ROUND_ARMS made strong exact."""
    return [
        item
        for item, (_, outcome) in _ROUND_ARMS[arm].items()
        if outcome is _SE
    ]


def test_a_round_gives_repair_at_1_as_counted_by_hand(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)

    report = round_run(base_dir, code_revision="rev")
    summary = _summary(base_dir)

    assert {
        item: source.gold.item_to_case[item] for item in _ROUND_BASE
    } == _ROUND_CASES
    assert _DEV_READY_CASES == tuple(
        sorted(
            case.case_id
            for case in source.gold.cases
            if case.spec.split == "dev"
        )
    )
    assert (report.stage, report.differences) == ("summary", ())
    assert report.arm_runs == _ARM_RUNS
    assert (
        report.summary_sha256
        == hashlib.sha256((base_dir / SUMMARY_PATH).read_bytes()).hexdigest()
    )
    assert (summary.triggered_items, summary.triggered_cases) == (7, 5)
    assert summary.by_base_outcome == {"invalid": 2, "silent_wrong": 5}
    assert summary.card_kinds == {"error": 2, "frames": 4, "none": 1}
    assert summary.bootstrap == {
        "resamples": 1000,
        "seed": 17,
        "cases": 12,
        "min_discordant_cases": 10,
    }
    assert (
        summary.plan_sha256
        == hashlib.sha256((base_dir / PLAN_PATH).read_bytes()).hexdigest()
    )
    assert summary.gold_hash == _GOLD_HASH
    assert [
        (case.case_id, case.ready_items, case.triggered_items)
        for case in summary.cases
    ] == [
        (case_id, 2, list(_ROUND_CASES.values()).count(case_id))
        for case_id in _DEV_READY_CASES
    ]
    # Repaired over triggered case shares: 0.5, 1.5 and 2.5 of 3.5. The
    # silent-wrong items' shares sum to 2.5 and the invalid ones' to 1.
    assert {
        arm.arm: (
            arm.repair_at_1.value,
            arm.repair_at_1_silent_wrong.value,
            arm.repair_at_1_invalid.value,
            arm.repaired,
            arm.shortcut,
        )
        for arm in summary.arms
    } == {
        "resample": (0.142857, 0.2, 0.0, 1, 0),
        "bare": (0.428571, 0.2, 1.0, 3, 1),
        "counterexample": (0.714286, 0.8, 0.5, 5, 0),
    }
    # The interval is the ratio estimator's over the base's 12 ready cases.
    for arm in summary.arms:
        assert arm.repair_at_1 == ratio_rate(
            _dev_shares(_repaired_by(arm.arm)),
            _dev_shares(list(_ROUND_BASE)),
            draw_indices(12),
            _DEV_READY_CASES,
        )
        assert arm.repair_at_1.resamples_used > 0
    assert [
        (
            item.first,
            item.second,
            item.difference.value,
            item.first_better,
            item.second_better,
            item.discordant,
            item.inconclusive,
            item.unit,
        )
        for item in summary.comparisons
    ] == [
        ("counterexample", "bare", 0.285714, 3, 1, 4, True, "cases"),
        ("counterexample", "resample", 0.571429, 4, 0, 4, True, "cases"),
        ("bare", "resample", 0.285714, 2, 0, 2, True, "cases"),
    ]


def test_a_round_reports_its_diagnostics_and_items(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)

    round_run(base_dir, code_revision="rev")
    summary = _summary(base_dir)
    report = (base_dir / SUMMARY_REPORT_PATH).read_text("utf-8")

    bare = summary.arms[1]
    assert tuple(arm.run for arm in summary.arms) == tuple(_ARM_RUNS.values())
    assert [arm.answer_unchanged for arm in summary.arms] == [6, 1, 1]
    assert [arm.card_value_reuse for arm in summary.arms] == [None, None, 2]
    assert bare.outcomes == {
        "provider_failed": 1,
        "malformed": 1,
        "abstained": 0,
        "false_ready": 0,
        "invalid": 0,
        "shortcut": 1,
        "silent_wrong": 1,
        "strong_exact": 3,
    }
    assert [
        (step.first.value, step.second.value, step.items)
        for step in bare.transitions
    ] == [
        ("invalid", "strong_exact", 2),
        ("silent_wrong", "provider_failed", 1),
        ("silent_wrong", "malformed", 1),
        ("silent_wrong", "shortcut", 1),
        ("silent_wrong", "silent_wrong", 1),
        ("silent_wrong", "strong_exact", 1),
    ]
    assert (bare.latency_ms_p50, bare.charged_usd_upper_bound) == (2.0, 0.002)
    assert bare.provider_reported_usd == 0.001
    arm_dir = base_dir.parent / _ARM_RUNS["bare"]
    assert (
        bare.run_manifest_sha256
        == hashlib.sha256(
            (arm_dir / "run_manifest.json").read_bytes()
        ).hexdigest()
    )
    assert (
        bare.outcomes_sha256
        == hashlib.sha256(
            (arm_dir / "scored" / "outcomes.jsonl").read_bytes()
        ).hexdigest()
    )
    frames = hashlib.sha256(card_json(_FRAMES_CARD).encode()).hexdigest()
    kinds = ["frames", "error", "none", "frames", "error", "frames", "frames"]
    assert [
        (
            item.item_id,
            item.case_id,
            item.base_outcome,
            item.base_outcome_now,
            item.card_kind,
            item.card_sha256 == frames,
            tuple(item.outcomes[arm] for arm in ARMS),
        )
        for item in summary.items
    ] == [
        (
            item_id,
            _ROUND_CASES[item_id],
            outcome.value,
            outcome,
            kind,
            kind == "frames",
            tuple(_ROUND_ARMS[arm][item_id][1] for arm in ARMS),
        )
        for (item_id, (_, outcome)), kind in zip(
            _ROUND_BASE.items(), kinds, strict=True
        )
    ]
    assert summary.base_outcome_changed == ()
    assert report.startswith("# Repair summary\n")
    assert "| counterexample | dev-model-a-cx-2026-10-01 | 0.714 [" in report
    assert "inconclusive (fewer than 10 discordant cases)" in report
    assert "Base outcome changed since the plan: none." in report
    # No answer text and no card reaches the report.
    assert "ip.ttl" not in report and "not json" not in report


def test_a_round_is_checked_byte_for_byte_and_a_check_never_writes(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    written = round_run(base_dir, code_revision="rev")
    committed = {
        path: (base_dir / path).read_bytes()
        for path in (SUMMARY_PATH, SUMMARY_REPORT_PATH)
    }

    checked = round_run(base_dir, code_revision="rev", check=True)
    (base_dir / SUMMARY_REPORT_PATH).write_bytes(b"# edited\n")
    (base_dir / SUMMARY_PATH).unlink()
    differs = round_run(base_dir, code_revision="rev", check=True)

    assert (written.checked, checked.checked) == (False, True)
    assert checked.differences == ()
    assert checked.summary_sha256 == written.summary_sha256
    assert differs.differences == ("repair/summary.json", "repair/summary.md")
    assert not (base_dir / SUMMARY_PATH).exists()
    assert (base_dir / SUMMARY_REPORT_PATH).read_bytes() == b"# edited\n"
    round_run(base_dir, code_revision="rev")
    assert {
        path: (base_dir / path).read_bytes() for path in committed
    } == committed
    assert not list((base_dir / "repair").glob(".*partial"))


def test_the_cli_writes_and_checks_a_round_and_refuses_a_partial_one(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_dir = _round(tmp_path, source)
    args = ["repair", "--run-dir", str(base_dir), "--code-revision", "rev"]

    assert main(args) == 0
    written = json.loads(capsys.readouterr().out)
    assert main([*args, "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    (base_dir / SUMMARY_REPORT_PATH).write_bytes(b"x\n")
    assert main([*args, "--check"]) == 1
    differs = json.loads(capsys.readouterr().out)
    shutil.rmtree(base_dir.parent / _ARM_RUNS["bare"])
    assert main(args) == 2
    refused = json.loads(capsys.readouterr().err)

    assert (written["stage"], written["arm_runs"]) == ("summary", _ARM_RUNS)
    assert checked["summary_sha256"] == written["summary_sha256"]
    assert checked["differences"] == []
    assert differs["differences"] == ["repair/summary.md"]
    assert refused["error"]["code"] == "repair_arms_incomplete"


@pytest.mark.parametrize(
    "present", [("resample",), ("resample", "bare"), ("counterexample",)]
)
def test_a_round_with_an_arm_missing_is_refused(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    present: tuple[str, ...],
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    for arm in present:
        _write_arm(base_dir, source, arm)
    built = len(spy.cards)

    error = _round_refusal(base_dir)

    assert error.code == "repair_arms_incomplete"
    # The arm runs are looked for before any card is built.
    assert len(spy.cards) == built


def test_a_round_with_an_arm_not_yet_published_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    _write_arm(base_dir, source, "bare")
    _write_arm(base_dir, source, "counterexample", published=False)

    assert _round_refusal(base_dir).code == "repair_arms_incomplete"


def test_a_round_with_an_arm_left_incomplete_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    # Every answer is published and scored, but the run says it is not done.
    _write_arm(base_dir, source, "bare", manifest={"status": "incomplete"})
    _write_arm(base_dir, source, "counterexample")

    error = _round_refusal(base_dir)

    assert error.code == "repair_arms_incomplete"
    assert str(error).startswith(f"{_ARM_RUNS['bare']} is not complete")


def test_a_round_whose_base_lost_its_scored_summary_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    (base_dir / "scored" / "summary.json").unlink()

    assert _round_refusal(base_dir).code == "base_unscored"


def test_prompt_sets_seeded_before_their_calls_are_checked_alone(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    for arm in _ARM_RUNS:
        _write_arm(base_dir, source, arm, published=False)

    checked = round_run(base_dir, code_revision="rev", check=True)
    written = round_run(base_dir, code_revision="rev")

    for report in (checked, written):
        assert (report.stage, report.arm_runs) == ("prompts", _ARM_RUNS)
        assert (report.summary_sha256, report.differences) == (None, ())
    assert (checked.checked, written.checked) == (True, False)
    assert not (base_dir / "repair" / "summary.json").exists()
    seeded = base_dir.parent / _ARM_RUNS["counterexample"]
    prompts = _arm_prompts(base_dir, "bare")
    shutil.rmtree(seeded)
    _write_arm(
        base_dir, source, "counterexample", prompts=prompts, published=False
    )
    assert _round_refusal(base_dir, check=True).code == "repair_prompt_mismatch"


@pytest.mark.parametrize(
    "update",
    [
        {
            "settings": RequestSettingsV1(
                model_id="vendor/model-a", temperature=0.5
            )
        },
        {
            "prices": TokenPricesV1(
                usd_per_million_input=0.1,
                usd_per_million_output=0.3,
                source="test",
            )
        },
        {"endpoint_host": "api.example.org"},
        {"max_attempts": 2},
        {"min_interval_seconds": 2.0},
    ],
    ids=["settings", "prices", "host", "attempts", "pacing"],
)
def test_an_arm_sent_otherwise_than_its_base_is_refused(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    update: dict[str, object],
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    _write_arm(base_dir, source, "bare")
    settings = update.get("settings", _SETTINGS)
    assert isinstance(settings, RequestSettingsV1)
    _write_arm(
        base_dir, source, "counterexample", settings=settings, manifest=update
    )

    error = _round_refusal(base_dir)

    assert error.code == "repair_settings_mismatch"
    assert str(error).startswith(_ARM_RUNS["counterexample"])


@pytest.mark.parametrize("damage", ["missing", "reversed", "moved"])
def test_an_arm_over_other_items_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy, damage: str
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    _write_arm(base_dir, source, "counterexample")
    prompts = _arm_prompts(base_dir, "bare")
    if damage == "missing":
        _write_arm(base_dir, source, "bare", prompts=prompts[:-1])
    elif damage == "reversed":
        _write_arm(base_dir, source, "bare", prompts=prompts[::-1])
    else:
        _write_arm(base_dir, source, "bare", moved="mei-0005")

    assert _round_refusal(base_dir).code == "repair_items_mismatch"


def _bare_on_another_answer(base_dir: Path) -> list[PreparedPromptV1]:
    """The bare prompts, mei-0002 continuing an answer it never gave."""
    prompts = _arm_prompts(base_dir, "bare")
    prompts[1] = follow_up_prompt(_arm_prompts(base_dir, "resample")[1], "{}")
    return prompts


def _bare_prompts(base_dir: Path) -> list[PreparedPromptV1]:
    """The bare arm's prompts."""
    return _arm_prompts(base_dir, "bare")


def _counterexample_prompts(base_dir: Path) -> list[PreparedPromptV1]:
    """The counterexample arm's prompts."""
    return _arm_prompts(base_dir, "counterexample")


@pytest.mark.parametrize(
    ("arm", "prompts", "item"),
    [
        ("counterexample", _bare_prompts, "mei-0001"),
        ("bare", _counterexample_prompts, "mei-0001"),
        ("resample", _bare_prompts, "mei-0001"),
        ("bare", _bare_on_another_answer, "mei-0002"),
    ],
    ids=["card-missing", "card-added", "resample-continued", "other-answer"],
)
# pylint: disable-next=too-many-arguments,too-many-positional-arguments
def test_an_arm_prompt_that_is_not_its_arms_is_refused(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    arm: str,
    prompts: Callable[[Path], list[PreparedPromptV1]],
    item: str,
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    for other in _ARM_RUNS:
        if other != arm:
            _write_arm(base_dir, source, other)
    _write_arm(base_dir, source, arm, prompts=prompts(base_dir))

    error = _round_refusal(base_dir)

    assert error.code == "repair_prompt_mismatch"
    assert str(error).startswith(f"{_ARM_RUNS[arm]} {item}:")


@pytest.mark.parametrize(
    "prepare",
    [
        {"model_inputs_sha256": "0" * 64},
        {"top_k": 8},
        {"prepare_id": "dev-model-a-cx-2026-10-02"},
    ],
    ids=["inputs", "depth", "name"],
)
def test_an_arm_that_is_not_a_c4_arm_of_its_base_is_refused(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    prepare: dict[str, object],
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    _write_arm(base_dir, source, "bare")
    _write_arm(base_dir, source, "counterexample", prepare=prepare)

    assert _round_refusal(base_dir).code == "repair_arm_mismatch"


def test_a_linked_misnamed_or_unscored_arm_is_refused(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    _write_arm(base_dir, source, "bare", scored=False)
    target = _write_arm(
        base_dir, source, "counterexample", name="dev-model-a-cx-2026-10-09"
    )
    linked = base_dir.parent / _ARM_RUNS["counterexample"]
    linked.symlink_to(target, target_is_directory=True)

    assert _round_refusal(base_dir).code == "repair_arm_mismatch"
    linked.unlink()
    # A run moved under another arm's name still names itself.
    shutil.move(target, linked)
    assert _round_refusal(base_dir).code == "repair_arm_mismatch"
    shutil.rmtree(linked)
    _write_arm(base_dir, source, "counterexample")
    assert _round_refusal(base_dir).code == "repair_arm_unscored"


def test_the_one_rerun_replaces_its_arm(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round_base(tmp_path / "results", source)
    _write_arm(base_dir, source, "resample")
    _write_arm(base_dir, source, "bare")
    # The first counterexample run was never scored.
    _write_arm(base_dir, source, "counterexample", scored=False)
    rerun = arm_run_ids(base_dir.name, "counterexample")[1]
    _write_arm(base_dir, source, "counterexample", name=rerun)

    report = round_run(base_dir, code_revision="rev")

    assert rerun == "dev-model-a-cx-r2-2026-10-01"
    assert report.arm_runs["counterexample"] == rerun
    assert _summary(base_dir).arms[2].run == rerun


def test_a_committed_plan_is_never_rewritten_under_its_arms(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    plan = base_dir / PLAN_PATH
    edited = plan.read_bytes() + b"\n"
    plan.write_bytes(edited)

    error = _round_refusal(base_dir)
    checked = round_run(base_dir, code_revision="rev", check=True)

    assert error.code == "repair_plan_changed"
    assert plan.read_bytes() == edited
    assert checked.differences == (
        "repair/plan.json",
        "repair/summary.json",
        "repair/summary.md",
    )


def test_a_corrected_base_keeps_the_plans_trigger_set(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    before = _summary(base_dir)
    shutil.copytree(base_dir / "scored", base_dir / "scored-original")
    verdicts = {item: outcome for item, (_, outcome) in _ROUND_BASE.items()}
    _write_scored(base_dir, source, {**verdicts, "mei-0003": _SE})

    report = round_run(base_dir, code_revision="rev")
    after = _summary(base_dir)

    assert report.differences == ()
    assert after.base_outcome_changed == ("mei-0003",)
    assert after.items[2].base_outcome == "silent_wrong"
    assert after.items[2].base_outcome_now is _SE
    assert after.arms == before.arms
    assert after.comparisons == before.comparisons
    assert "Base outcome changed since the plan: mei-0003." in (
        base_dir / SUMMARY_REPORT_PATH
    ).read_text("utf-8")


def _other_model(
    results: Path, summary: RepairSummaryV1, letter: str, **update: Any
) -> str:
    """Commits model ``letter``'s round: its counterexample repairs all."""
    run = f"dev-model-{letter}-2026-10-01"
    items = tuple(
        item.model_copy(
            update={"outcomes": {**item.outcomes, "counterexample": _SE}}
        )
        for item in summary.items
    )
    copy = summary.model_copy(
        update={
            "base_run": run,
            "model_id": f"vendor/model-{letter}",
            "items": items,
            **update,
        }
    )
    _write(results / run / SUMMARY_PATH, copy)
    return run


def test_pooled_repair_at_1_sums_every_models_cells(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    summary = _summary(base_dir)
    results = base_dir.parent
    runs = [_other_model(results, summary, "c"), base_dir.name]
    runs.append(_other_model(results, summary, "b"))

    report = pool_run(results, "dev", runs, code_revision="rev")
    pooled = RepairPoolV1.model_validate_json(
        (results / "repair-pool" / "dev.json").read_bytes()
    )
    alone = pool_summaries("dev", [(summary, "0" * 64)])

    assert report.bases == tuple(sorted(runs))
    assert [base.run for base in pooled.bases] == sorted(runs)
    assert (
        pooled.bases[0].summary_sha256
        == hashlib.sha256((base_dir / SUMMARY_PATH).read_bytes()).hexdigest()
    )
    # Three models' triggered shares sum to 10.5; counterexample repairs
    # 2.5 + 3.5 + 3.5 of them.
    assert [
        (arm.arm, arm.triggered_items, arm.repaired, arm.repair_at_1.value)
        for arm in pooled.arms
    ] == [
        ("resample", 21, 3, 0.142857),
        ("bare", 21, 9, 0.428571),
        ("counterexample", 21, 19, 0.904762),
    ]
    once = _dev_shares(_repaired_by("counterexample"))
    every = _dev_shares(list(_ROUND_BASE))
    assert pooled.arms[2].repair_at_1 == ratio_rate(
        {key: once[key] + 2 * every[key] for key in once},
        {key: 3 * value for key, value in every.items()},
        draw_indices(12),
        _DEV_READY_CASES,
    )
    # Cells: model a is 3 and 1, models b and c 3 and 0 each, so ten
    # discordant cells make counterexample - bare conclusive.
    assert [
        (
            item.first,
            item.second,
            item.difference.value,
            item.first_better,
            item.second_better,
            item.discordant,
            item.inconclusive,
            item.unit,
        )
        for item in pooled.comparisons
    ] == [
        ("counterexample", "bare", 0.47619, 9, 1, 10, False, "cells"),
        ("counterexample", "resample", 0.761905, 14, 0, 14, False, "cells"),
        ("bare", "resample", 0.285714, 6, 0, 6, True, "cells"),
    ]
    # One model pooled alone is its own round.
    assert [arm.repair_at_1 for arm in alone.arms] == [
        arm.repair_at_1 for arm in summary.arms
    ]
    assert [item.difference for item in alone.comparisons] == [
        item.difference for item in summary.comparisons
    ]
    text = (results / "repair-pool" / "dev.md").read_text("utf-8")
    assert "| counterexample - bare | 0.476 [" in text
    assert "| conclusive |" in text


def test_the_cli_writes_and_checks_a_pool_from_the_bases_it_names(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    results = base_dir.parent
    other = _other_model(results, _summary(base_dir), "b")
    args = ["repair-pool", "--results-dir", str(results), "--split", "dev"]
    args += ["--code-revision", "rev"]

    assert main([*args, "--base", base_dir.name, "--base", other]) == 0
    written = json.loads(capsys.readouterr().out)
    assert main([*args, "--check"]) == 0
    checked = json.loads(capsys.readouterr().out)
    (results / "repair-pool" / "dev.md").write_bytes(b"x\n")
    assert main([*args, "--check"]) == 1
    differs = json.loads(capsys.readouterr().out)
    (results / "repair-pool" / "dev.json").unlink()
    assert main([*args, "--check"]) == 2
    refused = json.loads(capsys.readouterr().err)

    assert written["schema_version"] == "repair-pool-report/1.0"
    assert written["bases"] == [base_dir.name, other]
    assert checked["pool_sha256"] == written["pool_sha256"]
    assert checked["differences"] == []
    assert differs["differences"] == ["repair-pool/dev.md"]
    assert refused["error"]["code"] == "repair_pool_bases_invalid"
    assert not (results / "repair-pool" / "dev.json").exists()


@pytest.mark.parametrize(
    ("bases", "code"),
    [
        ((), "repair_pool_bases_invalid"),
        (("../dev-model-a-2026-10-01",), "repair_pool_bases_invalid"),
        (("dev-model-a-2026-10-01",) * 2, "repair_pool_bases_invalid"),
        (("test-model-a-2026-10-01",), "repair_pool_bases_invalid"),
        (("dev-model-z-2026-10-01",), "repair_pool_unsummarized"),
        (("dev-model-u-2026-10-01",), "repair_pool_unsummarized"),
        (("dev-model-s-2026-10-01",), "repair_pool_mismatch"),
        (
            ("dev-model-a-2026-10-01", "dev-model-m-2026-10-01"),
            "repair_pool_mismatch",
        ),
        (
            ("dev-model-a-2026-10-01", "dev-model-x-2026-10-01"),
            "repair_pool_mismatch",
        ),
    ],
    ids=[
        "none",
        "path",
        "twice",
        "split",
        "absent",
        "unreadable",
        "another-pass",
        "same-model",
        "other-cases",
    ],
)
def test_bases_that_cannot_be_pooled_are_refused(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    bases: tuple[str, ...],
    code: str,
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    summary = _summary(base_dir)
    results = base_dir.parent
    _other_model(results, summary, "m", model_id=summary.model_id)
    extra = RepairCaseV1(case_id="extra-case", ready_items=2, triggered_items=0)
    _other_model(results, summary, "x", cases=(*summary.cases, extra))
    another = results / "dev-model-s-2026-10-01" / SUMMARY_PATH
    another.parent.mkdir(parents=True)
    shutil.copy(base_dir / SUMMARY_PATH, another)
    unreadable = results / "dev-model-u-2026-10-01" / SUMMARY_PATH
    unreadable.parent.mkdir(parents=True)
    unreadable.write_bytes(b"{}\n")

    with pytest.raises(RoundError) as error:
        pool_run(results, "dev", bases, code_revision="rev")

    assert error.value.code == code
    assert not (results / "repair-pool").exists()


def _damaged(summary: RepairSummaryV1, damage: str) -> dict[str, Any]:
    """The fields of a summary whose cases no longer describe its items."""
    cases, items = list(summary.cases), list(summary.items)
    if damage == "overfull":
        # tcp-expiring-ttl triggers both of its two ready items.
        cases[8] = cases[8].model_copy(update={"ready_items": 1})
    elif damage == "recounted":
        cases[0] = cases[0].model_copy(update={"triggered_items": 1})
    elif damage == "unlisted":
        del cases[8]
    elif damage == "repeated":
        items.append(items[0])
    elif damage == "armless":
        outcomes = dict(items[0].outcomes)
        del outcomes["bare"]
        items[0] = items[0].model_copy(update={"outcomes": outcomes})
    else:
        return {"arms": summary.arms[::-1]}
    return {"cases": tuple(cases), "items": tuple(items)}


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        ("overfull", "a case triggers at most its ready items"),
        ("recounted", "each case counts its triggered items"),
        ("unlisted", "every item is in one listed ready case"),
        ("repeated", "a summary lists each item once"),
        ("armless", "an item has an outcome in every arm"),
        ("reordered", "a summary lists the three arms in order"),
    ],
)
def test_a_summary_whose_counts_do_not_add_up_is_not_pooled(
    tmp_path: Path,
    source: ModelSplitArtifacts,
    spy: _Spy,
    damage: str,
    message: str,
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    summary = _summary(base_dir)
    results = base_dir.parent
    assert summary.cases[8].case_id == "tcp-expiring-ttl"
    assert summary.cases[0].triggered_items == 0
    run = _other_model(results, summary, "b", **_damaged(summary, damage))

    with pytest.raises(ValidationError, match=message):
        RepairSummaryV1.model_validate_json(
            (results / run / SUMMARY_PATH).read_bytes()
        )
    with pytest.raises(RoundError) as error:
        pool_run(results, "dev", [base_dir.name, run], code_revision="rev")

    assert error.value.code == "repair_pool_unsummarized"
    assert str(error.value).startswith(run)
    assert not (results / "repair-pool").exists()


def test_a_committed_pool_that_cannot_be_read_names_no_bases(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    results = base_dir.parent
    pool_run(results, "dev", [base_dir.name], code_revision="rev")
    (results / "repair-pool" / "dev.json").write_bytes(b"{}\n")

    with pytest.raises(RoundError) as error:
        pool_run(results, "dev", code_revision="rev", check=True)

    assert error.value.code == "repair_pool_bases_invalid"
    assert (results / "repair-pool" / "dev.json").read_bytes() == b"{}\n"


def test_a_report_cell_cannot_carry_markup_from_a_model_id(
    tmp_path: Path, source: ModelSplitArtifacts, spy: _Spy
) -> None:
    base_dir = _round(tmp_path, source)
    round_run(base_dir, code_revision="rev")
    hostile = _summary(base_dir).model_copy(
        update={"model_id": "evil|model\n# heading"}
    )

    text = render_summary(hostile)

    assert "Model: evil?model?? heading." in text
    assert "evil|model" not in text and "\n# heading" not in text


def test_the_arm_tags_are_the_ones_follow_up_names_runs_with() -> None:
    path = Path(__file__).parents[1] / "scripts" / "model_run.py"
    spec = importlib.util.spec_from_file_location("repair_model_run", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        tags = cast(Mapping[str, str], getattr(module, "_ARM_TAGS"))
        rerun = cast(str, getattr(module, "_ARM_RERUN"))
    finally:
        del sys.modules[spec.name]

    assert dict(ARM_TAGS) == dict(tags)
    assert ARM_RERUN == rerun
    assert arm_run_ids("dev-qwen3-32b-2026-09-26", "resample") == (
        "dev-qwen3-32b-res-2026-09-26",
        "dev-qwen3-32b-res-r2-2026-09-26",
    )


def _scored_item(
    item_id: str, case_id: str, outcome: OutcomeV1
) -> ItemOutcomeV1:
    """One base C4 outcome on ready gold."""
    return ItemOutcomeV1(
        condition="C4",
        item_id=item_id,
        case_id=case_id,
        outcome=outcome,
        gold_field_count=1,
        latency_ms=1.0,
    )


def _arm_result(outcomes: Mapping[str, OutcomeV1]) -> ArmResult:
    """An arm run that answered nothing worth reading but its outcomes."""
    return ArmResult(
        run="dev-model-a-cx-2026-10-01",
        manifest_sha256="1" * 64,
        outcomes_sha256="2" * 64,
        outcomes=outcomes,
        answers={item_id: None for item_id in outcomes},
        output_contract=OutputContractV1.TYPED_IR,
        latency_ms=(0.0, 0.0),
        charged_usd_upper_bound=0.0,
        provider_reported_usd=None,
    )


def test_repair_at_1_weights_each_case_by_its_share_of_its_items() -> None:
    """A case of one ready item weighs as much as a case of two.

    solo has one ready C4 item, triggered; pair has two, one triggered.
    The triggered shares are 1 and 0.5, 1.5 in all, so repairing only
    pair's item is 0.5 / 1.5 and only solo's 1 / 1.5, where an item ratio
    would read one of two for each.
    """
    outcomes = {
        "mei-0001": _scored_item("mei-0001", "solo", _SW),
        "mei-0002": _scored_item("mei-0002", "pair", _INV),
        "mei-0003": _scored_item("mei-0003", "pair", _SE),
        "mei-0004": _scored_item("mei-0004", "unclear", _SE).model_copy(
            update={"gold_status": "needs_clarification"}
        ),
    }
    plan = RepairPlanV1.model_validate(
        _plan(
            items=[
                {
                    "item_id": "mei-0001",
                    "base_outcome": "silent_wrong",
                    "card_kind": "none",
                },
                {
                    "item_id": "mei-0002",
                    "base_outcome": "invalid",
                    "card_kind": "none",
                },
            ]
        )
    )
    base = RoundBase(
        model_id="vendor/model-a",
        gold_hash=_GOLD_HASH,
        outcomes=outcomes,
        now={key: value.outcome for key, value in outcomes.items()},
        answers={key: "an answer" for key in outcomes},
    )

    summary = summarize_round(
        plan,
        "3" * 64,
        base,
        {
            "resample": _arm_result({"mei-0001": _SW, "mei-0002": _INV}),
            "bare": _arm_result({"mei-0001": _SW, "mei-0002": _SE}),
            "counterexample": _arm_result({"mei-0001": _SE, "mei-0002": _INV}),
        },
    )

    assert [
        (case.case_id, case.ready_items, case.triggered_items)
        for case in summary.cases
    ] == [("pair", 2, 1), ("solo", 1, 1)]
    assert summary.bootstrap["cases"] == 2
    assert [arm.repair_at_1.value for arm in summary.arms] == [
        0.0,
        0.333333,
        0.666667,
    ]
    assert [
        (arm.repair_at_1_silent_wrong.value, arm.repair_at_1_invalid.value)
        for arm in summary.arms
    ] == [(0.0, 0.0), (0.0, 1.0), (1.0, 0.0)]
    first = summary.comparisons[0]
    assert (first.first, first.second, first.difference.value) == (
        "counterexample",
        "bare",
        0.333333,
    )
    assert (first.first_better, first.second_better) == (1, 1)
    assert summary.arms[2].card_value_reuse == 0
