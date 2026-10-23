"""Verifier v1: the Reel pool's test answers replayed without witnesses.

Every published score uses verifier v2, whose probes end in the 33-packet
tail of :mod:`dfilterforge.witnesses`; verifier v1 reads the benchmark
captures alone. tshark reads a capture in one pass, so frames 1 to N
dissect alike in both and a v1 label set is its v2 set cut to them. It
reads the captures it is given and the committed specifications, receipts
and outcome rows; nothing that scores imports it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, TypeVar

from pydantic import ValidationError

from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.errors import DFilterForgeError
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.runner import TsharkRunner
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.witnesses import append_witnesses
from dfilterforge.witnesses import WITNESS_NAMES

SCHEMA_VERSION = "verifier-exhibits/1.0"
REGISTRY_PATH = Path("docs/decisions/evidence/test-runs.json")
V1_ANCHOR_PATH = Path(
    "docs/ablations/evidence/005-probe-adequacy-simplified.json"
)
FREEZE_PATH = Path("src/dfilterforge/held_out_freeze.json")
RESULTS_PATH = Path("docs/results")
# The Reel pool in pool order (docs/decisions/disproof-reel.md): pass A,
# then each slot's published winner, else its published fallback.
_POOL_ROLES = (
    "aa_pass_a winner_small fallback_small winner_mid fallback_mid"
    " winner_frontier fallback_frontier"
).split()
_ACCEPTED = ("strong_exact", "shortcut")
_EXECUTED = (*_ACCEPTED, "silent_wrong")
# Each record of a capture built with seed s is stamped 1700000000 + s.
_EPOCH = 1700000000
_NOTES = (
    "Every score on the board, in the receipts and in the headlines uses "
    "verifier v2: the benchmark captures followed by the 33-packet witness "
    "tail. Verifier v1, the benchmark captures alone, changes no score.",
    "Each answer's filter, a typed answer's as compiled in its receipt, ran "
    "once per probe on v1 with the pinned tshark, giving its receipt's v2 "
    "frames cut to the benchmark frames.",
    "A v1 label set is its v2 set cut to the benchmark frames; a case whose "
    "v1 sets are all empty is unscorable on v1, as the scorer refuses such "
    "gold. A shortcut hit comes from the answer's outcome row.",
    "witness_frames lists, for an answer v1 finds strong exact or a shortcut "
    "and v2 silent-wrong, each frame where it and its labels disagree.",
)
ProbeFrames = tuple[tuple[int, ...], ...]
_Model = TypeVar("_Model", SemanticSpecV1, EvaluationReceiptV1, ItemOutcomeV1)


class WitnessReplayError(DFilterForgeError, RuntimeError):
    """A replay failure carrying only a stable code and safe text."""


@dataclass(frozen=True, slots=True)
class ProbePair:
    """One scored probe as each verifier reads it.

    ``names`` names its v2 frames; v1 reads the first ``frames`` of them
    from ``path``; ``sha256`` is the v1 capture's digest, then the v2 one's.
    """

    probe_id: str
    names: tuple[str, ...]
    frames: int
    path: Path
    sha256: tuple[str, str]


def _parse(model: type[_Model], data: bytes, where: Path) -> _Model:
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise WitnessReplayError("input_invalid", where.name) from None


def strip_witness_tail(capture: bytes, frames: int) -> bytes:
    """Returns a capture of ``frames`` benchmark frames without its tail.

    The capture must be its first ``frames`` records with the tail that
    ``append_witnesses`` adds for the seed its first timestamp gives.
    """
    end = 24
    for _ in range(frames):
        end += 16 + int.from_bytes(capture[end + 8 : end + 12], "little")
    seed = int.from_bytes(capture[24:28], "little") - _EPOCH
    try:
        whole = capture[:4] == bytes.fromhex("d4c3b2a1") and (
            append_witnesses(capture[:end], seed, frames) == capture
        )
    except ValueError:
        whole = False
    if not whole:
        raise WitnessReplayError("witness_tail_mismatch", "A capture's tail")
    return capture[:end]


def tail_free(
    probes: Sequence[BenchmarkProbe], directory: Path
) -> tuple[ProbePair, ...]:
    """Writes each probe's v1 capture into ``directory`` under its name."""
    pairs: list[ProbePair] = []
    for probe in probes:
        frames = len(probe.recipes) - len(WITNESS_NAMES)
        if probe.recipes[frames:] != WITNESS_NAMES:
            raise WitnessReplayError("frames_unnamed", probe.probe_id)
        with_tail = probe.capture_path.read_bytes()
        without = strip_witness_tail(with_tail, frames)
        path = directory / probe.capture_path.name
        path.write_bytes(without)
        v1 = hashlib.sha256(without).hexdigest()
        v2 = hashlib.sha256(with_tail).hexdigest()
        pairs.append(
            ProbePair(probe.probe_id, probe.recipes, frames, path, (v1, v2))
        )
    return tuple(pairs)


def v1_labels(spec: SemanticSpecV1, pairs: Sequence[ProbePair]) -> ProbeFrames:
    """A case's v1 label sets: its v2 sets cut to the benchmark frames."""
    frames = {pair.probe_id: pair.frames for pair in pairs}
    return tuple(
        tuple(n for n in probe.expected_frames if n <= frames[probe.probe_id])
        for probe in spec.probes
    )


def replay(
    runner: TsharkRunner, pairs: Sequence[ProbePair], display_filter: str
) -> ProbeFrames:
    """Runs one filter once on each v1 capture, checking the bytes read."""
    found: list[tuple[int, ...]] = []
    for pair in pairs:
        result = runner.run(pair.path, display_filter)
        if result.capture_sha256 != pair.sha256[0]:
            raise WitnessReplayError("capture_changed", pair.probe_id)
        found.append(result.frames)
    return tuple(found)


def verdict(frames: ProbeFrames, labels: ProbeFrames, *, shortcut: bool) -> str:
    """The scorer's verdict, or unscorable where it would refuse the gold."""
    if not any(labels):
        return "unscorable"
    if frames != labels:
        return "silent_wrong"
    return "shortcut" if shortcut else "strong_exact"


def _pool(repo: Path, pairs: Sequence[ProbePair]) -> list[str]:
    """The pool's runs in pool order, once each capture matches its anchor."""
    try:
        adequacy, freeze, registry = (
            json.loads((repo / path).read_bytes())
            for path in (V1_ANCHOR_PATH, FREEZE_PATH, REGISTRY_PATH)
        )
        manifest = adequacy["measurement_identity"]["capture_manifest"]
        v1 = {row["probe_id"]: row["capture_sha256"] for row in manifest}
        v2 = freeze["digests"]
        for pair in pairs:
            anchor = (v1.get(pair.probe_id), v2.get(pair.probe_id))
            if anchor != pair.sha256:
                raise WitnessReplayError("anchor_mismatch", pair.probe_id)
        rows: list[Any] = [
            row
            for row in registry["runs"]
            if row["status"] == "published" and row["role"] in _POOL_ROLES
        ]
        rows.sort(key=lambda row: _POOL_ROLES.index(row["role"]))
        return [str(row["run_id"]) for row in rows]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise WitnessReplayError("input_invalid", "An anchor file") from None


def _rows(repo: Path, run_id: str) -> list[ItemOutcomeV1]:
    """One run's executed ready outcome rows, in file order."""
    path = repo / RESULTS_PATH / run_id / "scored" / "outcomes.jsonl"
    lines = path.read_bytes().splitlines()
    rows = [_parse(ItemOutcomeV1, line, path) for line in lines]
    return [
        row
        for row in rows
        if row.gold_status == "ready" and row.outcome in _EXECUTED
    ]


# pylint: disable-next=too-many-locals
def build_exhibits(
    repo: Path, probes: Sequence[BenchmarkProbe], runner: TsharkRunner
) -> dict[str, object]:
    """Replays the Reel pool's executed ready test answers on verifier v1.

    Each case's reference must select exactly its v1 labels, and each
    answer's v1 frames must be its receipt's v2 frames cut to the benchmark
    frames; ``score --check`` keeps the receipts and specifications.

    Args:
        repo: The repository root holding docs/ and src/.
        probes: The scored test probes, with the tail, in gold order.
        runner: The pinned tshark runner.

    Returns:
        The exhibits document; nothing in it varies between runs.

    Raises:
        WitnessReplayError: For an invalid input or a failed check.
    """
    labels: dict[str, ProbeFrames] = {}
    replays: dict[tuple[str, str], ProbeFrames] = {}
    answers: list[dict[str, object]] = []
    with TemporaryDirectory(prefix="dfilterforge-v1-") as staging:
        pairs = tail_free(probes, Path(staging))
        runs = _pool(repo, pairs)
        for run_id, row in ((r, row) for r in runs for row in _rows(repo, r)):
            scored = RESULTS_PATH / run_id / "scored"
            if row.case_id not in labels:
                path = repo / scored / "specs" / f"{row.case_id}.json"
                spec = _parse(SemanticSpecV1, path.read_bytes(), path)
                labels[row.case_id] = v1_labels(spec, pairs)
                gold = replay(runner, pairs, spec.reference_filter)
                if gold != labels[row.case_id]:
                    raise WitnessReplayError("gold_invalid", row.case_id)
            path = scored / "receipts" / row.condition / f"{row.item_id}.json"
            data = (repo / path).read_bytes()
            receipt = _parse(EvaluationReceiptV1, data, path)
            key = (row.case_id, receipt.candidate_filter)
            if key not in replays:
                replays[key] = replay(runner, pairs, key[1])
            if replays[key] != tuple(
                tuple(n for n in probe.candidate_frames if n <= pair.frames)
                for probe, pair in zip(receipt.probes, pairs, strict=True)
            ):
                raise WitnessReplayError("replay_mismatch", path.name)
            v1 = verdict(
                replays[key], labels[row.case_id], shortcut=bool(row.shortcuts)
            )
            answer: dict[str, object] = {
                "run_id": run_id,
                "condition": row.condition,
                "item_id": row.item_id,
                "case_id": row.case_id,
                "receipt": path.as_posix(),
                "receipt_sha256": hashlib.sha256(data).hexdigest(),
                "v1": v1,
                "v2": row.outcome.value,
            }
            if v1 in _ACCEPTED and row.outcome == "silent_wrong":
                answer["witness_frames"] = [
                    {
                        "probe_id": probe.probe_id,
                        "n": n,
                        "witness": pair.names[n - 1],
                        "answer_matched": n in probe.candidate_only,
                        "should_match": n in probe.reference_only,
                    }
                    for probe, pair in zip(receipt.probes, pairs, strict=True)
                    for n in sorted(
                        (*probe.candidate_only, *probe.reference_only)
                    )
                ]
            answers.append(answer)
    return {
        "schema_version": SCHEMA_VERSION,
        "notes": list(_NOTES),
        "sources": {
            "hosted_test": {
                "runs": runs,
                "probes": [
                    {
                        "probe_id": pair.probe_id,
                        "v1_capture_sha256": pair.sha256[0],
                        "v1_frames": pair.frames,
                        "v2_capture_sha256": pair.sha256[1],
                        "v2_frames": len(pair.names),
                    }
                    for pair in pairs
                ],
                "unscorable_cases": sorted(
                    case for case, sets in labels.items() if not any(sets)
                ),
                "answers": answers,
            }
        },
    }
