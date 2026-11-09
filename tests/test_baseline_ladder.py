"""The baseline ladder on small hand-built rows, and on the committed ones."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType
from typing import Any

import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import summarize

_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "baseline_ladder", _ROOT / "scripts" / "baseline_ladder.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("baseline_ladder cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ladder = _load()
EXACT, SILENT = OutcomeV1.STRONG_EXACT, OutcomeV1.SILENT_WRONG
_CASES = 12
_HEADLINE = Path("sft-v1") / "headline.json"
_SCORED = ("scored/outcomes.jsonl", "scored/summary.json")
# Any settings do: each baseline row is held to the base row's manifest.
_SETTINGS = {"json_mode": True, "model_id": "Qwen/Qwen3-1.7B", "seed": 17}
Exact = set[tuple[int, int]]
Odd = Mapping[tuple[int, int], tuple[OutcomeV1, str | None]]


def _both(cases: range) -> Exact:
    return {(case, side) for case in cases for side in (0, 1)}


def _item(
    key: str, case: str, outcome: OutcomeV1, **fields: Any
) -> ItemOutcomeV1:
    return ItemOutcomeV1(
        condition="C4",
        item_id=key,
        case_id=case,
        outcome=outcome,
        gold_field_count=2,
        latency_ms=1.0,
        **fields,
    )


def _row(results: Path, run: str, exact: Exact, odd: Odd) -> None:
    """24 ready C4 items, paraphrase 0 covered; a C1 and a non-ready one."""
    items: list[ItemOutcomeV1] = []
    for case in range(_CASES):
        for side in (0, 1):
            plain = (EXACT if (case, side) in exact else SILENT, None)
            outcome, finish = odd.get((case, side), plain)
            key, case_id = f"mei-{case:02d}{side}", f"case-{case:02d}"
            hits = {"retrieved_gold_field_count": 2 - side}
            item = _item(key, case_id, outcome, finish_reason=finish, **hits)
            items.append(item)
    status = {"gold_status": "needs_clarification"}
    items.append(_item("mei-nr", "nr", OutcomeV1.FALSE_READY, **status))
    items.append(items[0].model_copy(update={"condition": "C1"}))
    lines = "".join(canonical_json(item) + "\n" for item in items)
    _write(results / run / "scored" / "outcomes.jsonl", lines)
    summary = summarize(
        items,
        run=run,
        model_id="Qwen/Qwen3-1.7B",
        split="test",
        gold_hash="0" * 64,
        capture_hashes={},
        batch_hashes={},
    )
    _write(results / run / "scored" / "summary.json", canonical_json(summary))


def _write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, "utf-8")


def _tree(
    tmp_path: Path,
    exact: Mapping[str, Exact] | None = None,
    odd: Odd | None = None,
) -> Path:
    """Rows exact on case 0 unless named: base, schema, few_shot, s17..."""
    results = tmp_path / "results"
    names = {run: name for name, _, run, _ in ladder.ROWS[:3]}
    names |= {run: f"s{seed}" for seed, run in ladder.SEEDS.items()}
    for run, name in names.items():
        _row(results, run, (exact or {}).get(name, _both(range(1))), odd or {})
    manifest: dict[str, Any] = {
        "endpoint_host": "server.example",
        "max_attempts": 3,
        "min_interval_seconds": 1.0,
        "settings": _SETTINGS,
    }
    _write(results / ladder.BASE / "run_manifest.json", json.dumps(manifest))
    manifest["settings"] = _SETTINGS | {"response_schema": "typed-ir/1"}
    reply = {"status": "completed", "system_fingerprint": ladder.FINGERPRINT}
    # A failed reply may carry none; the check passes over it.
    failed = {"status": "failed", "system_fingerprint": None}
    for run in (ladder.SCHEMA, ladder.FEW_SHOT):
        _write(results / run / "run_manifest.json", json.dumps(manifest))
        replies = json.dumps({"completions": [reply, failed]})
        _write(results / run / "completions" / "C4.json", replies)
    (results / "sft-v1").mkdir()
    return results


def _rung(built: dict[str, Any], index: int) -> tuple[Any, ...]:
    rung = built["rungs"][index]
    counts = (rung["first_better_cases"], rung["second_better_cases"])
    return (rung["difference"]["value"], *counts, rung["reading"])


def test_each_rung_is_the_upper_row_minus_the_lower(tmp_path: Path) -> None:
    """Schema gains 11 cases, few-shot loses them, the seeds regain them."""
    every = _both(range(_CASES))
    named = {"schema": every, "s17": every, "s42": every, "s2026": every}
    results = _tree(tmp_path, named)
    output = results / ladder.OUTPUT

    assert ladder.main(["--results", str(results), "--check"]) == 1
    assert ladder.main(["--results", str(results)]) == 0
    assert ladder.main(["--results", str(results), "--check"]) == 0
    built = json.loads(output.read_text("utf-8"))
    assert [rung["rung"] for rung in built["rungs"]] == [
        "schema_minus_base",
        "few_shot_minus_schema",
        "sft_mean_minus_few_shot",
    ]
    assert _rung(built, 0) == (round(11 / 12, 6), 11, 0, "gain")
    assert _rung(built, 1) == (round(-11 / 12, 6), 0, 11, "loss")
    assert _rung(built, 2) == (round(11 / 12, 6), 11, 0, "gain")
    post_hoc = [row["post_hoc"] for row in built["rows"]]
    assert post_hoc == [False, True, True, False, False, False]
    output.write_bytes(output.read_bytes().replace(b'"items":24', b'"items":0'))
    assert ladder.main(["--results", str(results), "--check"]) == 1


def test_the_sft_rung_averages_the_seeds_before_it_counts(
    tmp_path: Path,
) -> None:
    """Seeds split on case 1 around few-shot's 0.5; nine gains stay a tie."""
    rest = _both(range(3, _CASES))
    named = {"few_shot": {(1, 0)}, "s17": rest | _both(range(1, 2))}
    named |= {"s42": rest, "s2026": rest | {(1, 0)}}
    built = ladder.build(_tree(tmp_path, named))

    assert built["sft_mean"]["rate"]["value"] == round(9.5 / 12, 6)
    assert _rung(built, 2) == (round(9 / 12, 6), 9, 0, "inconclusive")
    assert built["rungs"][2]["difference"]["low"] > 0


def test_a_rung_whose_interval_holds_0_is_inconclusive(tmp_path: Path) -> None:
    """Seven cases gained and five lost: enough discordant, no reading."""
    seeds = _both(range(5, _CASES))
    named = {"few_shot": _both(range(5)), "s17": seeds}
    named |= {"s42": seeds, "s2026": seeds}
    built = ladder.build(_tree(tmp_path, named))

    assert _rung(built, 2) == (round(2 / 12, 6), 7, 5, "inconclusive")
    difference = built["rungs"][2]["difference"]
    assert difference["low"] < 0 < difference["high"]


def test_rows_count_ready_c4_items_and_split_malformed_at_the_cap(
    tmp_path: Path,
) -> None:
    """The C1 and non-ready items stay out; one malformed reply hit 2048."""
    odd: Odd = {
        (1, 0): (OutcomeV1.MALFORMED, "length"),
        (1, 1): (OutcomeV1.MALFORMED, "stop"),
        (2, 0): (OutcomeV1.INVALID, None),
    }
    built = ladder.build(_tree(tmp_path, odd=odd))
    base = built["rows"][0]

    assert (built["cases"], built["items"]) == (12, 24)
    assert sum(base["outcomes"].values()) == 24
    assert base["outcomes"]["false_ready"] == 0
    outcomes = base["outcomes"]
    assert (outcomes["strong_exact"], outcomes["invalid"]) == (2, 1)
    assert base["malformed"] == {"truncated": 1, "other": 1}
    covered = base["coverage"]["every_gold_field_retrieved"]
    assert covered["value"] == round(1 / 12, 6)


def _drop(run: str, name: str) -> Callable[[Path], None]:
    return lambda results: (results / run / name).unlink()


def _change(
    run: str, name: str, change: Callable[[Any], object]
) -> Callable[[Path], None]:
    def edit(results: Path) -> None:
        path = results / run / name
        data = json.loads(path.read_text("utf-8"))
        change(data)
        path.write_text(json.dumps(data), "utf-8")

    return edit


def _lost_item(results: Path) -> None:
    path = results / ladder.FEW_SHOT / "scored" / "outcomes.jsonl"
    lines = path.read_text("utf-8").splitlines(keepends=True)
    path.write_text("".join(x for x in lines if "mei-111" not in x), "utf-8")


def _stale_summary(results: Path) -> None:
    _row(results.parent / "other", ladder.SCHEMA, _both(range(2)), {})
    stale = results.parent / "other" / ladder.SCHEMA / "scored" / "summary.json"
    shutil.copyfile(stale, results / ladder.SCHEMA / "scored" / "summary.json")


_SCHEMA, _FEW_SHOT = ladder.SCHEMA, ladder.FEW_SHOT
_UNSENT = "was not sent as registered:"


@pytest.mark.parametrize(
    ("edit", "error"),
    [
        (
            _drop(_SCHEMA, "scored/outcomes.jsonl"),
            f"run_not_scored: {_SCHEMA} has no scored/outcomes.jsonl",
        ),
        (
            _drop(_FEW_SHOT, "run_manifest.json"),
            f"run_not_scored: {_FEW_SHOT} has no run_manifest.json",
        ),
        (_lost_item, f"rows_differ: {_FEW_SHOT} answers other items"),
        (
            _stale_summary,
            f"summary_mismatch: {_SCHEMA} summary reports another C4 rate",
        ),
        (
            _change(
                _SCHEMA,
                "run_manifest.json",
                lambda data: data["settings"].pop("response_schema"),
            ),
            f"not_registered: {_SCHEMA} {_UNSENT} settings",
        ),
        (
            _change(
                _FEW_SHOT,
                "run_manifest.json",
                lambda data: data.update(endpoint_host="elsewhere"),
            ),
            f"not_registered: {_FEW_SHOT} {_UNSENT} host and call options",
        ),
        (
            _change(
                _SCHEMA,
                "completions/C4.json",
                lambda data: data["completions"][0].pop("system_fingerprint"),
            ),
            f"not_registered: {_SCHEMA} {_UNSENT} fingerprint",
        ),
    ],
)
def test_a_tree_the_registration_does_not_allow_writes_no_ladder(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    edit: Callable[[Path], None],
    error: str,
) -> None:
    """Before both baseline rows are scored the real tree stops here."""
    results = _tree(tmp_path)
    edit(results)

    assert ladder.main(["--results", str(results)]) == 2
    assert capsys.readouterr().err == error + "\n"
    assert not (results / ladder.OUTPUT).exists()


def test_on_the_committed_rows_the_sft_rung_is_the_headline_mean(
    tmp_path: Path,
) -> None:
    """Base copies in the two baseline rows' places give the headline."""
    committed = ladder.RESULTS
    if not (committed / _HEADLINE).is_file():
        pytest.skip("the test image carries no docs/ tree")
    results = tmp_path / "results"
    sent = (*_SCORED, "run_manifest.json", "completions/C4.json")
    copies: dict[str, tuple[str, tuple[str, ...]]] = {
        run: (run, _SCORED) for run in ladder.SEEDS.values()
    }
    copies[ladder.BASE] = (ladder.BASE, sent[:3])
    copies |= dict.fromkeys((_SCHEMA, _FEW_SHOT), (ladder.BASE, sent))
    for run, (source, names) in copies.items():
        for name in names:
            (results / run / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(committed / source / name, results / run / name)
    for run in (_SCHEMA, _FEW_SHOT):
        path = results / run / "run_manifest.json"
        manifest = json.loads(path.read_text("utf-8"))
        manifest["settings"]["response_schema"] = "typed-ir/1"
        path.write_text(json.dumps(manifest), "utf-8")
    headline = json.loads((committed / _HEADLINE).read_text("utf-8"))

    built = ladder.build(results)

    strata = headline["coverage"]
    assert (built["cases"], built["items"]) == (40, 80)
    assert built["coverage_items"] == {
        name: stratum["items"] for name, stratum in strata.items()
    }
    base, schema, few_shot, *seeds = built["rows"]
    assert (
        base["rate"] == schema["rate"] == few_shot["rate"] == headline["base"]
    )
    assert [s["rate"] for s in seeds] == [s["rate"] for s in headline["seeds"]]
    assert built["sft_mean"]["rate"] == headline["mean"]["rate"]
    mean = {
        key: value for key, value in headline["mean"].items() if key != "rate"
    }
    assert {key: built["rungs"][2][key] for key in mean} == mean
    for name, stratum in strata.items():
        for row in (base, schema, few_shot):
            assert row["coverage"][name] == stratum["base"]
        rates = [s["rate"] for s in stratum["seeds"]]
        assert [s["coverage"][name] for s in seeds] == rates
    assert base["outcomes"]["strong_exact"] == 5
    assert base["malformed"] == {"truncated": 4, "other": 17}
