"""Write the cost of the baseline rows and the 1.7B repair round.

``docs/protocol.md`` registers it (Training rules, amended 2026-10-26 and
2026-11-09), and the self-served note's "Cost ruled 2026-11-09" names the
inputs: the Modal bills of the three sessions that sent these runs, each the
``dfilterforge-vllm`` app's rows in the committed evidence, summed exactly,
over the requests those sessions sent, beside the GPU time the runs' attempt
latencies sum to at the L4's USD 0.80 an hour. The requests are each
committed run's ``requests_sent`` plus 224, the prompt count of the two
2026-10-26 test passes reported not run, which may not be opened, so the GPU
time leaves them out. The schema probes and the wake requests were billed
and are not counted, and an app of 2026-10-29 that sent none of these
requests is named and left out. Neither figure is a price for any other
serving. Where this file and that text differ, the text holds.

``--check`` rebuilds ``docs/results/sft-v1/cost.json`` and compares it byte
for byte. Exit 0 on success, 1 on a mismatch or a missing file, 2 when the
bills or a run's files are missing, the bills do not show a session's app on
its date alone, or a run was sent outside the hours its session billed.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import sys
from typing import Any, NamedTuple

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.errors import DFilterForgeError

SCHEMA_VERSION = "session-cost/1.0"
RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"
OUTPUT = Path("sft-v1") / "cost.json"
# The sessions' bills, by their repository path.
BILLS = Path(
    "docs/decisions/evidence/self-served/modal-billing-2026-10-28-to-11-05.json"
)
# The L4's price (self-served note, Stack).
USD_PER_GPU_HOUR = Decimal("0.80")


class Session(NamedTuple):
    """A Modal session: its local date, its app and the runs it sent.

    ``unread`` names runs it sent that may not be opened, and
    ``unread_requests`` stands for their requests.
    """

    date: str
    app: str
    runs: tuple[str, ...]
    unread: tuple[str, ...] = ()
    unread_requests: int = 0


def _arms(split: str) -> tuple[str, ...]:
    """The split's nine repair arm runs, in the order they were sent."""
    return tuple(
        f"{split}-qwen3-1.7b-sft-s{seed}-{arm}-2026-10-07"
        for seed in (17, 42, 2026)
        for arm in ("res", "bare", "cx")
    )


SESSIONS = (
    Session(
        "2026-10-28",
        "ap-gCT9ocTQKMTfTF5SLJER4I",
        (
            *_arms("dev"),
            "dev-qwen3-1.7b-schema-2026-10-26",
            "dev-qwen3-1.7b-fs8-2026-10-26",
        ),
        unread=(
            "test-qwen3-1.7b-schema-2026-10-26",
            "test-qwen3-1.7b-fs8-2026-10-26",
        ),
        unread_requests=224,
    ),
    Session("2026-10-31", "ap-GP0X6i9el6rilY602ncFdg", _arms("test")),
    Session(
        "2026-11-05",
        "ap-SQliMSGAdrKbVcwmGYI84B",
        (
            "dev-qwen3-1.7b-schema-ord-2026-10-26",
            "dev-qwen3-1.7b-fs8-ord-2026-10-26",
            "test-qwen3-1.7b-schema-ord-2026-10-26",
            "test-qwen3-1.7b-fs8-ord-2026-10-26",
        ),
    ),
)
# Billed, but it sent none of these runs' requests: named, not counted.
EXCLUDED = Session("2026-10-29", "ap-oeAVuNiK99WrMlnHTKvJkL", ())
# Billed and not counted.
NOT_COUNTED = ("schema_probes", "wake_requests")
_HOUR = timedelta(hours=1)  # each bill row covers one hour (-r h)
_PLACES = Decimal("0.00000001")
_DIFFERS = 1
_REFUSED = 2

Row = dict[str, str]
Span = tuple[datetime, datetime]


def _usd(value: Decimal) -> str:
    """Fixed-point text, never an exponent, whatever the rows wrote."""
    return format(value, "f")


def _bill(rows: Sequence[Row]) -> dict[str, Any]:
    """The rows' exact sum, in all and per resource."""
    resources: dict[str, Decimal] = {}
    for row in rows:
        name = row["resource"]
        resources[name] = resources.get(name, Decimal(0)) + Decimal(row["cost"])
    return {
        "bill_usd": _usd(sum(resources.values(), Decimal(0))),
        "bill_usd_by_resource": {
            name: _usd(value) for name, value in resources.items()
        },
    }


def _hours(latencies: Sequence[float]) -> float:
    """The latencies' sum in hours, to the microhour."""
    return round(math.fsum(latencies) / 3_600_000, 6)


def _gpu_usd(latencies: Sequence[float]) -> Decimal:
    """The L4 price of the hours the latencies sum to, before rounding."""
    return Decimal(math.fsum(latencies)) / 3_600_000 * USD_PER_GPU_HOUR


def _billed(rows: Sequence[Row], session: Session) -> tuple[list[Row], Span]:
    """The session's bill rows and the start and end of the hours they bill.

    Raises:
        DFilterForgeError: No row bills the session's app, or one bills it
            on another date.
    """
    mine = [row for row in rows if row["object_id"] == session.app]
    if {row["interval_start"][:10] for row in mine} != {session.date}:
        raise DFilterForgeError(
            "bills_differ",
            f"the bills do not show {session.app} on {session.date} alone",
        )
    hours = [datetime.fromisoformat(row["interval_start"]) for row in mine]
    return mine, (min(hours), max(hours) + _HOUR)


def _run(
    results: Path, run: str, session: Session, span: Span
) -> tuple[int, list[float], list[Path]]:
    """A run's requests, its attempts' latencies and the files they come from.

    Raises:
        DFilterForgeError: The run has no manifest or misses an attempts
            file, or one of its invocations lies outside ``span``.
    """
    files = [results / run / "run_manifest.json"]
    if not files[0].is_file():
        raise DFilterForgeError(
            "run_not_published", f"{run} has no run_manifest.json"
        )
    manifest = json.loads(files[0].read_text("utf-8"))
    requests = 0
    for invocation in manifest["invocations"]:
        started = datetime.fromisoformat(invocation["started_at"])
        finished = datetime.fromisoformat(invocation["finished_at"])
        if not span[0] <= started <= finished < span[1]:
            raise DFilterForgeError(
                "session_mismatch",
                f"{run} was sent outside the session of {session.date}",
            )
        requests += invocation["requests_sent"]
    latencies: list[float] = []
    for condition in manifest["conditions"]:
        files.append(results / run / condition["attempts_path"])
        if not files[-1].is_file():
            raise DFilterForgeError(
                "run_not_published",
                f"{run} has no {condition['attempts_path']}",
            )
        for line in files[-1].read_text("utf-8").splitlines():
            latencies.append(json.loads(line)["completion"]["latency_ms"])
    return requests, latencies, files


def _session(
    results: Path, rows: Sequence[Row], session: Session
) -> tuple[dict[str, Any], list[float], list[Path]]:
    """One session's entry, its runs' latencies and their files.

    Raises:
        DFilterForgeError: The bills do not show the session, a run is not
            published, or a run was sent outside the hours the session
            billed.
    """
    billed, span = _billed(rows, session)
    requests = session.unread_requests
    latencies: list[float] = []
    files: list[Path] = []
    for run in session.runs:
        sent, more, read = _run(results, run, session, span)
        requests += sent
        latencies += more
        files += read
    unread = {
        "runs": list(session.unread),
        "requests": session.unread_requests,
        "requests_from": "prompt_count",
        "latencies_in_gpu_time": False,
    }
    entry = {
        "date": session.date,
        "app": session.app,
        **_bill(billed),
        "requests": requests,
        "gpu_hours": _hours(latencies),
        "runs": list(session.runs),
        "unread": unread if session.unread else None,
    }
    return entry, latencies, files


def build(results: Path) -> dict[str, Any]:
    """Computes the cost from the committed bills and runs.

    Raises:
        DFilterForgeError: The bills are missing or do not show a session,
            or the excluded app, on its date alone; a run is not published;
            or a run was sent outside the hours its session billed.
    """
    bills = results.resolve().parents[1] / BILLS
    if not bills.is_file():
        raise DFilterForgeError(
            "bills_missing", f"{BILLS.as_posix()} is missing"
        )
    rows: list[Row] = json.loads(bills.read_text("utf-8"))["rows"]
    sessions: list[dict[str, Any]] = []
    latencies: list[float] = []
    files: list[Path] = []
    for session in SESSIONS:
        entry, more, read = _session(results, rows, session)
        sessions.append(entry)
        latencies += more
        files += read
    apps = {session.app for session in SESSIONS}
    total = _bill([row for row in rows if row["object_id"] in apps])
    requests: int = sum(entry["requests"] for entry in sessions)
    hours = _hours(latencies)
    per_1000 = Decimal(total["bill_usd"]) * 1000 / requests
    return {
        "schema_version": SCHEMA_VERSION,
        "usd_per_gpu_hour": _usd(USD_PER_GPU_HOUR),
        "sessions": sessions,
        "total": total
        | {
            "requests": requests,
            "usd_per_1000_requests": _usd(per_1000.quantize(_PLACES)),
            "gpu_hours": hours,
            "gpu_usd": _usd(_gpu_usd(latencies).quantize(_PLACES)),
        },
        "excluded": {
            "date": EXCLUDED.date,
            "app": EXCLUDED.app,
            "bill_usd": _bill(_billed(rows, EXCLUDED)[0])["bill_usd"],
        },
        "not_counted": list(NOT_COUNTED),
        "sources": {BILLS.as_posix(): file_sha256(bills)}
        | {
            f"docs/results/{file.relative_to(results).as_posix()}": (
                file_sha256(file)
            )
            for file in files
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Writes or checks the cost; returns the exit status."""
    parser = argparse.ArgumentParser(description="Write the session cost.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args(argv)
    path = args.results / OUTPUT
    try:
        data = canonical_json(build(args.results)).encode("utf-8") + b"\n"
    except DFilterForgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return _REFUSED
    # Bytes, so a Windows checkout writes and compares what CI does.
    if not args.check:
        path.write_bytes(data)
        return 0
    if path.is_file() and path.read_bytes() == data:
        return 0
    print(f"{path} differs from its rebuild", file=sys.stderr)
    return _DIFFERS


if __name__ == "__main__":
    sys.exit(main())
