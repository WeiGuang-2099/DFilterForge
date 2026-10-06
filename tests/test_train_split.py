"""The committed training set is disjoint from dev and test and rebuilds.

Every test reads the frozen set in data/train/v1 through the public
functions that built it. Tests that run tshark need the Linux test image,
like the rest of the suite's execution tests.
"""

from __future__ import annotations

from collections.abc import Iterator
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast

import pytest

from dfilterforge.benchmark import RECIPES
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import tshark_types
from dfilterforge.compiler import compile_intent
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.model_split import copy_with_witnesses
from dfilterforge.model_split import model_semantic_cases
from dfilterforge.runner import TsharkRunner
from dfilterforge.shortcuts import find_shortcuts
from dfilterforge.shortcuts import references
from dfilterforge.train_atoms import ATOMS
from dfilterforge.train_combos import canonical_key
from dfilterforge.train_combos import ngrams
from dfilterforge.train_combos import summarize
from dfilterforge.train_combos import TrainCombo

_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "data" / "train" / "v1"
_LINUX = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)
# Seeds of every other capture: the benchmark's 100 to 149 (dev, test and
# feedback copies included) and the pilot fixtures' 17, 42 and 2026.
_OTHER_SEEDS = frozenset((*range(100, 150), 17, 42, 2026))
# Candidates the prefix test labels again with tshark.
_PREFIX = 40


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "train_data", _ROOT / "scripts" / "train_data.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("train_data cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


train_data = _load()


def _rows() -> list[dict[str, Any]]:
    lines = (_DATA / "train.jsonl").read_text("utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _manifest() -> dict[str, Any]:
    return json.loads((_DATA / "manifest.json").read_text("utf-8"))


def _intent(row: dict[str, Any]) -> IntentIrV1:
    return IntentIrV1.model_validate(row["ir"])


def _gold_keys() -> set[str]:
    return {canonical_key(case.expression) for case in model_semantic_cases()}


def _signature(row: dict[str, Any]) -> tuple[tuple[int, ...], ...]:
    frames = cast(list[list[int]], row["frames"])
    return tuple(tuple(selected) for selected in frames)


def _packets(capture: bytes) -> Iterator[bytes]:
    """Yields the packet bytes of a little-endian PCAP."""
    offset = 24
    while offset < len(capture):
        length = int.from_bytes(capture[offset + 8 : offset + 12], "little")
        yield capture[offset + 16 : offset + 16 + length]
        offset += 16 + length


@pytest.fixture(name="gate", scope="module")
def fixture_gate(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """The build's own gate over freshly written train probes."""
    runner = TsharkRunner()
    intents = tuple(_intent(row) for row in _rows())
    gold = tuple(case.canonical_ir for case in model_semantic_cases())
    catalog = bind_catalog(runner, intents + gold)
    probes = train_data.write_probes(tmp_path_factory.mktemp("probes"))
    return train_data.Gate(runner, probes, catalog)


def test_the_atom_pool_is_the_dev_and_test_atom_pool() -> None:
    gold = {
        canonical_json(predicate)
        for case in model_semantic_cases()
        for _, predicate in walk_predicates(case.expression)
    }
    pool = [canonical_json(atom.predicate) for atom in ATOMS]

    assert set(pool) == gold
    assert len(pool) == len(gold)


def test_canonical_key_ignores_child_order_and_nesting() -> None:
    a, b, c = (
        Predicate(field="tcp.dstport", operator=Operator.EQ, value=443),
        Predicate(field="udp", operator=Operator.EXISTS),
        Predicate(field="udp.dstport", operator=Operator.IN, value=(53, 5353)),
    )
    swapped = c.model_copy(update={"value": (5353, 53)})

    nested = All(children=(a, All(children=(b, c))))
    assert canonical_key(nested) == canonical_key(All(children=(swapped, b, a)))
    assert canonical_key(All(children=(a, b))) != canonical_key(
        AnyOf(children=(a, b))
    )
    assert canonical_key(Not(child=a)) != canonical_key(a)


def test_canonical_keys_are_unique_and_disjoint_from_dev_and_test() -> None:
    keys = [row["canonical_key"] for row in _rows()]

    assert keys == [canonical_key(_intent(row).expression) for row in _rows()]
    assert len(set(keys)) == len(keys)
    assert not set(keys) & _gold_keys()


def test_requests_share_no_8_word_run_with_dev_or_test() -> None:
    gold: set[tuple[str, ...]] = set()
    for request in train_data.dev_test_requests():
        gold |= ngrams(request)
    requests = [row["request"] for row in _rows()]

    assert len(train_data.dev_test_requests()) == 152
    assert len(set(requests)) == len(requests)
    assert all(not ngrams(text) & gold for text in requests)


def test_probe_seeds_clients_and_packets_are_disjoint_from_others(
    tmp_path: Path,
) -> None:
    seeds = {seed for seed, *_ in train_data.PROBES}
    others = copy_with_witnesses(
        [f"semantic-{index:02}" for index in range(1, 51)], tmp_path / "others"
    )
    other_packets = {
        packet
        for probe in others.values()
        for packet in _packets(probe.capture_path.read_bytes())
    }
    probes = train_data.write_probes(tmp_path / "train")

    assert not seeds & _OTHER_SEEDS
    assert not {s % 200 for s in seeds} & {s % 200 for s in _OTHER_SEEDS}
    assert [row["seed"] for row in _manifest()["probes"]] == sorted(seeds)
    for probe, row in zip(probes, _manifest()["probes"]):
        assert file_sha256(probe.capture_path) == row["capture_sha256"]
        assert set(RECIPES) <= set(probe.recipes)
        packets = set(_packets(probe.capture_path.read_bytes()))
        assert len(packets) == len(probe.recipes)
        assert not packets & other_packets


@_LINUX
def test_frame_signatures_are_disjoint_from_dev_and_test(gate: Any) -> None:
    signatures = {_signature(row) for row in _rows()}
    recorded = _manifest()["dev_test"]["distinct_frame_sets"]

    assert len(gate.gold.frames) == recorded
    assert not signatures & gate.gold.frames


@_LINUX
def test_every_gold_compiles_hits_no_shortcut_and_is_not_degenerate(
    gate: Any,
) -> None:
    rows = _rows()
    fields = {
        p.field
        for row in rows
        for _, p in walk_predicates(_intent(row).expression)
    }
    types = tshark_types(fields)

    for row in rows:
        intent = _intent(row)
        target = GenerationResultV1.model_validate(row["target"])
        assert compile_intent(intent, gate.catalog) == row["filter"]
        assert not find_shortcuts(references(intent), row["request"], types)
        assert not gate.degenerate(_signature(row))
        assert row["depth"] <= 2 and 1 <= row["predicates"] <= 3
        assert target.intent_ir in (None, intent)


@_LINUX
def test_the_committed_set_matches_its_manifest_and_rebuilds(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    rows = _rows()
    combos = [
        TrainCombo(
            row["candidate"],
            _intent(row).expression,
            row["request"],
            GenerationResultV1.model_validate(row["target"]),
        )
        for row in rows
    ]
    train_data.build(tmp_path, _PREFIX, TsharkRunner())
    rebuilt = (tmp_path / "train.jsonl").read_text("utf-8").splitlines()
    prefix = [canonical_json(row) for row in rows if row["candidate"] < _PREFIX]

    assert (
        file_sha256(_DATA / "train.jsonl") == manifest["files"]["train.jsonl"]
    )
    assert summarize(combos) == manifest["counts"]
    assert (
        sum(manifest["dropped"].values()) + len(rows) == manifest["candidates"]
    )
    assert rebuilt == prefix and len(prefix) > 10
    rebuilt_manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert rebuilt_manifest["probes"] == manifest["probes"]
    assert rebuilt_manifest["tools"] == manifest["tools"]


@_LINUX
def test_the_cli_check_fails_on_a_set_that_differs(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text('{"candidates": 3}\n')
    (tmp_path / "train.jsonl").write_text("")

    assert train_data.main(["--check", "--output-dir", str(tmp_path)]) == 1
