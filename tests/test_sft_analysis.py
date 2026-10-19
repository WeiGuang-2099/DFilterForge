"""The analysis writer on a small hand-built tree, and on the committed one."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1

_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sft_analysis", _ROOT / "scripts" / "sft_analysis.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("sft_analysis cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


analysis = _load()
BASE = "test-base-2026-01-01"
SEED = "test-seed-2026-01-01"
HOSTED = "test-hosted-2026-01-01"
SYN = Predicate(field="tcp.flags.syn", operator=Operator.EQ, value=True)
ACK = Predicate(field="tcp.flags.ack", operator=Operator.EQ, value=True)
GOLD = {
    "case-a": IntentIrV1(expression=All(children=(SYN, ACK))),
    "case-b": IntentIrV1(expression=SYN),
}
# What every answer that is not strong exact says.
MISS = IntentIrV1(expression=SYN)
ITEMS = {"i-1": "case-a", "i-2": "case-a", "i-3": "case-b", "i-4": "case-b"}
# The base row misses every item; the seed gets every one exact.
Outcomes = dict[str, tuple[OutcomeV1, dict[str, Any]]]
BASE_OUTCOMES: Outcomes = {
    "i-1": (OutcomeV1.SILENT_WRONG, {}),
    "i-2": (OutcomeV1.INVALID, {"error_code": "unknown_field"}),
    "i-3": (OutcomeV1.MALFORMED, {"finish_reason": "length"}),
    "i-4": (OutcomeV1.ABSTAINED, {}),
}
_ZERO = {"value": 0.0, "low": 0.0, "high": 0.0, "resamples_used": 1000}
_ONE = {"value": 1.0, "low": 1.0, "high": 1.0, "resamples_used": 1000}
_NONE = {"value": None, "low": None, "high": None, "resamples_used": 0}


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), "utf-8")


def _run(results: Path, run: str, outcomes: Outcomes) -> None:
    """Writes one run's scored outcomes, intents, specs and C4 prompts."""
    scored = results / run / "scored"
    lines: list[str] = []
    for condition in ("C1", "C2", "C3", "C4"):
        for key, case in ITEMS.items():
            outcome, extra = outcomes[key]
            item = ItemOutcomeV1(
                condition=condition,
                item_id=key,
                case_id=case,
                outcome=outcome,
                gold_field_count=1,
                retrieved_gold_field_count=1,
                latency_ms=1.0,
                **extra,
            )
            lines.append(item.model_dump_json())
            answer = GOLD[case] if outcome is OutcomeV1.STRONG_EXACT else MISS
            if condition == "C4" and outcome in analysis.WITH_IR:
                _write(
                    scored / "intents" / "C4" / f"{key}.json",
                    answer.model_dump(),
                )
    (scored / "outcomes.jsonl").write_text("\n".join(lines) + "\n", "utf-8")
    for case, gold in GOLD.items():
        _write(
            scored / "specs" / f"{case}.json",
            {"canonical_ir": gold.model_dump()},
        )
    fields = [{"abbreviation": "tcp.flags.syn"}]
    _write(
        results / run / "prepared" / "C4.json",
        {
            "prompts": [
                {"item_id": key, "retrieved_fields": fields} for key in ITEMS
            ]
        },
    )


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    """A headline row set and a training set the analysis can read."""
    results = tmp_path / "results"
    exact: Outcomes = {key: (OutcomeV1.STRONG_EXACT, {}) for key in ITEMS}
    _run(results, BASE, BASE_OUTCOMES)
    _run(results, SEED, exact)
    _run(results, HOSTED, exact)
    _write(
        results / "sft-v1" / "headline.json",
        {
            "base_run": BASE,
            "seeds": [{"seed": 17, "run": SEED}],
            "hosted": [{"run": HOSTED}],
            "coverage": {
                "every_gold_field_retrieved": {
                    "base": _ZERO,
                    "seeds": [{"rate": _ONE}],
                },
                "some_gold_field_missing": {
                    "base": _NONE,
                    "seeds": [{"rate": _NONE}],
                },
            },
            "mean": {"rate": {"value": 1.0}},
        },
    )
    train = tmp_path / "train.jsonl"
    rows = [
        {
            "id": "train-0001",
            "request": "Show SYN or ACK.",
            "filter": "(tcp.flags.syn == true || tcp.flags.ack == true)",
            "target": {
                "status": "ready",
                "intent_ir": IntentIrV1(
                    expression=All(children=(ACK, SYN))
                ).model_dump(),
            },
        },
        {"id": "train-0002", "target": {"status": "needs_clarification"}},
    ]
    train.write_text("".join(json.dumps(row) + "\n" for row in rows), "utf-8")
    return results, train


def _main(results: Path, train: Path, *flags: str) -> int:
    code: int = analysis.main(
        ["--results", str(results), "--train", str(train), *flags]
    )
    return code


def test_a_small_tree_is_written_checked_and_refused_once_changed(
    tmp_path: Path,
) -> None:
    results, train = _tree(tmp_path)

    assert _main(results, train) == 0
    assert _main(results, train, "--check") == 0
    output = results / "sft-v1" / "analysis.json"
    document = json.loads(output.read_text("utf-8"))
    assert document["summary"]["range"]["loud_ran"] == {"low": 2, "high": 2}
    counts = document["classes"]["rows"][0]["counts"]
    assert [counts[kind] for kind in ("missing_field", "unknown_field")] == [
        1,
        1,
    ]
    assert [counts[kind] for kind in ("truncated", "abstained")] == [1, 1]
    assert [case["stratum"] for case in document["proximity"]["cases"]] == [
        "same_atoms",
        "inside_one_target",
    ]
    assert document["seed_mean"] == {"C1": 1.0, "C2": 1.0, "C3": 1.0, "C4": 1.0}
    assert len(document["coverage"]) == 3
    output.write_bytes(output.read_bytes().replace(b'"items":4', b'"items":5'))
    assert _main(results, train, "--check") == 1


def test_rows_the_headline_does_not_hold_are_refused(tmp_path: Path) -> None:
    results, train = _tree(tmp_path)
    headline = results / "sft-v1" / "headline.json"
    document = json.loads(headline.read_text("utf-8"))
    document["mean"]["rate"]["value"] = 0.5
    headline.write_text(json.dumps(document), "utf-8")

    assert _main(results, train) == 2
    assert not (results / "sft-v1" / "analysis.json").exists()


def test_a_seed_that_answers_other_items_is_refused(tmp_path: Path) -> None:
    results, train = _tree(tmp_path)
    outcomes = results / SEED / "scored" / "outcomes.jsonl"
    lines = outcomes.read_text("utf-8").splitlines()
    outcomes.write_text("\n".join(lines[:-1]) + "\n", "utf-8")

    assert _main(results, train) == 2


def test_the_committed_analysis_is_its_rebuild() -> None:
    """The committed file is what the committed scores give."""
    output = analysis.RESULTS / analysis.OUTPUT
    if not output.is_file():
        pytest.skip("the test image carries no docs/ tree")

    assert analysis.main(["--check"]) == 0
    document = json.loads(output.read_text("utf-8"))
    # The page's opening sentence.
    assert document["summary"]["range"]["loud_ran"] == {"low": 32, "high": 35}
    assert document["summary"]["range"]["loud_silent"] == {
        "low": 17,
        "high": 18,
    }
