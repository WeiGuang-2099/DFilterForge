"""The SFT headline's estimator, on small hand-built runs and on the tree."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
        "sft_headline", _ROOT / "scripts" / "sft_headline.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("sft_headline cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


headline = _load()
_CASES = 12


def _item(
    case: int, paraphrase: int, exact: bool, covered: bool
) -> ItemOutcomeV1:
    return ItemOutcomeV1(
        condition="C4",
        item_id=f"mei-{case:02d}{paraphrase}",
        case_id=f"case-{case:02d}",
        outcome=OutcomeV1.STRONG_EXACT if exact else OutcomeV1.SILENT_WRONG,
        gold_field_count=2,
        retrieved_gold_field_count=2 if covered else 1,
        latency_ms=1.0,
    )


def _write(results: Path, run: str, exact: set[tuple[int, int]]) -> None:
    """Writes a scored run whose items in ``exact`` are strong exact.

    The first paraphrase of every case has each gold field retrieved and
    the second misses one, so each case sits in both coverage strata.
    """
    items = [
        _item(case, paraphrase, (case, paraphrase) in exact, paraphrase == 0)
        for case in range(_CASES)
        for paraphrase in (0, 1)
    ]
    scored = results / run / "scored"
    scored.mkdir(parents=True)
    (scored / "outcomes.jsonl").write_text(
        "".join(canonical_json(item) + "\n" for item in items), encoding="utf-8"
    )
    summary = summarize(
        items,
        run=run,
        model_id=f"model-{run}",
        split="test",
        gold_hash="0" * 64,
        capture_hashes={},
        batch_hashes={},
    )
    (scored / "summary.json").write_text(canonical_json(summary), "utf-8")


def _both(cases: range) -> set[tuple[int, int]]:
    return {(case, paraphrase) for case in cases for paraphrase in (0, 1)}


def _tree(tmp_path: Path, seeds: dict[int, set[tuple[int, int]]]) -> Path:
    """Base exact on case 0; hosted rows exact on cases 0 to 5."""
    _write(tmp_path, headline.BASE, _both(range(1)))
    for seed, run in headline.SEEDS.items():
        _write(tmp_path, run, seeds[seed])
    for run in headline.HOSTED:
        _write(tmp_path, run, _both(range(6)))
    (tmp_path / "sft-v1").mkdir()
    return tmp_path


def _same(exact: set[tuple[int, int]]) -> dict[int, set[tuple[int, int]]]:
    return {seed: exact for seed in headline.SEEDS}


def _seed(ladder: dict[str, Any], seed: int) -> dict[str, Any]:
    (row,) = [row for row in ladder["seeds"] if row["seed"] == seed]
    return row


def test_a_seed_gains_only_with_ten_discordant_cases(tmp_path: Path) -> None:
    """Eleven cases gained is a gain; the base row's one case stays tied."""
    built = headline.build(_tree(tmp_path, _same(_both(range(_CASES)))))
    seed = _seed(built, 17)

    assert [row["seed"] for row in built["seeds"]] == [17, 42, 2026]
    assert built["base"]["value"] == pytest.approx(1 / 12, abs=1e-6)
    assert seed["difference"]["value"] == pytest.approx(11 / 12, abs=1e-6)
    assert (seed["first_better_cases"], seed["second_better_cases"]) == (11, 0)
    assert seed["reading"] == "gain"


def test_fewer_than_ten_discordant_cases_is_inconclusive(
    tmp_path: Path,
) -> None:
    """Nine cases gained excludes 0 from the interval but stays a tie."""
    built = headline.build(_tree(tmp_path, _same(_both(range(10)))))

    seed = _seed(built, 17)

    assert seed["discordant_cases"] == 9
    assert seed["difference"]["low"] > 0
    assert seed["reading"] == "inconclusive"


def test_the_mean_averages_the_seeds_case_by_case(tmp_path: Path) -> None:
    """Opposite seeds cancel on a case, so it is not discordant."""
    gained = _both(range(_CASES))
    seeds = {17: gained, 42: gained, 2026: _both(range(1))}
    built = headline.build(_tree(tmp_path, seeds))
    mean = built["mean"]

    assert mean["rate"]["value"] == pytest.approx(
        (1 + 1 + 1 / 12) / 3, abs=1e-6
    )
    assert mean["difference"]["value"] == pytest.approx(
        (11 / 12 + 11 / 12 + 0) / 3, abs=1e-6
    )
    assert mean["discordant_cases"] == 11
    assert _seed(built, 2026)["discordant_cases"] == 0


def test_the_coverage_split_is_a_ratio_over_the_shared_strata(
    tmp_path: Path,
) -> None:
    """Only the seeds' covered paraphrases are exact; nothing is read."""
    covered = {(case, 0) for case in range(_CASES)}
    built = headline.build(_tree(tmp_path, _same(covered)))
    full = built["coverage"]["every_gold_field_retrieved"]
    rest = built["coverage"]["some_gold_field_missing"]

    assert full["items"] == 12
    assert _seed(full, 42)["rate"]["value"] == pytest.approx(1.0)
    assert _seed(rest, 42)["rate"]["value"] == pytest.approx(0.0)
    assert rest["base"]["value"] == pytest.approx(1 / 12, abs=1e-6)
    assert _seed(full, 42)["discordant_cases"] == 11
    assert all("reading" not in row for row in (*full["seeds"], full["mean"]))


def test_hosted_rows_are_set_against_the_mean_without_a_verdict(
    tmp_path: Path,
) -> None:
    """Seven seed cases against six hosted ones differ on one case."""
    seeds = _same(_both(range(1, 7)) | _both(range(0, 1)))
    built = headline.build(_tree(tmp_path, seeds))

    assert [row["run"] for row in built["hosted"]] == list(headline.HOSTED)
    for row in built["hosted"]:
        assert row["difference"]["value"] == pytest.approx(1 / 12, abs=1e-6)
        assert row["reading"] == "not separable on these 40 cases"


def test_rows_that_answer_other_items_are_refused(tmp_path: Path) -> None:
    """A seed scored on another case set stops the build."""
    results = _tree(tmp_path, _same(_both(range(_CASES))))
    path = results / headline.SEEDS[42] / "scored" / "outcomes.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    assert headline.main(["--results", str(results)]) == 2


def test_an_unscored_seed_writes_no_headline(tmp_path: Path) -> None:
    """No mean is computed before every seed is scored."""
    results = _tree(tmp_path, _same(_both(range(_CASES))))
    (results / headline.SEEDS[17] / "scored" / "outcomes.jsonl").unlink()

    assert headline.main(["--results", str(results)]) == 2
    assert not (results / headline.OUTPUT).exists()


def test_a_summary_that_disagrees_is_refused(tmp_path: Path) -> None:
    """A stale summary.json cannot stand behind the headline."""
    results = _tree(tmp_path, _same(_both(range(_CASES))))
    _write(tmp_path / "other", headline.SEEDS[17], _both(range(2)))
    stale = tmp_path / "other" / headline.SEEDS[17] / "scored" / "summary.json"
    target = results / headline.SEEDS[17] / "scored" / "summary.json"
    target.write_text(stale.read_text("utf-8"), "utf-8")

    with pytest.raises(headline.DFilterForgeError, match="another C4 rate"):
        headline.build(results)


def test_check_compares_the_committed_bytes(tmp_path: Path) -> None:
    """--check passes on a fresh write and fails once the file changes."""
    results = _tree(tmp_path, _same(_both(range(_CASES))))

    assert headline.main(["--results", str(results)]) == 0
    assert headline.main(["--results", str(results), "--check"]) == 0
    output = results / headline.OUTPUT
    data: dict[str, Any] = json.loads(output.read_text("utf-8"))
    data["items"] = 0
    output.write_text(canonical_json(data) + "\n", "utf-8")
    assert headline.main(["--results", str(results), "--check"]) == 1


def test_the_committed_headline_is_its_rebuild() -> None:
    """The committed file is what the committed scores give."""
    if not (headline.RESULTS / headline.OUTPUT).is_file():
        pytest.skip("the test image carries no docs/ tree")

    assert headline.main(["--check"]) == 0
