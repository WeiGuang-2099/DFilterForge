"""The web data exporter: sourced values, selection, asserts and exit status.

A fixture repository in tmp_path holds a bake-off ranking with five dev runs
(one with a dotted id), the frame tables and the global evidence, each file
in the shape the committed ones take. A test resolver written apart from the
exporter re-derives every sourced value from those raw files. The test of
the committed tree skips where the test image carries no docs/ tree.
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
_ALLOWED = (
    "docs/results/",
    "docs/decisions/evidence/",
    "docs/ablations/evidence/",
)
_FREEZE = "src/dfilterforge/held_out_freeze.json"
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
            note = self.root / "docs/decisions/model-bakeoff.md"
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


def check_sources(root: Path, documents: dict[str, Document]) -> int:
    """Asserts every sourced node equals its source; returns the count."""
    resolver = Resolver(root)
    checked = 0
    for name, document in documents.items():
        for node in _nodes(document):
            expected = resolver.resolve(node["src"])
            if "t" in node:
                if "cap" in node:
                    expected = _capped(expected, node["cap"])
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


def _registration(
    *, not_run: tuple[str, ...] = (), slots: bool = True
) -> Document:
    runs = [
        {"role": "pass_a", "run_id": _PASS_A},
        {"role": "pass_b", "run_id": _PASS_B},
    ]
    if slots:
        runs += [
            {"dev_run_id": _DOTTED, "role": "small", "run_id": _TEST_SMALL},
            {"dev_run_id": _MID, "role": "mid", "run_id": _TEST_MID},
            {"dev_run_id": _FRONT, "role": "frontier", "run_id": _TEST_FRONT},
        ]
    return {"not_run": list(not_run), "runs": runs}


def _note() -> str:
    return " ".join(
        f"`{run_id}`."
        for run_id in (_PASS_A, _PASS_B, _TEST_SMALL, _TEST_MID, _TEST_FRONT)
    )


def test_test_rows_appear_only_when_every_registered_run_is_settled(
    fixture: Fixture,
) -> None:
    fixture.registration = _registration()
    fixture.note = _note()
    fixture.test_runs = (_PASS_A, _PASS_B, _TEST_SMALL, _TEST_MID)
    root = fixture.build()

    partial = _documents(exporter.export(root, "abc1234"))

    assert partial["board.json"]["test"] is None
    assert partial["board.json"]["test_registered"] is True
    assert partial["site.json"]["phase"]["test"] is False
    assert not any(
        item["run"].startswith("test-")
        for item in partial["routes.json"]["receipts"]
    )
    # The registration names the winners even before the test phase.
    assert [
        run["run_id"] for run in partial["site.json"]["runs"] if run["pool"]
    ] == [_ANCHOR, _DOTTED, _MID, _FRONT]

    _edit(
        root / "docs/decisions/evidence/test-runs.json",
        lambda value: value["not_run"].append(_TEST_FRONT),
    )
    documents = _documents(exporter.export(root, "abc1234"))

    board = documents["board.json"]
    assert [item["role"] for item in board["test"]["rows"]] == [
        "pass_a",
        "pass_b",
        "small",
        "mid",
    ]
    assert board["test"]["not_run"][0]["run_id"]["t"] == _TEST_FRONT
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


def _second_pass_a(doc: Document) -> None:
    doc["runs"].append({"role": "pass_a", "run_id": f"test-x-{_DATE}"})


def _no_pass_b(doc: Document) -> None:
    doc["runs"].pop(1)


def _unknown_not_run(doc: Document) -> None:
    doc["not_run"].append(f"test-x-{_DATE}")


def _unshown_winner(doc: Document) -> None:
    doc["runs"][2]["dev_run_id"] = f"dev-x-{_DATE}"


def _dev_pass_a(doc: Document) -> None:
    doc["runs"][0]["run_id"] = _ANCHOR


def _scored_not_run(doc: Document) -> None:
    doc["not_run"].append(_PASS_A)


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (_second_pass_a, "role_invalid"),
        (_no_pass_b, "role_missing"),
        (_unknown_not_run, "not_run_invalid"),
        (_unshown_winner, "pool_unshown"),
        (_dev_pass_a, "split_mismatch"),
        (_scored_not_run, "not_run_scored"),
    ],
)
def test_a_broken_registration_fails(
    fixture: Fixture, edit: Callable[[Document], None], code: str
) -> None:
    registration = _registration()
    edit(registration)
    fixture.registration = registration
    fixture.note = _note()
    fixture.test_runs = (_PASS_A,)
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == code


def test_a_run_missing_from_the_bakeoff_note_fails(fixture: Fixture) -> None:
    fixture.registration = _registration()
    fixture.note = _note().replace(_TEST_MID, f"{_TEST_MID}x")
    root = fixture.build()

    with pytest.raises(exporter.ContractError) as caught:
        exporter.export(root, "abc1234")
    assert caught.value.code == "run_unregistered"


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
    assert reel["repair_applies"] is True and reel["repair"] is None
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
    assert nothing["headline"]["silent_wrong"]["v"] == 0


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


def test_repair_traces_and_feedback_do_not_move_the_pick(
    fixture: Fixture,
) -> None:
    fixture.answers[(_ANCHOR, "C4", "i-0002")] = _wrong((2,), (1,), (4, 5))
    fixture.answers[(_MID, "C4", "i-0001")] = _wrong((2,), (), (4, 5))
    root = fixture.build()
    before = _reel(root)

    # A repair pass that would repair the pick and fail the other one.
    repair = root / f"docs/results/dev-anchor-repair-{_DATE}/scored"
    repair.mkdir(parents=True)
    (repair / "outcomes.jsonl").write_text(
        json.dumps(
            {"condition": "C4", "item_id": "i-0002", "outcome": "strong_exact"}
        )
        + "\n",
        encoding="utf-8",
    )
    _edit(
        root / f"docs/results/{_ANCHOR}/scored/summary.json",
        lambda value: value["not_measured"].update(repair_at_1="scored"),
    )
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
    assert after["trace_reason"] == "trace_limit"
    assert after["receipt_panel"]["repair"]["t"] == "scored"
    assert after["inputs_sha256"] != before["inputs_sha256"]


def _settled(fixture: Fixture) -> None:
    fixture.registration = _registration()
    fixture.note = _note()
    fixture.test_runs = (_PASS_A, _PASS_B, _TEST_SMALL, _TEST_MID, _TEST_FRONT)
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
    assert [item["role"] for item in reel["pool"]] == [
        "pass_a",
        "small",
        "mid",
        "frontier",
    ]
    assert [item["run_id"]["t"] for item in reel["pool"]][:2] == [
        _PASS_A,
        _TEST_SMALL,
    ]
    # Pass B holds the fewest frames and the dev runs fewer still.
    assert _picked(reel) == (_PASS_A, "C4", "i-1002")
    assert reel["candidates"]["v"] == 2
    assert reel["strips"][0]["probe_id"]["t"] == "semantic-31"
    assert reel["headline"]["silent_wrong"]["v"] == 2

    (root / f"docs/results/{_TEST_FRONT}/scored/summary.json").unlink()
    unsettled = _reel(root)

    assert unsettled["phase"] == "dev"
    # Before the test phase the registration still names the winners.
    assert [item["run_id"]["t"] for item in unsettled["pool"]] == [
        _ANCHOR,
        _DOTTED,
        _MID,
        _FRONT,
    ]
    assert _picked(unsettled) == (_ANCHOR, "C4", "i-0001")


def test_a_not_run_test_pass_leaves_the_pool(fixture: Fixture) -> None:
    _settled(fixture)
    fixture.test_runs = (_PASS_B, _TEST_SMALL, _TEST_MID, _TEST_FRONT)
    fixture.registration = _registration(not_run=(_PASS_A,))
    root = fixture.build()

    reel = _reel(root)

    assert reel["phase"] == "test"
    assert [item["role"] for item in reel["pool"]] == [
        "small",
        "mid",
        "frontier",
    ]
    assert _picked(reel) == (_TEST_SMALL, "C4", "i-1001")


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
    assert len(routes["receipts"]) == 651
    assert len(routes["cases"]) == 20
    assert [
        item["run_id"]["t"]
        for item in documents["board.json"]["selection"]["rows"]
    ][:2] == ["dev-qwen3-32b-2026-09-26", "dev-qwen3.5-9b-2026-09-26"]
    assert check_sources(_ROOT, documents) > 50_000


@pytest.mark.skipif(
    not _HAS_DOCS, reason="The test image carries no docs/ tree"
)
def test_the_committed_tree_picks_the_registered_reel() -> None:
    reel = json.loads(_committed()["reel.json"])

    assert [item["run_id"]["t"] for item in reel["pool"]] == [
        "dev-qwen3-32b-2026-09-26",
        "dev-qwen3.5-9b-2026-09-26",
        "dev-qwen3.5-122b-a10b-2026-09-26",
        "dev-deepseek-v4-pro-0813-2026-09-26",
    ]
    assert reel["candidates"]["v"] == 27
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
    check_sources(_ROOT, {"reel.json": reel})
