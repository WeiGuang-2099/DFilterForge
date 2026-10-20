"""The judge study's answer set, requests, verdict parser and table.

The committed-tree cases skip where the test image carries no docs/ tree.
The others read a small tree of two scored passes written from the real
contracts, with the module's pins, judge pass and counts patched to it.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

import pytest

from dfilterforge import judge
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import RetrievalV1
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1

_ROOT = Path(__file__).resolve().parents[1]
_RESULTS = _ROOT / "docs" / "results"
_NOTE = _ROOT / "docs" / "decisions" / "judge-study.md"
_NO_DOCS = "the test image carries no docs/ tree"
_OTHER = "dev-alpha-2026-09-26"
_OWN = "dev-judge-2026-09-26"
# Each scored row: its pass, condition, item, outcome, the filter that ran
# and the reference. Both passes wrote "tcp" for mei-0001, one request.
_ROWS: tuple[tuple[Any, ...], ...] = (
    (_OTHER, "C1", "mei-0001", "strong_exact", "tcp", "tcp"),
    (_OTHER, "C3", "mei-0002", "silent_wrong", "udp", "udp && dns"),
    (_OTHER, "C2", "mei-0003", "invalid", None, None),
    (_OWN, "C2", "mei-0001", "strong_exact", "tcp", "tcp"),
    (_OWN, "C4", "mei-0004", "silent_wrong", "dns", "dns && udp"),
)
_CONDITIONS = (
    ("C1", OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    ("C2", OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    ("C3", OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    ("C4", OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
)
# The note's counts: answers and silent-wrong ones per pass, the outcomes
# and the requests, two per distinct item and filter.
_REGISTERED: dict[judge.Split, Any] = {
    "test": (
        {
            "test-qwen3-32b-2026-09-26": (234, 49),
            "test-qwen3.5-9b-2026-09-26": (205, 51),
            "test-qwen3.5-122b-a10b-2026-09-26": (258, 38),
            "test-deepseek-v4-pro-0813-2026-09-26": (274, 27),
        },
        {"strong_exact": 804, "shortcut": 2, "silent_wrong": 165},
        1016,
    ),
    "dev": (
        {
            "dev-qwen3-32b-2026-09-26": (67, 17),
            "dev-qwen3.5-9b-2026-09-26": (61, 19),
            "dev-qwen3.5-122b-a10b-2026-09-26": (69, 12),
            "dev-deepseek-v4-pro-0813-2026-09-26": (87, 17),
        },
        {"strong_exact": 219, "silent_wrong": 65},
        282,
    ),
}


def _write_prompts(run_dir: Path) -> None:
    """Writes the four committed prompt files of one pass."""
    items = [
        GenerationInputV1(
            item_id=f"mei-000{number}",
            intent=f"Show the packets of request {number}.",
            user_assumptions=("Read the request at packet scope.",),
            split="dev",
        )
        for number in range(1, 5)
    ]
    lexical = [
        GenerationInputV1(
            item_id=item.item_id,
            intent=item.intent,
            user_assumptions=item.user_assumptions,
            retrieved_fields=(),
            split="dev",
        )
        for item in items
    ]
    for label, contract, retrieval in _CONDITIONS:
        shown = lexical if retrieval is RetrievalV1.LEXICAL else items
        batch = prepare_batch(
            shown, output_contract=contract, retrieval=retrieval
        )
        path = run_dir / "prepared" / f"{label}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(batch) + "\n", encoding="utf-8")


def _write_tree(results: Path) -> dict[str, str]:
    """Writes both scored passes; returns their outcome digests in order."""
    pins: dict[str, str] = {}
    for run in (_OTHER, _OWN):
        scored = results / run / "scored"
        scored.mkdir(parents=True)
        lines: list[str] = []
        for owner, label, item, outcome, ran, reference in _ROWS:
            if owner != run:
                continue
            row = ItemOutcomeV1(
                condition=label,
                item_id=item,
                case_id=f"case-{item}",
                outcome=OutcomeV1(outcome),
                candidate_filter=ran if label in ("C1", "C2") else None,
                gold_field_count=1,
                latency_ms=1.0,
            )
            lines.append(canonical_json(row) + "\n")
            if ran is not None:
                receipt = scored / "receipts" / label / f"{item}.json"
                receipt.parent.mkdir(parents=True, exist_ok=True)
                document: dict[str, object] = {
                    "run_id": run,
                    "candidate_filter": ran,
                    "reference_filter": reference,
                    "probes": [],
                }
                receipt.write_text(json.dumps(document), encoding="utf-8")
        (scored / "outcomes.jsonl").write_text("".join(lines), encoding="utf-8")
        _write_prompts(results / run)
        pins[run] = file_sha256(scored / "outcomes.jsonl")
    return pins


@pytest.fixture(name="tree")
def fixture_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The two passes, pinned as the dev answer set."""
    monkeypatch.setitem(judge.ANSWER_SETS, "dev", _write_tree(tmp_path))
    monkeypatch.setitem(judge.SELF_RUNS, "dev", _OWN)
    monkeypatch.setitem(judge.REGISTERED_COUNTS, "dev", (4, 3))
    return tmp_path


def _reply(request_id: str, text: str, finish: str = "stop") -> CompletionV1:
    return CompletionV1(
        item_id=request_id,
        status=CompletionStatusV1.COMPLETED,
        response_text=text,
        finish_reason=finish,
        latency_ms=1.0,
    )


def _says(verdict: str) -> str:
    return json.dumps({"reason": "One sentence.", "verdict": verdict})


def test_the_committed_answer_sets_are_the_registered_ones() -> None:
    """Pins, counts and the mean test prompt are the note's."""
    if not _NOTE.is_file():
        pytest.skip(_NO_DOCS)
    note = _NOTE.read_text(encoding="utf-8")
    prefixes = dict(
        re.findall(r"`((?:dev|test)-[a-z0-9.-]+)`[^`]*`([0-9a-f]{12})`", note)
    )
    for split, (runs, outcomes, requests) in _REGISTERED.items():
        built = judge.build_requests(_RESULTS, split)
        answers = built.answers
        silent = [a for a in answers if a.outcome is OutcomeV1.SILENT_WRONG]

        assert {run: prefixes[run] for run in runs} == {
            run: pin[:12] for run, pin in judge.ANSWER_SETS[split].items()
        }
        assert judge.SELF_RUNS[split] == list(runs)[-1]
        assert Counter(a.outcome.value for a in answers) == outcomes
        assert {
            run: (count, sum(a.run == run for a in silent))
            for run, count in Counter(a.run for a in answers).items()
        } == runs
        assert len(built.batch.prompts) == requests
    test = judge.build_requests(_RESULTS, "test").batch.prompts
    sizes = [sum(len(m.content.encode()) for m in p.messages) for p in test]
    assert round(sum(sizes) / len(sizes)) == 1315


def test_an_outcomes_file_that_breaks_its_pin_is_refused(tree: Path) -> None:
    """One changed byte in a pass's outcomes stops the build."""
    assert len(judge.build_requests(tree, "dev").answers) == 4
    path = tree / _OWN / "scored" / "outcomes.jsonl"
    path.write_bytes(path.read_bytes().replace(b"case-", b"Case-", 1))

    with pytest.raises(judge.JudgeError) as refused:
        judge.build_requests(tree, "dev")
    assert refused.value.code == "answer_set_changed"


def test_the_system_prompts_are_the_notes_fenced_blocks() -> None:
    """Both judge-v1 texts are the note's, byte for byte."""
    if not _NOTE.is_file():
        pytest.skip(_NO_DOCS)
    note = _NOTE.read_text(encoding="utf-8")
    blocks = re.findall(r"```text\n(.*?)\n```", note, flags=re.DOTALL)

    assert blocks == [judge.SYSTEM_PROMPTS[mode] for mode in judge.MODES]


@pytest.mark.parametrize("which", ["fixture", "committed"])
def test_only_the_secondary_mode_shows_the_reference_filter(
    which: str, request: pytest.FixtureRequest
) -> None:
    """A primary request shows the reference only inside the filter run.

    Its input holds the intent, the user assumptions and the filter that
    ran, and the reference filter appears nowhere else in the request; a
    secondary request also holds the receipt's reference filter, exactly.
    """
    splits: tuple[judge.Split, ...] = ("dev",)
    if which == "committed":
        if not _RESULTS.is_dir():
            pytest.skip(_NO_DOCS)
        results = _RESULTS
        splits = ("dev", "test")
    else:
        results = request.getfixturevalue("tree")
    for split in splits:
        built = judge.build_requests(results, split)
        prompts = {prompt.item_id: prompt for prompt in built.batch.prompts}
        for answer in built.answers:
            primary = prompts[answer.request_id("primary")].messages
            shown = json.loads(primary[1].content.removeprefix("INPUT_JSON\n"))
            texts = [primary[0].content, shown["intent"]]
            receipt = results / answer.receipt.removeprefix("docs/results/")
            secondary = prompts[answer.request_id("secondary")].messages
            judged = json.loads(
                secondary[1].content.removeprefix("INPUT_JSON\n")
            )

            assert set(shown) == {"intent", "user_assumptions", "filter"}
            assert shown["filter"] == answer.candidate_filter
            assert not any(
                answer.reference_filter in text
                for text in (*texts, *shown["user_assumptions"])
            )
            assert judged == shown | {
                "reference_filter": json.loads(receipt.read_text("utf-8"))[
                    "reference_filter"
                ]
            }


@pytest.mark.parametrize(
    ("text", "finish", "verdict"),
    [
        (_says("correct"), "stop", "correct"),
        ('{"verdict": "incorrect", "reason": "First."}', "stop", "incorrect"),
        ('{"verdict": "correct"}', "stop", None),
        ('{"reason": 7, "verdict": "correct"}', "stop", None),
        (_says("Correct"), "stop", None),
        (_says("partly"), "stop", None),
        ("correct", "stop", None),
        ('["correct"]', "stop", None),
        (
            '{"reason": "r", "verdict": "correct", "confidence": 1}',
            "stop",
            "correct",
        ),
        (
            json.dumps({"reason": "x" * 900, "verdict": "incorrect"}),
            "stop",
            "incorrect",
        ),
        (_says("correct"), "length", None),
        (
            '{"reason": "a", "verdict": "incorrect", "verdict": "correct"}',
            "stop",
            None,
        ),
        ('{"reason": 7, "reason": "a", "verdict": "correct"}', "stop", None),
    ],
)
def test_the_verdict_parser_takes_only_the_registered_reply(
    text: str, finish: str, verdict: str | None
) -> None:
    """A verdict needs a string reason; other keys and its length are free."""
    assert judge.parse_verdict(_reply("primary-x", text, finish)) == verdict


def test_a_failed_or_missing_reply_gives_no_verdict() -> None:
    """Only a completed reply is read."""
    failed = CompletionV1(
        item_id="primary-x",
        status=CompletionStatusV1.FAILED,
        error_code="http_error",
        http_status=429,
        latency_ms=1.0,
    )

    assert judge.parse_verdict(failed) is None
    assert judge.parse_verdict(None) is None


def test_the_table_counts_answers_and_lists_the_judge_apart(tree: Path) -> None:
    """A pair's verdict counts for each of its answers, its own pass apart.

    Primary: mei-0001 correct (both passes' answers), mei-0002 correct (a
    false acceptance), mei-0004 unanswered. Secondary: mei-0001 incorrect,
    mei-0002 a reply with no reason, mei-0004 correct (the judge's own).
    """
    built = judge.build_requests(tree, "dev")
    ids = {
        (a.item_id, mode): a.request_id(mode)
        for a in built.answers
        for mode in judge.MODES
    }
    texts = {
        ("mei-0001", "primary"): _says("correct"),
        ("mei-0002", "primary"): _says("correct"),
        ("mei-0001", "secondary"): _says("incorrect"),
        ("mei-0002", "secondary"): '{"verdict": "correct"}',
        ("mei-0004", "secondary"): _says("correct"),
    }
    replies = {ids[key]: _reply(ids[key], text) for key, text in texts.items()}
    table = judge.build_table(built, replies, {"b": "2", "a": "1"})
    primary, secondary = table["modes"]["primary"], table["modes"]["secondary"]
    none = {"correct": 0, "incorrect": 0, "none": 0}

    assert (table["answers"], table["requests_per_mode"]) == (4, 3)
    assert table["self_run"] == _OWN
    assert list(table["sources"]) == ["a", "b"]
    assert primary["overall"]["all"] == {
        "strong_exact": none | {"correct": 2},
        "shortcut": none,
        "silent_wrong": none | {"correct": 1, "none": 1},
    }
    assert primary["overall"]["self"]["strong_exact"] == none | {"correct": 1}
    assert primary["overall"]["self"]["silent_wrong"] == none | {"none": 1}
    assert primary["overall"]["others"]["silent_wrong"] == none | {"correct": 1}
    assert primary["conditions"]["C2"]["self"]["strong_exact"]["correct"] == 1
    assert primary["runs"][_OTHER]["strong_exact"]["correct"] == 1
    assert primary["headline"] == {
        "silent_wrong": 2,
        "silent_wrong_rated_correct": 1,
        "self_silent_wrong": 1,
        "self_silent_wrong_rated_correct": 0,
    }
    assert primary["silent_wrong_rated_correct"] == [
        {
            "run": _OTHER,
            "condition": "C3",
            "item_id": "mei-0002",
            "receipt": f"docs/results/{_OTHER}/scored/receipts/C3/mei-0002.json",
        }
    ]
    assert secondary["overall"]["all"]["strong_exact"] == none | {
        "incorrect": 2
    }
    assert secondary["overall"]["all"]["silent_wrong"] == none | {
        "correct": 1,
        "none": 1,
    }
    assert secondary["headline"]["self_silent_wrong_rated_correct"] == 1
    assert canonical_json(table) == canonical_json(
        judge.build_table(built, replies, {"a": "1", "b": "2"})
    )
