"""The web data exporter: sourced values, selection, asserts and exit status.

A fixture repository in tmp_path holds a bake-off ranking with five dev runs
(one with a dotted id), a bake-off ruling, the frame tables and the global
evidence, each file in the shape the committed ones take. A test that
registers test runs adds a test-runs/1.0 registry of 16 rows, its note's
Runs table and the test runs it publishes. A test resolver written apart
from the exporter re-derives every sourced value from those raw files. The
tests of the committed tree skip where the test image carries no docs/
tree; one of them repeats the registered dev Reel check on a copy of the
tree with the planned test runs registered again.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from dataclasses import field
import functools
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from types import ModuleType
from typing import Any, cast

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_web_data.py"
_DATE = "2026-01-01"
_LABELS = ("C1", "C2", "C3", "C4")
_TYPED = ("C3", "C4")
_FRAMES = 6
_BENCHMARK = 4
_PROBES = {
    "dev": ("semantic-11", "semantic-17", "semantic-23"),
    "test": ("semantic-31", "semantic-37", "semantic-43"),
}
_FEEDBACK = {"dev": "semantic-29", "test": "semantic-35"}
# Each split's cases: a ready case and a needs-clarification case, two
# items each, numbered from their split's block.
_CASES = {
    "dev": (("case-a", ("i-0001", "i-0002")), ("nc-b", ("i-0501", "i-0502"))),
    "test": (("case-t", ("i-1001", "i-1002")), ("nc-t", ("i-1501", "i-1502"))),
}
_READY = {"case-a", "case-t"}
_EXPECTED = ((2, 3), (1,), (4, 5))
_ANCHOR = f"dev-anchor-{_DATE}"
_SMALL = f"dev-small-{_DATE}"
_DOTTED = f"dev-small.b-{_DATE}"
_MID = f"dev-mid-{_DATE}"
_FRONT = f"dev-front-{_DATE}"
_PASS_A = f"test-anchor-{_DATE}"
_PASS_B = f"test-anchor-rerun-{_DATE}"
_TEST_SMALL = f"test-small-{_DATE}"
_TEST_MID = f"test-mid-{_DATE}"
_TEST_FRONT = f"test-front-{_DATE}"
# Beside the ranking, as the committed ruling is; the exporter reads it only
# through test-runs.json's "ruling" field.
_RULING = f"docs/decisions/evidence/bakeoff/ruling-{_DATE}.json"
_TEST_RUNS = "docs/decisions/evidence/test-runs.json"
# The planned rows of a test-runs/1.0 registry, in its order; every other
# row is a fallback or an outage re-run that names one.
_PLANNED = (
    ("aa_pass_a", _PASS_A),
    ("aa_pass_b", _PASS_B),
    ("winner_small", _TEST_SMALL),
    ("winner_mid", _TEST_MID),
    ("winner_frontier", _TEST_FRONT),
)
_ALLOWED = (
    "docs/results/",
    "docs/decisions/evidence/",
    "docs/ablations/evidence/",
)
_FREEZE = "src/dfilterforge/held_out_freeze.json"
# The contract for untrusted model text: a completion's response_text is cut
# at 4 KiB of UTF-8, and no other string is cut.
_RAW_TEXT_CAP = 4096
_RESPONSE_TEXT_FILE = re.compile(r"docs/results/[^/]+/completions/[^/]+\.json")
_RESPONSE_TEXT_POINTER = re.compile(
    r"/completions/(?:0|[1-9][0-9]*)/response_text"
)
_IMPORTS = {
    "__future__",
    "argparse",
    "collections",
    "dataclasses",
    "hashlib",
    "json",
    "pathlib",
    "re",
    "sys",
    "typing",
}
Document = dict[str, Any]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_web_data", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("export_web_data cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


exporter = _load()


def _ruling() -> Document:
    """A bakeoff-ruling/1.0 document in the committed ruling's shape.

    Its small winner is the dotted run, while the ranking's provisional
    small winner is the other one, so a dev pool that holds the dotted run
    took its winners from the ruling. The top-level ``winners`` holds model
    ids, as the committed ruling's does.
    """
    winners = {"small": _DOTTED, "mid": _MID, "frontier": _FRONT}
    return {
        "anchor": {"run_id": _ANCHOR},
        "date": _DATE,
        "ranking": f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json",
        "schema": "bakeoff-ruling/1.0",
        "slots": {
            slot: {"winner": {"model_id": f"m/{slot}", "run_id": run_id}}
            for slot, run_id in winners.items()
        },
        "winners": {slot: f"m/{slot}" for slot in winners},
    }


@dataclass(frozen=True)
class Answer:
    """One stored answer and how it scored.

    ``candidate`` holds the frames the answer selects on each scored probe;
    it is set only for an executed answer.
    """

    outcome: str
    candidate: tuple[tuple[int, ...], ...] | None = None
    error_code: str | None = None
    text: str = '{"status": "ready"}'


@dataclass
class Fixture:
    """Writes a repository in the shape of the committed evidence."""

    root: Path
    answers: dict[tuple[str, str, str], Answer] = field(
        default_factory=dict[tuple[str, str, str], Answer]
    )
    dev_runs: tuple[str, ...] = (_ANCHOR, _SMALL, _DOTTED, _MID, _FRONT)
    test_runs: tuple[str, ...] = ()
    registration: Document | None = None
    note: str = ""
    ruling: Document = field(default_factory=_ruling)

    def answer(self, run_id: str, label: str, item_id: str) -> Answer:
        """Returns a stored answer, by default exact or a clean abstention."""
        if (run_id, label, item_id) in self.answers:
            return self.answers[(run_id, label, item_id)]
        if _case_of(item_id) in _READY:
            return Answer("strong_exact", _EXPECTED)
        return Answer("abstained", text='{"status": "needs_clarification"}')

    def build(self) -> Path:
        """Writes every file and returns the repository root."""
        for run_id in self.dev_runs:
            self._run(run_id, "dev")
        for run_id in self.test_runs:
            self._run(run_id, "test")
        self._ranking()
        _write(self.root / _RULING, self.ruling)
        self._captures()
        _write(
            self.root / "docs/decisions/evidence/test-freeze-gate.json",
            {
                "categories": ["boundary", "subnet"],
                "counts": {
                    split: {
                        "executed": 9,
                        "killed": 8,
                        "survived": 1,
                        "waived": 1,
                    }
                    for split in ("dev", "test", "all")
                },
            },
        )
        _write(
            self.root / "docs/ablations/evidence/006-shortcut-policy.json",
            {
                "catalog": {"position_typed_fields": 7},
                "committed_answers": {"candidates": 3, "flagged": {"full": 0}},
                "gold": {"candidates": 5, "flagged": {"full": 0}},
            },
        )
        _write(self.root / _FREEZE, {"admitted_prepares": ["ab" * 32]})
        if self.registration is not None:
            _write(
                self.root / "docs/decisions/evidence/test-runs.json",
                self.registration,
            )
            note = self.root / "docs/decisions/test-runs.md"
            note.write_text(self.note, encoding="utf-8")
        return self.root

    def _ranking(self) -> None:
        def entry(run_id: str, rank: int) -> Document:
            return {
                "rank": rank,
                "run_id": run_id,
                "run_gates": "pass",
                "verdict": "passes the run gates",
                "strong_exact_ready": self._exact(run_id),
            }

        _write(
            self.root / f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json",
            {
                "anchor": {
                    "run_id": _ANCHOR,
                    "strong_exact_ready": self._exact(_ANCHOR),
                },
                "slots": {
                    # Listed out of rank order: the exporter sorts by rank.
                    "small": {
                        "candidates": [entry(_DOTTED, 2), entry(_SMALL, 1)],
                        "provisional_winner": _SMALL,
                    },
                    "mid": {
                        "candidates": [entry(_MID, 1)],
                        "provisional_winner": _MID,
                    },
                    "frontier": {
                        "candidates": [entry(_FRONT, 1)],
                        "provisional_winner": _FRONT,
                    },
                },
                "status": "provisional",
            },
        )
        # An older ranking that must lose to the lexicographically last.
        _write(
            self.root
            / "docs/decisions/evidence/bakeoff/ranking-2025-01-01.json",
            {"anchor": {"run_id": "dev-old-2025-01-01"}},
        )

    def _exact(self, run_id: str) -> int:
        return sum(
            1
            for label in _LABELS
            for case_id, items in _CASES["dev"]
            for item_id in items
            if case_id in _READY
            and self.answer(run_id, label, item_id).outcome == "strong_exact"
        )

    def _captures(self) -> None:
        rows: list[Document] = []
        for split in ("dev", "test"):
            for probe_id in (*_PROBES[split], _FEEDBACK[split]):
                rows.append(
                    {
                        "probe_id": probe_id,
                        "split": split,
                        "role": (
                            "feedback"
                            if probe_id == _FEEDBACK[split]
                            else "scored"
                        ),
                        "capture_sha256": _digest(probe_id),
                        "size_bytes": 100,
                        "benchmark_frames": _BENCHMARK,
                        "frames": [
                            {
                                "n": number,
                                "kind": (
                                    "recipe"
                                    if number <= _BENCHMARK
                                    else "witness"
                                ),
                                "name": f"recipe-{number}",
                            }
                            for number in range(1, _FRAMES + 1)
                        ],
                    }
                )
        _write(
            self.root / "docs/decisions/evidence/web/captures.json",
            {
                "notes": [],
                "probes": rows,
                "schema_version": "capture-frames/1.0",
            },
        )

    def _run(self, run_id: str, split: str) -> None:
        base = self.root / "docs/results" / run_id
        _write(
            base / "prepare.json",
            {
                "conditions": [
                    {
                        "label": label,
                        "output_contract": (
                            "typed_ir" if label in _TYPED else "display_filter"
                        ),
                        "path": f"prepared/{label}.json",
                        "retrieval": (
                            "lexical" if label in ("C2", "C4") else "none"
                        ),
                    }
                    for label in _LABELS
                ],
                "top_k": 4,
            },
        )
        items = [item for _, members in _CASES[split] for item in members]
        rows: list[Document] = []
        for label in _LABELS:
            _write(
                base / "prepared" / f"{label}.json",
                {
                    "prompts": [
                        {
                            "item_id": item_id,
                            "messages": [
                                {"content": "system", "role": "system"},
                                {
                                    "content": "INPUT_JSON\n"
                                    + json.dumps(
                                        {"intent": f"Request for {item_id}."}
                                    ),
                                    "role": "user",
                                },
                            ],
                        }
                        for item_id in items
                    ]
                },
            )
            _write(
                base / "completions" / f"{label}.json",
                {
                    "completions": [
                        {
                            "finish_reason": "stop",
                            "item_id": item_id,
                            "provider": "Provider",
                            "response_model": "vendor/model",
                            "response_text": self.answer(
                                run_id, label, item_id
                            ).text,
                        }
                        for item_id in items
                    ]
                },
            )
            for item_id in items:
                rows.append(self._item(base, run_id, label, item_id))
        (base / "scored").mkdir(parents=True, exist_ok=True)
        (base / "scored/outcomes.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8"
        )
        _write(base / "scored/summary.json", _summary(run_id, split, rows))
        _write(
            base / "scored/score_manifest.json",
            {
                "environment": {
                    "executable_sha256": "e" * 64,
                    "identity_scope": "binary-and-runner-source",
                    "runner_source_sha256": "f" * 64,
                    "tshark_version": "4.6.8",
                    "unmeasured": ["container_image_digest"],
                },
                "environment_hash": "a" * 64,
            },
        )
        for case_id, _ in _CASES[split]:
            _write(base / f"scored/specs/{case_id}.json", _spec(case_id, split))

    def _item(
        self, base: Path, run_id: str, label: str, item_id: str
    ) -> Document:
        answer = self.answer(run_id, label, item_id)
        case_id = _case_of(item_id)
        ready = case_id in _READY
        executed = answer.outcome in (
            "strong_exact",
            "shortcut",
            "silent_wrong",
        )
        if executed:
            assert answer.candidate is not None
            _write(
                base / f"scored/receipts/{label}/{item_id}.json",
                _receipt(run_id, base.name, item_id, answer.candidate),
            )
        if label in _TYPED and answer.outcome in (
            "false_ready",
            "invalid",
            "strong_exact",
            "shortcut",
            "silent_wrong",
        ):
            _write(
                base / f"scored/intents/{label}/{item_id}.json",
                {
                    "expression": {
                        "children": [
                            {"field": "dns.aaaa", "kind": "predicate"},
                            {
                                "children": [
                                    {"field": "ip.ttl", "kind": "predicate"}
                                ],
                                "kind": "not",
                            },
                        ],
                        "kind": "any",
                    },
                    "scope": "packet",
                },
            )
        abstained = answer.outcome == "abstained"
        return {
            "abstention_status": "needs_clarification" if abstained else None,
            "case_id": case_id,
            "condition": label,
            "error_code": answer.error_code,
            "gold_status": "ready" if ready else "needs_clarification",
            "item_id": item_id,
            "latency_ms": 1234.5,
            "outcome": answer.outcome,
            "packet_set_hash": _digest(f"{run_id}{label}{item_id}")
            if executed
            else None,
            "slot_match": None if ready or not abstained else True,
            "status_match": None if ready or not abstained else True,
        }


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")


def _edit(path: Path, edit: Callable[[Any], None]) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    edit(value)
    _write(path, value)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _case_of(item_id: str) -> str:
    for cases in _CASES.values():
        for case_id, items in cases:
            if item_id in items:
                return case_id
    raise KeyError(item_id)


def _spec(case_id: str, split: str) -> Document:
    if case_id not in _READY:
        return {
            "case_id": case_id,
            "missing_slots": ["port"],
            "rationale": "The port is never given.",
            "split": split,
            "status": "needs_clarification",
        }
    return {
        "canonical_ir": {
            "expression": {
                "children": [
                    {"field": "dns.qry.type", "kind": "predicate"},
                    {"field": "dns.flags.rcode", "kind": "predicate"},
                ],
                "kind": "any",
            }
        },
        "intent": "Show the gold request.",
        "probes": [
            {
                "capture_sha256": _digest(probe_id),
                "expected_frames": list(expected),
                "probe_id": probe_id,
            }
            for probe_id, expected in zip(_PROBES[split], _EXPECTED)
        ],
        "reference_filter": "dns.qry.type == 28 || dns.flags.rcode == 3",
        "split": split,
        "status": "ready",
        "task_id": case_id,
    }


def _receipt(
    run_id: str,
    directory: str,
    item_id: str,
    candidate: tuple[tuple[int, ...], ...],
) -> Document:
    split = "test" if directory.startswith("test-") else "dev"
    probes: list[Document] = []
    for probe_id, expected, chosen in zip(_PROBES[split], _EXPECTED, candidate):
        probes.append(
            {
                "candidate_frames": sorted(chosen),
                "candidate_only": sorted(set(chosen) - set(expected)),
                "exact": set(chosen) == set(expected),
                "expected_frames": list(expected),
                "probe_id": probe_id,
                "reference_only": sorted(set(expected) - set(chosen)),
                "runtime_ms": 60.25,
            }
        )
    return {
        "candidate_filter": f"filter for {item_id}",
        "code_revision": "1234abc",
        "created_at": "2026-01-01T00:00:00Z",
        "data_hash": "d" * 64,
        "environment_hash": "a" * 64,
        "model_hash": "m" * 64,
        "probes": probes,
        "prompt_hash": "p" * 64,
        "reference_filter": "dns.qry.type == 28",
        "run_id": run_id,
    }


def _summary(run_id: str, split: str, rows: list[Document]) -> Document:
    conditions: Document = {}
    for label in _LABELS:
        ready = [
            item["outcome"]
            for item in rows
            if item["condition"] == label and item["gold_status"] == "ready"
        ]

        def rate(outcome: str, outcomes: list[str] = ready) -> Document:
            value = round(outcomes.count(outcome) / len(outcomes), 6)
            return {"high": 1.0, "low": 0.0, "value": value}

        conditions[label] = {
            "compile_valid": rate("strong_exact"),
            "false_ready": rate("false_ready"),
            "over_abstention": rate("abstained"),
            "silent_wrong_all": rate("silent_wrong"),
            "silent_wrong_of_executable": None,
            "slot_match": {"high": 1.0, "low": 1.0, "value": 1.0},
            "strong_exact": rate("strong_exact"),
        }
    return {
        "bootstrap": {
            "cases": 1,
            "min_discordant_cases": 10,
            "non_ready_cases": 1,
            "resamples": 1000,
            "seed": 17,
        },
        "charged_usd_upper_bound": 0.02,
        "comparisons": [
            {
                "difference": {"high": 0.5, "low": -0.5, "value": 0.0},
                "discordant_cases": 0,
                "first": "C4",
                "first_better_cases": 0,
                "inconclusive": True,
                "metric": "strong_exact",
                "second": "C2",
                "second_better_cases": 0,
            }
        ],
        "conditions": conditions,
        "effective_settings": {"providers": ["Provider"]},
        "item_count": len(rows),
        "model_id": f"vendor/{run_id}",
        "not_measured": {"repair_at_1": "not_run"},
        "provider_reported_usd": 0.01,
        "run": run_id,
        "split": split,
    }


def _wrong(*candidate: tuple[int, ...]) -> Answer:
    return Answer("silent_wrong", candidate)


@pytest.fixture(name="fixture")
def fixture_fixture(tmp_path: Path) -> Fixture:
    return Fixture(tmp_path / "repo")


def _documents(files: dict[str, bytes]) -> dict[str, Document]:
    return {name: json.loads(data) for name, data in files.items()}


class Resolver:
    """Re-derives sourced values from raw files, apart from the exporter."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._json: dict[str, Any] = {}
        self._jsonl: dict[str, list[Document]] = {}
        self._rows: dict[
            tuple[str, tuple[str, ...]], dict[tuple[Any, ...], list[Document]]
        ] = {}

    def _path(self, path: str) -> Path:
        assert ".." not in path.split("/") and "\\" not in path
        assert path == _FREEZE or path.startswith(_ALLOWED), path
        literal = self.root.resolve().joinpath(*path.split("/"))
        # No component may be a link, inside the repository or out of it.
        assert literal.resolve() == literal, path
        return literal

    def json(self, path: str) -> Any:
        if path not in self._json:
            self._json[path] = json.loads(
                self._path(path).read_text(encoding="utf-8")
            )
        return self._json[path]

    def jsonl(self, path: str) -> list[Document]:
        if path not in self._jsonl:
            text = self._path(path).read_text(encoding="utf-8")
            self._jsonl[path] = [
                json.loads(line) for line in text.splitlines() if line
            ]
        return self._jsonl[path]

    @staticmethod
    def at(document: Any, pointer: str) -> Any:
        value: Any = document
        if pointer == "":
            return value
        assert pointer.startswith("/")
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, list):
                value = cast(list[Any], value)[int(token)]
            else:
                value = cast(dict[str, Any], value)[token]
        return value

    def resolve(self, src: list[Any]) -> Any:
        op, *rest = src
        if op == "ptr":
            return self.at(self.json(rest[0]), rest[1])
        if op == "row":
            path, keys, pointer = rest
            names = tuple(sorted(keys))
            if (path, names) not in self._rows:
                index: dict[tuple[Any, ...], list[Document]] = {}
                for item in self.jsonl(path):
                    found = tuple(item.get(name) for name in names)
                    index.setdefault(found, []).append(item)
                self._rows[(path, names)] = index
            matches = self._rows[(path, names)].get(
                tuple(keys[name] for name in names), []
            )
            assert len(matches) == 1
            return self.at(matches[0], pointer)
        if op == "count":
            path, pointer, where = rest
            items = (
                self.jsonl(path)
                if pointer is None
                else self.at(self.json(path), pointer)
            )
            return sum(
                all(item.get(key) in values for key, values in where.items())
                for item in items
            )
        if op == "len":
            return len(self.at(self.json(rest[0]), rest[1]))
        if op == "sum":
            return sum(self.resolve(item) for item in rest[0])
        if op == "sha256":
            return hashlib.sha256(self._path(rest[0]).read_bytes()).hexdigest()
        assert op == "input", op
        path, item_id, pointer = rest
        (prompt,) = [
            item
            for item in self.json(path)["prompts"]
            if item["item_id"] == item_id
        ]
        content: str = prompt["messages"][1]["content"]
        assert content.startswith("INPUT_JSON\n")
        return self.at(json.loads(content[len("INPUT_JSON\n") :]), pointer)


def _nodes(value: Any) -> Iterator[Document]:
    if isinstance(value, dict):
        members = cast(Document, value)
        if "src" in members:
            yield members
            return
        for item in members.values():
            yield from _nodes(item)
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            yield from _nodes(item)


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, list) and isinstance(right, list):
        lefts = cast(list[Any], left)
        rights = cast(list[Any], right)
        return len(lefts) == len(rights) and all(
            _same(a, b) for a, b in zip(lefts, rights)
        )
    return type(cast(object, left)) is type(cast(object, right)) and (
        left == right
    )


def _capped(text: str, limit: int) -> str:
    data = text.encode("utf-8")
    while len(data) > limit:
        text = text[:-1]
        data = text.encode("utf-8")
    return text


def _is_response_text(src: Any) -> bool:
    """Says whether a source names a completion's response_text."""
    if not isinstance(src, list):
        return False
    op = cast(list[object], src)
    return (
        len(op) == 3
        and op[0] == "ptr"
        and _RESPONSE_TEXT_FILE.fullmatch(str(op[1])) is not None
        and _RESPONSE_TEXT_POINTER.fullmatch(str(op[2])) is not None
    )


def check_sources(root: Path, documents: dict[str, Document]) -> int:
    """Asserts every sourced node equals its source; returns the count.

    The cut of model text is the contract's, never the node's own: a model
    answer must carry exactly ``_RAW_TEXT_CAP`` and nothing else a cap.
    """
    resolver = Resolver(root)
    checked = 0
    for name, document in documents.items():
        for node in _nodes(document):
            expected = resolver.resolve(node["src"])
            answer = _is_response_text(node["src"])
            assert node.get("cap") == (_RAW_TEXT_CAP if answer else None), (
                name,
                node["src"],
            )
            if "t" in node:
                if answer:
                    expected = _capped(expected, _RAW_TEXT_CAP)
                assert isinstance(node["t"], str), (name, node)
                assert node["t"] == expected, (name, node["src"])
            else:
                assert _same(node["v"], expected), (name, node, expected)
            checked += 1
    return checked


def _digits_in_commands(value: Any, key: str = "") -> Iterator[str]:
    """Yields literal command text holding a digit, outside sourced nodes."""
    if isinstance(value, dict):
        members = cast(Document, value)
        if "src" in members:
            return
        for name, item in members.items():
            yield from _digits_in_commands(item, name)
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            yield from _digits_in_commands(item, key)
    elif isinstance(value, str) and key == "replay":
        if any(character.isdigit() for character in value):
            yield value


def test_export_is_deterministic_compact_and_sorted(fixture: Fixture) -> None:
    root = fixture.build()

    first = exporter.export(root, "abc1234")
    second = exporter.export(root, "abc1234")

    assert first == second
    for name, data in first.items():
        assert data.endswith(b"\n") and not data.endswith(b"\n\n"), name
        document = json.loads(data)
        assert data == (
            json.dumps(
                document,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    assert json.loads(first["site.json"])["source_commit"] == "abc1234"


def test_every_sourced_value_resolves_from_the_raw_files(
    fixture: Fixture,
) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = _wrong((2,), (1,), (4, 5, 6))
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    assert check_sources(root, documents) > 1000
    for name, document in documents.items():
        assert not list(_digits_in_commands(document)), name


def test_shown_runs_follow_the_last_ranking_with_dot_free_slugs(
    fixture: Fixture,
) -> None:
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    site = documents["site.json"]
    assert [run["run_id"] for run in site["runs"]] == [
        _ANCHOR,
        _SMALL,
        _DOTTED,
        _MID,
        _FRONT,
    ]
    assert [run["role"] for run in site["runs"]] == [
        "anchor",
        "small",
        "small",
        "mid",
        "frontier",
    ]
    assert site["runs"][2]["slug"] == "dev-small_b-2026-01-01"
    assert [run["pool"] for run in site["runs"]] == [
        True,
        True,
        False,
        True,
        True,
    ]
    assert site["phase"] == {
        "aa": False,
        "dev": True,
        "repair": False,
        "test": False,
        "training": False,
    }
    assert not any("2025" in item["path"] for item in site["inputs"])
    assert [item["path"] for item in site["inputs"]] == sorted(
        item["path"] for item in site["inputs"]
    )
    routes = documents["routes.json"]
    assert routes["cases"] == [{"case": "case-a"}, {"case": "nc-b"}]
    # Each run executes both ready items in all four conditions.
    assert len(routes["receipts"]) == 5 * 4 * 2
    assert {
        "run": "dev-small_b-2026-01-01",
        "cond": "C4",
        "item": "i-0002",
    } in (routes["receipts"])
    receipts = {name for name in documents if name.startswith("receipts/")}
    assert receipts == {
        f"receipts/{item['run']}/{item['cond']}/{item['item']}.json"
        for item in routes["receipts"]
    }


def test_dev_board_shows_counts_in_ranking_order_with_no_interval(
    fixture: Fixture,
) -> None:
    fixture.answers[(_MID, "C2", "i-0002")] = Answer(
        "invalid", error_code="filter_unknown_field"
    )
    root = fixture.build()

    board = _documents(exporter.export(root, "abc1234"))["board.json"]

    assert board["test"] is None and board["test_registered"] is False
    rows = board["selection"]["rows"]
    assert [item["slot"] for item in rows] == [
        "anchor",
        "small",
        "small",
        "mid",
        "frontier",
    ]
    assert rows[0]["rank"] is None and rows[0]["verdict"] is None
    assert [item["rank"]["v"] for item in rows[1:3]] == [1, 2]
    mid = rows[3]
    assert mid["ready"]["v"] == 8
    assert mid["segments"]["strong_exact"]["v"] == 7
    assert mid["segments"]["invalid"]["v"] == 1
    assert mid["strong_exact_ready"]["v"] == 7
    text = json.dumps(board)
    for word in ("low", "high", "comparison", "interval", "value"):
        assert f'"{word}' not in text


def test_case_and_receipt_carry_gold_answers_and_frame_states(
    fixture: Fixture,
) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0002")] = _wrong((2,), (1,), (4, 5, 6))
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    receipt = documents["receipts/dev-anchor-2026-01-01/C4/i-0002.json"]
    assert (receipt["run"], receipt["cond"], receipt["item"]) == (
        "dev-anchor-2026-01-01",
        "C4",
        "i-0002",
    )
    assert receipt["run_id"]["t"] == _ANCHOR
    assert receipt["outcome"]["t"] == "silent_wrong"
    assert receipt["request"]["t"] == "Request for i-0002."
    assert [node["t"] for node in receipt["answer"]["fields"]] == [
        "dns.aaaa",
        "ip.ttl",
    ]
    assert receipt["probes"][0]["states"] == [
        "tn",
        "tp",
        "fn",
        "tn",
        "tn",
        "tn",
    ]
    assert receipt["probes"][2]["states"] == [
        "tn",
        "tn",
        "tn",
        "tp",
        "tp",
        "fp",
    ]
    assert [
        (item["side"], item["n"]["v"], item["kind"]["t"])
        for probe in receipt["probes"]
        for item in probe["disagree"]
    ] == [("reference_only", 3, "recipe"), ("candidate_only", 6, "witness")]
    assert receipt["trace"] is None and receipt["trace_reason"] == "not_traced"
    replay = receipt["replay"]
    assert replay[1]["t"] == _ANCHOR and replay[3]["t"] == "1234abc"
    assert (
        documents["receipts/dev-anchor-2026-01-01/C1/i-0002.json"]["answer"][
            "fields"
        ]
        is None
    )
    case = documents["cases/case-a.json"]
    assert [item["run"] for item in case["runs"]][2] == "dev-small_b-2026-01-01"
    assert case["reference_filter"]["t"].startswith("dns.qry.type")
    assert [node["t"] for node in case["canonical_fields"]] == [
        "dns.qry.type",
        "dns.flags.rcode",
    ]
    assert [item["item"] for item in case["paraphrases"]] == [
        "i-0001",
        "i-0002",
    ]
    assert len(case["runs"]) == 5
    assert len(case["runs"][0]["cells"]) == 8
    assert case["probes"][0]["expected"][1]["name"]["t"] == "recipe-3"
    other = documents["cases/nc-b.json"]
    assert other["probes"] == [] and other["intent"] is None
    assert [node["t"] for node in other["missing_slots"]] == ["port"]
    cell = other["runs"][0]["cells"][0]
    assert cell["receipt"] is False
    assert cell["abstention_status"]["t"] == "needs_clarification"
    assert cell["slot_match"]["v"] is True


def test_methodology_sources_the_protocol_constants(fixture: Fixture) -> None:
    root = fixture.build()

    methodology = _documents(exporter.export(root, "abc1234"))[
        "methodology.json"
    ]

    assert [item["label"]["t"] for item in methodology["conditions"]] == list(
        _LABELS
    )
    assert methodology["witnesses"]["count"]["v"] == _FRAMES - _BENCHMARK
    assert [node["t"] for node in methodology["witnesses"]["names"]] == [
        "recipe-5",
        "recipe-6",
    ]
    assert len(methodology["probes"]) == 8
    assert methodology["mutants"]["all"]["killed"]["v"] == 8
    assert methodology["not_measured"][0]["key"] == "repair_at_1"


def test_a_long_answer_is_capped_at_a_character_boundary(
    fixture: Fixture,
) -> None:
    text = "a" * 4095 + "\u00e9" + "tail"
    fixture.answers[(_ANCHOR, "C1", "i-0001")] = Answer(
        "strong_exact", _EXPECTED, text=text
    )
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    raw = documents["receipts/dev-anchor-2026-01-01/C1/i-0001.json"]
    assert raw["raw_truncated"] is True
    assert raw["raw"]["t"] == "a" * 4095 and raw["raw"]["cap"] == 4096
    check_sources(root, documents)
    assert exporter.cap_text("\u00e9" * 3, 5) == "\u00e9\u00e9"


def test_the_source_check_holds_a_cap_to_the_contract(
    fixture: Fixture,
) -> None:
    # A node's own cap is never trusted: a cut that agrees with it must
    # still fail when it is not the contract's.
    root = fixture.build()
    exported = _documents(exporter.export(root, "abc1234"))
    name = "receipts/dev-anchor-2026-01-01/C1/i-0001.json"
    check_sources(root, {name: exported[name]})

    def broken(change: Callable[[Document], None]) -> Document:
        receipt: Document = json.loads(json.dumps(exported[name]))
        change(receipt)
        return receipt

    def short_cut(receipt: Document) -> None:
        receipt["raw"] = {
            **receipt["raw"],
            "t": receipt["raw"]["t"][:1],
            "cap": 1,
        }

    def uncapped(receipt: Document) -> None:
        del receipt["raw"]["cap"]

    def capped_label(receipt: Document) -> None:
        label = next(
            node
            for node in _nodes(receipt)
            if "t" in node and not _is_response_text(node["src"])
        )
        label["cap"] = _RAW_TEXT_CAP

    for change in (short_cut, uncapped, capped_label):
        with pytest.raises(AssertionError):
            check_sources(root, {name: broken(change)})


def _tag(run_id: str, tag: str) -> str:
    """Names a fallback (fb) or an outage re-run (r2) as test-runs.md does."""
    return f"{run_id.removesuffix(f'-{_DATE}')}-{tag}-{_DATE}"


def _row(
    role: str,
    run_id: str,
    status: str,
    trigger: str | None = None,
    conditional_on: str | None = None,
    reason: str | None = None,
) -> Document:
    """One test-runs/1.0 row, with the fields the exporter reads."""
    return {
        "conditional_on": conditional_on,
        "reason": reason,
        "role": role,
        "run_id": run_id,
        "status": status,
        "trigger": trigger,
    }


def _registration() -> Document:
    """A test-runs/1.0 registry in the committed shape, 16 rows.

    The five planned rows are published. Each winner's fallback is an
    unused gate_stop row, and each planned and fallback row has an unused
    outage re-run. Every unused row names a published or unused run, so the
    registry is final once the five planned runs are scored.
    """
    planned = [_row(role, run_id, "published") for role, run_id in _PLANNED]
    fallbacks = [
        _row(
            role.replace("winner_", "fallback_"),
            _tag(run_id, "fb"),
            "unused",
            "gate_stop",
            run_id,
        )
        for role, run_id in _PLANNED[2:]
    ]
    reruns = [
        _row(
            item["role"],
            _tag(item["run_id"], "r2"),
            "unused",
            "outage",
            item["run_id"],
        )
        for item in planned + fallbacks
    ]
    return {
        "note": "docs/decisions/test-runs.md",
        "ruling": _RULING,
        "runs": planned + fallbacks + reruns,
        "schema": "test-runs/1.0",
    }


def _at(registration: Document, run_id: str) -> Document:
    """The one registry row of a run."""
    (found,) = [
        item for item in registration["runs"] if item["run_id"] == run_id
    ]
    return found


def _stop(registration: Document, run_id: str, reason: str) -> None:
    """Rules a run not_run with a reason, as the owner records a stop.

    Every unused row that names it gets a reason too: without one, the
    frozen-prompt guard still waits for that row, and so does the test
    phase.
    """
    for item in registration["runs"]:
        if item["run_id"] == run_id:
            item.update(status="not_run", reason=reason)
        elif item["conditional_on"] == run_id and item["status"] == "unused":
            item["reason"] = f"{run_id} ended by {reason}; not sent"


def _publish(registration: Document, run_id: str) -> None:
    _at(registration, run_id).update(status="published", reason=None)


def _note(
    runs: list[Document] | None = None, prose: str = "", start: int = 1
) -> str:
    """Renders test-runs.md: prose, the Runs table, then a numbered table.

    The Runs table lists the given registry rows, by default all 16 of
    ``_registration()``, in the committed note's column order, numbered
    from ``start``.
    """
    listed = _registration()["runs"] if runs is None else runs
    return "\n".join(
        [
            "# Hosted test runs",
            "",
            prose,
            "",
            "| # | Role | Run id | Model id | Runs |",
            "| --- | --- | --- | --- | --- |",
            *(
                f"| {number} | `{run['role']}` | `{run['run_id']}` | `m/m` |"
                " always |"
                for number, run in enumerate(listed, start=start)
            ),
            "",
            "| Exit | Meaning |",
            "| --- | --- |",
            "| 0 | Every row has a final state: `done`. |",
            "",
        ]
    )


def _register(
    fixture: Fixture, registration: Document, *test_runs: str
) -> None:
    """Commits a registry, its note's Runs table and the given test runs."""
    fixture.registration = registration
    fixture.note = _note(registration["runs"])
    fixture.test_runs = test_runs


def test_test_rows_appear_only_when_every_registered_run_is_final(
    fixture: Fixture,
) -> None:
    registration = _registration()
    _at(registration, _TEST_FRONT)["status"] = "registered"
    _register(fixture, registration, _PASS_A, _PASS_B, _TEST_SMALL, _TEST_MID)
    root = fixture.build()

    partial = _documents(exporter.export(root, "abc1234"))

    assert partial["board.json"]["test"] is None
    assert partial["board.json"]["test_registered"] is True
    assert partial["site.json"]["phase"]["test"] is False
    assert not any(
        item["run"].startswith("test-")
        for item in partial["routes.json"]["receipts"]
    )
    # The ruling the registration names gives the winners even before the
    # test phase: its small winner, not the ranking's provisional one.
    assert [
        run["run_id"] for run in partial["site.json"]["runs"] if run["pool"]
    ] == [_ANCHOR, _DOTTED, _MID, _FRONT]

    _publish(registration, _TEST_FRONT)
    fixture.test_runs += (_TEST_FRONT,)
    fixture.build()
    documents = _documents(exporter.export(root, "abc1234"))

    board = documents["board.json"]
    assert [
        (item["role"], item["run_id"]["t"]) for item in board["test"]["rows"]
    ] == [item for item in _PLANNED if item[0] != "aa_pass_b"]
    assert board["test"]["rerun"]["run_id"]["t"] == _PASS_B
    assert board["test"]["not_run"] == []
    first = board["test"]["rows"][0]
    metric = first["conditions"][3]["metrics"]["strong_exact"]
    assert metric["value"]["src"] == [
        "ptr",
        f"docs/results/{_PASS_A}/scored/summary.json",
        "/conditions/C4/strong_exact/value",
    ]
    assert (
        first["conditions"][0]["metrics"]["silent_wrong_of_executable"] is None
    )
    assert first["comparisons"][0]["inconclusive"]["v"] is True
    assert documents["site.json"]["phase"]["test"] is True
    assert {"case": "case-t"} in documents["routes.json"]["cases"]
    check_sources(root, documents)


def test_the_test_phase_board_rows_are_the_pool_and_pass_b_is_the_rerun(
    fixture: Fixture,
) -> None:
    _register(fixture, _registration(), *(run for _, run in _PLANNED))
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    # locked-test-v1.md: pass A is the counted pass, and pass B serves only
    # as its rerun, so the rows are the Reel's pool and never pass B.
    test = documents["board.json"]["test"]
    assert [item["role"] for item in test["rows"]] == [
        "aa_pass_a",
        "winner_small",
        "winner_mid",
        "winner_frontier",
    ]
    assert [item["run_id"]["t"] for item in test["rows"]] == [
        item["run_id"]["t"] for item in documents["reel.json"]["pool"]
    ]
    rerun = test["rerun"]
    assert (rerun["role"], rerun["run_id"]["t"]) == ("aa_pass_b", _PASS_B)
    summary = f"docs/results/{_PASS_B}/scored/summary.json"
    comparisons = list(_nodes(rerun["comparisons"]))
    assert comparisons and all(
        node["src"][:2] == ["ptr", summary]
        and node["src"][2].startswith("/comparisons/0/")
        for node in comparisons
    )
    assert test["not_run"] == []
    # Pass B is still a shown run, with its receipts.
    assert _PASS_B in [run["run_id"] for run in documents["site.json"]["runs"]]
    assert any(
        item["run"] == _PASS_B for item in documents["routes.json"]["receipts"]
    )
    check_sources(root, documents)


def test_a_not_run_pass_b_leaves_the_board_no_rerun(fixture: Fixture) -> None:
    registration = _registration()
    _stop(registration, _PASS_B, "outage")
    _register(
        fixture, registration, _PASS_A, _TEST_SMALL, _TEST_MID, _TEST_FRONT
    )
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    test = documents["board.json"]["test"]
    assert [item["role"] for item in test["rows"]] == [
        "aa_pass_a",
        "winner_small",
        "winner_mid",
        "winner_frontier",
    ]
    assert test["rerun"] is None
    assert test["not_run"] == [
        {
            "role": "aa_pass_b",
            "run_id": {
                "t": _PASS_B,
                "src": ["ptr", _TEST_RUNS, "/runs/1/run_id"],
            },
            "reason": {
                "t": "outage",
                "src": ["ptr", _TEST_RUNS, "/runs/1/reason"],
            },
        }
    ]
    check_sources(root, {"board.json": documents["board.json"]})


def test_a_published_run_without_a_summary_keeps_the_test_phase_off(
    fixture: Fixture,
) -> None:
    _register(fixture, _registration(), *(run for _, run in _PLANNED))
    root = fixture.build()
    # Published but not scored yet, as test-runs.md allowed before the
    # repair-cards merge: the phase waits, and nothing is wrong.
    shutil.rmtree(root / f"docs/results/{_TEST_MID}/scored")

    documents = _documents(exporter.export(root, "abc1234"))

    assert documents["board.json"]["test"] is None
    assert documents["board.json"]["test_registered"] is True
    assert documents["site.json"]["phase"]["test"] is False
    assert documents["reel.json"]["phase"] == "dev"
    assert not any(
        item["run"].startswith("test-")
        for item in documents["routes.json"]["receipts"]
    )


def test_an_unused_row_whose_named_run_is_not_run_waits_for_a_reason(
    fixture: Fixture,
) -> None:
    registration = _registration()
    _at(registration, _TEST_FRONT).update(status="not_run", reason="outage")
    _register(fixture, registration, _PASS_A, _PASS_B, _TEST_SMALL, _TEST_MID)
    root = fixture.build()
    path = root / _TEST_RUNS

    def phase() -> bool:
        site = json.loads(exporter.export(root, "abc1234")["site.json"])
        return site["phase"]["test"]

    assert phase() is False
    _edit(
        path,
        lambda value: _at(value, _tag(_TEST_FRONT, "fb")).update(
            reason="an outage is no gate stop"
        ),
    )
    # The frontier re-run still names a not_run run and gives no reason.
    assert phase() is False
    _edit(
        path,
        lambda value: _at(value, _tag(_TEST_FRONT, "r2")).update(
            reason="the owner ruled the re-run not sent"
        ),
    )
    documents = _documents(exporter.export(root, "abc1234"))

    assert documents["site.json"]["phase"]["test"] is True
    assert [item["role"] for item in documents["reel.json"]["pool"]] == [
        "aa_pass_a",
        "winner_small",
        "winner_mid",
    ]
    assert documents["board.json"]["test"]["not_run"] == [
        {
            "role": "winner_frontier",
            "run_id": {
                "t": _TEST_FRONT,
                "src": ["ptr", _TEST_RUNS, "/runs/4/run_id"],
            },
            "reason": {
                "t": "outage",
                "src": ["ptr", _TEST_RUNS, "/runs/4/reason"],
            },
        }
    ]
    check_sources(root, documents)


def test_a_published_fallback_fills_its_slot(fixture: Fixture) -> None:
    fallback = _tag(_TEST_SMALL, "fb")
    registration = _registration()
    _stop(registration, _TEST_SMALL, "gate stop")
    _publish(registration, fallback)
    _register(
        fixture,
        registration,
        _PASS_A,
        _PASS_B,
        fallback,
        _TEST_MID,
        _TEST_FRONT,
    )
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    pool = documents["reel.json"]["pool"]
    assert [item["role"] for item in pool] == [
        "aa_pass_a",
        "fallback_small",
        "winner_mid",
        "winner_frontier",
    ]
    assert pool[1]["run_id"]["t"] == fallback
    pooled = {
        run["run_id"]: run["pool"] for run in documents["site.json"]["runs"]
    }
    assert pooled[fallback] is True and pooled[_PASS_B] is False
    assert [
        item["run_id"]["t"]
        for item in documents["board.json"]["test"]["not_run"]
    ] == [_TEST_SMALL]


def test_a_published_outage_rerun_keeps_its_role(fixture: Fixture) -> None:
    rerun = _tag(_TEST_MID, "r2")
    registration = _registration()
    _stop(registration, _TEST_MID, "outage")
    _publish(registration, rerun)
    _register(
        fixture, registration, _PASS_A, _PASS_B, _TEST_SMALL, rerun, _TEST_FRONT
    )
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    mid = documents["reel.json"]["pool"][2]
    assert (mid["role"], mid["run_id"]["t"]) == ("winner_mid", rerun)
    assert [
        (item["role"], item["run_id"]["t"])
        for item in documents["board.json"]["test"]["not_run"]
    ] == [("winner_mid", _TEST_MID)]
    check_sources(root, {"board.json": documents["board.json"]})


def test_not_run_rows_are_listed_in_role_order(fixture: Fixture) -> None:
    fallback = _tag(_TEST_SMALL, "fb")
    registration = _registration()
    _stop(registration, _TEST_SMALL, "gate stop")
    _stop(registration, fallback, "outage")
    _stop(registration, _TEST_MID, "outage")
    _register(fixture, registration, _PASS_A, _PASS_B, _TEST_FRONT)
    root = fixture.build()

    documents = _documents(exporter.export(root, "abc1234"))

    # In registry order the small fallback, row 6, would follow winner_mid,
    # row 4; role order keeps it beside its winner.
    assert documents["site.json"]["phase"]["test"] is True
    assert [
        (item["role"], item["run_id"]["t"])
        for item in documents["board.json"]["test"]["not_run"]
    ] == [
        ("winner_small", _TEST_SMALL),
        ("fallback_small", fallback),
        ("winner_mid", _TEST_MID),
    ]
    check_sources(root, {"board.json": documents["board.json"]})


def test_a_registry_of_another_schema_exits_two(
    fixture: Fixture, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registration = _registration()
    registration["schema"] = "test-runs/0.9"
    _register(fixture, registration)
    root = fixture.build()

    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "schema_invalid"
    status = exporter.main(
        [
            "--repo",
            str(root),
            "--out",
            str(tmp_path / "out"),
            "--source-commit",
            "abc1234",
        ]
    )

    assert status == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == (
        "schema_invalid"
    )


def _unknown_role(value: Document, _: Path) -> None:
    _at(value, _TEST_MID)["role"] = "winner_huge"


def _mid_and_its_rerun_published(value: Document, _: Path) -> None:
    # A run and the re-run naming it cannot both be published under the
    # condition rule, so here the re-run names a stopped pass B: only the
    # one-per-slot rule refuses the second published mid row.
    _stop(value, _PASS_B, "gate stop")
    _publish(value, _tag(_TEST_MID, "r2"))
    _at(value, _tag(_TEST_MID, "r2"))["conditional_on"] = _PASS_B


def _rerun_and_fallback_published(value: Document, _: Path) -> None:
    _stop(value, _TEST_MID, "outage")
    _publish(value, _tag(_TEST_MID, "r2"))
    _publish(value, _tag(_TEST_MID, "fb"))


def _unknown_status(value: Document, _: Path) -> None:
    _at(value, _TEST_MID)["status"] = "done"


def _repeated_run_id(value: Document, _: Path) -> None:
    _at(value, _TEST_FRONT)["run_id"] = _TEST_MID


def _dev_run_id(value: Document, _: Path) -> None:
    _at(value, _PASS_A)["run_id"] = _ANCHOR


def _malformed_run_id(value: Document, _: Path) -> None:
    _at(value, _PASS_A)["run_id"] = f"test-Bad_X-{_DATE}"


def _not_run_without_a_reason(value: Document, _: Path) -> None:
    _at(value, _TEST_MID)["status"] = "not_run"


def _not_run_with_an_empty_reason(value: Document, _: Path) -> None:
    _at(value, _TEST_MID).update(status="not_run", reason="")


def _dangling_condition(value: Document, _: Path) -> None:
    _at(value, _tag(_TEST_MID, "fb"))["conditional_on"] = f"test-x-{_DATE}"


def _trigger_without_a_named_run(value: Document, _: Path) -> None:
    _at(value, _tag(_TEST_MID, "fb"))["conditional_on"] = None


def _unknown_trigger(value: Document, _: Path) -> None:
    _at(value, _tag(_TEST_MID, "fb"))["trigger"] = "owner_wish"


def _self_named_row(value: Document, _: Path) -> None:
    # A row that names itself would count as final once unused, since the
    # run it names is then not not_run.
    fallback = _tag(_TEST_MID, "fb")
    _at(value, fallback)["conditional_on"] = fallback


def _planned_row_unused(value: Document, _: Path) -> None:
    _at(value, _TEST_MID)["status"] = "unused"


def _fallback_beside_its_published_winner(value: Document, _: Path) -> None:
    _at(value, _tag(_TEST_SMALL, "fb")).update(
        status="not_run", reason="outage"
    )


def _no_mid_winner(value: Document, _: Path) -> None:
    # Drops winner_mid and every row its condition chain reaches, so only
    # the planned roles are wrong.
    dropped = {_TEST_MID}
    for item in value["runs"]:
        if item["conditional_on"] in dropped:
            dropped.add(item["run_id"])
    value["runs"] = [
        item for item in value["runs"] if item["run_id"] not in dropped
    ]


def _planned_rows_out_of_order(value: Document, _: Path) -> None:
    runs = value["runs"]
    runs[2], runs[3] = runs[3], runs[2]


def _scored_not_run(value: Document, root: Path) -> None:
    _stop(value, _TEST_MID, "outage")
    _write(
        root / f"docs/results/{_TEST_MID}/scored/summary.json",
        {"run": _TEST_MID},
    )


def _unused_with_a_manifest(_: Document, root: Path) -> None:
    _write(
        root / f"docs/results/{_tag(_TEST_MID, 'fb')}/run_manifest.json",
        {"run_id": _tag(_TEST_MID, "fb")},
    )


def _registered_with_a_manifest(value: Document, root: Path) -> None:
    # Results committed while the row still says registered: the phase
    # would stay dev and hide the test runs with no error.
    _at(value, _TEST_MID)["status"] = "registered"
    _write(
        root / f"docs/results/{_TEST_MID}/run_manifest.json",
        {"run_id": _TEST_MID},
    )


def _another_note(value: Document, _: Path) -> None:
    value["note"] = "docs/decisions/model-bakeoff.md"


@pytest.mark.parametrize(
    ("edit", "code", "named"),
    [
        (_unknown_role, "role_invalid", "'winner_huge'"),
        (_mid_and_its_rerun_published, "role_invalid", _tag(_TEST_MID, "r2")),
        (_rerun_and_fallback_published, "role_invalid", _tag(_TEST_MID, "fb")),
        (_unknown_status, "status_invalid", "'done'"),
        (_repeated_run_id, "run_repeated", f"row 5 repeats {_TEST_MID}"),
        (_dev_run_id, "split_mismatch", _ANCHOR),
        (_malformed_run_id, "run_id_invalid", "test-Bad_X"),
        (_not_run_without_a_reason, "not_run_invalid", _TEST_MID),
        (
            _not_run_with_an_empty_reason,
            "not_run_invalid",
            f"{_TEST_MID} is not_run with no reason",
        ),
        (_dangling_condition, "condition_invalid", f"test-x-{_DATE}"),
        (
            _trigger_without_a_named_run,
            "condition_invalid",
            _tag(_TEST_MID, "fb"),
        ),
        (_unknown_trigger, "condition_invalid", "the trigger 'owner_wish'"),
        (
            _self_named_row,
            "condition_invalid",
            f"names {_tag(_TEST_MID, 'fb')}, which is no other row",
        ),
        (_planned_row_unused, "condition_invalid", _TEST_MID),
        (
            _fallback_beside_its_published_winner,
            "condition_invalid",
            f"{_TEST_SMALL} is published",
        ),
        (_no_mid_winner, "role_missing", "winner_small, winner_frontier,"),
        (
            _planned_rows_out_of_order,
            "role_missing",
            "winner_mid, winner_small",
        ),
        (_scored_not_run, "not_run_scored", f"{_TEST_MID} holds scored/"),
        (
            _unused_with_a_manifest,
            "not_run_scored",
            f"{_tag(_TEST_MID, 'fb')} holds run_manifest.json",
        ),
        (
            _registered_with_a_manifest,
            "not_run_scored",
            f"{_TEST_MID} holds run_manifest.json, but its row in "
            f"{_TEST_RUNS} is registered",
        ),
        (_another_note, "note_mismatch", "note"),
    ],
)
def test_a_broken_registration_fails(
    fixture: Fixture,
    edit: Callable[[Document, Path], None],
    code: str,
    named: str,
) -> None:
    registration = _registration()
    edit(registration, fixture.root)
    # The note lists the edited rows, so only the edit can fail.
    _register(fixture, registration)
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == code
    assert named in str(caught.value)


def _ruling_schema(_: Document, ruling: Document) -> None:
    ruling["schema"] = "bakeoff-ruling/0.9"


def _slot_without_winner(_: Document, ruling: Document) -> None:
    del ruling["slots"]["mid"]["winner"]


def _test_winner(_: Document, ruling: Document) -> None:
    ruling["slots"]["small"]["winner"]["run_id"] = _TEST_SMALL


def _unshown_winner(_: Document, ruling: Document) -> None:
    ruling["slots"]["small"]["winner"]["run_id"] = f"dev-x-{_DATE}"


def _ruling_outside_the_roots(registration: Document, _: Document) -> None:
    registration["ruling"] = "docs/decisions/model-bakeoff.md"


@pytest.mark.parametrize(
    ("edit", "code", "status"),
    [
        (_ruling_schema, "schema_invalid", 2),
        (_slot_without_winner, "schema_invalid", 2),
        (_test_winner, "split_mismatch", 1),
        (_unshown_winner, "pool_unshown", 1),
        (_ruling_outside_the_roots, "path_refused", 2),
    ],
)
def test_a_broken_ruling_fails(
    fixture: Fixture,
    edit: Callable[[Document, Document], None],
    code: str,
    status: int,
) -> None:
    registration = _registration()
    edit(registration, fixture.ruling)
    fixture.registration = registration
    fixture.note = _note()
    root = fixture.build()

    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == code
    assert caught.value.exit_status == status
    # The refusal names the ruling the registry names.
    assert registration["ruling"] in str(caught.value)


def test_a_run_missing_from_the_registry_note_fails(fixture: Fixture) -> None:
    fixture.registration = _registration()
    fixture.note = _note().replace(_TEST_MID, f"{_TEST_MID}x")
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "run_unregistered"


def _without_a_row(runs: list[Document]) -> str:
    return _note([*runs[:3], *runs[4:]])


def _with_two_rows_swapped(runs: list[Document]) -> str:
    return _note([*runs[:2], runs[3], runs[2], *runs[4:]])


def _with_another_role(runs: list[Document]) -> str:
    return _note([*runs[:3], runs[3] | {"role": "small"}, *runs[4:]])


def _with_pass_a_only_in_prose(runs: list[Document]) -> str:
    return _note(runs[1:], prose=f"Pass A's run id is `{_PASS_A}`.")


def _numbered_from_zero(runs: list[Document]) -> str:
    # The right rows in the right order, under numbers the registry lacks.
    return _note(runs, start=0)


def _with_an_extra_row(runs: list[Document]) -> str:
    # A 17th row would register a run test-runs.json does not hold.
    return _note([*runs, runs[-1] | {"run_id": f"test-extra-{_DATE}"}])


@pytest.mark.parametrize(
    ("note", "row"),
    [
        (_without_a_row, 4),
        (_with_two_rows_swapped, 3),
        (_with_another_role, 4),
        (_with_pass_a_only_in_prose, 1),
        (_numbered_from_zero, 1),
        (_with_an_extra_row, 17),
    ],
)
def test_a_note_that_differs_from_the_registry_fails(
    fixture: Fixture, note: Callable[[list[Document]], str], row: int
) -> None:
    registration = _registration()
    fixture.registration = registration
    fixture.note = note(registration["runs"])
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "run_unregistered"
    assert f"Runs row {row} " in str(caught.value)


def _drop_receipt(root: Path) -> None:
    (root / f"docs/results/{_MID}/scored/receipts/C1/i-0001.json").unlink()


def _extra_receipt(root: Path) -> None:
    source = root / f"docs/results/{_MID}/scored/receipts/C1/i-0001.json"
    target = source.with_name("i-0501.json")
    target.write_bytes(source.read_bytes())


def _drop_intent(root: Path) -> None:
    (root / f"docs/results/{_MID}/scored/intents/C4/i-0001.json").unlink()


def _rewrite_rows(root: Path, edit: Callable[[Document], None]) -> None:
    path = root / f"docs/results/{_MID}/scored/outcomes.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for item in rows:
        edit(item)
    path.write_text("".join(json.dumps(item) + "\n" for item in rows))


def _third_item(root: Path) -> None:
    def edit(item: Document) -> None:
        if item["item_id"] == "i-0501":
            item["case_id"] = "case-a"

    _rewrite_rows(root, edit)


def _ready_false_ready(root: Path) -> None:
    # A ready gold item scored false_ready belongs to no segment; the
    # receipt, the summary and the ranking are kept consistent with it.
    def edit(item: Document) -> None:
        if item["item_id"] == "i-0001" and item["condition"] == "C1":
            item["outcome"] = "false_ready"

    _rewrite_rows(root, edit)
    _drop_receipt(root)
    _edit(
        root / f"docs/results/{_MID}/scored/summary.json",
        lambda value: value["conditions"]["C1"]["strong_exact"].update(
            value=0.5
        ),
    )
    _edit(
        root / f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json",
        lambda value: value["slots"]["mid"]["candidates"][0].update(
            strong_exact_ready=7
        ),
    )


def _ranking_count(root: Path) -> None:
    _edit(
        root / f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json",
        lambda value: value["slots"]["mid"]["candidates"][0].update(
            strong_exact_ready=3
        ),
    )


def _summary_mean(root: Path) -> None:
    _edit(
        root / f"docs/results/{_MID}/scored/summary.json",
        lambda value: value["conditions"]["C2"]["strong_exact"].update(
            value=0.5
        ),
    )


def _bad_run_id(root: Path) -> None:
    _edit(
        root / f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json",
        lambda value: value["slots"]["mid"]["candidates"][0].update(
            run_id="dev-Mid_X-2026-01-01"
        ),
    )


def _listed_twice(root: Path) -> None:
    def edit(value: Document) -> None:
        value["slots"]["mid"]["candidates"].append(
            {**value["slots"]["mid"]["candidates"][0], "rank": 2}
        )

    _edit(root / f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json", edit)


def _receipt_frames(root: Path) -> None:
    _edit(
        root / f"docs/results/{_MID}/scored/receipts/C1/i-0001.json",
        lambda value: value["probes"][0].update(reference_only=[3]),
    )


def _spec_drift(root: Path) -> None:
    _edit(
        root / f"docs/results/{_MID}/scored/specs/case-a.json",
        lambda value: value.update(intent="Another request."),
    )


def _summary_run(root: Path) -> None:
    _edit(
        root / f"docs/results/{_MID}/scored/summary.json",
        lambda value: value.update(run=_FRONT),
    )


def _stale_trace(root: Path) -> None:
    _write(
        root / f"docs/decisions/evidence/web/traces/{_MID}/C1/i-0001.json",
        {
            "receipt_file_sha256": "0" * 64,
            "receipt_path": f"docs/results/{_MID}/scored/receipts/C1/i-0001.json",
            "result": {},
        },
    )


def _mid(root: Path, relative: str) -> Path:
    return root / f"docs/results/{_MID}/{relative}"


def _ranking_path(root: Path) -> Path:
    return root / f"docs/decisions/evidence/bakeoff/ranking-{_DATE}.json"


def _unnumbered_frames(root: Path) -> None:
    _edit(
        root / "docs/decisions/evidence/web/captures.json",
        lambda value: value["probes"][0]["frames"][2].update(n=9),
    )


def _unknown_probe(root: Path) -> None:
    _edit(
        _mid(root, "scored/receipts/C1/i-0001.json"),
        lambda value: value["probes"][0].update(probe_id="semantic-99"),
    )


def _frame_out_of_range(root: Path) -> None:
    def edit(value: Document) -> None:
        value["probes"][0]["candidate_frames"] = [2, 3, 9]
        value["probes"][0]["candidate_only"] = [9]

    _edit(_mid(root, "scored/receipts/C1/i-0001.json"), edit)


def _repeated_condition(root: Path) -> None:
    _edit(
        _mid(root, "prepare.json"),
        lambda value: value["conditions"][1].update(label="C1"),
    )


def _rows(root: Path) -> list[Document]:
    text = _mid(root, "scored/outcomes.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _put_rows(root: Path, rows: list[Document]) -> None:
    _mid(root, "scored/outcomes.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8"
    )


def _row_twice(root: Path) -> None:
    rows = _rows(root)
    _put_rows(root, rows + rows[:1])


def _row_dropped(root: Path) -> None:
    _put_rows(
        root,
        [
            item
            for item in _rows(root)
            if (item["condition"], item["item_id"]) != ("C4", "i-0501")
        ],
    )


def _two_cases(root: Path) -> None:
    def edit(item: Document) -> None:
        if (item["condition"], item["item_id"]) == ("C3", "i-0502"):
            item["case_id"] = "case-a"

    _rewrite_rows(root, edit)


def _dotted_case(root: Path) -> None:
    def edit(item: Document) -> None:
        if item["case_id"] == "nc-b":
            item["case_id"] = "nc.b"

    _rewrite_rows(root, edit)


def _completion_twice(root: Path) -> None:
    _edit(
        _mid(root, "completions/C2.json"),
        lambda value: value["completions"].append(value["completions"][0]),
    )


def _completion_dropped(root: Path) -> None:
    _edit(
        _mid(root, "completions/C2.json"),
        lambda value: value["completions"].pop(),
    )


def _rank_repeated(root: Path) -> None:
    _edit(
        _ranking_path(root),
        lambda value: value["slots"]["small"]["candidates"][0].update(rank=1),
    )


def _test_run_ranked(root: Path) -> None:
    _edit(
        _ranking_path(root),
        lambda value: value["slots"]["mid"]["candidates"][0].update(
            run_id=f"test-mid-{_DATE}"
        ),
    )


def _winner_not_ranked(root: Path) -> None:
    _edit(
        _ranking_path(root),
        lambda value: value["slots"]["mid"].update(
            provisional_winner=f"dev-other-{_DATE}"
        ),
    )


def _receipt_run(root: Path) -> None:
    _edit(
        _mid(root, "scored/receipts/C1/i-0001.json"),
        lambda value: value.update(run_id=_FRONT),
    )


def _spec_names_other(root: Path) -> None:
    for run_id in (_ANCHOR, _SMALL, _DOTTED, _MID, _FRONT):
        _edit(
            root / f"docs/results/{run_id}/scored/specs/case-a.json",
            lambda value: value.update(task_id="case-z"),
        )


def _summary_split(root: Path) -> None:
    _edit(
        _mid(root, "scored/summary.json"),
        lambda value: value.update(split="test"),
    )


def _prompt_twice(root: Path) -> None:
    _edit(
        _mid(root, "prepared/C1.json"),
        lambda value: value["prompts"].append(value["prompts"][0]),
    )


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (_drop_receipt, "receipts_mismatch"),
        (_extra_receipt, "receipts_mismatch"),
        (_drop_intent, "intents_mismatch"),
        (_third_item, "case_items"),
        (_ready_false_ready, "segments_mismatch"),
        (_ranking_count, "ranking_mismatch"),
        (_summary_mean, "mean_mismatch"),
        (_bad_run_id, "run_id_invalid"),
        (_listed_twice, "slug_collision"),
        (_receipt_frames, "receipt_inconsistent"),
        (_spec_drift, "spec_mismatch"),
        (_summary_run, "run_mismatch"),
        (_stale_trace, "trace_stale"),
        (_unnumbered_frames, "frames_unnumbered"),
        (_unknown_probe, "probe_unknown"),
        (_frame_out_of_range, "frame_out_of_range"),
        (_repeated_condition, "condition_repeated"),
        (_row_twice, "row_unexpected"),
        (_row_dropped, "row_missing"),
        (_two_cases, "case_mismatch"),
        (_dotted_case, "route_unsafe"),
        (_completion_twice, "completion_repeated"),
        (_completion_dropped, "completion_missing"),
        (_rank_repeated, "rank_repeated"),
        (_test_run_ranked, "split_mismatch"),
        (_winner_not_ranked, "pool_unshown"),
        (_receipt_run, "receipt_inconsistent"),
        (_spec_names_other, "spec_mismatch"),
        (_prompt_twice, "prompt_not_unique"),
        (_summary_split, "split_mismatch"),
    ],
)
def test_each_contract_assert_fails_alone(
    fixture: Fixture, damage: Callable[[Path], None], code: str
) -> None:
    root = fixture.build()
    exporter.export(root, "abc1234")

    damage(root)

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == code


def _no_input_json(root: Path) -> None:
    _edit(
        _mid(root, "prepared/C1.json"),
        lambda value: value["prompts"][0]["messages"][1].update(content="{}"),
    )


def _lone_surrogate_answer(root: Path) -> None:
    _edit(
        _mid(root, "completions/C1.json"),
        lambda value: value["completions"][0].update(
            response_text="bad \ud800 text"
        ),
    )


def _lone_surrogate_request(root: Path) -> None:
    def edit(value: Document) -> None:
        value["prompts"][0]["messages"][1]["content"] = (
            "INPUT_JSON\n" + json.dumps({"intent": "bad \ud800"})
        )

    _edit(_mid(root, "prepared/C1.json"), edit)


def _bad_condition_path(root: Path) -> None:
    _edit(
        _mid(root, "prepare.json"),
        lambda value: value["conditions"][0].update(path="../C1.json"),
    )


def _string_count(root: Path) -> None:
    _edit(
        _mid(root, "scored/summary.json"),
        lambda value: value.update(item_count="many"),
    )


def _string_rank(root: Path) -> None:
    _edit(
        _ranking_path(root),
        lambda value: value["slots"]["mid"]["candidates"][0].update(rank="1"),
    )


def _object_candidates(root: Path) -> None:
    _edit(
        _ranking_path(root),
        lambda value: value["slots"]["mid"].update(candidates={}),
    )


def _number_label(root: Path) -> None:
    _edit(
        _mid(root, "prepare.json"),
        lambda value: value["conditions"][0].update(label=1),
    )


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (_no_input_json, "schema_invalid"),
        (_lone_surrogate_answer, "schema_invalid"),
        (_lone_surrogate_request, "schema_invalid"),
        (_bad_condition_path, "schema_invalid"),
        (_string_count, "schema_invalid"),
        (_string_rank, "schema_invalid"),
        (_object_candidates, "schema_invalid"),
        (_number_label, "schema_invalid"),
    ],
)
def test_each_unreadable_shape_exits_two(
    fixture: Fixture, damage: Callable[[Path], None], code: str
) -> None:
    root = fixture.build()

    damage(root)

    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == code
    assert caught.value.exit_status == 2


def test_no_executed_answer_leaves_no_receipt_route(fixture: Fixture) -> None:
    for run_id in fixture.dev_runs:
        for label in _LABELS:
            for item_id in ("i-0001", "i-0002"):
                fixture.answers[(run_id, label, item_id)] = Answer(
                    "abstained", text='{"status": "not_expressible"}'
                )
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "routes_empty"


def test_a_row_lookup_must_match_exactly_one_row(fixture: Fixture) -> None:
    root = fixture.build()
    repo = exporter.Repo(root)
    path = f"docs/results/{_MID}/scored/outcomes.jsonl"

    with pytest.raises(exporter.ContractError) as caught:
        repo.find_row(path, {"condition": "C1"})
    assert caught.value.code == "row_not_unique"
    assert (
        repo.find_row(path, {"condition": "C1", "item_id": "i-0001"})["outcome"]
        == "strong_exact"
    )


@pytest.mark.skipif(
    sys.platform == "win32", reason="Symbolic links need privileges here"
)
def test_links_out_of_the_tree_are_refused(
    fixture: Fixture, tmp_path: Path
) -> None:
    root = fixture.build()
    outside = tmp_path / "outside"
    outside.mkdir()
    receipts = _mid(root, "scored/receipts/C1")
    target = outside / "i-0001.json"
    target.write_bytes((receipts / "i-0001.json").read_bytes())
    (receipts / "i-0001.json").unlink()
    (receipts / "i-0001.json").symlink_to(target)

    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "input_invalid"

    (receipts / "i-0001.json").unlink()
    (receipts / "i-0001.json").write_bytes(target.read_bytes())
    linked = _mid(root, "scored/intents")
    linked.rename(outside / "intents")
    linked.symlink_to(outside / "intents", target_is_directory=True)

    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "path_refused"


@pytest.mark.skipif(
    sys.platform == "win32", reason="Symbolic links need privileges here"
)
def test_links_inside_the_tree_are_refused_too(fixture: Fixture) -> None:
    # A link from an allowed root to a folder that is not one would publish
    # that folder's bytes under the allowed path.
    root = fixture.build()
    private = root / "private"
    private.mkdir()
    (private / "secret.json").write_text('{"token": "x"}\n', encoding="utf-8")
    linked = root / "docs" / "results" / "dev-x-2026-09-26"
    linked.symlink_to(Path("..", "..", "private"), target_is_directory=True)
    repo = exporter.Repo(root)

    with pytest.raises(exporter.ExportError) as caught:
        repo.resolve(["ptr", "docs/results/dev-x-2026-09-26/secret.json", ""])
    assert caught.value.code == "path_refused"
    assert not repo.inputs

    linked.unlink()
    intents = _mid(root, "scored/intents")
    moved = root / "artifacts" / "intents"
    moved.parent.mkdir()
    intents.rename(moved)
    intents.symlink_to(
        Path("..", "..", "..", "..", "artifacts", "intents"),
        target_is_directory=True,
    )
    assert intents.resolve() == moved.resolve()

    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "path_refused"


def test_an_unwritable_output_exits_two(
    fixture: Fixture, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = fixture.build()
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")

    status = exporter.main(
        [
            "--repo",
            str(root),
            "--out",
            str(blocker / "data"),
            "--source-commit",
            "abc1234",
        ]
    )

    assert status == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "io_error"


def test_a_trace_is_linked_only_to_its_receipt_bytes(fixture: Fixture) -> None:
    root = fixture.build()
    receipt = f"docs/results/{_MID}/scored/receipts/C1/i-0001.json"
    trace = f"docs/decisions/evidence/web/traces/{_MID}/C1/i-0001.json"
    limited = f"docs/decisions/evidence/web/traces/{_MID}/C1/i-0002.json"
    _write(
        root / trace,
        {
            "receipt_file_sha256": hashlib.sha256(
                (root / receipt).read_bytes()
            ).hexdigest(),
            "receipt_path": receipt,
            "result": {"exact": False},
        },
    )
    other = receipt.replace("i-0001", "i-0002")
    _write(
        root / limited,
        {
            "receipt_file_sha256": hashlib.sha256(
                (root / other).read_bytes()
            ).hexdigest(),
            "receipt_path": other,
            "result": {"status": "trace_limit"},
        },
    )

    documents = _documents(exporter.export(root, "abc1234"))

    linked = documents["receipts/dev-mid-2026-01-01/C1/i-0001.json"]
    assert linked["trace"]["path"] == trace and linked["trace_reason"] is None
    capped = documents["receipts/dev-mid-2026-01-01/C1/i-0002.json"]
    assert capped["trace"] is None and capped["trace_reason"] == "trace_limit"
    check_sources(root, documents)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/docs/results/a.json",
        "docs/results/../src/x.json",
        "docs/results/./a.json",
        "docs/results//a.json",
        "docs\\results\\a.json",
        "C:/docs/results/a.json",
        "docs/decisions/model-bakeoff.md",
        "docs/decisions/test-runs.md",
        "src/dfilterforge/model_split.py",
        "docs/resultsx/a.json",
    ],
)
def test_paths_outside_the_roots_are_refused(path: str) -> None:
    with pytest.raises(exporter.ExportError) as caught:
        exporter.check_path(path)
    assert caught.value.code == "path_refused"


def test_allowed_paths_pass() -> None:
    for path in (
        "docs/results/dev-a-2026-01-01/prepare.json",
        "docs/decisions/evidence/web/captures.json",
        "docs/ablations/evidence/006-shortcut-policy.json",
        _FREEZE,
    ):
        assert exporter.check_path(path) == path


def test_a_source_op_outside_the_contract_is_refused(fixture: Fixture) -> None:
    repo = exporter.Repo(fixture.build())

    for src, code in (
        (["eval", "docs/results/x.json"], "source_invalid"),
        (["ptr", "src/dfilterforge/cli.py", ""], "path_refused"),
        (
            ["ptr", "docs/decisions/evidence/web/captures.json", "/nope"],
            ("pointer_invalid"),
        ),
        (
            ["ptr", "docs/decisions/evidence/web/captures.json", "probes"],
            ("pointer_invalid"),
        ),
        (
            ["ptr", "docs/decisions/evidence/web/captures.json", "/probes/01"],
            "pointer_invalid",
        ),
        (
            ["ptr", "docs/decisions/evidence/web/captures.json", "/probes/99"],
            "pointer_invalid",
        ),
        (
            ["ptr", "docs/decisions/evidence/web/captures.json", "/notes/0/x"],
            "pointer_invalid",
        ),
    ):
        with pytest.raises(exporter.ExportError) as caught:
            repo.resolve(src)
        assert caught.value.code == code, src


def test_pointer_escapes_round_trip() -> None:
    document = {"a/b": {"c~d": [10, 20]}}

    path = exporter.pointer("a/b", "c~d", 1)

    assert path == "/a~1b/c~0d/1"
    assert exporter.pointer_get(document, path) == 20
    assert exporter.pointer_get(document, "") is document


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b'{"probes": NaN}', "schema_invalid"),
        (b'{"probes": [], "probes": []}', "schema_invalid"),
        (b"\xff\xfe", "schema_invalid"),
        (b"{", "schema_invalid"),
        (b"[]", "schema_invalid"),
    ],
)
def test_an_unreadable_input_exits_two(
    fixture: Fixture,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: bytes,
    code: str,
) -> None:
    root = fixture.build()
    (root / "docs/decisions/evidence/web/captures.json").write_bytes(content)

    status = exporter.main(
        [
            "--repo",
            str(root),
            "--out",
            str(tmp_path / "out"),
            "--source-commit",
            "abc1234",
        ]
    )

    assert status == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == code
    assert not (tmp_path / "out").exists()


def test_missing_and_oversized_inputs_exit_two(
    fixture: Fixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = fixture.build()
    arguments = ["--repo", str(root), "--source-commit", "abc1234", "--out"]

    monkeypatch.setattr(exporter, "MAX_INPUT_BYTES", 64)
    assert exporter.main([*arguments, str(tmp_path / "a")]) == 2
    monkeypatch.undo()
    (root / _FREEZE).unlink()
    assert exporter.main([*arguments, str(tmp_path / "b")]) == 2
    for name in (root / "docs/decisions/evidence/bakeoff").iterdir():
        name.unlink()
    with pytest.raises(exporter.ExportError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "ranking_missing"


def test_the_command_writes_once_and_refuses_a_non_empty_output(
    fixture: Fixture,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = fixture.build()
    out = tmp_path / "data"
    arguments = [
        "--repo",
        str(root),
        "--out",
        str(out),
        "--source-commit",
        "abc1234",
    ]

    assert exporter.main(arguments) == 0
    printed = json.loads(capsys.readouterr().out)
    written = sorted(
        path.relative_to(out).as_posix()
        for path in out.rglob("*")
        if path.is_file()
    )
    assert printed["files"] == len(written) and printed["receipts"] == 40
    assert printed["cases"] == 2
    assert printed["bytes"] == sum(
        (out / name).stat().st_size for name in written
    )
    assert exporter.main(arguments) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == (
        "output_exists"
    )


@pytest.mark.parametrize("commit", ["", "-rf", "a b", "x" * 65, "abc;rm"])
def test_an_unsafe_source_commit_exits_two(
    fixture: Fixture, tmp_path: Path, commit: str
) -> None:
    root = fixture.build()

    status = exporter.main(
        [
            "--repo",
            str(root),
            "--out",
            str(tmp_path / "out"),
            f"--source-commit={commit}",
        ]
    )

    assert status == 2


def test_a_contract_failure_exits_one_with_the_envelope(
    fixture: Fixture, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = fixture.build()
    _drop_receipt(root)

    status = exporter.main(
        [
            "--repo",
            str(root),
            "--out",
            str(tmp_path / "out"),
            "--source-commit",
            "abc1234",
        ]
    )

    assert status == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert error["code"] == "receipts_mismatch"
    assert not (tmp_path / "out").exists()


def test_the_exporter_imports_only_the_allowed_standard_library() -> None:
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {
                "__import__",
                "compile",
                "eval",
                "exec",
                "open",
            }, node.func.id

    assert imported <= _IMPORTS, imported - _IMPORTS
    assert "dfilterforge" not in imported


def _reel(root: Path) -> Document:
    return json.loads(exporter.export(root, "abc1234")["reel.json"])


def _picked(reel: Document) -> tuple[str, str, str]:
    pick = reel["pick"]
    return pick["run_id"]["t"], pick["cond"], pick["item"]


def _choice(reel: Document) -> Document:
    """The parts of a Reel that reel-v1's steps 1 to 4 decide."""
    return {
        "candidates": reel["candidates"],
        "condition": reel["candidate_condition"],
        "highlight": reel["highlight"],
        "pick": reel["pick"],
        "pool": reel["pool"],
        "states": [strip["states"] for strip in reel["strips"]],
    }


def test_reel_picks_the_fewest_disagreeing_frames(fixture: Fixture) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = _wrong((2,), (1,), (4,))
    fixture.answers[(_SMALL, "C4", "i-0002")] = _wrong((2, 3), (1,), (4,))
    # Not in the pool: the dotted run is the small slot's second rank.
    fixture.answers[(_DOTTED, "C4", "i-0001")] = _wrong((2, 3), (1,), (4, 5, 6))
    root = fixture.build()

    reel = _reel(root)

    assert reel["rule"] == "reel-v1" and reel["phase"] == "dev"
    assert [item["role"] for item in reel["pool"]] == [
        "anchor",
        "small",
        "mid",
        "frontier",
    ]
    assert reel["candidate_condition"] == "C4"
    assert reel["candidates"]["v"] == 2
    assert _picked(reel) == (_SMALL, "C4", "i-0002")
    assert reel["pick"]["disagreeing"]["v"] == 1
    assert reel["pick"]["request"]["t"] == "Request for i-0002."
    assert [node["t"] for node in reel["pick"]["answer"]["fields"]] == [
        "dns.aaaa",
        "ip.ttl",
    ]
    highlight = reel["highlight"]
    assert (highlight["probe"], highlight["frame"]["v"]) == (2, 5)
    assert highlight["kind"]["t"] == "witness"
    assert highlight["request_selects"] and not highlight["filter_selects"]
    assert reel["strips"][2]["states"] == ["tn", "tn", "tn", "tp", "fn", "tn"]
    assert reel["repair_applies"] is True
    assert reel["repair"] == {"reason": "no_round", "turn": None}
    assert reel["receipt_panel"]["repair"]["t"] == "not_run"
    assert reel["receipt_panel"]["replay"][1]["t"] == _SMALL
    assert reel["trace"] is None and reel["trace_reason"] == "not_traced"
    assert reel["headline"]["compiled"]["v"] == 4 * 8
    assert reel["headline"]["silent_wrong"]["v"] == 2
    assert [
        item["segments"]["silent_wrong"]["v"] for item in reel["board"]
    ] == [
        1,
        1,
        0,
        0,
    ]
    assert len(reel["inputs_sha256"]) == 64
    check_sources(root, {"reel.json": reel})


def test_reel_ties_go_to_the_earlier_pool_run_then_the_lower_item(
    tmp_path: Path,
) -> None:
    one_frame = _wrong((2,), (1,), (4, 5))
    later = Fixture(tmp_path / "later")
    later.answers[(_ANCHOR, "C4", "i-0002")] = one_frame
    later.answers[(_SMALL, "C4", "i-0001")] = one_frame
    lower = Fixture(tmp_path / "lower")
    lower.answers[(_ANCHOR, "C4", "i-0002")] = one_frame
    lower.answers[(_ANCHOR, "C4", "i-0001")] = one_frame

    assert _picked(_reel(later.build())) == (_ANCHOR, "C4", "i-0002")
    assert _picked(_reel(lower.build())) == (_ANCHOR, "C4", "i-0001")


def test_reel_falls_back_from_c4_through_c1(tmp_path: Path) -> None:
    typed = Fixture(tmp_path / "typed")
    typed.answers[(_SMALL, "C3", "i-0001")] = _wrong((2,), (1,), (4, 5))
    typed.answers[(_ANCHOR, "C1", "i-0001")] = _wrong((2,), (1,), (4, 5))
    clean = Fixture(tmp_path / "clean")

    fallback = _reel(typed.build())
    nothing = _reel(clean.build())

    assert fallback["candidate_condition"] == "C3"
    assert fallback["candidates"]["v"] == 1
    assert _picked(fallback) == (_SMALL, "C3", "i-0001")
    assert fallback["repair_applies"] is False
    assert nothing["candidate_condition"] is None
    assert nothing["candidates"]["v"] == 0
    assert nothing["pick"] is None and nothing["highlight"] is None
    assert nothing["strips"] == [] and nothing["receipt_panel"] is None
    assert nothing["repair"] is None
    assert nothing["headline"]["silent_wrong"]["v"] == 0


def test_reel_strips_name_every_frame_from_the_captures(
    fixture: Fixture,
) -> None:
    # The Reel's cursor shows any frame, so its strips list them all, each
    # from captures.json; a receipt lists only the frames that disagree.
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = _wrong((2,), (1,), (4, 5))
    root = fixture.build()
    files = exporter.export(root, "abc1234")

    reel = json.loads(files["reel.json"])
    receipt = json.loads(
        files[f"receipts/{exporter.run_slug(_ANCHOR)}/C4/i-0001.json"]
    )

    # The dev probes are the first rows of the fixture's captures.json.
    for row_index, strip in enumerate(reel["strips"]):
        rows = strip["frame_rows"]
        assert [row["n"]["v"] for row in rows] == list(range(1, _FRAMES + 1))
        kinds = [row["kind"]["t"] for row in rows]
        assert kinds == ["recipe"] * _BENCHMARK + ["witness"] * (
            _FRAMES - _BENCHMARK
        )
        assert rows[2]["name"] == {
            "t": "recipe-3",
            "src": [
                "ptr",
                "docs/decisions/evidence/web/captures.json",
                f"/probes/{row_index}/frames/2/name",
            ],
        }
    assert all("frame_rows" not in probe for probe in receipt["probes"])
    check_sources(root, {"reel.json": reel})


@pytest.mark.parametrize(
    ("candidate", "probe", "frame", "side"),
    [
        # Second and first disagree: the second wins.
        (((2,), (), (4, 5)), 1, 1, "reference_only"),
        # Second agrees: the first, at its lowest frame.
        (((1,), (1,), (4,)), 0, 1, "candidate_only"),
        (((2, 3, 6), (1,), (4,)), 0, 6, "candidate_only"),
        # Only the third disagrees.
        (((2, 3), (1,), (5,)), 2, 4, "reference_only"),
    ],
)
def test_highlight_takes_the_second_then_first_then_third_probe(
    fixture: Fixture,
    candidate: tuple[tuple[int, ...], ...],
    probe: int,
    frame: int,
    side: str,
) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = _wrong(*candidate)
    root = fixture.build()

    highlight = _reel(root)["highlight"]

    assert (highlight["probe"], highlight["frame"]["v"]) == (probe, frame)
    assert highlight["filter_selects"] is (side == "candidate_only")
    assert highlight["request_selects"] is (side == "reference_only")
    assert highlight["frame"]["src"][2].startswith(f"/probes/{probe}/{side}/")


@pytest.mark.parametrize(
    "repaired", [_ANCHOR, _MID], ids=["pick_repaired", "other_repaired"]
)
def test_repair_traces_and_feedback_do_not_move_the_pick(
    fixture: Fixture, repaired: str
) -> None:
    candidates = {_ANCHOR: "i-0002", _MID: "i-0001"}
    fixture.answers[(_ANCHOR, "C4", "i-0002")] = _wrong((2,), (1,), (4, 5))
    fixture.answers[(_MID, "C4", "i-0001")] = _wrong((2,), (), (4, 5))
    root = fixture.build()
    before = _reel(root)

    # Scored rounds in which only one candidate's counterexample turn
    # repairs, either way round. A pick that leaned toward a repair that
    # worked, the bias reel-v1 exists to prevent, moves to the other
    # candidate when only that one repairs; one that leaned toward a failed
    # repair moves when only the pick repairs.
    for run_id, item_id in candidates.items():
        _round(fixture, run_id, (item_id,), _tag(run_id, "cx"))
        if run_id != repaired:
            fixture.answers[(_tag(run_id, "cx"), "C4", item_id)] = _wrong(
                (2,), (), (4, 5)
            )
    fixture.build()
    # Traces of both candidates, one refused by the trace budget.
    for run_id, item_id, result in (
        (_ANCHOR, "i-0002", {"status": "trace_limit"}),
        (_MID, "i-0001", {"exact": False}),
    ):
        receipt = f"docs/results/{run_id}/scored/receipts/C4/{item_id}.json"
        _write(
            root / f"docs/decisions/evidence/web/traces/{run_id}/C4/"
            f"{item_id}.json",
            {
                "receipt_file_sha256": hashlib.sha256(
                    (root / receipt).read_bytes()
                ).hexdigest(),
                "receipt_path": receipt,
                "result": result,
            },
        )
    # The feedback probe's frames change.
    _edit(
        root / "docs/decisions/evidence/web/captures.json",
        lambda value: value["probes"][3]["frames"][0].update(name="renamed"),
    )
    after = _reel(root)

    assert _picked(before) == (_ANCHOR, "C4", "i-0002")
    assert _choice(after) == _choice(before)
    assert after["repair"]["turn"]["outcome"]["t"] == (
        "strong_exact" if repaired == _ANCHOR else "silent_wrong"
    )
    assert after["trace_reason"] == "trace_limit"
    assert after["inputs_sha256"] != before["inputs_sha256"]


def _settled(fixture: Fixture) -> None:
    _register(fixture, _registration(), *(run for _, run in _PLANNED))
    one_frame = _wrong((2,), (1,), (4, 5))
    two_frames = _wrong((2,), (1,), (4,))
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = one_frame
    fixture.answers[(_DOTTED, "C4", "i-0002")] = one_frame
    fixture.answers[(_PASS_B, "C4", "i-1001")] = one_frame
    fixture.answers[(_TEST_SMALL, "C4", "i-1001")] = two_frames
    fixture.answers[(_PASS_A, "C4", "i-1002")] = two_frames


def test_the_test_phase_pools_pass_a_and_the_winners_never_pass_b(
    fixture: Fixture,
) -> None:
    _settled(fixture)
    root = fixture.build()

    reel = _reel(root)

    assert reel["phase"] == "test"
    assert [(item["role"], item["run_id"]["t"]) for item in reel["pool"]] == [
        item for item in _PLANNED if item[0] != "aa_pass_b"
    ]
    # Pass B holds the fewest frames and the dev runs fewer still.
    assert _picked(reel) == (_PASS_A, "C4", "i-1002")
    assert reel["candidates"]["v"] == 2
    assert reel["strips"][0]["probe_id"]["t"] == "semantic-31"
    assert reel["headline"]["silent_wrong"]["v"] == 2

    (root / f"docs/results/{_TEST_FRONT}/scored/summary.json").unlink()
    unsettled = _reel(root)

    assert unsettled["phase"] == "dev"
    # Before the test phase the ruling the registration names still gives
    # the winners.
    assert [item["run_id"]["t"] for item in unsettled["pool"]] == [
        _ANCHOR,
        _DOTTED,
        _MID,
        _FRONT,
    ]
    assert _picked(unsettled) == (_ANCHOR, "C4", "i-0001")


def test_a_not_run_test_pass_leaves_the_pool(fixture: Fixture) -> None:
    _settled(fixture)
    registration = _registration()
    _stop(registration, _PASS_A, "outage")
    _register(
        fixture, registration, _PASS_B, _TEST_SMALL, _TEST_MID, _TEST_FRONT
    )
    root = fixture.build()

    reel = _reel(root)

    assert reel["phase"] == "test"
    assert [item["role"] for item in reel["pool"]] == [
        "winner_small",
        "winner_mid",
        "winner_frontier",
    ]
    assert _picked(reel) == (_TEST_SMALL, "C4", "i-1001")


def test_an_empty_test_pool_has_no_pick(fixture: Fixture) -> None:
    _settled(fixture)
    registration = _registration()
    for run_id in (_PASS_A, _TEST_SMALL, _TEST_MID, _TEST_FRONT):
        _stop(registration, run_id, "outage")
    # Only pass B is published, and it has a silent-wrong answer.
    _register(fixture, registration, _PASS_B)
    root = fixture.build()

    reel = _reel(root)

    assert reel["phase"] == "test"
    assert reel["pool"] == [] and reel["board"] == []
    assert reel["pick"] is None and reel["candidate_condition"] is None
    assert reel["candidates"]["v"] == 0
    assert reel["headline"]["compiled"]["v"] == 0
    assert reel["headline"]["silent_wrong"]["v"] == 0
    check_sources(root, {"reel.json": reel})


def _round(
    fixture: Fixture, base: str, items: tuple[str, ...], arm: str | None
) -> str:
    """Writes a pass's repair plan and scored round; returns the summary.

    The round triggers ``items``, each with a frames card. Its arms are the
    resample and bare runs and the counterexample run ``arm``, which the
    fixture then writes in the pass's split; with ``arm`` None the gate
    stopped that arm, as arms_not_run records it.
    """
    split = base.split("-", 1)[0]
    repair = f"docs/results/{base}/repair"
    _write(
        fixture.root / repair / "plan.json",
        {
            "base_run": base,
            "items": [
                {
                    "base_outcome": "silent_wrong",
                    "card": json.dumps({"frames": [{"frame": 5}]}),
                    "card_kind": "frames",
                    "item_id": item_id,
                }
                for item_id in items
            ],
            "split": split,
        },
    )
    arms = {"resample": _tag(base, "res"), "bare": _tag(base, "bare")}
    if arm is not None:
        arms["counterexample"] = arm
        if split == "dev":
            fixture.dev_runs += (arm,)
        else:
            fixture.test_runs += (arm,)
    _write(
        fixture.root / repair / "summary.json",
        {
            "arms": [
                {"arm": name, "repaired": index, "run": run_id}
                for index, (name, run_id) in enumerate(arms.items())
            ],
            "arms_not_run": (
                {}
                if arm is not None
                else {"counterexample": "thinking_not_honoured"}
            ),
            "base_run": base,
            "items": [{"item_id": item_id} for item_id in items],
            "model_id": f"vendor/{base}",
            "schema_version": "repair-summary/1.0",
            "split": split,
            "triggered_items": len(items),
        },
    )
    return f"{repair}/summary.json"


@pytest.mark.parametrize(
    "answer",
    [
        Answer("strong_exact", _EXPECTED),
        Answer("invalid", error_code="filter_unknown_field"),
    ],
    ids=["strong_exact", "invalid"],
)
def test_the_reel_shows_the_picks_counterexample_turn_whatever_it_scored(
    fixture: Fixture, answer: Answer
) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = _wrong((2,), (1,), (4, 5))
    # An outage re-run of the arm: the round names it, nothing guesses it.
    arm = _tag(_ANCHOR, "cx-r2")
    fixture.answers[(arm, "C4", "i-0001")] = answer
    summary = _round(fixture, _ANCHOR, ("i-0001",), arm)
    root = fixture.build()

    reel = _reel(root)

    assert _picked(reel) == (_ANCHOR, "C4", "i-0001")
    assert reel["repair"]["reason"] is None
    turn = reel["repair"]["turn"]
    assert turn["item"] == "i-0001"
    assert turn["run_id"] == {"t": arm, "src": ["ptr", summary, "/arms/2/run"]}
    assert turn["card"]["src"] == [
        "ptr",
        f"docs/results/{_ANCHOR}/repair/plan.json",
        "/items/0/card",
    ]
    assert turn["outcome"] == {
        "t": answer.outcome,
        "src": [
            "row",
            f"docs/results/{arm}/scored/outcomes.jsonl",
            {"condition": "C4", "item_id": "i-0001"},
            "/outcome",
        ],
    }
    assert turn["raw"]["cap"] == 4096 and turn["raw_truncated"] is False
    if answer.outcome == "strong_exact":
        assert turn["filter"]["t"] == "filter for i-0001"
        assert [strip["disagree"] for strip in turn["strips"]] == [[], [], []]
    else:
        assert turn["filter"] is None and turn["strips"] == []
    # The round's line replaces the scorer's not_run status.
    assert reel["receipt_panel"]["repair"] is None
    check_sources(root, {"reel.json": reel})


def test_only_the_picks_own_round_gives_the_reel_a_turn(
    fixture: Fixture,
) -> None:
    _settled(fixture)
    # Another pool run's round, with its counterexample arm run.
    _round(fixture, _TEST_SMALL, ("i-1001",), _tag(_TEST_SMALL, "cx"))
    root = fixture.build()

    reel = _reel(root)

    assert _picked(reel) == (_PASS_A, "C4", "i-1002")
    assert reel["repair"] == {"reason": "no_round", "turn": None}
    assert reel["receipt_panel"]["repair"]["t"] == "not_run"
    check_sources(root, {"reel.json": reel})


@pytest.mark.parametrize(
    "frontier",
    [_TEST_FRONT, _tag(_TEST_FRONT, "fb")],
    ids=["winner", "fallback"],
)
def test_a_frontier_round_without_the_picks_round_stops_the_export(
    fixture: Fixture, frontier: str
) -> None:
    # The pick's pass has no round, so disproof-reel.md would show the
    # frontier slot's repair trajectory from that slot's test round. It is
    # not built, so the export stops rather than drop it.
    _settled(fixture)
    registration = _registration()
    if frontier != _TEST_FRONT:
        _stop(registration, _TEST_FRONT, "gate stop")
        _publish(registration, frontier)
    _register(
        fixture,
        registration,
        _PASS_A,
        _PASS_B,
        _TEST_SMALL,
        _TEST_MID,
        frontier,
    )
    _round(fixture, frontier, ("i-1001",), _tag(frontier, "cx"))
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "repair_fallback_unbuilt"

    # Without the frontier round there is no trajectory to show.
    (root / f"docs/results/{frontier}/repair/summary.json").unlink()
    reel = _reel(root)

    assert _picked(reel) == (_PASS_A, "C4", "i-1002")
    assert reel["repair"] == {"reason": "no_round", "turn": None}


@pytest.mark.parametrize(
    ("label", "items", "arm"),
    [
        ("C3", ("i-0001",), _tag(_ANCHOR, "cx")),
        ("C4", ("i-0002",), _tag(_ANCHOR, "cx")),
        ("C4", ("i-0001",), None),
    ],
    ids=["not_c4", "item_not_in_round", "arm_not_run"],
)
def test_a_round_without_the_picks_counterexample_turn_stops_the_export(
    fixture: Fixture, label: str, items: tuple[str, ...], arm: str | None
) -> None:
    # disproof-reel.md would show the frontier slot's repair trajectory
    # instead. It is not built, so the export stops rather than drop it.
    fixture.answers[(_ANCHOR, label, "i-0001")] = _wrong((2,), (1,), (4, 5))
    _round(fixture, _ANCHOR, items, arm)
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "repair_fallback_unbuilt"


def _statuses(run_id: str) -> list[Document]:
    """The methodology's not_measured list as a run's summary gives it."""
    summary = f"docs/results/{run_id}/scored/summary.json"
    return [
        {
            "key": "repair_at_1",
            "split": {
                "t": run_id.split("-", 1)[0],
                "src": ["ptr", summary, "/split"],
            },
            "value": {
                "t": "not_run",
                "src": ["ptr", summary, "/not_measured/repair_at_1"],
            },
        }
    ]


def _methodology(root: Path) -> Document:
    repo = exporter.Repo(root)
    return exporter.build_methodology(repo, exporter.select(repo))


@pytest.mark.parametrize(
    ("stopped", "cited"),
    [
        ((), _PASS_A),
        # Without pass A the small slot's winner leads the pool.
        ((_PASS_A,), _TEST_SMALL),
        # Only pass B is published: no pool run reports a test round.
        ((_PASS_A, _TEST_SMALL, _TEST_MID, _TEST_FRONT), None),
    ],
)
def test_the_test_phase_methodology_cites_the_first_pool_run(
    fixture: Fixture, stopped: tuple[str, ...], cited: str | None
) -> None:
    # The page's repair line describes the round the site reports, which in
    # the test phase is the test round, so a scored dev round of the anchor
    # changes nothing.
    _settled(fixture)
    registration = _registration()
    for run_id in stopped:
        _stop(registration, run_id, "outage")
    _register(
        fixture,
        registration,
        *(run_id for _, run_id in _PLANNED if run_id not in stopped),
    )
    root = fixture.build()
    _write(
        root / f"docs/results/{_ANCHOR}/repair/summary.json",
        {"schema": "repair-summary/1.0"},
    )

    documents = _documents(exporter.export(root, "abc1234"))

    assert documents["reel.json"]["phase"] == "test"
    methodology = documents["methodology.json"]
    assert methodology["not_measured"] == (
        [] if cited is None else _statuses(cited)
    )
    assert methodology["repair"] is None
    # Everything else stays the dev anchor's.
    assert methodology["bootstrap"]["seed"]["src"] == [
        "ptr",
        f"docs/results/{_ANCHOR}/scored/summary.json",
        "/bootstrap/seed",
    ]
    check_sources(root, {"methodology.json": methodology})


@pytest.mark.parametrize(
    ("phase", "cited", "item_id", "arm"),
    [
        ("test", _PASS_A, "i-1002", _tag(_PASS_A, "cx")),
        # A round whose counterexample arm the gate stopped.
        ("dev", _ANCHOR, "i-0001", None),
    ],
)
def test_a_scored_round_gives_the_methodology_its_repair_line(
    fixture: Fixture, phase: str, cited: str, item_id: str, arm: str | None
) -> None:
    # The scorer leaves the cited run's repair_at_1 at not_run after a
    # round, so the status gives way to the round's own line.
    if phase == "test":
        _settled(fixture)
    summary = _round(fixture, cited, (item_id,), arm)
    root = fixture.build()

    methodology = _methodology(root)

    assert methodology["not_measured"] == []
    line = methodology["repair"]
    assert line["split"] == {"t": phase, "src": ["ptr", summary, "/split"]}
    assert line["model_id"]["t"] == f"vendor/{cited}"
    assert line["triggered_items"]["v"] == 1
    assert [
        (each["arm"]["t"], each["repaired"]["v"]) for each in line["arms"]
    ] == [
        ("resample", 0),
        ("bare", 1),
        *([] if arm is None else [("counterexample", 2)]),
    ]
    assert line["not_run"] == (
        []
        if arm is not None
        else [
            {
                "arm": "counterexample",
                "reason": {
                    "t": "thinking_not_honoured",
                    "src": ["ptr", summary, "/arms_not_run/counterexample"],
                },
            }
        ]
    )
    check_sources(root, {"methodology.json": methodology})


@pytest.mark.parametrize(
    ("key", "value"), [("base_run", _PASS_B), ("split", "dev")]
)
def test_a_round_that_names_another_pass_is_refused(
    fixture: Fixture, key: str, value: str
) -> None:
    _settled(fixture)
    summary = _round(fixture, _PASS_A, ("i-1002",), _tag(_PASS_A, "cx"))
    _edit(
        fixture.root / summary, lambda document: document.update({key: value})
    )
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "repair_inconsistent"


@pytest.mark.parametrize(
    ("phase", "cited"), [("test", _PASS_A), ("dev", _ANCHOR)]
)
def test_the_repair_line_names_the_split_of_the_run_it_cites(
    fixture: Fixture, phase: str, cited: str
) -> None:
    # Once rounds of both splits are committed, a line that names no split
    # reads as if no repair round had been measured. The page labels it
    # "Test repair round" or "Dev repair round" from this node, so it must
    # be the cited summary's own split, never the phase or another run's.
    if phase == "test":
        _settled(fixture)
    root = fixture.build()
    summary = f"docs/results/{cited}/scored/summary.json"

    methodology = _methodology(root)

    assert [entry["split"] for entry in methodology["not_measured"]] == [
        {"t": phase, "src": ["ptr", summary, "/split"]}
    ]
    check_sources(root, {"methodology.json": methodology})


def test_repair_results_outside_the_pool_leave_the_export_alone(
    fixture: Fixture,
) -> None:
    _settled(fixture)
    root = fixture.build()
    before = exporter.export(root, "abc1234")

    for path in (
        # Pass B is never pooled.
        f"docs/results/{_PASS_B}/repair/summary.json",
        f"docs/results/test-anchor-rerun-cx-{_DATE}/scored/summary.json",
        # Dev passes and the dev split, in the test phase; the methodology
        # cites pass A, not the anchor.
        f"docs/results/{_MID}/repair/summary.json",
        f"docs/results/{_ANCHOR}/repair/summary.json",
        "docs/results/repair-pool/dev.json",
    ):
        _write(root / path, {"schema": "repair-summary/1.0"})

    assert exporter.export(root, "abc1234") == before


_REPAIR_POOL = "docs/results/repair-pool/test.json"
_POOL_RUNS = (_PASS_A, _TEST_SMALL, _TEST_MID, _TEST_FRONT)


def _rated(path: Path) -> None:
    """Gives a written round the rates and comparisons the board reads."""

    def rate(document: Document) -> None:
        for arm in document["arms"]:
            arm["repair_at_1"] = {"value": 0.5, "low": 0.25, "high": 0.75}
        document["comparisons"] = [
            {
                "difference": {"value": 0.5, "low": -0.25, "high": 1.0},
                "discordant": 3,
                "first": "counterexample",
                "first_better": 2,
                "inconclusive": True,
                "second": "bare",
                "second_better": 1,
            }
        ]
        document["triggered_cases"] = 1

    _edit(path, rate)


def _pool(*runs: str) -> Document:
    """A repair-pool/1.0 file over the given passes, with one arm."""
    return {
        "arms": [
            {
                "arm": "bare",
                "repair_at_1": {"value": 0.25, "low": 0.0, "high": 0.5},
                "repaired": 1,
                "triggered_items": 4,
            }
        ],
        "bases": [{"run": run_id} for run_id in runs],
        "bootstrap": {
            "cases": 2,
            "min_discordant_cases": 10,
            "resamples": 1000,
            "seed": 17,
        },
        "comparisons": [],
        "schema_version": "repair-pool/1.0",
        "split": "test",
    }


def _pooled_rounds(fixture: Fixture) -> Path:
    """The test phase with every pool pass's round scored, none pooled.

    Pass A's round holds the Reel pick's counterexample turn; the gate
    stopped the other passes' counterexample arms.
    """
    _settled(fixture)
    rounds = [_round(fixture, _PASS_A, ("i-1002",), _tag(_PASS_A, "cx"))]
    rounds += [
        _round(fixture, run_id, ("i-1001",), None) for run_id in _POOL_RUNS[1:]
    ]
    root = fixture.build()
    for summary in rounds:
        _rated(root / summary)
    return root


def test_the_pool_file_gives_the_board_the_test_repair_round(
    fixture: Fixture,
) -> None:
    root = _pooled_rounds(fixture)
    before = _documents(exporter.export(root, "abc1234"))
    _write(root / _REPAIR_POOL, _pool(*reversed(_POOL_RUNS)))

    documents = _documents(exporter.export(root, "abc1234"))

    assert before["board.json"]["test"]["repair"] is None
    assert before["site.json"]["phase"]["repair"] is False
    assert documents["site.json"]["phase"]["repair"] is True
    repair = documents["board.json"]["test"]["repair"]
    assert repair["arms"][0]["triggered"]["src"] == [
        "ptr",
        _REPAIR_POOL,
        "/arms/0/triggered_items",
    ]
    # Pool order, whatever order the pool file lists its passes in.
    assert [
        (item["role"], item["model_id"]["t"]) for item in repair["models"]
    ] == [
        (role, f"vendor/{run_id}")
        for role, run_id in _PLANNED
        if role != "aa_pass_b"
    ]
    first, small = repair["models"][:2]
    summary = f"docs/results/{_PASS_A}/repair/summary.json"
    assert [arm["arm"]["t"] for arm in first["arms"]] == [
        "resample",
        "bare",
        "counterexample",
    ]
    assert first["arms"][2]["triggered"]["src"] == [
        "ptr",
        summary,
        "/triggered_items",
    ]
    assert first["comparisons"][0]["inconclusive"] == {
        "v": True,
        "src": ["ptr", summary, "/comparisons/0/inconclusive"],
    }
    assert [arm["arm"] for arm in small["not_run"]] == ["counterexample"]
    # The two sources disproof-reel.md allows; never an arm run's summary.
    assert {node["src"][1] for node in _nodes(repair)} == {
        _REPAIR_POOL,
        *(
            f"docs/results/{run_id}/repair/summary.json"
            for run_id in _POOL_RUNS
        ),
    }
    check_sources(root, documents)


@pytest.mark.parametrize("change", ["pass_b", "dev_split", "no_round"])
def test_a_pool_file_of_other_rounds_stops_the_export(
    fixture: Fixture, change: str
) -> None:
    root = _pooled_rounds(fixture)
    pool = _pool(*_POOL_RUNS)
    if change == "pass_b":
        # Pass B is never pooled.
        pool["bases"][0]["run"] = _PASS_B
    elif change == "dev_split":
        pool["split"] = "dev"
    else:
        (root / f"docs/results/{_TEST_MID}/repair/summary.json").unlink()
    _write(root / _REPAIR_POOL, pool)

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "repair_inconsistent"


@pytest.mark.parametrize("phase", ["dev", "test"])
def test_the_reel_hashes_the_ruling(fixture: Fixture, phase: str) -> None:
    _settled(fixture)
    if phase == "dev":
        # No test run exists, so the phase stays dev and the pool holds the
        # ruling's dev winners.
        fixture.test_runs = ()
    root = fixture.build()
    before = _reel(root)

    _edit(root / _RULING, lambda value: value.update(date="2026-01-02"))
    after = _reel(root)

    assert before["phase"] == after["phase"] == phase
    assert _choice(after) == _choice(before)
    assert after["inputs_sha256"] != before["inputs_sha256"]


def test_a_silent_wrong_receipt_must_disagree_somewhere(
    fixture: Fixture,
) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0001")] = Answer(
        "silent_wrong", _EXPECTED
    )
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "no_disagreement"


def test_a_summary_without_a_case_mean_is_not_checked(
    fixture: Fixture,
) -> None:
    root = fixture.build()
    _edit(
        _mid(root, "scored/summary.json"),
        lambda value: value["conditions"]["C2"].update(silent_wrong_all=None),
    )

    assert "reel.json" in exporter.export(root, "abc1234")


def test_a_slot_without_a_winner_leaves_the_pool(fixture: Fixture) -> None:
    fixture.answers[(_MID, "C4", "i-0001")] = _wrong((2,), (1,), (4, 5))
    root = fixture.build()
    _edit(
        _ranking_path(root),
        lambda value: value["slots"]["mid"].update(provisional_winner=None),
    )

    reel = _reel(root)

    assert [item["role"] for item in reel["pool"]] == [
        "anchor",
        "small",
        "frontier",
    ]
    assert reel["pick"] is None and reel["candidates"]["v"] == 0


_HAS_DOCS = (_ROOT / "docs" / "results").is_dir()


@functools.cache
def _committed() -> dict[str, bytes]:
    return exporter.export(_ROOT, "x")


@pytest.mark.skipif(
    not _HAS_DOCS, reason="The test image carries no docs/ tree"
)
def test_the_committed_tree_exports_every_executed_answer() -> None:
    documents = _documents(_committed())

    routes = documents["routes.json"]
    assert len(routes["receipts"]) == 1854
    assert len(routes["cases"]) == 76
    board = documents["board.json"]
    assert [item["run_id"]["t"] for item in board["selection"]["rows"]][:2] == [
        "dev-qwen3-32b-2026-09-26",
        "dev-qwen3.5-9b-2026-09-26",
    ]
    # Every registry row is final: the five planned runs are published and
    # scored, and the eleven conditional rows are unused. The rows are the
    # four pool runs; pass B is only pass A's rerun.
    assert [
        (item["role"], item["run_id"]["t"]) for item in board["test"]["rows"]
    ] == [
        ("aa_pass_a", "test-qwen3-32b-2026-09-26"),
        ("winner_small", "test-qwen3.5-9b-2026-09-26"),
        ("winner_mid", "test-qwen3.5-122b-a10b-2026-09-26"),
        ("winner_frontier", "test-deepseek-v4-pro-0813-2026-09-26"),
    ]
    rerun = board["test"]["rerun"]
    assert (rerun["role"], rerun["run_id"]["t"]) == (
        "aa_pass_b",
        "test-qwen3-32b-passb-2026-09-26",
    )
    assert board["test"]["not_run"] == []
    # The test repair round, pooled and per pass in pool order, as
    # locked-test-v1.md reports it.
    repair = board["test"]["repair"]
    assert [
        (arm["arm"]["t"], arm["repaired"]["v"], arm["triggered"]["v"])
        for arm in repair["arms"]
    ] == [("resample", 4, 75), ("bare", 21, 75), ("counterexample", 35, 75)]
    assert [
        (
            item["first"]["t"],
            item["second"]["t"],
            item["first_better"]["v"],
            item["second_better"]["v"],
            item["discordant"]["v"],
            item["inconclusive"]["v"],
        )
        for item in repair["comparisons"]
    ] == [
        ("counterexample", "bare", 12, 4, 16, False),
        ("counterexample", "resample", 21, 2, 23, False),
        ("bare", "resample", 13, 0, 13, False),
    ]
    assert [item["model_id"]["t"] for item in repair["models"]] == [
        "qwen/qwen3-32b",
        "qwen/qwen3.5-9b",
        "qwen/qwen3.5-122b-a10b",
        "deepseek/deepseek-v4-pro-0813",
    ]
    # The primary, counterexample against bare, reads for one model alone.
    assert [
        item["comparisons"][0]["inconclusive"]["v"] for item in repair["models"]
    ] == [True, True, False, True]
    assert documents["site.json"]["phase"]["repair"] is True
    # The repair line describes the test round, so it cites pass A, whose
    # scored round replaces the not_run status.
    methodology = documents["methodology.json"]
    assert methodology["not_measured"] == []
    line = methodology["repair"]
    assert line["split"]["src"] == [
        "ptr",
        "docs/results/test-qwen3-32b-2026-09-26/repair/summary.json",
        "/split",
    ]
    assert (line["split"]["t"], line["model_id"]["t"]) == (
        "test",
        "qwen/qwen3-32b",
    )
    assert line["triggered_items"]["v"] == 28
    assert [
        (arm["arm"]["t"], arm["repaired"]["v"]) for arm in line["arms"]
    ] == [
        ("resample", 1),
        ("bare", 14),
        ("counterexample", 16),
    ]
    assert line["not_run"] == []
    assert check_sources(_ROOT, documents) > 150_000


@pytest.mark.skipif(
    not _HAS_DOCS, reason="The test image carries no docs/ tree"
)
def test_the_committed_tree_picks_the_registered_reel() -> None:
    reel = json.loads(_committed()["reel.json"])

    assert reel["phase"] == "test"
    assert [item["run_id"]["t"] for item in reel["pool"]] == [
        "test-qwen3-32b-2026-09-26",
        "test-qwen3.5-9b-2026-09-26",
        "test-qwen3.5-122b-a10b-2026-09-26",
        "test-deepseek-v4-pro-0813-2026-09-26",
    ]
    assert reel["candidate_condition"] == "C4"
    assert reel["candidates"]["v"] == 54
    assert _picked(reel) == ("test-qwen3-32b-2026-09-26", "C4", "mei-1038")
    assert reel["pick"]["request"]["t"] == (
        "I want every TCP segment with FIN set whose source port is 443, "
        "whether or not ACK is also set. Judge by the port alone; a FIN sent "
        "to destination port 443 from some other source port doesn't belong."
    )
    assert reel["pick"]["answer"]["filter"]["t"] == (
        "(tcp.srcport == 443 && tcp.completeness.fin == true)"
    )
    assert [
        [item["n"]["v"] for item in strip["disagree"]]
        for strip in reel["strips"]
    ] == [[59], [60], [66]]
    highlight = reel["highlight"]
    assert highlight["probe_id"]["t"] == "semantic-37"
    assert highlight["frame"]["v"] == 60
    assert highlight["name"]["t"] == "server-fin-ack"
    assert reel["headline"]["compiled"]["v"] == 971
    assert reel["headline"]["silent_wrong"]["v"] == 165
    # Step 5: the pick's turn in pass A's counterexample arm, item 15 of the
    # pass's repair plan, which repaired it.
    assert reel["repair"]["reason"] is None
    turn = reel["repair"]["turn"]
    assert turn["run_id"] == {
        "t": "test-qwen3-32b-cx-2026-09-26",
        "src": [
            "ptr",
            "docs/results/test-qwen3-32b-2026-09-26/repair/summary.json",
            "/arms/2/run",
        ],
    }
    assert turn["card"]["src"] == [
        "ptr",
        "docs/results/test-qwen3-32b-2026-09-26/repair/plan.json",
        "/items/15/card",
    ]
    assert (turn["base_outcome"]["t"], turn["card_kind"]["t"]) == (
        "silent_wrong",
        "frames",
    )
    assert turn["outcome"]["t"] == "strong_exact"
    assert turn["filter"]["t"] == (
        "(tcp.srcport == 443 && tcp.flags.fin == true)"
    )
    assert [strip["disagree"] for strip in turn["strips"]] == [[], [], []]
    assert reel["receipt_panel"]["repair"] is None
    check_sources(_ROOT, {"reel.json": reel})


# What a dev-phase export reads besides the ranking's runs: the evidence
# trees, which hold the ranking, the ruling and test-runs.json, the
# registry note and the held-out freeze record.
_DEV_INPUTS = (
    "docs/decisions/evidence",
    "docs/decisions/test-runs.md",
    "docs/ablations/evidence",
    _FREEZE,
)


def _ranking_runs() -> list[str]:
    """The anchor and every candidate run of the latest committed ranking."""
    bakeoff = _ROOT / "docs" / "decisions" / "evidence" / "bakeoff"
    ranking = json.loads(
        sorted(bakeoff.glob("ranking-*.json"))[-1].read_text(encoding="utf-8")
    )
    return [
        ranking["anchor"]["run_id"],
        *(
            candidate["run_id"]
            for slot in ranking["slots"].values()
            for candidate in slot["candidates"]
        ),
    ]


def _copy_run(root: Path, run_id: str) -> None:
    """Copies a committed run's directory without its repair/ directory.

    No repair file is an input to reel-v1's steps 1 to 4
    (docs/decisions/disproof-reel.md), so the copy leaves them out.
    """
    source = _ROOT / "docs" / "results" / run_id
    shutil.copytree(
        source,
        root / "docs" / "results" / run_id,
        ignore=lambda directory, _: (
            ["repair"] if Path(directory) == source else []
        ),
    )


def _registered_again(value: Document) -> None:
    # The five planned rows, registered on 2026-10-01 and published since.
    for entry in value["runs"][:5]:
        entry["status"] = "registered"


@pytest.fixture(name="dev_tree")
def dev_tree_fixture(tmp_path: Path) -> Iterator[Path]:
    """A copy of the committed tree as the 2026-10-01 dev check found it.

    It holds no test-run directory, and its test-runs.json has the five
    planned rows registered, as they were that day, so the test phase is
    off for the reason docs/decisions/disproof-reel.md gives ("Checked on
    today's data"). The copy is removed at the end: /tmp in the CI test
    container is a small tmpfs.
    """
    root = tmp_path / "dev"
    try:
        for relative in _DEV_INPUTS:
            source = _ROOT / relative
            if source.is_dir():
                shutil.copytree(source, root / relative)
            else:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, root / relative)
        for run_id in _ranking_runs():
            _copy_run(root, run_id)
        _edit(root / _TEST_RUNS, _registered_again)
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.skipif(
    not _HAS_DOCS, reason="The test image carries no docs/ tree"
)
def test_the_committed_dev_pool_picks_the_registered_dev_reel(
    dev_tree: Path,
) -> None:
    # disproof-reel.md asks the exporter's tests to repeat its dev check,
    # and the committed tree has since moved to the test phase, so the
    # check runs on the copy.
    reel = _reel(dev_tree)

    assert reel["phase"] == "dev"
    # The dev anchor, then the winners the registry's ruling names.
    assert [item["run_id"]["t"] for item in reel["pool"]] == [
        "dev-qwen3-32b-2026-09-26",
        "dev-qwen3.5-9b-2026-09-26",
        "dev-qwen3.5-122b-a10b-2026-09-26",
        "dev-deepseek-v4-pro-0813-2026-09-26",
    ]
    assert reel["candidates"]["v"] == 27
    # Three candidates tie at three frames; pool order picks the anchor's.
    assert _picked(reel) == ("dev-qwen3-32b-2026-09-26", "C4", "mei-0015")
    assert reel["pick"]["request"]["t"] == (
        "Show DNS AAAA questions or DNS NXDOMAIN messages."
    )
    assert reel["pick"]["answer"]["filter"]["t"] == (
        "(dns.aaaa || dns.flags.rcode == 3)"
    )
    assert [
        [item["n"]["v"] for item in strip["disagree"]]
        for strip in reel["strips"]
    ] == [[17], [3], [9]]
    highlight = reel["highlight"]
    assert highlight["probe_id"]["t"] == "semantic-17"
    assert highlight["frame"]["v"] == 3
    assert highlight["name"]["t"] == "udp-aaaa"
    assert reel["headline"]["compiled"]["v"] == 284
    assert reel["headline"]["silent_wrong"]["v"] == 65
    check_sources(dev_tree, {"reel.json": reel})
