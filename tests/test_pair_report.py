"""A pair of scored passes: changed answers, transitions and flipped cases.

The fixture is two published, scored two-condition passes whose every
number below was counted by hand from the tables in this file; the last
test reads the two committed dev passes that share their C1 and C2 prompts
and checks the repeat the typed-IR prompt v2 note reports.
"""

from datetime import datetime
from datetime import timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Literal, NamedTuple

import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.cli import main
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import RetrievalV1
from dfilterforge.pair_report import ConditionPass
from dfilterforge.pair_report import noise_reading
from dfilterforge.pair_report import pair_condition
from dfilterforge.pair_report import pair_runs
from dfilterforge.pair_report import PairError
from dfilterforge.pair_report import transitions
from dfilterforge.pair_report import TransitionV1
from dfilterforge.run_store import ScoringError
from dfilterforge.score_summary import ComparisonV1
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import GoldStatus
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import RateV1
from dfilterforge.score_summary import summarize

_CREATED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)
_SETTINGS = RequestSettingsV1(model_id="vendor/model-a")
_GOLD_HASH = "9" * 64
_LABELS: dict[ConditionLabel, tuple[OutputContractV1, RetrievalV1]] = {
    "C1": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    "C2": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
}
_CASES: dict[str, tuple[str, GoldStatus]] = {
    "mei-0001": ("case-a", "ready"),
    "mei-0002": ("case-a", "ready"),
    "mei-0003": ("case-b", "ready"),
    "mei-0004": ("case-b", "ready"),
    "mei-0005": ("case-c", "ready"),
    "mei-0006": ("case-c", "ready"),
    "mei-0007": ("case-n", "needs_clarification"),
    "mei-0008": ("case-n", "needs_clarification"),
}
_SE = OutcomeV1.STRONG_EXACT
_SW = OutcomeV1.SILENT_WRONG
_INV = OutcomeV1.INVALID
_PF = OutcomeV1.PROVIDER_FAILED
_AB = OutcomeV1.ABSTAINED
_FR = OutcomeV1.FALSE_READY


class _Answer(NamedTuple):
    """One item of one pass: its outcome and stored text, None if failed."""

    outcome: OutcomeV1
    text: str | None


_Table = dict[ConditionLabel, dict[str, _Answer]]

# The first pass and its rerun, item by item. In C1, mei-0002 is fixed,
# mei-0003 changes its text but not its outcome, mei-0005 fails, mei-0007
# turns ready on non-ready gold and mei-0008 fails in both passes. In C2
# only mei-0004 changes.
_FIRST: _Table = {
    "C1": {
        "mei-0001": _Answer(_SE, "ip.ttl <= 1"),
        "mei-0002": _Answer(_SW, "ip.ttl < 1"),
        "mei-0003": _Answer(_SE, "tcp.port == 443"),
        "mei-0004": _Answer(_INV, "tcp.prot == 443"),
        "mei-0005": _Answer(_SE, "dns"),
        "mei-0006": _Answer(_SE, "dns && udp"),
        "mei-0007": _Answer(_AB, "abstain"),
        "mei-0008": _Answer(_PF, None),
    },
    "C2": {
        "mei-0001": _Answer(_SE, "ip.ttl <= 1"),
        "mei-0002": _Answer(_SE, "ip.ttl <= 1"),
        "mei-0003": _Answer(_SE, "tcp.port == 443"),
        "mei-0004": _Answer(_SE, "tcp.port == 443"),
        "mei-0005": _Answer(_SE, "dns"),
        "mei-0006": _Answer(_SE, "dns"),
        "mei-0007": _Answer(_AB, "abstain"),
        "mei-0008": _Answer(_AB, "abstain"),
    },
}
_SECOND: _Table = {
    "C1": {
        **_FIRST["C1"],
        "mei-0002": _Answer(_SE, "ip.ttl <= 1"),
        "mei-0003": _Answer(_SE, "tcp.dstport == 443"),
        "mei-0005": _Answer(_PF, None),
        "mei-0007": _Answer(_FR, "tcp"),
    },
    "C2": {**_FIRST["C2"], "mei-0004": _Answer(_SW, "tcp.srcport == 443")},
}


def _write(path: Path, value: object) -> bytes:
    """Writes one contract as canonical JSON with an LF ending."""
    payload = (canonical_json(value) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _outcome(
    label: ConditionLabel, item_id: str, outcome: OutcomeV1
) -> ItemOutcomeV1:
    """Scores one item as the scorer records it."""
    case_id, status = _CASES[item_id]
    return ItemOutcomeV1(
        condition=label,
        item_id=item_id,
        case_id=case_id,
        outcome=outcome,
        gold_field_count=1,
        latency_ms=1.0,
        gold_status=status,
    )


def _completion(item_id: str, answer: _Answer) -> CompletionV1:
    """Stores one answer, or a provider failure when it has no text."""
    if answer.text is None:
        return CompletionV1(
            item_id=item_id,
            status=CompletionStatusV1.FAILED,
            error_code="timeout",
            latency_ms=1.0,
        )
    return CompletionV1(
        item_id=item_id,
        status=CompletionStatusV1.COMPLETED,
        response_text=answer.text,
        latency_ms=1.0,
        finish_reason="stop",
    )


# pylint: disable-next=too-many-arguments,too-many-locals
def _write_pass(
    run_dir: Path,
    table: _Table,
    *,
    split: Literal["dev", "test"] = "dev",
    settings: RequestSettingsV1 = _SETTINGS,
    gold_hash: str = _GOLD_HASH,
    intents: dict[str, str] | None = None,
) -> Path:
    """Publishes and scores one pass whose answers and outcomes are given.

    ``intents`` replaces an item's request text in every prompt, so a
    pass can prepare other prompts for the same items.
    """
    run_dir = run_dir.with_name(f"{split}-{run_dir.name}")
    outcomes: list[ItemOutcomeV1] = []
    prepared: list[PreparedConditionV1] = []
    census: list[ConditionRunV1] = []
    for label, answers in table.items():
        output_contract, retrieval = _LABELS[label]
        batch = prepare_batch(
            [
                GenerationInputV1(
                    item_id=item_id,
                    intent=(intents or {}).get(item_id, f"request {item_id}"),
                    retrieved_fields=(
                        () if retrieval is RetrievalV1.LEXICAL else None
                    ),
                    split=split,
                )
                for item_id in answers
            ],
            output_contract=output_contract,
            retrieval=retrieval,
        )
        payload = _write(run_dir / "prepared" / f"{label}.json", batch)
        _write(
            run_dir / "completions" / f"{label}.json",
            CompletionBatchV1(
                output_contract=output_contract,
                retrieval=retrieval,
                settings=settings,
                completions=tuple(
                    _completion(item_id, answer)
                    for item_id, answer in answers.items()
                ),
            ),
        )
        prepared.append(
            PreparedConditionV1(
                label=label,
                output_contract=output_contract,
                retrieval=retrieval,
                path=f"prepared/{label}.json",
                sha256=hashlib.sha256(payload).hexdigest(),
                system_prompt_sha256="5" * 64,
                prompt_count=len(answers),
            )
        )
        failed = sum(1 for answer in answers.values() if answer.text is None)
        census.append(
            ConditionRunV1(
                label=label,
                attempts_path=f"attempts/{label}.jsonl",
                attempts_sha256="7" * 64,
                completions_path=f"completions/{label}.json",
                completions_sha256="8" * 64,
                attempts={item_id: 1 for item_id in answers},
                completed=len(answers) - failed,
                failed=failed,
                pending=0,
            )
        )
        outcomes.extend(
            _outcome(label, item_id, answer.outcome)
            for item_id, answer in answers.items()
        )
    prepare = PrepareManifestV1(
        prepare_id="prep-0001",
        created_at=_CREATED_AT,
        source_revision="revision",
        source_files={"scripts/model_run.py": "1" * 64},
        split=split,
        item_ids=tuple(_CASES),
        model_inputs_sha256="2" * 64,
        catalog=CatalogIdentityV1(
            file_name="catalog.sqlite3",
            file_sha256="3" * 64,
            sqlite_sha256="3" * 64,
            catalog_hash="4" * 64,
            tshark_version="4.6.8",
        ),
        top_k=16,
        conditions=tuple(prepared),
    )
    _write(run_dir / "prepare.json", prepare)
    _write(
        run_dir / "run_manifest.json",
        RunManifestV1(
            run_id=run_dir.name,
            created_at=_CREATED_AT,
            prepare=prepare,
            prepare_sha256="6" * 64,
            endpoint_host="openrouter.ai",
            settings=settings,
            max_attempts=3,
            min_interval_seconds=1.0,
            invocations=(
                InvocationV1(
                    source_revision="revision",
                    source_files={"scripts/model_run.py": "1" * 64},
                    started_at=_CREATED_AT,
                    finished_at=_CREATED_AT,
                    max_usd=0.05,
                    requests_sent=len(outcomes),
                ),
            ),
            status="complete",
            charged_usd_upper_bound=0.01,
            conditions=tuple(census),
        ),
    )
    ordered = sorted(outcomes, key=lambda item: (item.condition, item.item_id))
    scored = run_dir / "scored"
    scored.mkdir(parents=True)
    (scored / "outcomes.jsonl").write_bytes(
        "".join(canonical_json(item) + "\n" for item in ordered).encode()
    )
    _write(
        scored / "summary.json",
        summarize(
            ordered,
            run=run_dir.name,
            model_id=settings.model_id,
            split=split,
            gold_hash=gold_hash,
            capture_hashes={},
            batch_hashes={},
        ),
    )
    return run_dir


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    """The hand-counted pair: a first pass and its rerun."""
    return (
        _write_pass(tmp_path / "first", _FIRST),
        _write_pass(tmp_path / "second", _SECOND),
    )


def _refused(first: Path, second: Path) -> str:
    """Pairs two passes that must be refused and returns the code."""
    with pytest.raises(PairError) as error:
        pair_runs(first, second)
    return error.value.code


def test_transitions_count_each_pair_in_outcome_order() -> None:
    pairs = [(_SE, _SE), (_SW, _SE), (_SE, _SE), (_PF, _SE), (_SE, _PF)]

    counted = transitions(pairs)

    assert counted == (
        TransitionV1(first=_PF, second=_SE, items=1),
        TransitionV1(first=_SW, second=_SE, items=1),
        TransitionV1(first=_SE, second=_PF, items=1),
        TransitionV1(first=_SE, second=_SE, items=2),
    )
    assert not transitions([])


def test_a_hand_counted_pair_reports_each_condition(tmp_path: Path) -> None:
    first, second = _pair(tmp_path)

    report = pair_runs(first, second)
    c1, c2 = report.conditions

    assert report.split == "dev" and report.gold_hash == _GOLD_HASH
    assert report.first.run == "dev-first" and report.second.run == "dev-second"
    assert report.first.model_id == "vendor/model-a"
    assert (
        report.first.outcomes_sha256
        == hashlib.sha256(
            (first / "scored" / "outcomes.jsonl").read_bytes()
        ).hexdigest()
    )
    assert report.settings_identical is True
    # C1: 0002, 0003, 0005 and 0007 stored other text; 0008 failed twice.
    assert (c1.condition, c1.items, c1.prompts_identical) == ("C1", 8, True)
    assert c1.changed_answers == 4
    assert c1.changed_outcomes == 3
    assert c1.changed_outcome_items == ("mei-0002", "mei-0005", "mei-0007")
    assert [(t.first, t.second, t.items) for t in c1.transitions] == [
        (_PF, _PF, 1),
        (_AB, _FR, 1),
        (_INV, _INV, 1),
        (_SW, _SE, 1),
        (_SE, _PF, 1),
        (_SE, _SE, 3),
    ]
    # Case a goes 0.5 -> 1, case b stays 0.5, case c goes 1 -> 0.5.
    assert c1.ready_cases == 3
    assert c1.flipped_cases == 2
    assert (c1.first_better_cases, c1.second_better_cases) == (1, 1)
    assert c1.flipped_case_ids == ("case-a", "case-c")
    assert (c2.changed_answers, c2.changed_outcomes) == (1, 1)
    assert c2.changed_outcome_items == ("mei-0004",)
    assert [(t.first, t.second, t.items) for t in c2.transitions] == [
        (_AB, _AB, 2),
        (_SE, _SW, 1),
        (_SE, _SE, 5),
    ]
    assert (c2.flipped_cases, c2.first_better_cases) == (1, 1)
    assert c2.flipped_case_ids == ("case-b",)


def test_the_pair_reads_each_summary_comparison_against_its_noise(
    tmp_path: Path,
) -> None:
    first, second = _pair(tmp_path)

    (comparison,) = pair_runs(first, second).comparisons

    # C2 - C1 favours C2 on cases a and b first, on case c in the rerun.
    assert (comparison.first, comparison.second) == ("C2", "C1")
    # 2 * sqrt((1 + 2) / 2), flipped in C2 and C1.
    assert comparison.noise_bound == 2.44949
    assert comparison.first_pass.net_cases == 2
    assert comparison.first_pass.discordant_cases == 2
    assert comparison.second_pass.net_cases == 1
    assert comparison.second_pass.discordant_cases == 1
    # Under 10 discordant cases a comparison is inconclusive, not noise.
    assert comparison.first_pass.within_noise is None
    assert comparison.second_pass.within_noise is None
    assert comparison.sign_reversed is False


def _comparison(first_better: int, second_better: int) -> ComparisonV1:
    """A C4 - C2 comparison as a summary holds it."""
    discordant = first_better + second_better
    return ComparisonV1(
        first="C4",
        second="C2",
        difference=RateV1(value=0.0),
        first_better_cases=first_better,
        second_better_cases=second_better,
        discordant_cases=discordant,
        inconclusive=discordant < 10,
    )


@pytest.mark.parametrize(
    ("flipped", "bound", "within"),
    [
        # 2 * sqrt((32 + 18) / 2) = 10: a net of 10 is at the bound.
        ({"C4": 32, "C2": 18}, 10.0, (True, True)),
        # 2 * sqrt((25 + 24) / 2) = 9.899495: a net of 10 is past it.
        ({"C4": 25, "C2": 24}, 9.899495, (False, True)),
        ({"C4": 0, "C2": 0}, 0.0, (False, False)),
    ],
)
def test_a_conclusive_comparison_is_read_against_the_bound(
    flipped: dict[ConditionLabel, int],
    bound: float,
    within: tuple[bool, bool],
) -> None:
    reading = noise_reading(_comparison(11, 1), _comparison(2, 9), flipped)

    assert reading.noise_bound == bound
    assert (reading.first_pass.net_cases, reading.second_pass.net_cases) == (
        10,
        -7,
    )
    assert (
        reading.first_pass.within_noise,
        reading.second_pass.within_noise,
    ) == within
    assert reading.sign_reversed is True


def test_a_rerun_with_the_same_sign_or_none_is_not_reversed() -> None:
    flipped: dict[ConditionLabel, int] = {"C4": 1, "C2": 1}

    same = noise_reading(_comparison(11, 1), _comparison(9, 2), flipped)
    level = noise_reading(_comparison(11, 1), _comparison(5, 5), flipped)

    assert same.sign_reversed is False
    assert level.sign_reversed is False
    assert level.second_pass.net_cases == 0


def test_two_comparisons_of_other_conditions_are_not_read_together() -> None:
    other = _comparison(1, 1).model_copy(update={"first": "C3"})

    with pytest.raises(ValueError):
        noise_reading(_comparison(1, 1), other, {"C4": 0, "C2": 0, "C3": 0})


def test_a_pass_paired_with_itself_changes_nothing(tmp_path: Path) -> None:
    first, _ = _pair(tmp_path)

    report = pair_runs(first, first)

    for condition in report.conditions:
        assert condition.prompts_identical is True
        assert condition.changed_answers == 0
        assert condition.changed_outcomes == 0
        assert condition.flipped_cases == 0
        assert all(t.first is t.second for t in condition.transitions)
        assert sum(t.items for t in condition.transitions) == 8
    assert report.comparisons[0].noise_bound == 0.0


def test_other_prompts_or_settings_are_reported_not_refused(
    tmp_path: Path,
) -> None:
    first, _ = _pair(tmp_path)
    second = _write_pass(
        tmp_path / "rerun",
        _FIRST,
        settings=RequestSettingsV1(model_id="vendor/model-a", temperature=0.5),
        intents={"mei-0003": "another request"},
    )

    report = pair_runs(first, second)

    assert [c.prompts_identical for c in report.conditions] == [False, False]
    assert report.settings_identical is False
    assert all(c.changed_answers == 0 for c in report.conditions)


@pytest.mark.parametrize(
    "update",
    [
        {"endpoint_host": "api.example.org"},
        {"max_attempts": 2},
        {"min_interval_seconds": 2.0},
    ],
)
def test_another_host_attempt_limit_or_pacing_is_not_identical(
    tmp_path: Path, update: dict[str, object]
) -> None:
    first, second = _pair(tmp_path)
    path = second / "run_manifest.json"
    manifest = RunManifestV1.model_validate_json(path.read_bytes())
    _write(path, manifest.model_copy(update=update))

    assert pair_runs(first, second).settings_identical is False
    assert pair_runs(first, first).settings_identical is True


def _side(
    table: dict[str, _Answer], cases: dict[str, str] | None = None
) -> ConditionPass:
    """One condition of a pass, with any item routed to another case."""
    return ConditionPass(
        outcomes=[
            _outcome("C1", item_id, answer.outcome).model_copy(
                update={
                    "case_id": (cases or {}).get(item_id, _CASES[item_id][0])
                }
            )
            for item_id, answer in table.items()
        ],
        answers={item_id: answer.text for item_id, answer in table.items()},
        prompts_sha256="0" * 64,
    )


def test_a_condition_pair_needs_the_same_items_on_the_same_gold() -> None:
    whole = _side(_FIRST["C1"])
    fewer = _side({k: v for k, v in _FIRST["C1"].items() if k != "mei-0008"})
    moved = _side(_FIRST["C1"], {"mei-0001": "case-b"})
    repeated = whole._replace(outcomes=[*whole.outcomes, whole.outcomes[0]])

    for first, second in (
        (whole, fewer),
        (whole, moved),
        (repeated, whole),
    ):
        with pytest.raises(PairError) as error:
            pair_condition("C1", first, second)
        assert error.value.code == "pair_mismatch"
    assert pair_condition("C1", whole, whole).changed_answers == 0


def test_passes_of_other_splits_conditions_or_gold_are_refused(
    tmp_path: Path,
) -> None:
    first, _ = _pair(tmp_path)
    other_split = _write_pass(tmp_path / "split", _FIRST, split="test")
    one_condition = _write_pass(tmp_path / "one", {"C1": _FIRST["C1"]})
    other_gold = _write_pass(tmp_path / "gold", _FIRST, gold_hash="a" * 64)

    assert _refused(first, other_split) == "pair_mismatch"
    assert _refused(first, one_condition) == "pair_mismatch"
    assert _refused(first, other_gold) == "pair_mismatch"


def test_an_unpublished_pass_is_refused(tmp_path: Path) -> None:
    first, second = _pair(tmp_path)
    (second / "run_manifest.json").unlink()

    assert _refused(first, second) == "pair_unpublished"


def _outcome_lines(run_dir: Path) -> list[bytes]:
    """The committed outcome lines of a pass."""
    return (
        (run_dir / "scored" / "outcomes.jsonl")
        .read_bytes()
        .splitlines(keepends=True)
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "unreadable",
        "repeated",
        "short",
        "unprepared",
        "symlink",
        "summary",
        "foreign summary",
    ],
)
def test_a_pass_whose_outcomes_do_not_score_its_prompts_is_refused(
    tmp_path: Path, damage: str
) -> None:
    first, second = _pair(tmp_path)
    outcomes = second / "scored" / "outcomes.jsonl"
    lines = _outcome_lines(second)
    unprepared = _outcome("C1", "mei-0001", _SE).model_copy(
        update={"condition": "C3"}
    )
    if damage == "missing":
        outcomes.unlink()
    elif damage == "unreadable":
        outcomes.write_bytes(b"".join([*lines, b"{}\n"]))
    elif damage == "repeated":
        outcomes.write_bytes(b"".join([*lines, lines[0]]))
    elif damage == "short":
        outcomes.write_bytes(b"".join(lines[1:]))
    elif damage == "unprepared":
        extra = (canonical_json(unprepared) + "\n").encode()
        outcomes.write_bytes(b"".join([*lines, extra]))
    elif damage == "symlink":
        shutil.move(outcomes, tmp_path / "elsewhere.jsonl")
        try:
            outcomes.symlink_to(tmp_path / "elsewhere.jsonl")
        except OSError:
            pytest.skip("symlinks are not available here")
    elif damage == "summary":
        (second / "scored" / "summary.json").write_bytes(b"{}\n")
    else:
        shutil.copyfile(
            first / "scored" / "summary.json",
            second / "scored" / "summary.json",
        )

    assert _refused(first, second) == "pair_unscored"


def test_a_pass_whose_layout_fails_is_refused_as_scoring_is(
    tmp_path: Path,
) -> None:
    first, second = _pair(tmp_path)
    (second / "completions" / "C2.json").unlink()

    with pytest.raises(ScoringError) as error:
        pair_runs(first, second)
    assert error.value.code == "run_layout_invalid"


def test_the_cli_prints_the_report_and_refuses_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = _pair(tmp_path)
    expected = json.loads(canonical_json(pair_runs(first, second)))
    args = ["pair", "--first-run-dir", str(first), "--second-run-dir"]

    assert main([*args, str(second)]) == 0
    printed = json.loads(capsys.readouterr().out)
    (second / "scored" / "outcomes.jsonl").unlink()
    assert main([*args, str(second)]) == 2
    refused = json.loads(capsys.readouterr().err)

    assert printed == expected
    assert printed["schema_version"] == "pair-report/1.0"
    assert [c["changed_answers"] for c in printed["conditions"]] == [4, 1]
    assert refused["error"]["code"] == "pair_unscored"


_RESULTS = Path(__file__).parents[1] / "docs" / "results"


def test_the_committed_c1_and_c2_rerun_is_the_one_the_v2_note_reports() -> None:
    """The typed-IR prompt v2 note's repeatability paragraph, re-counted.

    C1 and C2 were prepared byte for byte the same in both dev passes, the
    answer text is identical on 12 and 14 of 16 items, and the only outcome
    that changed is C1/mei-0005, which flips its case and takes C1 from 8 to
    9 strong exact.
    """
    first = _RESULTS / "dev-qwen3-32b-2026-09-21"
    second = _RESULTS / "dev-qwen3-32b-v2-2026-09-23"
    if not (first.is_dir() and second.is_dir()):
        pytest.skip("the test image carries no docs/ tree")

    report = pair_runs(first, second)
    c1, c2, c3, c4 = report.conditions

    assert report.settings_identical is True
    assert (c1.prompts_identical, c2.prompts_identical) == (True, True)
    assert (c3.prompts_identical, c4.prompts_identical) == (False, False)
    assert (c1.items, c1.changed_answers, c2.changed_answers) == (16, 4, 2)
    assert c1.changed_outcome_items == ("mei-0005",)
    assert [
        (t.first, t.second) for t in c1.transitions if t.first != t.second
    ] == [(_SW, _SE)]
    assert c2.changed_outcomes == 0
    assert (c1.flipped_cases, c1.second_better_cases) == (1, 1)
    assert c2.flipped_cases == 0
    exact = [
        sum(t.items for t in c1.transitions if getattr(t, side) is _SE)
        for side in ("first", "second")
    ]
    assert exact == [8, 9]
