"""Offline scoring through the CLI with the pinned Docker tshark.

Every test in this file regenerates the model split and executes the real
pinned executable against it, exactly as ``tests/test_cli_live.py`` does, so
the file carries no skip: the test image must supply tshark 4.6.8 and the
frozen field catalog.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.cli import main
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.field_catalog import FieldType
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.generation import RetrievedFieldV1
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import MissingSlot
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import ModelInputItemV1

_MODEL_ID = "vendor/model-a"
_UNKNOWN_FIELD_FILTER = "ip.ttll <= 1"
_REJECTED_FILTER = "tcp &&"
_MALFORMED_REPLY = "not json"
_CLARIFYING_QUESTION = "Which protocol should the filter keep?"
_TAMPERED_ITEM = "mei-0003"
_TAMPERED_CASE = "tcp-expiring-ttl"
_UNKNOWN_FIELD_IR = IntentIrV1(
    expression=Predicate(field="ip.ttll", operator=Operator.LE, value=1)
)


class _ScoredRun(NamedTuple):
    """One mixed run directory, scored once for the whole module."""

    run_dir: Path
    split_dir: Path
    exit_code: int

    def args(self, *extra: str) -> list[str]:
        """Builds the argv of one scoring pass over this run directory."""
        return [
            "score",
            "--run-dir",
            str(self.run_dir),
            "--code-revision",
            "test",
            "--split-dir",
            str(self.split_dir),
            *extra,
        ]


def _write_json(path: Path, value: object) -> None:
    """Writes one committed contract as canonical JSON with an LF ending."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((canonical_json(value) + "\n").encode("utf-8"))


def _prepared(
    items: Sequence[ModelInputItemV1], output_contract: OutputContractV1
) -> PreparedBatchV1:
    """Prepares one condition's prompts exactly as the call step would."""
    return prepare_batch(
        [
            GenerationInputV1(
                item_id=item.item_id,
                intent=item.intent,
                user_assumptions=item.user_assumptions,
                split=item.split,
            )
            for item in items
        ],
        output_contract=output_contract,
        retrieval=RetrievalV1.NONE,
    )


def _filter_reply(display_filter: str) -> str:
    """Renders one ready display-filter envelope."""
    return canonical_json(
        DirectFilterResultV1(
            status=GenerationStatus.READY, display_filter=display_filter
        )
    )


def _ir_reply(intent_ir: IntentIrV1) -> str:
    """Renders one ready typed-IR envelope."""
    return canonical_json(
        GenerationResultV1(status=GenerationStatus.READY, intent_ir=intent_ir)
    )


def _filter_replies(cases: Sequence[ModelGoldCaseV1]) -> list[str | None]:
    """Answers the display-filter condition, four items wrong on purpose."""
    replies: list[str | None] = [
        _filter_reply(case.spec.reference_filter) for case in cases[:12]
    ]
    replies.append(_filter_reply(cases[12].mutation_filter))
    replies.append(_filter_reply(_UNKNOWN_FIELD_FILTER))
    replies.append(_filter_reply(_REJECTED_FILTER))
    replies.append(_MALFORMED_REPLY)
    return replies


def _typed_replies(cases: Sequence[ModelGoldCaseV1]) -> list[str | None]:
    """Answers the typed-IR condition, three items wrong on purpose."""
    replies: list[str | None] = [
        _ir_reply(case.spec.canonical_ir) for case in cases[:13]
    ]
    replies.append(
        canonical_json(
            GenerationResultV1(
                status=GenerationStatus.NEEDS_CLARIFICATION,
                clarifying_question=_CLARIFYING_QUESTION,
                missing_slots=(MissingSlot.FIELD,),
            )
        )
    )
    replies.append(_ir_reply(_UNKNOWN_FIELD_IR))
    replies.append(None)
    return replies


def _completions(
    items: Sequence[ModelInputItemV1], replies: Sequence[str | None]
) -> tuple[CompletionV1, ...]:
    """Records one stored answer per item; a null reply is a failure."""
    return tuple(
        (
            CompletionV1(
                item_id=item.item_id,
                status=CompletionStatusV1.FAILED,
                error_code="timeout",
                latency_ms=120.0,
            )
            if reply is None
            else CompletionV1(
                item_id=item.item_id,
                status=CompletionStatusV1.COMPLETED,
                response_text=reply,
                latency_ms=120.0,
                prompt_tokens=400,
                completion_tokens=40,
                finish_reason="stop",
            )
        )
        for item, reply in zip(items, replies)
    )


def _build_run(root: Path) -> Path:
    """Writes a C1 and C3 run directory answered from the dev gold.

    The scripted replies answer the first sixteen ready dev items.
    """
    artifacts = generate_model_split(root / "source")
    by_case = {case.case_id: case for case in artifacts.gold.cases}
    items = [
        item
        for item in artifacts.inputs
        if item.split == "dev"
        and artifacts.gold.item_to_case[item.item_id] in by_case
    ][:16]
    routed = [
        by_case[artifacts.gold.item_to_case[item.item_id]] for item in items
    ]
    run_dir = root / "dev-0001"
    conditions = (
        ("C1", OutputContractV1.DISPLAY_FILTER, _filter_replies(routed)),
        ("C3", OutputContractV1.TYPED_IR, _typed_replies(routed)),
    )
    for label, output_contract, replies in conditions:
        _write_json(
            run_dir / "prepared" / f"{label}.json",
            _prepared(items, output_contract),
        )
        _write_json(
            run_dir / "completions" / f"{label}.json",
            CompletionBatchV1(
                output_contract=output_contract,
                retrieval=RetrievalV1.NONE,
                settings=RequestSettingsV1(model_id=_MODEL_ID),
                completions=_completions(items, replies),
            ),
        )
    return run_dir


def _digests(scored: Path) -> dict[str, str]:
    """Hashes every committed file of the scored tree by relative name."""
    return {
        path.relative_to(scored)
        .as_posix(): hashlib.sha256(path.read_bytes())
        .hexdigest()
        for path in sorted(scored.rglob("*"))
        if path.is_file()
    }


@contextmanager
def _edited(path: Path, payload: bytes) -> Generator[None, None, None]:
    """Temporarily replaces one committed file's bytes."""
    original = path.read_bytes()
    path.write_bytes(payload)
    try:
        yield
    finally:
        path.write_bytes(original)


@pytest.fixture(name="scored_run", scope="module")
def fixture_scored_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> _ScoredRun:
    """Builds one mixed run directory and scores it once for the module."""
    root = tmp_path_factory.mktemp("score")
    pending = _ScoredRun(_build_run(root), root / "split", 0)
    return _ScoredRun(pending.run_dir, pending.split_dir, main(pending.args()))


def test_score_classifies_a_mixed_run(scored_run: _ScoredRun) -> None:
    """Every protocol outcome is reached by one run of sixteen items."""
    scored = scored_run.run_dir / "scored"
    summary: dict[str, Any] = json.loads(
        (scored / "summary.json").read_text(encoding="utf-8")
    )
    direct: dict[str, Any] = summary["conditions"]["C1"]
    typed: dict[str, Any] = summary["conditions"]["C3"]
    receipts = sorted(path for path in (scored / "receipts").rglob("*.json"))

    assert scored_run.exit_code == 0
    assert direct["outcomes"]["strong_exact"] == 12
    assert direct["outcomes"]["silent_wrong"] == 1
    assert direct["outcomes"]["invalid"] == 2
    assert direct["outcomes"]["malformed"] == 1
    assert direct["error_codes"]["filter_unknown_field"] == 1
    assert direct["error_codes"]["filter_rejected"] == 1
    assert typed["outcomes"]["strong_exact"] == 13
    assert typed["outcomes"]["abstained"] == 1
    assert typed["outcomes"]["invalid"] == 1
    assert typed["outcomes"]["provider_failed"] == 1
    assert typed["error_codes"]["unknown_field"] == 1
    assert len(receipts) == 26
    assert len(list((scored / "receipts" / "C1").glob("*.json"))) == 13
    assert len(list((scored / "receipts" / "C3").glob("*.json"))) == 13


def test_score_check_reproduces_outcomes_summary_receipts_and_specs(
    scored_run: _ScoredRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second pass over the same run reproduces every committed byte."""
    scored = scored_run.run_dir / "scored"
    before = _digests(scored)

    exit_code = main(scored_run.args("--check"))

    report: dict[str, Any] = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["checked"] is True
    assert report["differences"] == []
    assert report["items"] == 32
    assert "score_manifest.json" in before
    assert _digests(scored) == before


def test_score_check_reports_a_tampered_outcome_line(
    scored_run: _ScoredRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """One rewritten outcome line is named, and no model text is printed."""
    outcomes = scored_run.run_dir / "scored" / "outcomes.jsonl"
    rewritten: list[str] = []
    for line in outcomes.read_text(encoding="utf-8").splitlines():
        record: dict[str, Any] = json.loads(line)
        if (record["condition"], record["item_id"]) == ("C1", _TAMPERED_ITEM):
            record["outcome"] = "silent_wrong"
        rewritten.append(canonical_json(record))
    drifted = "".join(f"{line}\n" for line in rewritten).encode("utf-8")

    with _edited(outcomes, drifted):
        exit_code = main(scored_run.args("--check"))

    printed = capsys.readouterr().out
    report: dict[str, Any] = json.loads(printed)
    assert exit_code == 1
    assert report["differences"] == [f"outcomes:C1/{_TAMPERED_ITEM}"]
    assert _UNKNOWN_FIELD_FILTER not in printed
    assert "ip.ttl" not in printed


def test_score_check_reports_a_tampered_receipt_and_spec(
    scored_run: _ScoredRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """Receipts and specifications are under the guard; runtimes are not."""
    scored = scored_run.run_dir / "scored"
    receipt = scored / "receipts" / "C1" / f"{_TAMPERED_ITEM}.json"
    spec = scored / "specs" / f"{_TAMPERED_CASE}.json"
    recorded: dict[str, Any] = json.loads(receipt.read_text(encoding="utf-8"))
    tampered: dict[str, Any] = json.loads(json.dumps(recorded))
    tampered["probes"][0]["candidate_frames"] = []
    jittered: dict[str, Any] = json.loads(json.dumps(recorded))
    for probe in jittered["probes"]:
        probe["runtime_ms"] = 99.0

    with _edited(receipt, json.dumps(tampered).encode("utf-8")):
        with _edited(spec, spec.read_bytes() + b" "):
            flagged = main(scored_run.args("--check"))
            report: dict[str, Any] = json.loads(capsys.readouterr().out)
    with _edited(receipt, json.dumps(jittered).encode("utf-8")):
        unchanged = main(scored_run.args("--check"))
        jitter: dict[str, Any] = json.loads(capsys.readouterr().out)

    assert flagged == 1
    assert report["differences"] == [
        f"receipts:C1/{_TAMPERED_ITEM}",
        f"specs:{_TAMPERED_CASE}",
    ]
    assert unchanged == 0
    assert jitter["differences"] == []


def test_score_stops_on_prompt_drift(
    scored_run: _ScoredRun, capsys: pytest.CaptureFixture[str]
) -> None:
    """A committed prompt that cannot be rebuilt stops the whole run."""
    prepared = scored_run.run_dir / "prepared" / "C1.json"
    document: dict[str, Any] = json.loads(prepared.read_text(encoding="utf-8"))
    document["prompts"][0]["messages"][0]["content"] += " "
    drifted = (canonical_json(document) + "\n").encode("utf-8")

    with _edited(prepared, drifted):
        exit_code = main(scored_run.args())

    streams = capsys.readouterr()
    assert exit_code == 2
    assert json.loads(streams.err)["error"]["code"] == "prompt_mismatch"
    assert streams.out == ""


# The four conditions the protocol runs, in published order.
_CONTROL_CONDITIONS: tuple[tuple[str, OutputContractV1, RetrievalV1], ...] = (
    ("C1", OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    ("C2", OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    ("C3", OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    ("C4", OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
)
# The dev gold's own field types, so the hand-built context reads as the
# catalog would describe it. A gold case that reaches for a field absent
# here fails the lookup, which is the signal that this table is stale.
_FIELD_TYPES: dict[str, FieldType] = {
    "dns": FieldType.PROTOCOL,
    "dns.flags.rcode": FieldType.INTEGER,
    "dns.flags.response": FieldType.BOOLEAN,
    "dns.qry.type": FieldType.INTEGER,
    "frame.len": FieldType.INTEGER,
    "ip.dst": FieldType.IPV4,
    "ip.ttl": FieldType.INTEGER,
    "tcp": FieldType.PROTOCOL,
    "tcp.dstport": FieldType.INTEGER,
    "tcp.flags.ack": FieldType.BOOLEAN,
    "tcp.flags.ece": FieldType.BOOLEAN,
    "tcp.flags.fin": FieldType.BOOLEAN,
    "tcp.flags.reset": FieldType.BOOLEAN,
    "tcp.flags.syn": FieldType.BOOLEAN,
    "udp": FieldType.PROTOCOL,
}
# The committed dev split: 12 ready and 8 non-ready cases, two items each.
_READY_DEV_ITEMS = 24
_NON_READY_DEV_ITEMS = 16
# One field no dev case needs, so a retrieved context is never exactly the
# gold field set and full coverage still has something to be measured over.
_DISTRACTOR_FIELD = "frame.len"


class _ControlRun(NamedTuple):
    """One prepared-only run directory, scored once under each control."""

    run_dir: Path
    split_dir: Path
    reference: int
    mutation: int

    def args(self, mode: str, *extra: str) -> list[str]:
        """Builds the argv of one control pass over this run directory."""
        return [
            "score",
            "--run-dir",
            str(self.run_dir),
            "--code-revision",
            "test",
            "--split-dir",
            str(self.split_dir),
            "--control",
            mode,
            *extra,
        ]


def _retrieved(case: ModelGoldCaseV1) -> tuple[RetrievedFieldV1, ...]:
    """Builds one item's ranked context from its own gold fields.

    Retrieval itself is measured elsewhere; this context is hand-built so
    that the recall the control pass reports is a known number and the
    reference answer can be exact in every condition.
    """
    gold = sorted(
        {
            predicate.field
            for _, predicate in walk_predicates(
                case.spec.canonical_ir.expression
            )
        }
    )
    return tuple(
        RetrievedFieldV1(
            rank=rank,
            abbreviation=name,
            field_type=_FIELD_TYPES[name],
            protocol=name.split(".", maxsplit=1)[0],
            display_name=name,
        )
        for rank, name in enumerate([*gold, _DISTRACTOR_FIELD], start=1)
    )


def _context(
    case: ModelGoldCaseV1 | None,
) -> tuple[RetrievedFieldV1, ...]:
    """Builds a ready item's context from gold; a non-ready one is empty."""
    return () if case is None else _retrieved(case)


def _build_control_run(root: Path) -> Path:
    """Writes the four committed conditions with no stored answers at all.

    A non-ready item gets an empty context, as an item no field matches
    does.
    """
    artifacts = generate_model_split(root / "source")
    by_case = {case.case_id: case for case in artifacts.gold.cases}
    items = [item for item in artifacts.inputs if item.split == "dev"]
    routed = {
        item.item_id: by_case.get(artifacts.gold.item_to_case[item.item_id])
        for item in items
    }
    run_dir = root / "control-0001"
    for label, output_contract, retrieval in _CONTROL_CONDITIONS:
        batch = prepare_batch(
            [
                GenerationInputV1(
                    item_id=item.item_id,
                    intent=item.intent,
                    user_assumptions=item.user_assumptions,
                    retrieved_fields=(
                        _context(routed[item.item_id])
                        if retrieval is RetrievalV1.LEXICAL
                        else None
                    ),
                    split=item.split,
                )
                for item in items
            ],
            output_contract=output_contract,
            retrieval=retrieval,
        )
        _write_json(run_dir / "prepared" / f"{label}.json", batch)
    return run_dir


def _summary(scored: Path) -> dict[str, Any]:
    """Reads one committed summary back as plain JSON."""
    document: dict[str, Any] = json.loads(
        (scored / "summary.json").read_text(encoding="utf-8")
    )
    return document


@pytest.fixture(name="control_run", scope="module")
def fixture_control_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> _ControlRun:
    """Scores the committed prompts from gold once under each control."""
    root = tmp_path_factory.mktemp("control")
    pending = _ControlRun(_build_control_run(root), root / "split", 0, 0)
    reference = main(pending.args("reference"))
    mutation = main(pending.args("mutation"))
    return _ControlRun(pending.run_dir, pending.split_dir, reference, mutation)


def test_reference_control_is_strong_exact_in_every_condition(
    control_run: _ControlRun,
) -> None:
    """Gold answers score exact everywhere, and the check reproduces them."""
    scored = control_run.run_dir / "control-reference"
    summary = _summary(scored)
    conditions: dict[str, Any] = summary["conditions"]
    before = _digests(scored)

    rechecked = main(control_run.args("reference", "--check"))

    assert control_run.reference == 0
    for label, _, _ in _CONTROL_CONDITIONS:
        condition: dict[str, Any] = conditions[label]
        assert condition["items"] == _READY_DEV_ITEMS + _NON_READY_DEV_ITEMS
        assert condition["outcomes"]["strong_exact"] == _READY_DEV_ITEMS
        assert condition["outcomes"]["abstained"] == _NON_READY_DEV_ITEMS
        assert condition["compile_valid"]["value"] == 1.0
        assert condition["strong_exact"]["value"] == 1.0
        assert condition["false_ready"]["value"] == 0.0
        assert condition["slot_match"]["value"] == 1.0
    for label in ("C2", "C4"):
        recall: dict[str, Any] = conditions[label]["gold_field_recall"]
        assert recall["mean_recall"] == 1.0
        assert recall["full_coverage"] == 1.0
    assert conditions["C1"]["gold_field_recall"] is None
    assert conditions["C3"]["gold_field_recall"] is None
    assert "repair_at_1" in summary["not_measured"]
    assert not {"false_ready", "slot_match"} & set(summary["not_measured"])
    assert rechecked == 0
    assert _digests(scored) == before


def test_mutation_control_is_silent_wrong_for_display_filters(
    control_run: _ControlRun,
) -> None:
    """Every authored mutation is distinguishable on the three probes."""
    summary = _summary(control_run.run_dir / "control-mutation")
    conditions: dict[str, Any] = summary["conditions"]

    assert control_run.mutation == 0
    assert set(conditions) == {"C1", "C2"}
    for label in ("C1", "C2"):
        outcomes: dict[str, Any] = conditions[label]["outcomes"]
        assert outcomes["silent_wrong"] == _READY_DEV_ITEMS
        assert outcomes["false_ready"] == _NON_READY_DEV_ITEMS
        assert conditions[label]["outcomes"]["strong_exact"] == 0
    assert summary["not_measured"]["C3"] == "no_typed_mutation"
    assert summary["not_measured"]["C4"] == "no_typed_mutation"


def test_control_and_stored_completions_write_separate_directories(
    scored_run: _ScoredRun,
) -> None:
    """A control pass leaves the stored-answer tree byte for byte alone."""
    scored = scored_run.run_dir / "scored"
    before = _digests(scored)

    exit_code = main(scored_run.args("--control", "reference"))

    control = scored_run.run_dir / "control-reference"
    assert exit_code == 0
    assert _digests(scored) == before
    assert _summary(scored)["model_id"] == _MODEL_ID
    assert _summary(control)["model_id"] == "control-reference"
