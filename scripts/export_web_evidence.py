"""Committed evidence the web site reads instead of running tshark.

``captures`` regenerates the eight curated captures of the model split in
pure Python, the six scored probes and both unscored feedback probes, and
records each one's identity and frame table: the frame number, whether the
frame is a benchmark recipe frame or part of the witness tail, and its recipe
or witness name. The site shows these names beside frame numbers and never
reads packet bytes.

``captures --write`` writes ``docs/decisions/evidence/web/captures.json``
after the anchor checks below hold. ``captures --check`` and ``check``
regenerate it, compare it byte for byte with the committed file and check
each capture hash against the committed anchors: the test-freeze adequacy
receipt for all eight captures, every committed scored specification that
names a probe, and the held-out freeze digests for the test captures.

Exit status: 0 when the file is written or every check holds, 1 when a check
fails, 2 when the evidence cannot be built or an input cannot be read.
"""

# The error envelope repeats scripts/probe_adequacy.py on purpose: each
# script is a standalone file loaded by path, and neither may import the
# other.
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import cast, NoReturn

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.canonical import canonical_json
from dfilterforge.errors import DFilterForgeError
from dfilterforge.model_feedback import FEEDBACK_PROBE_IDS
from dfilterforge.model_feedback import generate_feedback_probes
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelSplit
from dfilterforge.witnesses import WITNESS_NAMES

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_VERSION = "capture-frames/1.0"
CAPTURES_PATH = Path("docs/decisions/evidence/web/captures.json")
GATE_PATH = Path("docs/decisions/evidence/test-freeze-gate.json")
FREEZE_PATH = Path("src/dfilterforge/held_out_freeze.json")
RESULTS_PATH = Path("docs/results")
# The same input ceiling as the run store's JSON reads.
MAX_INPUT_BYTES = 32 * 1024 * 1024
_SPLITS: tuple[ModelSplit, ...] = ("dev", "test")
_PCAP_MAGIC = (0xA1B2C3D4).to_bytes(4, "little")
_PCAP_HEADER_BYTES = 24
_RECORD_HEADER_BYTES = 16
_FAILED = 1
_ERROR = 2
_NOTES: tuple[str, ...] = (
    "Frame numbers count from 1, as tshark numbers frames.",
    "A recipe frame is a benchmark frame, named by its packet recipe; a "
    "witness frame belongs to the witness tail and is named by its witness.",
    "Built in pure Python by dfilterforge.model_split and "
    "dfilterforge.model_feedback; no tshark run and no packet bytes.",
)


class EvidenceError(DFilterForgeError, RuntimeError):
    """An evidence failure carrying only a stable code and safe text."""


def _refuse_constant(name: str) -> NoReturn:
    raise EvidenceError("schema_invalid", f"JSON constant {name} is refused")


def read_json(path: Path) -> object:
    """Reads one committed JSON file as UTF-8 within the input ceiling."""
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise EvidenceError("input_too_large", f"{path.name} exceeds 32 MiB")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_refuse_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EvidenceError(
            "schema_invalid", f"{path.name} is not UTF-8 JSON"
        ) from None


def _mapping(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise EvidenceError("schema_invalid", f"{where} is not an object")
    return cast(dict[str, object], value)


def _items(value: object, where: str) -> list[object]:
    if not isinstance(value, list):
        raise EvidenceError("schema_invalid", f"{where} is not an array")
    return cast(list[object], value)


def record_count(capture: bytes) -> int:
    """Counts the records of a little-endian PCAP, refusing a torn one."""
    if len(capture) < _PCAP_HEADER_BYTES or capture[:4] != _PCAP_MAGIC:
        raise EvidenceError(
            "capture_invalid", "A capture is not a little-endian PCAP"
        )
    count = 0
    offset = _PCAP_HEADER_BYTES
    while offset < len(capture):
        header_end = offset + _RECORD_HEADER_BYTES
        if header_end > len(capture):
            raise EvidenceError(
                "capture_invalid", "A capture ends inside a record header"
            )
        length = int.from_bytes(capture[offset + 8 : offset + 12], "little")
        offset = header_end + length
        if offset > len(capture):
            raise EvidenceError(
                "capture_invalid", "A capture ends inside a record"
            )
        count += 1
    return count


def probe_row(
    probe: BenchmarkProbe, split: str, role: str
) -> dict[str, object]:
    """Records one capture's identity and its named frames."""
    witnesses = len(WITNESS_NAMES)
    if probe.recipes[-witnesses:] != WITNESS_NAMES:
        raise EvidenceError(
            "witness_tail_missing",
            f"{probe.probe_id} does not end in the witness tail",
        )
    capture = probe.capture_path.read_bytes()
    if record_count(capture) != len(probe.recipes):
        raise EvidenceError(
            "frame_count_mismatch",
            f"{probe.probe_id} has another frame count than its recipes",
        )
    benchmark_frames = len(probe.recipes) - witnesses
    return {
        "probe_id": probe.probe_id,
        "split": split,
        "role": role,
        "capture_sha256": hashlib.sha256(capture).hexdigest(),
        "size_bytes": len(capture),
        "benchmark_frames": benchmark_frames,
        "frames": [
            {
                "n": number,
                "kind": "recipe" if number <= benchmark_frames else "witness",
                "name": name,
            }
            for number, name in enumerate(probe.recipes, 1)
        ],
    }


def build_captures() -> dict[str, object]:
    """Regenerates the eight curated captures and returns their frame tables.

    The scored probes come from the split generator and the feedback probes
    from the feedback generator, the same code that builds them for scoring
    and for the repair round, so no probe ID is listed here. Rows run dev
    then test; within a split, the scored probes in the split generator's
    order, then the feedback probe.
    """
    with TemporaryDirectory(prefix="dfilterforge-web-evidence-") as staging:
        split = generate_model_split(Path(staging))
        feedback = generate_feedback_probes(split)
        scored_splits = {
            expected.probe_id: case.spec.split
            for case in split.gold.cases
            for expected in case.spec.probes
        }
        feedback_by_id = {probe.probe_id: probe for probe in feedback.probes}
        rows: list[dict[str, object]] = []
        for name in _SPLITS:
            rows.extend(
                probe_row(probe, name, "scored")
                for probe in split.probes
                if scored_splits[probe.probe_id] == name
            )
            rows.append(
                probe_row(
                    feedback_by_id[FEEDBACK_PROBE_IDS[name]], name, "feedback"
                )
            )
    return {
        "schema_version": _SCHEMA_VERSION,
        "probes": rows,
        "notes": list(_NOTES),
    }


def render(document: Mapping[str, object]) -> bytes:
    """Serializes evidence sorted and indented, with one trailing LF."""
    return (
        json.dumps(document, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _rows(document: Mapping[str, object]) -> dict[str, dict[str, object]]:
    rows = (
        _mapping(row, "a probe row")
        for row in _items(document["probes"], "probes")
    )
    return {cast(str, row["probe_id"]): row for row in rows}


def _gate_failures(
    repo: Path, rows: Mapping[str, Mapping[str, object]]
) -> Iterator[str]:
    """Matches every capture to the test-freeze receipt's manifests."""
    identity = _mapping(
        _mapping(read_json(repo / GATE_PATH), GATE_PATH.name).get(
            "measurement_identity"
        ),
        "measurement_identity",
    )
    entries = [
        _mapping(entry, "a manifest row")
        for key in ("capture_manifest", "feedback_manifest")
        for entry in _items(identity.get(key), key)
    ]
    for probe_id, row in rows.items():
        matches = [
            entry for entry in entries if entry.get("probe_id") == probe_id
        ]
        if len(matches) != 1:
            yield f"{probe_id}: {GATE_PATH} lists it {len(matches)} times"
            continue
        for key in ("split", "capture_sha256", "size_bytes"):
            if matches[0].get(key) != row[key]:
                yield f"{probe_id}: {key} differs from {GATE_PATH}"


def _freeze_failures(
    repo: Path, rows: Mapping[str, Mapping[str, object]]
) -> Iterator[str]:
    """Matches every test capture to the held-out freeze digests."""
    digests = _mapping(
        _mapping(read_json(repo / FREEZE_PATH), FREEZE_PATH.name).get(
            "digests"
        ),
        "digests",
    )
    for probe_id, row in rows.items():
        if row["split"] == "test" and digests.get(probe_id) != (
            row["capture_sha256"]
        ):
            yield f"{probe_id}: capture_sha256 differs from {FREEZE_PATH}"


def _spec_failures(
    repo: Path, rows: Mapping[str, Mapping[str, object]]
) -> Iterator[str]:
    """Matches captures to every committed scored specification naming one.

    Each dev scored probe must be named by at least one specification.
    """
    named: set[str] = set()
    for path in sorted((repo / RESULTS_PATH).glob("*/scored/specs/*.json")):
        where = path.relative_to(repo).as_posix()
        spec = _mapping(read_json(path), where)
        for item in _items(spec.get("probes", []), where):
            expected = _mapping(item, where)
            row = rows.get(cast(str, expected.get("probe_id")))
            if row is None:
                continue
            named.add(cast(str, row["probe_id"]))
            if expected.get("capture_sha256") != row["capture_sha256"]:
                yield f"{row['probe_id']}: capture_sha256 differs from {where}"
            if spec.get("split") != row["split"]:
                yield f"{row['probe_id']}: split differs from {where}"
    for probe_id, row in rows.items():
        if (row["split"], row["role"]) == ("dev", "scored") and (
            probe_id not in named
        ):
            yield f"{probe_id}: no committed scored specification names it"


def anchor_failures(repo: Path, document: Mapping[str, object]) -> list[str]:
    """Checks every capture hash against the committed anchors."""
    rows = _rows(document)
    return [
        *_gate_failures(repo, rows),
        *_freeze_failures(repo, rows),
        *_spec_failures(repo, rows),
    ]


def check(repo: Path, document: Mapping[str, object]) -> list[str]:
    """Compares the committed file with a regeneration and checks anchors.

    Args:
        repo: The repository root holding ``docs`` and ``src``.
        document: The regenerated evidence, from ``build_captures``.

    Returns:
        One message per failed check; empty when every check holds.
    """
    committed = repo / CAPTURES_PATH
    if not committed.is_file():
        failures = [f"{CAPTURES_PATH} is missing"]
    elif committed.read_bytes() != render(document):
        failures = [f"{CAPTURES_PATH} differs from a regeneration"]
    else:
        failures = []
    return failures + anchor_failures(repo, document)


def _summary(document: Mapping[str, object]) -> dict[str, object]:
    data = render(document)
    rows = _rows(document)
    return {
        "path": CAPTURES_PATH.as_posix(),
        "probes": len(rows),
        "frames": sum(
            len(_items(row["frames"], "frames")) for row in rows.values()
        ),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _print_error(code: str, message: str) -> None:
    """Writes the machine-readable error envelope to stderr."""
    envelope = {"error": {"code": code, "message": message}}
    print(canonical_json(envelope), file=sys.stderr)


def _run(arguments: argparse.Namespace) -> int:
    repo = cast(Path, arguments.repo)
    document = build_captures()
    if cast(bool, getattr(arguments, "write", False)):
        failures = anchor_failures(repo, document)
        if not failures:
            target = repo / CAPTURES_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(render(document))
    else:
        failures = check(repo, document)
    for failure in failures:
        _print_error("check_failed", failure)
    if failures:
        return _FAILED
    print(canonical_json(_summary(document)))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Writes or checks the web evidence and returns a process exit code.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        0 when written or every check holds, 1 when a check fails, 2 when
        the evidence cannot be built or an input cannot be read.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=_PROJECT_ROOT,
        help="repository root holding docs/ and src/",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    captures = commands.add_parser(
        "captures", help="write or check the frame tables"
    )
    mode = captures.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    commands.add_parser("check", help="check every committed web evidence")
    arguments = parser.parse_args(argv)
    try:
        return _run(arguments)
    except DFilterForgeError as error:
        _print_error(error.code, str(error))
        return _ERROR
    except OSError:
        _print_error("io_error", "File operation failed")
        return _ERROR


if __name__ == "__main__":
    raise SystemExit(main())
