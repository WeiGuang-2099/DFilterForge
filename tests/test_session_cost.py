"""The session cost, on a small hand-built tree and on the committed one."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from dfilterforge.canonical import canonical_json

_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "session_cost", _ROOT / "scripts" / "session_cost.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("session_cost cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cost = _load()
# Every app bills USD 0.25 for the hour from 16:30 local time (06:00 UTC).
_ROWS = (("L4", "0.20000000"), ("CPU", "0.04999954"), ("Memory", "4.6E-7"))
_LATENCY_MS = 36_000.0  # a hundredth of an hour

Rows = list[dict[str, str]]


def _publish(results: Path, run: str, sent_at: str, requests: int) -> None:
    """Writes a run whose one invocation sent ``requests`` at ``sent_at``."""
    attempts = results / run / "attempts"
    attempts.mkdir(parents=True)
    line = canonical_json({"completion": {"latency_ms": _LATENCY_MS}})
    (attempts / "C4.jsonl").write_text(f"{line}\n" * requests, "utf-8")
    invocation = {"started_at": sent_at, "finished_at": sent_at}
    manifest = {
        "conditions": [{"label": "C4", "attempts_path": "attempts/C4.jsonl"}],
        "invocations": [invocation | {"requests_sent": requests}],
    }
    (results / run / "run_manifest.json").write_text(
        canonical_json(manifest), "utf-8"
    )


def _tree(tmp_path: Path) -> Path:
    """Every listed run sent at 06:30 UTC on its session's date.

    Each sends one request but the last, which sends three, so the
    sessions send 11, 9 and 6, and the unread passes add 224: 250 in all.
    The results directory sits under docs/, beside the bills' directory.
    """
    results = tmp_path / "docs" / "results"
    runs = [(day.date, run) for day in cost.SESSIONS for run in day.runs]
    for index, (date, run) in enumerate(runs, start=1):
        sent = 3 if index == len(runs) else 1
        _publish(results, run, f"{date}T06:30:00Z", sent)
    rows = [
        {
            "object_id": day.app,
            "interval_start": f"{day.date}T16:30:00+10:30",
            "resource": resource,
            "cost": usd,
        }
        for day in (*cost.SESSIONS, cost.EXCLUDED)
        for resource, usd in _ROWS
    ]
    bills = tmp_path / cost.BILLS
    bills.parent.mkdir(parents=True)
    bills.write_text(json.dumps({"rows": rows}), "utf-8")
    (results / "sft-v1").mkdir()
    return results


def test_the_bills_sum_over_the_requests_beside_the_gpu_time(
    tmp_path: Path,
) -> None:
    """USD 0.75 over 250 requests; the 224 unread ones add no GPU time."""
    results = _tree(tmp_path)

    assert cost.main(["--results", str(results)]) == 0
    built = json.loads((results / cost.OUTPUT).read_text("utf-8"))
    sessions: list[dict[str, Any]] = built["sessions"]
    assert built["total"] == {
        "bill_usd": "0.75000000",
        "bill_usd_by_resource": {
            "CPU": "0.14999862",
            "L4": "0.60000000",
            "Memory": "0.00000138",
        },
        "requests": 250,
        "usd_per_1000_requests": "3.00000000",
        "gpu_hours": 0.26,
        "gpu_usd": "0.20800000",
    }
    assert [
        (day["date"], day["bill_usd"], day["requests"], day["gpu_hours"])
        for day in sessions
    ] == [
        ("2026-10-28", "0.25000000", 235, 0.11),
        ("2026-10-31", "0.25000000", 9, 0.09),
        ("2026-11-05", "0.25000000", 6, 0.06),
    ]
    assert sessions[0]["unread"] == {
        "runs": list(cost.SESSIONS[0].unread),
        "requests": 224,
        "requests_from": "prompt_count",
        "latencies_in_gpu_time": False,
    }
    assert sessions[1]["unread"] is None
    assert built["excluded"] == {
        "date": "2026-10-29",
        "app": cost.EXCLUDED.app,
        "bill_usd": "0.25000000",
    }
    assert built["not_counted"] == ["schema_probes", "wake_requests"]
    assert len(built["sources"]) == 1 + 2 * 24


@pytest.mark.parametrize(
    ("missing", "named"),
    [
        (
            (
                "test-qwen3-1.7b-schema-ord-2026-10-26/run_manifest.json",
                "test-qwen3-1.7b-fs8-ord-2026-10-26/run_manifest.json",
            ),
            "test-qwen3-1.7b-schema-ord-2026-10-26 has no run_manifest.json",
        ),
        (
            ("dev-qwen3-1.7b-sft-s42-cx-2026-10-07/attempts/C4.jsonl",),
            "dev-qwen3-1.7b-sft-s42-cx-2026-10-07 has no attempts/C4.jsonl",
        ),
    ],
    ids=["no_manifest", "no_attempts"],
)
def test_a_run_not_published_refuses_and_writes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing: tuple[str, ...],
    named: str,
) -> None:
    """The first missing file is named, as on a tree like today's."""
    results = _tree(tmp_path)
    for path in missing:
        (results / path).unlink()

    assert cost.main(["--results", str(results)]) == 2
    assert cost.main(["--results", str(results), "--check"]) == 2
    assert capsys.readouterr().err == f"run_not_published: {named}\n" * 2
    assert not (results / cost.OUTPUT).exists()


@pytest.mark.parametrize(
    ("started", "finished"),
    [
        ("2026-10-31T06:50:00Z", "2026-10-31T07:10:00Z"),
        ("2026-10-30T06:30:00Z", "2026-10-30T06:40:00Z"),
    ],
    ids=["past_the_billed_hour", "a_day_early"],
)
def test_a_run_sent_outside_its_session_refuses(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    started: str,
    finished: str,
) -> None:
    """A resume past the session's billed hour, or one a day early."""
    results = _tree(tmp_path)
    run = cost.SESSIONS[1].runs[4]
    path = results / run / "run_manifest.json"
    manifest = json.loads(path.read_text("utf-8"))
    manifest["invocations"].append(
        {"started_at": started, "finished_at": finished, "requests_sent": 1}
    )
    path.write_text(canonical_json(manifest), "utf-8")

    assert cost.main(["--results", str(results)]) == 2
    assert capsys.readouterr().err == (
        f"session_mismatch: {run} was sent outside the session of 2026-10-31\n"
    )
    assert not (results / cost.OUTPUT).exists()


def _rows(change: Callable[[Rows], Rows]) -> Callable[[Path], None]:
    """An edit that replaces the bills' rows with ``change`` of them."""

    def edit(bills: Path) -> None:
        data = json.loads(bills.read_text("utf-8"))
        bills.write_text(json.dumps({"rows": change(data["rows"])}), "utf-8")

    return edit


@pytest.mark.parametrize(
    ("edit", "refusal"),
    [
        (
            _rows(
                lambda rows: [
                    row for row in rows if row["object_id"] != cost.EXCLUDED.app
                ]
            ),
            "bills_differ: the bills do not show ap-oeAVuNiK99WrMlnHTKvJkL"
            " on 2026-10-29 alone",
        ),
        (
            _rows(
                lambda rows: [
                    (
                        row | {"interval_start": "2026-11-01T16:30:00+10:30"}
                        if row["object_id"] == cost.SESSIONS[1].app
                        and row["resource"] == "CPU"
                        else row
                    )
                    for row in rows
                ]
            ),
            "bills_differ: the bills do not show ap-GP0X6i9el6rilY602ncFdg"
            " on 2026-10-31 alone",
        ),
        (
            Path.unlink,
            "bills_missing: docs/decisions/evidence/self-served/"
            "modal-billing-2026-10-28-to-11-05.json is missing",
        ),
    ],
    ids=["no_row_of_an_app", "a_row_a_day_late", "no_bills"],
)
def test_bills_that_do_not_show_each_session_on_its_date_refuse(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    edit: Callable[[Path], None],
    refusal: str,
) -> None:
    """No row for an app, rows on another date, or no bills at all."""
    results = _tree(tmp_path)
    edit(tmp_path / cost.BILLS)

    assert cost.main(["--results", str(results)]) == 2
    assert capsys.readouterr().err == f"{refusal}\n"
    assert not (results / cost.OUTPUT).exists()


def test_check_finds_one_changed_byte_and_passes_after_the_rebuild(
    tmp_path: Path,
) -> None:
    """--check is 1 while the file is missing or differs, 0 once rebuilt."""
    results = _tree(tmp_path)
    output = results / cost.OUTPUT
    write = ["--results", str(results)]

    assert cost.main([*write, "--check"]) == 1
    assert cost.main(write) == 0
    written = output.read_bytes()
    assert cost.main([*write, "--check"]) == 0
    changed = written.replace(b'"3.00000000"', b'"3.00000001"')
    assert changed != written
    output.write_bytes(changed)
    assert cost.main([*write, "--check"]) == 1
    assert cost.main(write) == 0
    assert cost.main([*write, "--check"]) == 0
    assert output.read_bytes() == written


def test_the_committed_sessions_sent_the_requests_the_notes_count() -> None:
    """46 and 125 requests per repair arm, 40 per dev pass, and 224.

    The repair note counts the arms' requests, the two 2026-10-26 dev
    passes sent each of their 40 items once, and the 224 is the prompt
    count of the corrected test prepares, whose prompts are byte for byte
    the unread passes'. The excluded app billed USD 0.0108, as the
    self-served note says. Skips until every listed run is published,
    since the cost refuses until then; the test image has no docs/ tree.
    """
    runs = [run for day in cost.SESSIONS for run in day.runs]
    if not all(
        (cost.RESULTS / run / "run_manifest.json").is_file() for run in runs
    ):
        pytest.skip("a run the cost lists is not published yet")
    built = cost.build(cost.RESULTS)
    prepares = [
        json.loads((cost.RESULTS / run / "prepare.json").read_text("utf-8"))
        for run in cost.SESSIONS[2].runs[2:]
    ]

    assert [day["requests"] for day in built["sessions"][:2]] == [
        3 * 46 + 2 * 40 + 224,
        3 * 125,
    ]
    assert cost.SESSIONS[0].unread_requests == sum(
        condition["prompt_count"]
        for prepare in prepares
        for condition in prepare["conditions"]
    )
    assert round(Decimal(built["excluded"]["bill_usd"]), 4) == Decimal("0.0108")
