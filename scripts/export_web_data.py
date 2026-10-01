"""Exports the web site's data from committed files only.

The site shows nothing it cannot trace. Every value it renders arrives here
as a sourced node: ``{"t": text, "src": op}`` for a string, or
``{"v": value, "src": op}`` for a number, a boolean or an array of integers.
``op`` names committed bytes and the one reading that yields the value:

- ``["ptr", path, pointer]``: an RFC 6901 pointer into a JSON file.
- ``["row", path, {key: text}, pointer]``: the one JSONL row whose keys
  all equal the given strings, then a pointer into that row.
- ``["count", path, pointer, {key: [text]}]``: the JSONL rows (pointer
  null) or the array items at the pointer whose every key holds one of the
  listed strings.
- ``["len", path, pointer]``: the length of the array at the pointer.
- ``["sum", [op]]``: the sum of integer operands.
- ``["sha256", path]``: the SHA-256 of the file's bytes.
- ``["input", path, item_id, pointer]``: the INPUT_JSON object of a
  prepared prompt's user message, then a pointer into it.

A raw model answer also carries ``"cap"``: its text is the resolved string
cut to that many UTF-8 bytes at a character boundary. Paths are relative to
the repository and lie under docs/results/, docs/decisions/evidence/ or
docs/ablations/evidence/, or are exactly the held-out freeze record; any
other path, and any path with a dot segment, is refused.

Shown runs come from committed files, never from a hand list: the runs of
the lexicographically last bake-off ranking (the anchor, then the small, mid
and frontier slots, rank by rank) and, once every run that
docs/decisions/evidence/test-runs.json registers is scored or listed as not
run, the registered test runs. That file is read as
``{"runs": [{"role", "run_id", "dev_run_id"}], "not_run": [run_id]}``, with
roles pass_a, pass_b, small, mid and frontier; a slot role names its
winner's counted dev pass in ``dev_run_id``. The site never divides: dev runs
get counts only, and rates, intervals and comparisons are pointers into a
test run's summary.json.

Outputs, schema family web-*/1.0, one JSON document per file, written with
sorted keys, compact separators and one trailing LF: site.json, routes.json,
board.json, methodology.json, reel.json, cases/<case_id>.json and
receipts/<run_slug>/<condition>/<item_id>.json, where the run slug is the
run id with each dot replaced by an underscore.

reel.json projects the home page's Disproof Reel by the pre-registered
rule reel-v1 (docs/decisions/disproof-reel.md once registered). Pool: in
the test phase pass A then the small, mid and frontier winners' test runs,
skipping runs not run; else the dev anchor then the winners' dev passes
(test-runs.json's, else the ranking's provisional winners); pass B never.
Candidates: pool items in C4 with ready gold and outcome silent_wrong,
else C3, then C2, then C1. Pick: the fewest frames in candidate_only plus
reference_only over the scored probes, ties to the earlier pool run, then
the lower item id. Highlight: the second scored probe if it disagrees,
else the first, else the third, and on it the lowest disagreeing frame.
No repair outcome, feedback-probe result or trace is read before the pick.

The exporter imports only the standard library, never runs a process, never
opens a socket and reads no clock, environment variable or git state, so
the same files and flags give the same bytes.

Exit status: 0 when every file is written, 1 when the committed files break
the data contract, 2 when an input cannot be read, a flag is invalid or the
output directory is not empty.
"""

# One file on purpose: the Docker data stage copies this script alone into
# a stage with no project package, and a second module would need its own
# loader there and in the tests. Most of the length is the output shapes.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import cast, NoReturn

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The same input ceiling as the run store's JSON reads.
MAX_INPUT_BYTES = 32 * 1024 * 1024
RAW_TEXT_CAP = 4096
# A count over ready items equals the summary's case mean only because
# every case has exactly two items; summaries round to six places.
MEAN_TOLERANCE = 5e-7
RESULTS = "docs/results"
RANKING_DIR = "docs/decisions/evidence/bakeoff"
TEST_RUNS = "docs/decisions/evidence/test-runs.json"
CAPTURES = "docs/decisions/evidence/web/captures.json"
TRACES = "docs/decisions/evidence/web/traces"
GATE = "docs/decisions/evidence/test-freeze-gate.json"
SHORTCUTS = "docs/ablations/evidence/006-shortcut-policy.json"
FREEZE = "src/dfilterforge/held_out_freeze.json"
# Read only to check that every registered test run is named in the
# binding prose; no sourced value ever points into it.
BAKEOFF_NOTE = "docs/decisions/model-bakeoff.md"
_ROOTS = (
    "docs/results/",
    "docs/decisions/evidence/",
    "docs/ablations/evidence/",
)
# scripts/model_run.py's result-name pattern, with ASCII digits only.
_RUN_ID = re.compile(
    r"(dev|test)-[a-z0-9][a-z0-9.-]{0,31}-[0-9]{4}-[0-9]{2}-[0-9]{2}"
)
# A route segment: Next drops the trailing slash of a dotted last segment.
_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_COMMIT = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}")
_INDEX = re.compile(r"0|[1-9][0-9]*")
_SLOTS = ("small", "mid", "frontier")
_TEST_ROLES = ("pass_a", "pass_b", *_SLOTS)
_EXECUTED = ("strong_exact", "shortcut", "silent_wrong")
# Outcomes of an answer that parsed with status ready.
_READY_ANSWERS = ("false_ready", "invalid", *_EXECUTED)
# Every outcome a ready gold item can take, in board order.
SEGMENTS = (
    "strong_exact",
    "shortcut",
    "silent_wrong",
    "invalid",
    "malformed",
    "provider_failed",
    "abstained",
)
_TEST_METRICS = (
    "strong_exact",
    "silent_wrong_all",
    "silent_wrong_of_executable",
    "compile_valid",
    "over_abstention",
    "false_ready",
    "slot_match",
)
_MEAN_CHECKS = (
    ("strong_exact", "strong_exact"),
    ("silent_wrong_all", "silent_wrong"),
)
_ARITY = {
    "ptr": 3,
    "row": 4,
    "count": 4,
    "len": 3,
    "sum": 2,
    "sha256": 2,
    "input": 4,
}
REEL_RULE = "reel-v1"
# reel-v1 step 2: C4 first, then C3, C2 and C1.
_REEL_CONDITIONS = ("C4", "C3", "C2", "C1")
# reel-v1 step 4: the second scored probe, then the first, then the third.
_HIGHLIGHT = (1, 0, 2)
_INPUT_PREFIX = "INPUT_JSON\n"
# The POSIX file-type bits of st_mode, which Windows reports alike.
_FILE_TYPE = 0o170000
_REGULAR_FILE = 0o100000
# The ci.yml form; a shown command names a run and a revision, never a
# filter.
_REPLAY_HEAD = (
    "docker compose --profile pilot run --rm lab score --run-dir "
    "/workspace/results/"
)
_REPLAY_TAIL = " --check --code-revision "
_IDENTITY = (
    "environment_hash",
    "code_revision",
    "created_at",
    "prompt_hash",
    "model_hash",
    "data_hash",
)
_ENVIRONMENT = (
    "tshark_version",
    "executable_sha256",
    "runner_source_sha256",
    "identity_scope",
)

Src = list[object]
Node = dict[str, object]
Document = dict[str, object]
Rows = list[dict[str, object]]


class ExportError(Exception):
    """An input the exporter cannot read; the process exits 2."""

    exit_status = 2

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ContractError(ExportError):
    """Committed files that break the data contract; the process exits 1."""

    exit_status = 1


def _refuse_constant(name: str) -> NoReturn:
    raise ExportError("schema_invalid", f"JSON constant {name} is refused")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ExportError("schema_invalid", f"Duplicate JSON key {key!r}")
        document[key] = value
    return document


def parse_json(text: str, where: str) -> object:
    """Parses JSON, refusing NaN, Infinity and duplicate keys."""
    try:
        return json.loads(
            text,
            parse_constant=_refuse_constant,
            object_pairs_hook=_unique_keys,
        )
    except json.JSONDecodeError:
        raise ExportError("schema_invalid", f"{where} is not JSON") from None


def _obj(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ExportError("schema_invalid", f"{where} is not an object")
    return cast(dict[str, object], value)


def _arr(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise ExportError("schema_invalid", f"{where} is not an array")
    return cast(list[object], value)


def _text(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise ExportError("schema_invalid", f"{where} is not a string")
    return value


def _int(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExportError("schema_invalid", f"{where} is not an integer")
    return value


def _ints(value: object, where: str) -> list[int]:
    return [_int(item, where) for item in _arr(value, where)]


def check_path(path: str) -> str:
    """Returns a repository path the exporter may read, or refuses it.

    Args:
        path: A slash-separated path relative to the repository root.

    Returns:
        The same path.

    Raises:
        ExportError: With code ``path_refused`` for an absolute path, a
            backslash, a drive, an empty or dot segment, or a path outside
            the allowed roots.
    """
    if (
        not path
        or "\\" in path
        or ":" in path
        or any(part in ("", ".", "..") for part in path.split("/"))
    ):
        raise ExportError("path_refused", f"{path!r} is not a clean path")
    if path != FREEZE and not path.startswith(_ROOTS):
        raise ExportError("path_refused", f"{path!r} is outside the roots")
    return path


def pointer(*tokens: str | int) -> str:
    """Builds an RFC 6901 pointer from object keys and array indexes."""
    return "".join(
        "/" + str(token).replace("~", "~0").replace("/", "~1")
        for token in tokens
    )


def _unescape(path: str) -> list[str]:
    return [
        token.replace("~1", "/").replace("~0", "~")
        for token in path[1:].split("/")
    ]


def pointer_get(document: object, path: str) -> object:
    """Resolves an RFC 6901 pointer, refusing any missing step."""
    if not path:
        return document
    if not path.startswith("/"):
        raise ExportError("pointer_invalid", f"{path!r} is not a pointer")
    value = document
    for key in _unescape(path):
        if isinstance(value, dict) and key in value:
            value = cast(dict[str, object], value)[key]
        elif (
            isinstance(value, list)
            and _INDEX.fullmatch(key)
            and int(key) < len(cast(list[object], value))
        ):
            value = cast(list[object], value)[int(key)]
        else:
            raise ExportError("pointer_invalid", f"{path!r} is missing")
    return value


def cap_text(text: str, limit: int) -> str:
    """Cuts text to at most ``limit`` UTF-8 bytes at a character boundary."""
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise ExportError("schema_invalid", "A text is not UTF-8") from None
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "ignore")


def run_slug(run_id: str) -> str:
    """Names a run in a URL; injective because run ids hold no underscore."""
    return run_id.replace(".", "_")


def check_run_id(run_id: str) -> str:
    """Returns a run id that matches the result-name pattern, or fails."""
    if not _RUN_ID.fullmatch(run_id):
        raise ContractError("run_id_invalid", f"{run_id!r} is not a run id")
    return run_id


def check_segment(value: str) -> str:
    """Returns a dot-free route segment, or fails."""
    if not _SEGMENT.fullmatch(value):
        raise ContractError("route_unsafe", f"{value!r} is no route segment")
    return value


def ptr(path: str, *tokens: str | int) -> Src:
    """Builds a ``ptr`` source."""
    return ["ptr", path, pointer(*tokens)]


def row(path: str, keys: Mapping[str, str], *tokens: str | int) -> Src:
    """Builds a ``row`` source."""
    return ["row", path, dict(keys), pointer(*tokens)]


def count(
    path: str, where: Mapping[str, Sequence[str]], at: str | None = None
) -> Src:
    """Builds a ``count`` source over JSONL rows or the array at ``at``."""
    return ["count", path, at, {key: list(each) for key, each in where.items()}]


def frame_src(row_index: int, frame: int, key: str) -> Src:
    """Builds a ``ptr`` source into one frame of the frame tables."""
    return ptr(CAPTURES, "probes", row_index, "frames", frame - 1, key)


class _Scope:
    """Collects the paths a block of work touches, cached or not."""

    def __init__(self, scopes: list[set[str]]) -> None:
        self._scopes = scopes
        self.paths: set[str] = set()

    def __enter__(self) -> set[str]:
        self._scopes.append(self.paths)
        return self.paths

    def __exit__(self, *_: object) -> None:
        self._scopes[:] = [
            paths for paths in self._scopes if paths is not self.paths
        ]


class Repo:
    """Reads committed files under the allowed roots and resolves sources.

    Every file read is recorded with its SHA-256, so site.json can list the
    exact bytes the export depends on.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.inputs: dict[str, str] = {}
        self._bytes: dict[str, bytes] = {}
        # JSON documents, JSONL row lists and INPUT_JSON payloads by key.
        self._parsed: dict[object, object] = {}
        self._index: dict[tuple[str, tuple[str, ...]], dict[object, Rows]] = {}
        self._scopes: list[set[str]] = []
        self._directories: dict[str, Path] = {}

    def scope(self) -> _Scope:
        """Returns a context that collects every path touched inside it."""
        return _Scope(self._scopes)

    def _directory(self, directory: str) -> Path:
        """Resolves a directory once, refusing one that leaves the root."""
        if directory not in self._directories:
            resolved = (self.root / directory).resolve()
            if not resolved.is_relative_to(self.root):
                raise ExportError(
                    "path_refused", f"{directory!r} leaves the repository"
                )
            self._directories[directory] = resolved
        return self._directories[directory]

    def _regular(self, path: str) -> tuple[Path, int] | None:
        """Returns a regular file's location and size, None when absent.

        One lstat per file: the directories are resolved once, and a
        symbolic link or any other non-regular entry is refused.
        """
        directory, _, name = path.rpartition("/")
        location = self._directory(directory) / name
        try:
            status = location.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        if status.st_mode & _FILE_TYPE != _REGULAR_FILE:
            raise ExportError("input_invalid", f"{path} is not a regular file")
        return location, status.st_size

    def exists(self, path: str) -> bool:
        """Says whether a file exists at an allowed path; reads nothing."""
        return self._regular(check_path(path)) is not None

    def names(self, directory: str) -> list[str]:
        """Lists the JSON entry names of an allowed directory, sorted."""
        location = self._directory(check_path(directory))
        if not location.is_dir():
            return []
        return sorted(
            entry.name
            for entry in location.iterdir()
            if entry.name.endswith(".json")
        )

    def data(self, path: str, *, note: bool = False) -> bytes:
        """Reads one file's bytes within the input ceiling and records it."""
        if not (note and path == BAKEOFF_NOTE):
            check_path(path)
        for paths in self._scopes:
            paths.add(path)
        if path in self._bytes:
            return self._bytes[path]
        found = self._regular(path)
        if found is None:
            raise ExportError("input_missing", f"{path} is missing")
        if found[1] > MAX_INPUT_BYTES:
            raise ExportError("input_too_large", f"{path} exceeds 32 MiB")
        data = found[0].read_bytes()
        self._bytes[path] = data
        self.inputs[path] = hashlib.sha256(data).hexdigest()
        return data

    def text(self, path: str, *, note: bool = False) -> str:
        """Reads one file as UTF-8."""
        try:
            return self.data(path, note=note).decode("utf-8")
        except UnicodeDecodeError:
            raise ExportError(
                "schema_invalid", f"{path} is not UTF-8"
            ) from None

    def json(self, path: str) -> object:
        """Reads one JSON file."""
        text = self.text(path)
        if path not in self._parsed:
            self._parsed[path] = parse_json(text, path)
        return self._parsed[path]

    def rows(self, path: str) -> Rows:
        """Reads one JSONL file; every non-empty line is an object."""
        text = self.text(path)
        if path not in self._parsed:
            self._parsed[path] = [
                _obj(parse_json(line, path), f"{path} row")
                for line in text.split("\n")
                if line
            ]
        return cast(Rows, self._parsed[path])

    def find_row(self, path: str, keys: Mapping[str, object]) -> Document:
        """Returns the one JSONL row whose keys hold the given values."""
        names = tuple(sorted(keys))
        lines = self.rows(path)
        if (path, names) not in self._index:
            index: dict[object, Rows] = {}
            for item in lines:
                found = tuple(item.get(name) for name in names)
                index.setdefault(found, []).append(item)
            self._index[(path, names)] = index
        matches = self._index[(path, names)].get(
            tuple(keys[name] for name in names), []
        )
        if len(matches) != 1:
            raise ContractError(
                "row_not_unique",
                f"{path}: {len(matches)} rows match {dict(keys)}",
            )
        return matches[0]

    def payload(self, path: str, item_id: str) -> object:
        """Returns the INPUT_JSON object of one prepared prompt."""
        prompts = _arr(
            _obj(self.json(path), path).get("prompts"), f"{path} prompts"
        )
        if (path, item_id) in self._parsed:
            return self._parsed[(path, item_id)]
        matches = [
            prompt
            for prompt in (_obj(item, f"{path} prompt") for item in prompts)
            if prompt.get("item_id") == item_id
        ]
        if len(matches) != 1:
            raise ContractError(
                "prompt_not_unique", f"{path}: {item_id} is not one prompt"
            )
        content = _text(
            pointer_get(matches[0], "/messages/1/content"),
            f"{path} {item_id} user message",
        )
        if not content.startswith(_INPUT_PREFIX):
            raise ExportError(
                "schema_invalid", f"{path} {item_id} has no INPUT_JSON"
            )
        payload = parse_json(content[len(_INPUT_PREFIX) :], path)
        self._parsed[(path, item_id)] = payload
        return payload

    def resolve(self, src: Src) -> object:
        """Evaluates one source against the committed files.

        Args:
            src: One source op, as the module docstring lists.

        Returns:
            The value the source names.

        Raises:
            ExportError: When the op is malformed or a step is missing.
        """
        op = src[0] if src else None
        if not isinstance(op, str) or _ARITY.get(op) != len(src):
            raise ExportError("source_invalid", f"Malformed source {src!r}")
        handler: Callable[[Src], object] = getattr(self, f"_op_{op}")
        return handler(src)

    def _op_ptr(self, src: Src) -> object:
        return pointer_get(
            self.json(_text(src[1], "path")), _text(src[2], "pointer")
        )

    def _op_row(self, src: Src) -> object:
        found = self.find_row(_text(src[1], "path"), _obj(src[2], "row keys"))
        return pointer_get(found, _text(src[3], "pointer"))

    def _op_count(self, src: Src) -> object:
        path = _text(src[1], "path")
        if src[2] is None:
            items: list[object] = list(self.rows(path))
        else:
            at = _text(src[2], "pointer")
            items = _arr(pointer_get(self.json(path), at), f"{path} {at}")
        where = {
            key: _arr(values, "count values")
            for key, values in _obj(src[3], "count keys").items()
        }
        return sum(
            1
            for item in items
            if all(
                _obj(item, f"{path} item").get(key) in values
                for key, values in where.items()
            )
        )

    def _op_len(self, src: Src) -> object:
        return len(_arr(self._op_ptr(src), f"{src[1]} {src[2]}"))

    def _op_sum(self, src: Src) -> object:
        return sum(
            _int(self.resolve(cast(Src, item)), "a sum operand")
            for item in _arr(src[1], "sum operands")
        )

    def _op_sha256(self, src: Src) -> object:
        return hashlib.sha256(self.data(_text(src[1], "path"))).hexdigest()

    def _op_input(self, src: Src) -> object:
        return pointer_get(
            self.payload(_text(src[1], "path"), _text(src[2], "item_id")),
            _text(src[3], "pointer"),
        )

    def t(self, src: Src) -> Node:
        """Returns a sourced string node."""
        return {"t": _text(self.resolve(src), f"{src}"), "src": src}

    def v(self, src: Src) -> Node:
        """Returns a sourced number, boolean or integer-array node."""
        value = self.resolve(src)
        if isinstance(value, list):
            _ints(cast(list[object], value), f"{src}")
        elif not isinstance(value, (bool, int, float)):
            raise ExportError("schema_invalid", f"{src} is not a number")
        return {"v": value, "src": src}

    def opt_t(self, src: Src) -> Node | None:
        """Returns a sourced string node, or None for a JSON null."""
        return None if self.resolve(src) is None else self.t(src)

    def opt_v(self, src: Src) -> Node | None:
        """Returns a sourced number node, or None for a JSON null."""
        return None if self.resolve(src) is None else self.v(src)

    def texts(
        self, path: str, keys: Sequence[str], *at: str | int
    ) -> dict[str, Node]:
        """Sources several strings that sit side by side."""
        return {key: self.t(ptr(path, *at, key)) for key in keys}

    def numbers(
        self, path: str, keys: Sequence[str], *at: str | int
    ) -> dict[str, Node]:
        """Sources several numbers that sit side by side."""
        return {key: self.v(ptr(path, *at, key)) for key in keys}

    def listed(self, path: str, *at: str | int) -> list[Node]:
        """Sources every string of an array."""
        items = _arr(self.resolve(ptr(path, *at)), f"{path} {pointer(*at)}")
        return [self.t(ptr(path, *at, index)) for index in range(len(items))]

    def raw(self, src: Src) -> tuple[Node, bool]:
        """Returns untrusted model text capped at ``RAW_TEXT_CAP`` bytes."""
        value = _text(self.resolve(src), f"{src}")
        capped = cap_text(value, RAW_TEXT_CAP)
        return {"t": capped, "src": src, "cap": RAW_TEXT_CAP}, capped != value


@dataclass(frozen=True)
class Condition:
    """One prompt condition of a run, as its prepare.json lists it."""

    index: int
    label: str
    typed: bool
    prepared: str
    completions: str


class Captures:
    """The committed frame tables of the curated captures."""

    def __init__(self, repo: Repo) -> None:
        document = _obj(repo.json(CAPTURES), CAPTURES)
        self.position: dict[str, int] = {}
        self.frames: dict[str, int] = {}
        for index, item in enumerate(_arr(document.get("probes"), CAPTURES)):
            probe = _obj(item, f"{CAPTURES} probe")
            probe_id = _text(probe.get("probe_id"), f"{CAPTURES} probe_id")
            frames = _arr(probe.get("frames"), f"{CAPTURES} frames")
            for number, frame in enumerate(frames, 1):
                if _obj(frame, f"{CAPTURES} frame").get("n") != number:
                    raise ContractError(
                        "frames_unnumbered", f"{probe_id} skips frame {number}"
                    )
            self.position[probe_id] = index
            self.frames[probe_id] = len(frames)

    def index(self, probe_id: str) -> int:
        """Returns the row of a probe, or fails."""
        if probe_id not in self.position:
            raise ContractError("probe_unknown", f"{probe_id} has no frames")
        return self.position[probe_id]

    def check(self, probe_id: str, frames: Sequence[int], where: str) -> int:
        """Returns a probe's row once every frame number lies in it."""
        index = self.index(probe_id)
        if any(not 1 <= frame <= self.frames[probe_id] for frame in frames):
            raise ContractError(
                "frame_out_of_range", f"{where} {probe_id} frame numbers"
            )
        return index


class Run:
    """One shown run's committed files, checked against the contract."""

    def __init__(self, repo: Repo, run_id: str) -> None:
        self.run_id = check_run_id(run_id)
        check_segment(self.slug)
        self.conditions = self._conditions(repo)
        document = _obj(repo.json(self.summary), self.summary)
        if document.get("run") != run_id:
            raise ContractError(
                "run_mismatch", f"{self.summary} names another run"
            )
        if document.get("split") != self.split:
            raise ContractError(
                "split_mismatch", f"{self.summary} names another split"
            )
        self.rows = self._rows(repo)
        self.cases = self._cases()
        self.completion = self._completions(repo)
        self._check_trees(repo)
        self._check_means(_obj(document.get("conditions"), self.summary))

    @property
    def slug(self) -> str:
        """The run's URL segment."""
        return run_slug(self.run_id)

    @property
    def split(self) -> str:
        """The split the run id names."""
        return self.run_id.split("-", 1)[0]

    @property
    def base(self) -> str:
        """The run directory."""
        return f"{RESULTS}/{self.run_id}"

    @property
    def prepare(self) -> str:
        """The run's prepare manifest."""
        return f"{self.base}/prepare.json"

    @property
    def summary(self) -> str:
        """The run's scored summary."""
        return f"{self.base}/scored/summary.json"

    @property
    def manifest(self) -> str:
        """The run's score manifest."""
        return f"{self.base}/scored/score_manifest.json"

    @property
    def outcomes(self) -> str:
        """The run's outcome rows."""
        return f"{self.base}/scored/outcomes.jsonl"

    @property
    def labels(self) -> list[str]:
        """The condition labels in prepare order."""
        return [condition.label for condition in self.conditions]

    def condition(self, label: str) -> Condition:
        """Returns one condition by label."""
        return self.conditions[self.labels.index(label)]

    def receipt(self, label: str, item_id: str) -> str:
        """The path of one executed answer's receipt."""
        return f"{self.base}/scored/receipts/{label}/{item_id}.json"

    def intent(self, label: str, item_id: str) -> str:
        """The path of one typed ready answer's intent."""
        return f"{self.base}/scored/intents/{label}/{item_id}.json"

    def spec(self, case_id: str) -> str:
        """The path of one case's gold specification."""
        return f"{self.base}/scored/specs/{case_id}.json"

    def outcome(self, label: str, item_id: str) -> str:
        """Returns one item's outcome."""
        return _text(self.rows[(label, item_id)].get("outcome"), "outcome")

    def executed(self) -> list[tuple[str, str]]:
        """Every executed answer, as (label, item id), sorted."""
        return sorted(
            key for key in self.rows if self.outcome(*key) in _EXECUTED
        )

    def count(self, where: Mapping[str, Sequence[str]]) -> Src:
        """Builds a count over this run's outcome rows."""
        return count(self.outcomes, where)

    def _conditions(self, repo: Repo) -> list[Condition]:
        items = _arr(
            _obj(repo.json(self.prepare), self.prepare).get("conditions"),
            f"{self.prepare} conditions",
        )
        conditions: list[Condition] = []
        for index, item in enumerate(items):
            entry = _obj(item, f"{self.prepare} condition")
            label = check_segment(_text(entry.get("label"), "label"))
            relative = _text(entry.get("path"), f"{label} path")
            name = relative.removeprefix("prepared/")
            if name == relative or "/" in name or not name.endswith(".json"):
                raise ExportError("schema_invalid", f"{label} path {relative}")
            conditions.append(
                Condition(
                    index=index,
                    label=label,
                    typed=entry.get("output_contract") == "typed_ir",
                    prepared=f"{self.base}/prepared/{name}",
                    completions=f"{self.base}/completions/{name}",
                )
            )
        labels = [condition.label for condition in conditions]
        if len(set(labels)) != len(labels):
            raise ContractError("condition_repeated", self.prepare)
        return conditions

    def _rows(self, repo: Repo) -> dict[tuple[str, str], Document]:
        labels = set(self.labels)
        found: dict[tuple[str, str], Document] = {}
        for item in repo.rows(self.outcomes):
            label = _text(item.get("condition"), f"{self.outcomes} condition")
            item_id = check_segment(
                _text(item.get("item_id"), f"{self.outcomes} item_id")
            )
            if label not in labels or (label, item_id) in found:
                raise ContractError(
                    "row_unexpected", f"{self.run_id} {label} {item_id}"
                )
            found[(label, item_id)] = item
        return found

    def _cases(self) -> dict[str, tuple[str, ...]]:
        """Maps each case to its two items, the same in every condition."""
        members: dict[str, set[str]] = {}
        owner: dict[str, str] = {}
        for (_, item_id), item in self.rows.items():
            case_id = check_segment(_text(item.get("case_id"), "case_id"))
            if owner.setdefault(item_id, case_id) != case_id:
                raise ContractError(
                    "case_mismatch", f"{self.run_id} {item_id} has two cases"
                )
            members.setdefault(case_id, set()).add(item_id)
        for case_id, items in members.items():
            if len(items) != 2:
                raise ContractError(
                    "case_items",
                    f"{self.run_id} {case_id} has {len(items)} items",
                )
        missing = [
            (label, item_id)
            for label in self.labels
            for item_id in owner
            if (label, item_id) not in self.rows
        ]
        if missing:
            raise ContractError("row_missing", f"{self.run_id} {missing[0]}")
        return {
            case_id: tuple(sorted(items)) for case_id, items in members.items()
        }

    def _completions(self, repo: Repo) -> dict[tuple[str, str], int]:
        positions: dict[tuple[str, str], int] = {}
        for condition in self.conditions:
            path = condition.completions
            items = _arr(_obj(repo.json(path), path).get("completions"), path)
            for index, item in enumerate(items):
                item_id = _obj(item, path).get("item_id")
                key = (condition.label, _text(item_id, f"{path} item_id"))
                if key in positions:
                    raise ContractError(
                        "completion_repeated", f"{self.run_id} {key}"
                    )
                positions[key] = index
        missing = sorted(set(self.rows) - set(positions))
        if missing:
            raise ContractError(
                "completion_missing", f"{self.run_id} {missing[0]}"
            )
        return positions

    def _check_trees(self, repo: Repo) -> None:
        """Matches receipts to executed rows and intents to typed answers."""
        expected = {
            "receipts": set(self.executed()),
            "intents": {
                key
                for key in self.rows
                if self.condition(key[0]).typed
                and self.outcome(*key) in _READY_ANSWERS
            },
        }
        for tree, wanted in expected.items():
            found = {
                (label, name.removesuffix(".json"))
                for label in self.labels
                for name in repo.names(f"{self.base}/scored/{tree}/{label}")
            }
            if found != wanted:
                raise ContractError(
                    f"{tree}_mismatch",
                    f"{self.run_id}: {len(wanted - found)} rows lack one of "
                    f"{tree}, {len(found - wanted)} of {tree} lack a row",
                )

    def _check_means(self, conditions: Mapping[str, object]) -> None:
        """Checks ready counts against the summary's case means."""
        for label in self.labels:
            ready = [
                self.outcome(each, item_id)
                for (each, item_id), item in self.rows.items()
                if each == label and item.get("gold_status") == "ready"
            ]
            metrics = _obj(conditions.get(label), f"{self.summary} {label}")
            for metric, outcome in _MEAN_CHECKS:
                block = metrics.get(metric)
                if block is None or not ready:
                    continue
                value = _obj(block, f"{label} {metric}").get("value")
                share = ready.count(outcome) / len(ready)
                if not isinstance(value, (int, float)) or (
                    abs(share - value) > MEAN_TOLERANCE
                ):
                    raise ContractError(
                        "mean_mismatch",
                        f"{self.run_id} {label} {metric} differs from the "
                        "ready count",
                    )


@dataclass(frozen=True)
class Shown:
    """A run shown on the site, with its role and its ranking entry."""

    run: Run
    role: str
    entry: str | None = None


@dataclass(frozen=True)
class Selection:
    """The shown runs, the Reel pool and the test phase."""

    ranking: str
    rows: list[Shown]
    tests: list[Shown]
    not_run: list[tuple[str, int]]
    pool: list[Shown]
    test_phase: bool
    registered: bool

    @property
    def shown(self) -> list[Shown]:
        """Every shown run, selection rows first."""
        return self.rows + self.tests


@dataclass(frozen=True)
class Registration:
    """What test-runs.json registers: runs by role, not-run ids, winners."""

    runs: list[tuple[str, str]]
    not_run: list[str]
    winners: dict[str, str]


def latest_ranking(repo: Repo) -> str:
    """Returns the lexicographically last bake-off ranking."""
    names = [
        name for name in repo.names(RANKING_DIR) if name.startswith("ranking-")
    ]
    if not names:
        raise ExportError("ranking_missing", "No bake-off ranking is committed")
    return f"{RANKING_DIR}/{names[-1]}"


def _ranking_entries(
    repo: Repo, ranking: str
) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    """Lists (role, entry pointer, run id) in display order, and winners."""
    document = _obj(repo.json(ranking), ranking)
    anchor = _obj(document.get("anchor"), f"{ranking} anchor")
    entries = [("anchor", "/anchor", _text(anchor.get("run_id"), "anchor"))]
    winners: dict[str, str] = {}
    slots = _obj(document.get("slots"), f"{ranking} slots")
    for slot in _SLOTS:
        block = _obj(slots.get(slot), f"{ranking} {slot}")
        candidates = [
            _obj(item, f"{ranking} {slot}")
            for item in _arr(block.get("candidates"), f"{ranking} {slot}")
        ]
        ranked = sorted(
            (_int(item.get("rank"), f"{slot} rank"), index)
            for index, item in enumerate(candidates)
        )
        if len({rank for rank, _ in ranked}) != len(ranked):
            raise ContractError("rank_repeated", f"{ranking} {slot}")
        entries.extend(
            (
                slot,
                pointer("slots", slot, "candidates", index),
                _text(candidates[index].get("run_id"), f"{slot} run_id"),
            )
            for _, index in ranked
        )
        winner = block.get("provisional_winner")
        if winner is not None:
            winners[slot] = _text(winner, f"{slot} provisional_winner")
    return entries, winners


def _note_names(note: str, run_id: str) -> bool:
    edge = re.escape(run_id)
    found = re.search(rf"(?<![A-Za-z0-9._-]){edge}(?![A-Za-z0-9_-])", note)
    return found is not None


def read_registration(repo: Repo, selected: set[str]) -> Registration:
    """Reads test-runs.json and checks it against the ranking and the note.

    Args:
        repo: The repository.
        selected: The dev run ids the ranking shows.

    Returns:
        The registered runs by role, the not-run ids and the slot winners.

    Raises:
        ContractError: For an unknown or repeated role, a missing A/A pass,
            a winner the ranking does not show, a not-run id that is not
            registered, or a run id the bake-off note does not name.
    """
    document = _obj(repo.json(TEST_RUNS), TEST_RUNS)
    runs: list[tuple[str, str]] = []
    winners: dict[str, str] = {}
    for item in _arr(document.get("runs"), f"{TEST_RUNS} runs"):
        entry = _obj(item, f"{TEST_RUNS} run")
        role = _text(entry.get("role"), f"{TEST_RUNS} role")
        run_id = check_run_id(_text(entry.get("run_id"), f"{role} run_id"))
        if role not in _TEST_ROLES or role in dict(runs):
            raise ContractError("role_invalid", f"{TEST_RUNS} {role!r}")
        if not run_id.startswith("test-"):
            raise ContractError("split_mismatch", f"{TEST_RUNS} {run_id}")
        if role in _SLOTS:
            dev_run = check_run_id(
                _text(entry.get("dev_run_id"), f"{role} dev_run_id")
            )
            if dev_run not in selected:
                raise ContractError("pool_unshown", f"{dev_run} is not shown")
            winners[role] = dev_run
        runs.append((role, run_id))
    if not {"pass_a", "pass_b"} <= set(dict(runs)):
        raise ContractError("role_missing", f"{TEST_RUNS} lacks the A/A pair")
    listed = {run_id for _, run_id in runs}
    not_run = [
        _text(item, f"{TEST_RUNS} not_run")
        for item in _arr(document.get("not_run", []), f"{TEST_RUNS} not_run")
    ]
    if not set(not_run) <= listed or len(set(not_run)) != len(not_run):
        raise ContractError("not_run_invalid", f"{TEST_RUNS} not_run")
    note = repo.text(BAKEOFF_NOTE, note=True)
    for run_id in sorted(listed):
        if not _note_names(note, run_id):
            raise ContractError(
                "run_unregistered", f"{run_id} is not in {BAKEOFF_NOTE}"
            )
    return Registration(runs, not_run, winners)


def _claim(seen: dict[str, str], run: Run) -> Run:
    """Refuses a run listed twice or a slug two runs share."""
    if run.slug in seen:
        raise ContractError(
            "slug_collision",
            f"{run.run_id} and {seen[run.slug]} share the slug {run.slug}",
        )
    seen[run.slug] = run.run_id
    return run


def _check_ranking_count(repo: Repo, ranking: str, shown: Shown) -> None:
    """Checks the ranking's selection count against the outcome rows."""
    entry = cast(str, shown.entry)
    ranked = repo.resolve(ptr(ranking, *_unescape(entry), "strong_exact_ready"))
    counted = repo.resolve(
        shown.run.count({"gold_status": ["ready"], "outcome": ["strong_exact"]})
    )
    if ranked != counted:
        raise ContractError(
            "ranking_mismatch",
            f"{shown.run.run_id}: the ranking counts {ranked} strong-exact "
            f"ready items, the outcome rows {counted}",
        )


def _summary_exists(repo: Repo, run_id: str) -> bool:
    return repo.exists(f"{RESULTS}/{check_run_id(run_id)}/scored/summary.json")


def _test_rows(
    repo: Repo, registration: Registration, seen: dict[str, str]
) -> tuple[list[Shown], list[tuple[str, int]]] | None:
    """Returns the test rows once every registered run is settled."""
    for run_id in registration.not_run:
        if _summary_exists(repo, run_id):
            raise ContractError(
                "not_run_scored", f"{run_id} is scored but listed as not run"
            )
    if not all(
        run_id in registration.not_run or _summary_exists(repo, run_id)
        for _, run_id in registration.runs
    ):
        return None
    tests: list[Shown] = []
    not_run: list[tuple[str, int]] = []
    for role in _TEST_ROLES:
        for run_id in (
            each for name, each in registration.runs if name == role
        ):
            if run_id in registration.not_run:
                not_run.append((role, registration.not_run.index(run_id)))
            else:
                tests.append(Shown(_claim(seen, Run(repo, run_id)), role))
    return tests, not_run


def select(repo: Repo) -> Selection:
    """Computes the shown runs, the pool and the test phase from files.

    Args:
        repo: The repository.

    Returns:
        The selection rows in ranking order, the test rows once the test
        phase is on, and the Reel pool: pass A and the slot winners' test
        runs in the test phase, else the dev anchor and the winners' passes.

    Raises:
        ContractError: When the ranking or registration breaks the contract.
    """
    ranking = latest_ranking(repo)
    entries, winners = _ranking_entries(repo, ranking)
    seen: dict[str, str] = {}
    rows: list[Shown] = []
    for role, entry, run_id in entries:
        if not run_id.startswith("dev-"):
            raise ContractError("split_mismatch", f"{ranking} {run_id}")
        rows.append(Shown(_claim(seen, Run(repo, run_id)), role, entry))
        _check_ranking_count(repo, ranking, rows[-1])
    registered = repo.exists(TEST_RUNS)
    settled = None
    if registered:
        registration = read_registration(
            repo, {item.run.run_id for item in rows}
        )
        winners = registration.winners
        settled = _test_rows(repo, registration, seen)
    tests, not_run = settled if settled is not None else ([], [])
    return Selection(
        ranking=ranking,
        rows=rows,
        tests=tests,
        not_run=not_run,
        pool=_pool(rows, tests, winners, test_phase=settled is not None),
        test_phase=settled is not None,
        registered=registered,
    )


def _pool(
    rows: Sequence[Shown],
    tests: Sequence[Shown],
    winners: Mapping[str, str],
    *,
    test_phase: bool,
) -> list[Shown]:
    """Pass A and the winners' test runs, else the anchor and winners."""
    if test_phase:
        return [item for item in tests if item.role != "pass_b"]
    shown = {item.run.run_id: item for item in rows}
    pool = [rows[0]]
    for slot in _SLOTS:
        if slot not in winners:
            continue
        if winners[slot] not in shown:
            raise ContractError("pool_unshown", f"{winners[slot]} is not shown")
        found = shown[winners[slot]]
        pool.append(Shown(found.run, slot, found.entry))
    return pool


def segments(repo: Repo, run: Run, label: str | None = None) -> Node:
    """Counts ready items and each ready outcome; they must add up."""
    where: dict[str, list[str]] = {"gold_status": ["ready"]}
    if label is not None:
        where["condition"] = [label]
    ready = repo.v(run.count(where))
    parts = {
        outcome: repo.v(run.count({**where, "outcome": [outcome]}))
        for outcome in SEGMENTS
    }
    if sum(cast(int, node["v"]) for node in parts.values()) != ready["v"]:
        raise ContractError(
            "segments_mismatch",
            f"{run.run_id}: ready outcomes do not add up to the ready items",
        )
    return {"ready": ready, "segments": parts}


def run_header(repo: Repo, run: Run) -> Node:
    """The run's slug, id and model id."""
    return {
        "run": run.slug,
        "run_id": repo.t(ptr(run.summary, "run")),
        "model_id": repo.t(ptr(run.summary, "model_id")),
    }


def _served(repo: Repo, run: Run) -> Node:
    return {
        "providers": repo.listed(
            run.summary, "effective_settings", "providers"
        ),
        "provider_reported_usd": repo.opt_v(
            ptr(run.summary, "provider_reported_usd")
        ),
        "charged_usd_upper_bound": repo.opt_v(
            ptr(run.summary, "charged_usd_upper_bound")
        ),
        "items": repo.v(ptr(run.summary, "item_count")),
    }


def _selection_row(repo: Repo, ranking: str, shown: Shown) -> Node:
    tokens = _unescape(cast(str, shown.entry))
    entry = _obj(repo.resolve(ptr(ranking, *tokens)), cast(str, shown.entry))
    ranked = shown.role != "anchor"
    return {
        **run_header(repo, shown.run),
        **_served(repo, shown.run),
        **segments(repo, shown.run),
        "slot": shown.role,
        "rank": repo.v(ptr(ranking, *tokens, "rank")) if ranked else None,
        "verdict": (
            repo.t(ptr(ranking, *tokens, "verdict")) if ranked else None
        ),
        "run_gates": (
            repo.t(ptr(ranking, *tokens, "run_gates"))
            if ranked and "run_gates" in entry
            else None
        ),
        "strong_exact_ready": repo.v(
            ptr(ranking, *tokens, "strong_exact_ready")
        ),
    }


def _interval(repo: Repo, path: str, *at: str | int) -> Node | None:
    if repo.resolve(ptr(path, *at)) is None:
        return None
    return {
        key: repo.opt_v(ptr(path, *at, key)) for key in ("value", "low", "high")
    }


def _test_row(repo: Repo, shown: Shown) -> Node:
    run = shown.run
    comparisons = _arr(
        repo.resolve(ptr(run.summary, "comparisons")), "comparisons"
    )
    return {
        **run_header(repo, run),
        **_served(repo, run),
        "role": shown.role,
        "conditions": [
            {
                "label": repo.t(
                    ptr(run.prepare, "conditions", condition.index, "label")
                ),
                "metrics": {
                    metric: _interval(
                        repo, run.summary, "conditions", condition.label, metric
                    )
                    for metric in _TEST_METRICS
                },
                **segments(repo, run, condition.label),
            }
            for condition in run.conditions
        ],
        "comparisons": [
            {
                **repo.texts(
                    run.summary,
                    ("first", "second", "metric"),
                    "comparisons",
                    index,
                ),
                "difference": _interval(
                    repo, run.summary, "comparisons", index, "difference"
                ),
                **repo.numbers(
                    run.summary,
                    (
                        "discordant_cases",
                        "first_better_cases",
                        "second_better_cases",
                        "inconclusive",
                    ),
                    "comparisons",
                    index,
                ),
            }
            for index in range(len(comparisons))
        ],
    }


def build_board(repo: Repo, selection: Selection) -> Document:
    """Dev counts as model selection; test rates only from summaries."""
    test: Node | None = None
    if selection.test_phase:
        test = {
            "rows": [_test_row(repo, shown) for shown in selection.tests],
            "not_run": [
                {
                    "role": role,
                    "run_id": repo.t(ptr(TEST_RUNS, "not_run", index)),
                }
                for role, index in selection.not_run
            ],
            "aa": None,
            "repair": None,
        }
    return {
        "schema": "web-board/1.0",
        "selection": {
            "ranking": selection.ranking,
            "status": repo.opt_t(ptr(selection.ranking, "status")),
            "rows": [
                _selection_row(repo, selection.ranking, shown)
                for shown in selection.rows
            ],
        },
        "test_registered": selection.registered,
        "test": test,
    }


def ir_fields(
    repo: Repo, path: str, document: object, *at: str | int
) -> list[Node]:
    """Sources every predicate field name of an IR, in document order."""
    nodes: list[Node] = []
    if isinstance(document, dict):
        for key, value in cast(dict[str, object], document).items():
            if key == "field" and isinstance(value, str):
                nodes.append(repo.t(ptr(path, *at, key)))
            else:
                nodes.extend(ir_fields(repo, path, value, *at, key))
    elif isinstance(document, list):
        for index, value in enumerate(cast(list[object], document)):
            nodes.extend(ir_fields(repo, path, value, *at, index))
    return nodes


def spec_probes(repo: Repo, spec: str) -> dict[str, tuple[int, list[int]]]:
    """Maps each probe of a ready spec to its position and its labels."""
    probes = _arr(
        _obj(repo.json(spec), spec).get("probes", []), f"{spec} probes"
    )
    found: dict[str, tuple[int, list[int]]] = {}
    for index, item in enumerate(probes):
        probe = _obj(item, f"{spec} probe")
        found[_text(probe.get("probe_id"), f"{spec} probe_id")] = (
            index,
            _ints(probe.get("expected_frames"), f"{spec} expected_frames"),
        )
    return found


def _state(selected: bool, requested: bool) -> str:
    if selected:
        return "tp" if requested else "fp"
    return "fn" if requested else "tn"


def _disagree_node(
    repo: Repo, at: Src, row_index: int, frame: int, side: str
) -> Node:
    return {
        "side": side,
        "n": repo.v(at),
        "name": repo.t(frame_src(row_index, frame, "name")),
        "kind": repo.t(frame_src(row_index, frame, "kind")),
    }


def _probe_node(
    repo: Repo,
    captures: Captures,
    receipt: str,
    index: int,
    labelled: Mapping[str, tuple[int, list[int]]],
) -> Node:
    """Sources one probe's frame sets and derives every frame's state."""
    at = ("probes", index)
    probe = _obj(repo.resolve(ptr(receipt, *at)), f"{receipt} probe")
    probe_id = _text(probe.get("probe_id"), f"{receipt} probe_id")
    expected = _ints(probe.get("expected_frames"), "expected_frames")
    chosen = _ints(probe.get("candidate_frames"), "candidate_frames")
    sides = {
        "candidate_only": _ints(probe.get("candidate_only"), "candidate"),
        "reference_only": _ints(probe.get("reference_only"), "reference"),
    }
    row_index = captures.check(probe_id, chosen + expected, receipt)
    if (
        labelled.get(probe_id, (0, None))[1] != expected
        or sides["candidate_only"] != sorted(set(chosen) - set(expected))
        or sides["reference_only"] != sorted(set(expected) - set(chosen))
    ):
        raise ContractError(
            "receipt_inconsistent", f"{receipt} {probe_id} frame sets"
        )
    disagree = sorted(
        (frame, side, position)
        for side, frames in sides.items()
        for position, frame in enumerate(frames)
    )
    total = captures.frames[probe_id]
    return {
        "probe_id": repo.t(ptr(receipt, *at, "probe_id")),
        "exact": repo.v(ptr(receipt, *at, "exact")),
        "runtime_ms": repo.opt_v(ptr(receipt, *at, "runtime_ms")),
        "frames": repo.v(
            ["len", CAPTURES, pointer("probes", row_index, "frames")]
        ),
        "benchmark_frames": repo.v(
            ptr(CAPTURES, "probes", row_index, "benchmark_frames")
        ),
        "expected": repo.v(ptr(receipt, *at, "expected_frames")),
        "candidate": repo.v(ptr(receipt, *at, "candidate_frames")),
        "states": [
            _state(frame in chosen, frame in expected)
            for frame in range(1, total + 1)
        ],
        "disagree": [
            _disagree_node(
                repo, ptr(receipt, *at, side, position), row_index, frame, side
            )
            for frame, side, position in disagree
        ],
    }


def probe_nodes(
    repo: Repo, captures: Captures, receipt: str, spec: str
) -> list[Node]:
    """Sources each probe of a receipt; see ``_state`` for frame states.

    A state says whether the filter selected the frame and whether the
    request did: ``tp`` both, ``fp`` the filter only, ``fn`` the request
    only, ``tn`` neither.
    """
    labelled = spec_probes(repo, spec)
    probes = _arr(
        _obj(repo.json(receipt), receipt).get("probes"), f"{receipt} probes"
    )
    return [
        _probe_node(repo, captures, receipt, index, labelled)
        for index in range(len(probes))
    ]


def trace_node(
    repo: Repo, run: Run, label: str, item_id: str
) -> tuple[Node | None, str | None]:
    """Links a committed predicate trace, or says why there is none."""
    path = f"{TRACES}/{run.run_id}/{label}/{item_id}.json"
    if not repo.exists(path):
        return None, "not_traced"
    document = _obj(repo.json(path), path)
    receipt = run.receipt(label, item_id)
    if document.get("receipt_path") != receipt or document.get(
        "receipt_file_sha256"
    ) != repo.resolve(["sha256", receipt]):
        raise ContractError("trace_stale", f"{path} names other receipt bytes")
    result = document.get("result")
    if isinstance(result, dict) and (
        cast(dict[str, object], result).get("status") == "trace_limit"
    ):
        return None, "trace_limit"
    return {"path": path, "sha256": repo.t(["sha256", path])}, None


def replay_parts(repo: Repo, run: Run, receipt: str) -> list[object]:
    """The run-level offline re-score command, as text and sourced parts."""
    return [
        _REPLAY_HEAD,
        repo.t(ptr(run.summary, "run")),
        _REPLAY_TAIL,
        repo.t(ptr(receipt, "code_revision")),
    ]


def answer_node(repo: Repo, run: Run, label: str, item_id: str) -> Node:
    """The executed filter and, for a typed answer, its field names."""
    receipt = run.receipt(label, item_id)
    fields: list[Node] | None = None
    if run.condition(label).typed:
        intent = run.intent(label, item_id)
        fields = ir_fields(repo, intent, repo.json(intent))
    return {
        "filter": repo.t(ptr(receipt, "candidate_filter")),
        "fields": fields,
    }


def _environment(repo: Repo, run: Run) -> Node:
    return {
        **repo.texts(run.manifest, _ENVIRONMENT, "environment"),
        "environment_hash": repo.t(ptr(run.manifest, "environment_hash")),
        "unmeasured": repo.listed(run.manifest, "environment", "unmeasured"),
    }


def build_receipt(
    repo: Repo, captures: Captures, run: Run, label: str, item_id: str
) -> Document:
    """One executed answer: request, answer, frame states and identity."""
    condition = run.condition(label)
    receipt = run.receipt(label, item_id)
    document = _obj(repo.json(receipt), receipt)
    if document.get("run_id") != run.run_id or document.get(
        "environment_hash"
    ) != _obj(repo.json(run.manifest), run.manifest).get("environment_hash"):
        raise ContractError("receipt_inconsistent", f"{receipt} identity")
    keys = {"condition": label, "item_id": item_id}
    case_id = _text(run.rows[(label, item_id)].get("case_id"), "case_id")
    position = run.completion[(label, item_id)]
    raw, truncated = repo.raw(
        ptr(condition.completions, "completions", position, "response_text")
    )
    trace, reason = trace_node(repo, run, label, item_id)
    return {
        "schema": "web-receipt/1.0",
        "cond": label,
        "item": item_id,
        "case": case_id,
        **run_header(repo, run),
        **{
            name: repo.t(ptr(run.prepare, "conditions", condition.index, key))
            for name, key in (
                ("condition", "label"),
                ("contract", "output_contract"),
                ("retrieval", "retrieval"),
            )
        },
        **{
            key: repo.t(row(run.outcomes, keys, key))
            for key in ("item_id", "case_id", "outcome")
        },
        "request": repo.t(["input", condition.prepared, item_id, "/intent"]),
        "answer": answer_node(repo, run, label, item_id),
        "reference_filter": repo.t(ptr(receipt, "reference_filter")),
        "raw": raw,
        "raw_truncated": truncated,
        "served": {
            key: repo.opt_t(
                ptr(condition.completions, "completions", position, key)
            )
            for key in ("provider", "response_model", "finish_reason")
        },
        "latency_ms": repo.opt_v(row(run.outcomes, keys, "latency_ms")),
        "identity": {
            "sha256": repo.t(["sha256", receipt]),
            "packet_set_hash": repo.t(
                row(run.outcomes, keys, "packet_set_hash")
            ),
            **repo.texts(receipt, _IDENTITY),
        },
        "environment": _environment(repo, run),
        "probes": probe_nodes(repo, captures, receipt, run.spec(case_id)),
        "trace": trace,
        "trace_reason": reason,
        "replay": replay_parts(repo, run, receipt),
    }


def _case_probes(repo: Repo, captures: Captures, spec: str) -> list[Node]:
    probes: list[Node] = []
    for probe_id, (index, expected) in spec_probes(repo, spec).items():
        row_index = captures.check(probe_id, expected, spec)
        at = ("probes", index)
        probes.append(
            {
                **repo.texts(spec, ("probe_id", "capture_sha256"), *at),
                "frames": repo.v(
                    ["len", CAPTURES, pointer("probes", row_index, "frames")]
                ),
                "benchmark_frames": repo.v(
                    ptr(CAPTURES, "probes", row_index, "benchmark_frames")
                ),
                "expected": [
                    {
                        "n": repo.v(ptr(spec, *at, "expected_frames", place)),
                        "name": repo.t(frame_src(row_index, frame, "name")),
                    }
                    for place, frame in enumerate(expected)
                ],
            }
        )
    return probes


def _case_run(repo: Repo, run: Run, case_id: str) -> Node:
    cells: list[Node] = []
    for label in run.labels:
        for item_id in run.cases[case_id]:
            keys = {"condition": label, "item_id": item_id}
            cells.append(
                {
                    "cond": label,
                    "item": item_id,
                    "outcome": repo.t(row(run.outcomes, keys, "outcome")),
                    "receipt": run.outcome(label, item_id) in _EXECUTED,
                    **{
                        key: repo.opt_t(row(run.outcomes, keys, key))
                        for key in ("error_code", "abstention_status")
                    },
                    **{
                        key: repo.opt_v(row(run.outcomes, keys, key))
                        for key in ("slot_match", "status_match")
                    },
                }
            )
    return {**run_header(repo, run), "cells": cells}


def build_case(
    repo: Repo, captures: Captures, selection: Selection, case_id: str
) -> Document:
    """One case: gold, paraphrases and every shown run's answers."""
    runs = [item.run for item in selection.shown if case_id in item.run.cases]
    first = runs[0]
    spec = first.spec(case_id)
    for run in runs[1:]:
        if repo.data(run.spec(case_id)) != repo.data(spec):
            raise ContractError(
                "spec_mismatch", f"{run.spec(case_id)} differs from {spec}"
            )
    document = _obj(repo.json(spec), spec)
    key = "task_id" if "task_id" in document else "case_id"
    if document.get(key) != case_id:
        raise ContractError("spec_mismatch", f"{spec} names another case")
    ready = document.get("status") == "ready"
    shown_first = first.conditions[0]
    return {
        "schema": "web-case/1.0",
        "case": case_id,
        "case_id": repo.t(ptr(spec, key)),
        **repo.texts(spec, ("split", "status")),
        "intent": repo.t(ptr(spec, "intent")) if ready else None,
        "reference_filter": (
            repo.t(ptr(spec, "reference_filter")) if ready else None
        ),
        "canonical_fields": (
            ir_fields(repo, spec, document["canonical_ir"], "canonical_ir")
            if ready
            else None
        ),
        "probes": _case_probes(repo, captures, spec),
        "missing_slots": (
            repo.listed(spec, "missing_slots")
            if "missing_slots" in document
            else []
        ),
        "rationale": None if ready else repo.opt_t(ptr(spec, "rationale")),
        "paraphrases": [
            {
                "item": item_id,
                "item_id": repo.t(
                    row(
                        first.outcomes,
                        {"condition": shown_first.label, "item_id": item_id},
                        "item_id",
                    )
                ),
                "request": repo.t(
                    ["input", shown_first.prepared, item_id, "/intent"]
                ),
            }
            for item_id in first.cases[case_id]
        ],
        "conditions": [
            repo.t(ptr(first.prepare, "conditions", condition.index, "label"))
            for condition in first.conditions
        ],
        "runs": [_case_run(repo, run, case_id) for run in runs],
    }


def build_methodology(repo: Repo, selection: Selection) -> Document:
    """Conditions, bootstrap, environment, gates and what is unmeasured."""
    anchor = selection.rows[0].run
    frames = _arr(repo.resolve(ptr(CAPTURES, "probes", 0, "frames")), "frames")
    probes = _arr(repo.resolve(ptr(CAPTURES, "probes")), "probes")
    not_measured = _obj(
        repo.resolve(ptr(anchor.summary, "not_measured")), "not_measured"
    )
    return {
        "schema": "web-methodology/1.0",
        "conditions": [
            repo.texts(
                anchor.prepare,
                ("label", "output_contract", "retrieval"),
                "conditions",
                condition.index,
            )
            for condition in anchor.conditions
        ],
        "top_k": repo.v(ptr(anchor.prepare, "top_k")),
        "bootstrap": repo.numbers(
            anchor.summary,
            (
                "cases",
                "non_ready_cases",
                "resamples",
                "seed",
                "min_discordant_cases",
            ),
            "bootstrap",
        ),
        "environment": _environment(repo, anchor),
        "mutants": {
            split: repo.numbers(
                GATE,
                ("executed", "killed", "survived", "waived"),
                "counts",
                split,
            )
            for split in ("dev", "test", "all")
        },
        "mutant_categories": repo.listed(GATE, "categories"),
        "witnesses": {
            "count": repo.v(
                count(
                    CAPTURES,
                    {"kind": ["witness"]},
                    pointer("probes", 0, "frames"),
                )
            ),
            "names": [
                repo.t(frame_src(0, number, "name"))
                for number, frame in enumerate(frames, 1)
                if _obj(frame, "frame").get("kind") == "witness"
            ],
        },
        "probes": [
            {
                **repo.texts(
                    CAPTURES,
                    ("probe_id", "split", "role", "capture_sha256"),
                    "probes",
                    index,
                ),
                "frames": repo.v(
                    ["len", CAPTURES, pointer("probes", index, "frames")]
                ),
                "benchmark_frames": repo.v(
                    ptr(CAPTURES, "probes", index, "benchmark_frames")
                ),
            }
            for index in range(len(probes))
        ],
        "shortcuts": {
            name: repo.v(ptr(SHORTCUTS, *tokens))
            for name, tokens in (
                ("position_typed_fields", ("catalog", "position_typed_fields")),
                ("gold_candidates", ("gold", "candidates")),
                ("gold_flagged", ("gold", "flagged", "full")),
                ("answer_candidates", ("committed_answers", "candidates")),
                ("answers_flagged", ("committed_answers", "flagged", "full")),
            )
        },
        "not_measured": [
            {
                "key": key,
                "value": repo.t(ptr(anchor.summary, "not_measured", key)),
            }
            for key in sorted(not_measured)
        ],
        "admitted_prepares": repo.listed(FREEZE, "admitted_prepares"),
    }


@dataclass(frozen=True, order=True)
class Candidate:
    """One Reel candidate; the ordering is reel-v1's pick order."""

    disagreeing: int
    position: int
    item_id: str
    label: str


def disagreeing_src(repo: Repo, receipt: str) -> Src:
    """Sums the frames in candidate_only and reference_only of a receipt."""
    probes = _arr(
        _obj(repo.json(receipt), receipt).get("probes"), f"{receipt} probes"
    )
    return [
        "sum",
        [
            ["len", receipt, pointer("probes", index, side)]
            for index in range(len(probes))
            for side in ("candidate_only", "reference_only")
        ],
    ]


def reel_candidates(
    repo: Repo, pool: Sequence[Shown]
) -> tuple[str | None, list[Candidate]]:
    """Steps 2 and 3 of reel-v1: the first condition with candidates.

    Reads only the pool runs' outcome rows and the candidates' receipts:
    no repair outcome, feedback-probe result or predicate trace.
    """
    for label in _REEL_CONDITIONS:
        found: list[Candidate] = []
        for position, shown in enumerate(pool):
            run = shown.run
            for (each, item_id), item in sorted(run.rows.items()):
                if (
                    each == label
                    and item.get("gold_status") == "ready"
                    and run.outcome(each, item_id) == "silent_wrong"
                ):
                    receipt = run.receipt(label, item_id)
                    found.append(
                        Candidate(
                            disagreeing=_int(
                                repo.resolve(disagreeing_src(repo, receipt)),
                                "disagreeing frames",
                            ),
                            position=position,
                            item_id=item_id,
                            label=label,
                        )
                    )
        if found:
            return label, found
    return None, []


def highlight_node(repo: Repo, captures: Captures, receipt: str) -> Node:
    """Step 4 of reel-v1: the probe and the lowest frame to show first."""
    probes = _arr(
        _obj(repo.json(receipt), receipt).get("probes"), f"{receipt} probes"
    )
    for index in (place for place in _HIGHLIGHT if place < len(probes)):
        probe = _obj(probes[index], f"{receipt} probe")
        sides = [
            (frame, side, position)
            for side in ("candidate_only", "reference_only")
            for position, frame in enumerate(_ints(probe.get(side), side))
        ]
        if not sides:
            continue
        frame, side, position = min(sides)
        row_index = captures.index(
            _text(probe.get("probe_id"), f"{receipt} probe_id")
        )
        return {
            "probe": index,
            "probe_id": repo.t(ptr(receipt, "probes", index, "probe_id")),
            "frame": repo.v(ptr(receipt, "probes", index, side, position)),
            "name": repo.t(frame_src(row_index, frame, "name")),
            "kind": repo.t(frame_src(row_index, frame, "kind")),
            "filter_selects": side == "candidate_only",
            "request_selects": side == "reference_only",
        }
    raise ContractError("no_disagreement", f"{receipt} agrees on every probe")


def _reel_pick(
    repo: Repo, captures: Captures, run: Run, pick: Candidate
) -> Document:
    """The picked answer, its strips, highlight, trace and receipt panel."""
    label, item_id = pick.label, pick.item_id
    condition = run.condition(label)
    receipt = run.receipt(label, item_id)
    keys = {"condition": label, "item_id": item_id}
    case_id = _text(run.rows[(label, item_id)].get("case_id"), "case_id")
    position = run.completion[(label, item_id)]
    not_measured = _obj(
        _obj(repo.json(run.summary), run.summary).get("not_measured", {}),
        f"{run.summary} not_measured",
    )
    trace, reason = trace_node(repo, run, label, item_id)
    return {
        "pick": {
            "cond": label,
            "item": item_id,
            "case": case_id,
            **run_header(repo, run),
            "provider": repo.opt_t(
                ptr(condition.completions, "completions", position, "provider")
            ),
            "condition": repo.t(
                ptr(run.prepare, "conditions", condition.index, "label")
            ),
            "request": repo.t(
                ["input", condition.prepared, item_id, "/intent"]
            ),
            "answer": answer_node(repo, run, label, item_id),
            "reference_filter": repo.t(ptr(receipt, "reference_filter")),
            "outcome": repo.t(row(run.outcomes, keys, "outcome")),
            "disagreeing": repo.v(disagreeing_src(repo, receipt)),
        },
        "strips": probe_nodes(repo, captures, receipt, run.spec(case_id)),
        "highlight": highlight_node(repo, captures, receipt),
        "trace": trace,
        "trace_reason": reason,
        "receipt_panel": {
            "sha256": repo.t(["sha256", receipt]),
            "packet_set_hash": repo.t(
                row(run.outcomes, keys, "packet_set_hash")
            ),
            "replay": replay_parts(repo, run, receipt),
            "repair": (
                repo.t(ptr(run.summary, "not_measured", "repair_at_1"))
                if "repair_at_1" in not_measured
                else None
            ),
        },
        "repair_applies": label == "C4",
    }


def build_reel(
    repo: Repo, captures: Captures, selection: Selection
) -> Document:
    """Projects the Disproof Reel by the pre-registered rule reel-v1.

    Args:
        repo: The repository.
        captures: The committed frame tables.
        selection: The shown runs and the pool, from ``select``.

    Returns:
        The rule id, the pool, the pick with its strips, highlight, trace
        and receipt panel (or no pick when no pool answer is silent-wrong),
        one bar per pool run, the headline counts and ``inputs_sha256``,
        the SHA-256 of every input path and digest the Reel touched.
    """
    with repo.scope() as used:
        repo.json(selection.ranking)
        if selection.registered:
            repo.json(TEST_RUNS)
        pool = selection.pool
        label, candidates = reel_candidates(repo, pool)
        where: dict[str, list[str]] = {
            "gold_status": ["ready"],
            "outcome": ["silent_wrong"],
        }
        if label is not None:
            where["condition"] = [label]
        document: Document = {
            "schema": "web-reel/1.0",
            "rule": REEL_RULE,
            "phase": "test" if selection.test_phase else "dev",
            "pool": [
                {**run_header(repo, shown.run), "role": shown.role}
                for shown in pool
            ],
            "candidate_condition": label,
            "candidates": repo.v(
                ["sum", [shown.run.count(where) for shown in pool]]
            ),
            "pick": None,
            "strips": [],
            "highlight": None,
            "trace": None,
            "trace_reason": None,
            "receipt_panel": None,
            "repair_applies": None,
            "repair": None,
            "training": None,
            "board": [
                {
                    **run_header(repo, shown.run),
                    "role": shown.role,
                    **segments(repo, shown.run),
                }
                for shown in pool
            ],
            "headline": {
                name: repo.v(
                    [
                        "sum",
                        [
                            shown.run.count(
                                {"gold_status": ["ready"], "outcome": outcomes}
                            )
                            for shown in pool
                        ],
                    ]
                )
                for name, outcomes in (
                    ("compiled", list(_EXECUTED)),
                    ("silent_wrong", ["silent_wrong"]),
                )
            },
        }
        if candidates:
            pick = min(candidates)
            document.update(
                _reel_pick(repo, captures, pool[pick.position].run, pick)
            )
    document["inputs_sha256"] = hashlib.sha256(
        render([[path, repo.inputs[path]] for path in sorted(used)])
    ).hexdigest()
    return document


def build_site(
    repo: Repo, selection: Selection, source_commit: str
) -> Document:
    """The build identity: inputs with their hashes, phases and slugs."""
    pool = {shown.run.run_id for shown in selection.pool}
    return {
        "schema": "web-site/1.0",
        "source_commit": source_commit,
        "inputs": [
            {"path": path, "sha256": repo.inputs[path]}
            for path in sorted(repo.inputs)
        ],
        "phase": {
            "dev": bool(selection.rows),
            "test": selection.test_phase,
            "repair": False,
            "training": False,
            "aa": False,
        },
        "runs": [
            {
                "run_id": shown.run.run_id,
                "slug": shown.run.slug,
                "split": shown.run.split,
                "role": shown.role,
                "pool": shown.run.run_id in pool,
            }
            for shown in selection.shown
        ],
    }


def render(document: object) -> bytes:
    """Serializes one output: sorted keys, compact, one trailing LF."""
    try:
        text = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return (text + "\n").encode("utf-8")
    except (UnicodeEncodeError, ValueError):
        raise ExportError("schema_invalid", "An output is not JSON") from None


def export(root: Path, source_commit: str) -> dict[str, bytes]:
    """Builds every output from the committed files under ``root``.

    Args:
        root: The repository root holding docs/ and src/.
        source_commit: The commit the site is built from, as given.

    Returns:
        Each output's bytes by its path relative to the output directory.

    Raises:
        ExportError: When an input cannot be read (exit 2) or, as a
            ``ContractError``, when the files break the contract (exit 1).
    """
    if not _COMMIT.fullmatch(source_commit):
        raise ExportError("flag_invalid", "--source-commit is not a revision")
    repo = Repo(root)
    selection = select(repo)
    captures = Captures(repo)
    receipts = [
        (shown.run, label, item_id)
        for shown in selection.shown
        for label, item_id in shown.run.executed()
    ]
    cases = sorted(
        {case for item in selection.shown for case in item.run.cases}
    )
    if not cases or not receipts:
        raise ContractError("routes_empty", "A dynamic route has no page")
    files = {
        f"receipts/{run.slug}/{label}/{item_id}.json": render(
            build_receipt(repo, captures, run, label, item_id)
        )
        for run, label, item_id in receipts
    }
    files.update(
        {
            f"cases/{case_id}.json": render(
                build_case(repo, captures, selection, case_id)
            )
            for case_id in cases
        }
    )
    files["board.json"] = render(build_board(repo, selection))
    files["methodology.json"] = render(build_methodology(repo, selection))
    files["reel.json"] = render(build_reel(repo, captures, selection))
    files["routes.json"] = render(
        {
            "schema": "web-routes/1.0",
            "cases": [{"case": case_id} for case_id in cases],
            "receipts": [
                {"run": run.slug, "cond": label, "item": item_id}
                for run, label, item_id in receipts
            ],
        }
    )
    files["site.json"] = render(build_site(repo, selection, source_commit))
    return files


def write(out: Path, files: Mapping[str, bytes]) -> None:
    """Writes every output into an empty or missing directory."""
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ExportError("output_exists", f"{out.name} is not empty")
    for name in sorted(files):
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(files[name])


def tally(files: Mapping[str, bytes]) -> dict[str, object]:
    """Counts what one export wrote."""
    return {
        "files": len(files),
        "bytes": sum(len(data) for data in files.values()),
        "receipts": sum(1 for name in files if name.startswith("receipts/")),
        "cases": sum(1 for name in files if name.startswith("cases/")),
    }


def _print_json(value: object, *, error: bool = False) -> None:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    print(text, file=sys.stderr if error else sys.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    """Exports the site data and returns a process exit code.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        0 when written, 1 when the files break the data contract, 2 when an
        input cannot be read, a flag is invalid or the output is not empty.
    """
    parser = argparse.ArgumentParser(
        description="Export the web site's data from committed files."
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=_PROJECT_ROOT,
        help="repository root holding docs/ and src/",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    arguments = parser.parse_args(argv)
    try:
        files = export(
            cast(Path, arguments.repo), cast(str, arguments.source_commit)
        )
        write(cast(Path, arguments.out), files)
    except ExportError as error:
        _print_json(
            {"error": {"code": error.code, "message": str(error)}}, error=True
        )
        return error.exit_status
    except OSError:
        _print_json(
            {"error": {"code": "io_error", "message": "File operation failed"}},
            error=True,
        )
        return 2
    _print_json(tally(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
