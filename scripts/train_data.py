"""Build the frozen SFT training set from train-only probes and tshark labels.

Each candidate of :func:`dfilterforge.train_combos.sample_combo` is compiled
against the frozen catalog and run by pinned tshark on three train-only
probes: the benchmark recipes and the witness tail on seeds, and so client
addresses 192.0.2.(seed % 200 + 1), that no other probe uses. The frames
tshark selects are the label. ``DROP_RULES`` drop a candidate, first rule
first, that fails to compile, has a dev or test gold's canonical key or an
earlier candidate's, hits a shortcut rule, shares an 8-word run with a dev
or test request, selects no frame or every frame on all three probes, or
selects the frames a dev or test gold selects there.

Writes ``train.jsonl`` and ``manifest.json``; ``--check`` rebuilds the
committed set and compares both files byte for byte. Exit 0 on success, 1
on a mismatch, 2 on an execution failure.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from dfilterforge import __version__
from dfilterforge.benchmark import BenchmarkProbe
from dfilterforge.benchmark import capture_bytes
from dfilterforge.benchmark import RECIPES
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import tshark_types
from dfilterforge.compiler import compile_intent
from dfilterforge.compiler import CompileError
from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.model_cases import model_non_ready_cases
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.runner import TsharkRunner
from dfilterforge.shortcuts import find_shortcuts
from dfilterforge.shortcuts import references
from dfilterforge.train_combos import canonical_key
from dfilterforge.train_combos import depth
from dfilterforge.train_combos import NGRAM
from dfilterforge.train_combos import ngrams
from dfilterforge.train_combos import sample_combo
from dfilterforge.train_combos import summarize
from dfilterforge.train_combos import TrainCombo
from dfilterforge.witnesses import append_witnesses
from dfilterforge.witnesses import WITNESS_NAMES

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "train" / "v1"
SAMPLER_SEED = 1
CANDIDATES = 2400
# Seed, recipe rotation, reversed, and how many leading recipes repeat.
PROBES: tuple[tuple[int, int, bool, int], ...] = (
    (7001, 7, True, 3),
    (7002, 13, False, 0),
    (7003, 3, False, 6),
)
DROP_RULES = tuple(
    "compile dev_test_key duplicate_key shortcut dev_test_text degenerate"
    " dev_test_frames".split()
)
_FILES = ("train.jsonl", "manifest.json")
Signature = tuple[tuple[int, ...], ...]


def write_probes(directory: Path) -> tuple[BenchmarkProbe, ...]:
    """Writes the three train probes, each with the witness tail."""
    directory.mkdir(parents=True, exist_ok=True)
    probes: list[BenchmarkProbe] = []
    for seed, offset, backwards, repeats in PROBES:
        recipes = RECIPES[offset:] + RECIPES[:offset]
        recipes = tuple(reversed(recipes)) if backwards else recipes
        recipes += recipes[:repeats]
        path = directory / f"train-{seed}.pcap"
        capture = capture_bytes(recipes, seed)
        path.write_bytes(append_witnesses(capture, seed, len(recipes)))
        probes.append(
            BenchmarkProbe(f"train-{seed}", path, recipes + WITNESS_NAMES)
        )
    return tuple(probes)


def dev_test_requests() -> tuple[str, ...]:
    """Returns every dev and test request, ready and non-ready."""
    cases = (*model_semantic_cases(), *model_non_ready_cases())
    return tuple(text for case in cases for text in case.paraphrases)


@dataclass(frozen=True)
class DevTestGold:
    """What no train candidate may share with the dev and test gold.

    Attributes:
        keys: The canonical keys of the ready gold.
        text: The 8-word runs of every dev and test request.
        frames: The frames each ready gold selects on the train probes.
    """

    keys: frozenset[str]
    text: frozenset[tuple[str, ...]]
    frames: frozenset[Signature]


class Gate:
    """Labels candidates with tshark and applies the drop rules in order."""

    def __init__(
        self,
        runner: TsharkRunner,
        probes: Sequence[BenchmarkProbe],
        catalog: FieldCatalogV1,
    ) -> None:
        self.runner = runner
        self.probes = tuple(probes)
        self.catalog = catalog
        self.types = tshark_types(
            field.abbreviation for field in catalog.fields
        )
        cases = model_semantic_cases()
        self.gold = DevTestGold(
            frozenset(canonical_key(case.expression) for case in cases),
            frozenset[tuple[str, ...]]().union(
                *map(ngrams, dev_test_requests())
            ),
            frozenset(
                self.frames(compile_intent(case.canonical_ir, catalog))
                for case in cases
            ),
        )
        self.seen: set[str] = set()
        self.dropped: dict[str, int] = dict.fromkeys(DROP_RULES, 0)

    def frames(self, display_filter: str) -> Signature:
        """Returns the frames one filter selects on each probe."""
        return tuple(
            self.runner.run(probe.capture_path, display_filter).frames
            for probe in self.probes
        )

    def degenerate(self, frames: Signature) -> bool:
        """No frame on any probe, or every frame on every probe."""
        return not any(frames) or all(
            len(selected) == len(probe.recipes)
            for selected, probe in zip(frames, self.probes)
        )

    def admit(self, combo: TrainCombo) -> tuple[str, Signature] | None:
        """Returns the compiled filter and labels, or None when dropped."""
        intent = IntentIrV1(expression=combo.expression)
        try:
            display_filter = compile_intent(intent, self.catalog)
        except (CatalogError, CompileError):
            self.dropped["compile"] += 1
            return None
        key = canonical_key(combo.expression)
        hits = find_shortcuts(references(intent), combo.request, self.types)
        static = (
            ("dev_test_key", key in self.gold.keys),
            ("duplicate_key", key in self.seen),
            ("shortcut", bool(hits)),
            ("dev_test_text", bool(ngrams(combo.request) & self.gold.text)),
        )
        self.seen.add(key)
        rule = next((name for name, hit in static if hit), None)
        if rule is None:
            frames = self.frames(display_filter)
            if self.degenerate(frames):
                rule = "degenerate"
            elif frames in self.gold.frames:
                rule = "dev_test_frames"
            else:
                return display_filter, frames
        self.dropped[rule] += 1
        return None


def _row(
    combo: TrainCombo, number: int, display_filter: str, frames: Signature
) -> dict[str, object]:
    return {
        "id": f"train-{number:04d}",
        "candidate": combo.index,
        "request": combo.request,
        "target": combo.target.model_dump(mode="json"),
        "ir": IntentIrV1(expression=combo.expression).model_dump(mode="json"),
        "canonical_key": canonical_key(combo.expression),
        "filter": display_filter,
        "frames": [list(selected) for selected in frames],
        "depth": depth(combo.expression),
        "predicates": len(walk_predicates(combo.expression)),
    }


def build(directory: Path, candidates: int, runner: TsharkRunner) -> None:
    """Samples, labels and filters candidates; writes the set and manifest.

    Args:
        directory: Where ``train.jsonl`` and ``manifest.json`` go; the
            probes are written to a temporary directory.
        candidates: How many candidates to sample, from index 0.
        runner: The pinned tshark runner.
    """
    combos = [sample_combo(SAMPLER_SEED, index) for index in range(candidates)]
    catalog = bind_catalog(
        runner,
        tuple(IntentIrV1(expression=combo.expression) for combo in combos)
        + tuple(case.canonical_ir for case in model_semantic_cases()),
    )
    kept: list[TrainCombo] = []
    rows: list[dict[str, object]] = []
    with TemporaryDirectory(prefix="dfilterforge-train-") as staging:
        gate = Gate(runner, write_probes(Path(staging)), catalog)
        for combo in combos:
            admitted = gate.admit(combo)
            if admitted is not None:
                kept.append(combo)
                rows.append(_row(combo, len(rows) + 1, *admitted))
        probes = [
            {
                "probe_id": probe.probe_id,
                "seed": seed,
                "recipes": list(probe.recipes),
                "capture_sha256": file_sha256(probe.capture_path),
            }
            for probe, (seed, *_) in zip(gate.probes, PROBES)
        ]
    directory.mkdir(parents=True, exist_ok=True)
    data = directory / _FILES[0]
    data.write_text(
        "".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )
    manifest = {
        "schema_version": "train-set/1.0",
        "sampler_seed": SAMPLER_SEED,
        "candidates": candidates,
        "dropped": gate.dropped,
        "counts": summarize(kept),
        "probes": probes,
        "dev_test": {
            "ready_cases": len(model_semantic_cases()),
            "distinct_frame_sets": len(gate.gold.frames),
            "requests": len(dev_test_requests()),
            "ngram": NGRAM,
        },
        "tools": {
            "tshark": runner.version(),
            "catalog": catalog.source_catalog_hash,
            "dfilterforge": __version__,
        },
        "files": {data.name: file_sha256(data)},
    }
    (directory / _FILES[1]).write_text(
        canonical_json(manifest) + "\n", encoding="utf-8"
    )


def check(directory: Path, runner: TsharkRunner) -> bool:
    """Rebuilds the committed set and compares it byte for byte."""
    manifest = json.loads((directory / _FILES[1]).read_text("utf-8"))
    with TemporaryDirectory(prefix="dfilterforge-train-check-") as rebuilt:
        build(Path(rebuilt), int(manifest["candidates"]), runner)
        return all(
            (Path(rebuilt) / name).read_bytes()
            == (directory / name).read_bytes()
            for name in _FILES
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Builds or checks the training set; returns the exit status."""
    parser = argparse.ArgumentParser(description="Build the SFT train set.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--candidates", type=int, default=CANDIDATES)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.check:
            if check(args.output_dir, TsharkRunner()):
                return 0
            print("the train set differs from its rebuild", file=sys.stderr)
            return 1
        build(args.output_dir, args.candidates, TsharkRunner())
    except DFilterForgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    print(f"train.jsonl sha256 {file_sha256(args.output_dir / _FILES[0])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
