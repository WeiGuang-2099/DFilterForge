"""Owner batch and offline judge for the bake-off's two-turn smoke.

Run from the worktree whose generation.py accepts a second turn, with
that worktree's own uv environment (docs/decisions/second-turn.md):

    uv run --frozen python scripts/two_turn_smoke.py prepare --summary S
        [--reserve SLOT]
    uv run --frozen python scripts/two_turn_smoke.py run [--dry-run]
    uv run --frozen python scripts/two_turn_smoke.py judge

``prepare`` is offline and free. For every candidate the bake-off runner's
summary S lists as passing the run gates, the anchor included, it checks
the counted pass's config file against that pass's run manifest and runs
``scripts/model_run.py follow-up`` on the pass's run directory, found
under the summary's own repository root. That continues the first two dev
C4 items in prepare order whose counted answer completed with
finish_reason stop and parses as ready; with fewer than two the smoke
fails without a request. A smoke's run id is
``dev-<model>[-fb]-rs-<prepare date>``; a re-run after a harness failure
is ``-rs2``, ``-rs3`` and so on, one character longer, so every listed
model's re-run id fits the 32-character result name but a fallback
nemotron's.

``prepare --reserve SLOT`` is offline and free too, for the note's rule 6:
once every run-gate survivor of SLOT has failed its smoke, the owner runs
``scripts/dev_bakeoff.py --only reserve-SLOT --after-smoke-failures`` from
the main checkout, which holds the bake-off's runs, and passes the new
summary it writes as S. The plan must exist, every ranked smoke of SLOT
must read ``fail`` as ``judge`` reads it, every survivor of SLOT in S
must be a pass the plan smoked, and the reserve must pass the run gates
in S and have no smoke yet. It appends that one smoke, named after
today's date, and records S's path and digest beside it; the other
smokes, their runs and verdicts stay as they are, and a failure removes
only the new smoke's directory. Never prepare every survivor again into
another out dir instead: that would re-send the smokes already judged
and give a candidate that failed its smoke a second one.

``run`` is the owner's one paid command, from the shell that holds the
key. Each smoke is one ``scripts/model_run.py call`` started as an
argument list with no shell, with the counted pass's exact config file,
``--gate-first``, ``--max-attempts 3``, ``--min-interval-seconds 1.0`` and
``--max-usd 0.20``. Items left pending by transient failures are resumed
after a 60 s wait with the same options. Before the first paid call every
call is made once with the key withheld and must stop at
``api_key_missing``; paid calls start only when the key variable is
present and the tooling is committed. Running it again skips smokes with
a verdict, resumes pending ones and starts the re-run a harness failure
left owed, one new run per smoke and execution. ``run --dry-run`` sends
nothing and starts no call step: it makes the same input checks, so it
also refuses a smoke still owed a call whose prompt set recorded other
model-side code than the checkout's, then prints each smoke's state and
next call. The keyless preflight, which only ``run`` makes, stays the
full free check.

``judge`` is offline. It rebuilds every smoke's prompts from its source
run, reads each run by the note's rule and writes one verdict per smoke
plus a summary. A smoke passes when both items end completed with
finish_reason stop, no reply shows reasoning, a model sent a reasoning
switch reports a reasoning-token count, and both replies parse under the
C4 contract. A reply that reasons, a completed reply that fails those
checks, or a final error or refusal of the second turn fails it. A
harness or operator failure (HTTP 401, 402 or 403, a budget stop, an item
with no completed reply only through transient failures, or a run whose
settings are not the counted pass's) is never a fail: it owes a re-run
under a new run id. An observed model failure is final even if the other
item met a harness failure. The anchor's verdict is informational. Each
verdict file and summary line also names the providers that served the
smoke's runs and says PROVIDER CHANGED or MODEL CHANGED when a provider
or model other than the counted pass's served one; by the owner's ruling
of 2026-09-27 that is a flag and never changes a verdict.

Everything is written under artifacts/two-turn-smoke/: the plan, the
prepared smokes with their runs, the step log, the lock, one verdict per
smoke and the summary. The key is inherited by the paid calls only; this
script never reads, prints or writes it.

Exit codes of ``run``:
    0    Every smoke has a verdict, pass or fail.
    1    A smoke owes a resume or a re-run, or the batch stopped for the
         owner: read the reason. Running the same command again makes
         an owed resume or re-run. It does not clear a run directory that
         cannot be judged: the message names it and says what may be
         done with it. After an error the batch did not expect, requests
         may have been sent; read steps.jsonl before running it again.
    2    Refused before any request: the plan, a prompt set, a config
         file, the cap, model-side code a prompt set owed a call no
         longer matches (the message says whether to re-prepare or to
         restore the files), the lock, git, uncommitted tooling or the
         keyless preflight.
    3    Aborted: the key variable is not set, or the account refused a
         request (HTTP 401, 402 or 403). Fix it, then run the same
         command; the refused run is owed a re-run.
    130  Interrupted with Ctrl-C. Do not press it while a request is in
         flight: the call step shares the console, so that request may be
         billed but not recorded. It is then missing from the attempt log
         and the charged upper bound, and the next run sends it again. A
         call step still running after the wait keeps the lock,
         artifacts/two-turn-smoke/.lock: delete it once that process has
         exited, then run the same command. If only the judging after the
         batch was interrupted, run ``judge``; it sends nothing.
``run`` prints the judge's summary afterwards, but its own code reads the
runs alone; ``judge`` also rebuilds every smoke's source run.

Exit codes of ``judge``:
    0    Every smoke has a verdict, pass or fail.
    1    A smoke owes a resume or a re-run, or has not run yet.
    2    Refused (no usable plan), or a smoke cannot be judged: a run
         directory is unreadable, a run follows one that was not a
         harness failure, or its source run no longer rebuilds.

``prepare`` exits 0 when it wrote the plan or appended a reserve's smoke
to it, and 2 when it refused.
"""

# The rule the judge applies and the batch that resumes and re-runs by it
# share one file, so a run and its verdict can never be read two ways.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Sequence
import contextlib
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Any, cast, Literal
from urllib.parse import urlsplit

from pydantic import Field
from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.completions import CODE_PATTERN
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import thinking_state
from dfilterforge.completions import TokenPricesV1
from dfilterforge.generation import FOLLOW_UP_TEXT
from dfilterforge.generation import GenerationError
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.run_store import served_values

ROOT = Path(__file__).resolve().parents[1]
MODEL_RUN = "scripts/model_run.py"
OUT_DIR = "artifacts/two-turn-smoke"
CONFIG_DIR = "docs/decisions/evidence/bakeoff/configs"
PLAN_NAME = "plan.json"
LOCK_NAME = ".lock"
VERDICT_DIR = "verdicts"
# Paths whose committed state the revision each call records must cover.
TOOLING = (
    "src",
    "scripts",
    CONFIG_DIR,
    "docs/decisions/model-bakeoff.md",
    "docs/decisions/second-turn.md",
)
LABEL = "C4"
ITEMS = 2
MAX_ATTEMPTS = 3
MIN_INTERVAL_SECONDS = 1.0
MAX_USD = "0.20"
CAP_MICRO_USD = 200_000
MICRO = 1_000_000
TOKEN_BOUND_SLACK = 64
RESUME_WAIT_SECONDS = 60.0
INTERRUPT_GRACE_SECONDS = 30.0
SMOKE_TAG = "rs"
MAX_RUNS_PER_SMOKE = 9
READY_ANSWERS_MISSING = "ready_answers_missing"
RANKED_SLOTS = ("small", "mid", "frontier")
REPORT_KEYS = ("stop_reason", "requests_sent", "charged_usd_upper_bound")
DEV_RUN = re.compile(r"dev-([a-z0-9][a-z0-9.-]*)-([0-9]{4}-[0-9]{2}-[0-9]{2})")
CONFIG_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
# A provider name a summary line may print as it is.
SHOWN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._()/+-]{0,63}")


class PlanError(RuntimeError):
    """Refused before any request: the smoke cannot run as it stands."""


class BatchStop(RuntimeError):
    """The owner has to look at something before the batch goes on."""


class BatchAbort(RuntimeError):
    """The key or the account stops every smoke alike."""


def _sibling(name: str) -> ModuleType:
    """Loads one sibling script for its public contract."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"two_turn_{name}", path)
    loader = None if spec is None else spec.loader
    if spec is None or loader is None:
        raise RuntimeError(f"scripts/{name}.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


# The bake-off runner's own call-step rules, invoker and lock, and the call
# step itself: one definition of each, shared with the passes they follow.
db = _sibling("dev_bakeoff")
model_run = db.load_model_run()
# The bake-off runner's exit codes, which this batch keeps.
EXIT_OK: int = db.EXIT_OK
EXIT_STOPPED: int = db.EXIT_STOPPED
EXIT_REFUSED: int = db.EXIT_REFUSED
EXIT_ABORTED: int = db.EXIT_ABORTED
EXIT_INTERRUPTED: int = db.EXIT_INTERRUPTED


class SmokeV1(FrozenModel):
    """One run-gate survivor's smoke, as ``prepare`` fixed it."""

    slot: str
    rank: str
    candidate: str
    informational: bool
    smoke_id: str
    source_run_id: str
    source_run_dir: str
    source_run_manifest_sha256: str
    config: str
    config_path: str
    config_sha256: str
    settings: RequestSettingsV1
    prices: TokenPricesV1
    endpoint_host: str
    status: Literal["prepared", "ready_answers_missing"]
    items: tuple[str, ...] = ()
    prompt_bytes: dict[str, int] = Field(default_factory=dict)
    c4_sha256: str | None = None
    prepare_sha256: str | None = None

    @property
    def reasoning_switch(self) -> str | None:
        """Returns the reasoning switch the counted pass sent, if any."""
        options = self.settings.openrouter
        return None if options is None else options.reasoning


class ReserveV1(FrozenModel):
    """Where a reserve's smoke, appended by ``prepare --reserve``, came from."""

    smoke_id: str
    prepare_date: str
    source_revision: str
    summary_path: str
    summary_sha256: str


class PlanV1(FrozenModel):
    """Every smoke ``prepare`` built, in the runner summary's order.

    A reserve's smoke is appended after them; the fields above ``smokes``
    stay those of the first prepare, and ``reserves`` records the later
    summary each appended smoke was read from.
    """

    schema_version: Literal["two-turn-smoke-plan/1.0"] = (
        "two-turn-smoke-plan/1.0"
    )
    written_at: datetime
    source_revision: str
    prepare_date: str
    summary_path: str
    summary_sha256: str
    follow_up_text_sha256: str
    smokes: tuple[SmokeV1, ...]
    reserves: tuple[ReserveV1, ...] = ()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _relative(path: Path) -> str:
    """Spells a path from the repository root when it lies inside it."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _resolve(spelled: str) -> Path:
    """Reads back a path ``_relative`` spelled."""
    path = Path(spelled)
    return path if path.is_absolute() else ROOT / path


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        canonical_json(value) + "\n", encoding="utf-8", newline="\n"
    )


def _replace_json(path: Path, value: object) -> None:
    """Rewrites a file whole or not at all, for one that records runs."""
    staging = path.with_name(f".{path.name}.partial")
    _write_json(staging, value)
    os.replace(staging, path)


def uncommitted(paths: Sequence[str]) -> list[str]:
    """Lists uncommitted changes under the given repository paths."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        check=True,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    return status.stdout.splitlines()


def smoke_run_id(source_run_id: str, date: str) -> str:
    """Names a smoke after its counted pass and its prepare's date.

    Raises:
        PlanError: If the pass is not a dev run or the name is too long.
    """
    match = DEV_RUN.fullmatch(source_run_id)
    if match is None:
        raise PlanError(f"{source_run_id}: not a dev run id")
    name = f"dev-{match.group(1)}-{SMOKE_TAG}-{date}"
    if db.RESULT_DIR.fullmatch(name) is None:
        raise PlanError(f"{name}: not a usable result name")
    return name


def run_ids(smoke_id: str) -> Iterator[str]:
    """Yields a smoke's run ids: its own, then each re-run's."""
    yield smoke_id
    stem, date = smoke_id[: -len("-0000-00-00")], smoke_id[-10:]
    for number in range(2, MAX_RUNS_PER_SMOKE + 1):
        yield f"{stem}{number}-{date}"


def _last_json(text: str) -> dict[str, Any] | None:
    """Parses the last line of a child's output when it is a JSON object."""
    lines = text.strip().splitlines()
    if not lines:
        return None
    try:
        value = json.loads(lines[-1])
    except ValueError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def follow_up(
    source_run: Path, output_dir: Path, revision: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Runs ``model_run.py follow-up`` in process, offline.

    Returns:
        The printed report, or None and the refusal code.
    """
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = [
        "follow-up",
        "--from-run",
        str(source_run),
        "--output-dir",
        str(output_dir),
        "--source-revision",
        revision,
    ]
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = int(model_run.main(argv))
    if code == 0:
        return _last_json(stdout.getvalue()), None
    error = (_last_json(stderr.getvalue()) or {}).get("error")
    reason = cast(dict[str, Any], error).get("code") if error else None
    return None, str(reason)


def worst_case_micro_usd(smoke: SmokeV1) -> int:
    """Mirrors the call step's pre-request bound for the dearest item."""
    prices = smoke.prices
    return max(
        math.ceil(
            (size + TOKEN_BOUND_SLACK) * prices.usd_per_million_input
            + smoke.settings.max_output_tokens * prices.usd_per_million_output
        )
        for size in smoke.prompt_bytes.values()
    )


def check_cap(smoke: SmokeV1) -> None:
    """Requires the cap to cover every attempt at its worst case.

    Raises:
        PlanError: If three attempts of both items could exceed it.
    """
    worst = worst_case_micro_usd(smoke) * ITEMS * MAX_ATTEMPTS
    if worst > CAP_MICRO_USD:
        raise PlanError(
            f"{smoke.smoke_id}: {worst / MICRO:.4f} USD worst case is over"
            f" the {MAX_USD} USD cap"
        )


# Preparing.


def _passing(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns the summary's candidates that passed the run gates."""
    records = cast(list[dict[str, Any]], summary.get("candidates", []))
    return [
        record
        for record in records
        if record.get("passes") and record.get("qualifying_pass")
    ]


def _read_summary(summary_path: Path) -> tuple[bytes, dict[str, Any], Path]:
    """Reads the runner's summary and finds the raw runs it names.

    Returns:
        The summary's bytes, its content and its prepare directory.
    """
    data = summary_path.read_bytes()
    summary = cast(dict[str, Any], json.loads(data))
    source_root = summary_path.resolve().parents[2] / str(
        summary["prepare_dir"]
    )
    return data, summary, source_root


def _source_manifest(run_dir: Path) -> tuple[RunManifestV1, str]:
    """Reads a counted pass's manifest and the digest of its bytes.

    Raises:
        PlanError: If the run directory holds no usable manifest.
    """
    path = run_dir / "run_manifest.json"
    if not path.is_file():
        raise PlanError(f"{_relative(run_dir)}: no run_manifest.json")
    data = path.read_bytes()
    return RunManifestV1.model_validate_json(data), _sha256(data)


def _smoke_base(
    record: dict[str, Any], source_root: Path, config_dir: Path, date: str
) -> dict[str, Any]:
    """Checks one survivor's counted pass and config, before any prompt.

    Raises:
        PlanError: If the pass is not complete or its config file is not
            the one that pass sent.
    """
    qualifying = cast(dict[str, Any], record["qualifying_pass"])
    source_id = str(qualifying["run_id"])
    config = str(qualifying["config"])
    if CONFIG_NAME.fullmatch(config) is None:
        raise PlanError(f"{config}: not a config name")
    run_dir = source_root / "runs" / source_id
    manifest, digest = _source_manifest(run_dir)
    if manifest.status != "complete" or manifest.prices is None:
        raise PlanError(f"{source_id}: the counted pass is not complete")
    config_path = config_dir / f"{config}.json"
    if not config_path.is_file():
        raise PlanError(f"config {config} is missing")
    data = config_path.read_bytes()
    call = model_run.CallConfigV1.model_validate_json(data)
    host = urlsplit(str(call.endpoint_url)).hostname
    if (call.settings, call.prices, host) != (
        manifest.settings,
        manifest.prices,
        manifest.endpoint_host,
    ):
        raise PlanError(f"{config}: not the config {source_id} sent")
    return {
        "slot": str(record["slot"]),
        "rank": str(record["rank"]),
        "candidate": str(record["candidate"]),
        "informational": record["slot"] == "anchor",
        "smoke_id": smoke_run_id(source_id, date),
        "source_run_id": source_id,
        "source_run_dir": run_dir.resolve().as_posix(),
        "source_run_manifest_sha256": digest,
        "config": config,
        "config_path": _relative(config_path),
        "config_sha256": _sha256(data),
        "settings": manifest.settings,
        "prices": manifest.prices,
        "endpoint_host": manifest.endpoint_host,
    }


def _prepare_smoke(
    base: dict[str, Any], out_dir: Path, revision: str
) -> SmokeV1:
    """Writes one smoke's prompt set, or records why it has none.

    Raises:
        PlanError: If the follow-up step refuses for another reason.
    """
    prepare_dir = out_dir / str(base["smoke_id"])
    report, code = follow_up(
        Path(str(base["source_run_dir"])), prepare_dir, revision
    )
    if report is None:
        if code == READY_ANSWERS_MISSING:
            return SmokeV1(**base, status="ready_answers_missing")
        raise PlanError(f"{base['source_run_id']}: follow-up refused ({code})")
    if (
        report["source_run_manifest_sha256"]
        != base["source_run_manifest_sha256"]
    ):
        raise PlanError(f"{base['source_run_id']}: the run changed meanwhile")
    return SmokeV1(
        **base,
        status="prepared",
        items=tuple(cast(list[str], report["items"])),
        prompt_bytes=cast(dict[str, int], report["prompt_bytes"]),
        c4_sha256=str(cast(dict[str, Any], report["conditions"])[LABEL]),
        prepare_sha256=_sha256((prepare_dir / "prepare.json").read_bytes()),
    )


def _refuse_taken(out_dir: Path, smoke_ids: Sequence[str]) -> None:
    """Refuses smoke directories that exist before prepare writes any.

    A smoke directory holds its runs, which may be paid evidence, and a
    leftover ``.<id>.partial`` is a prepare that was killed; prepare
    writes over neither, so its cleanup only removes what it made.

    Raises:
        PlanError: If any of them, or its staging directory, exists.
    """
    taken = [
        _relative(path)
        for smoke_id in smoke_ids
        for path in (out_dir / smoke_id, out_dir / f".{smoke_id}.partial")
        if path.exists()
    ]
    if taken:
        raise PlanError(
            f"{', '.join(taken)} already exist and prepare never writes over"
            " a smoke directory. Remove one only if it holds no runs/"
            " directory: a run there may be paid evidence"
        )


def prepare(
    summary_path: Path,
    out_dir: Path,
    revision: str,
    config_dir: Path | None = None,
) -> PlanV1:
    """Builds every survivor's smoke prompts offline and writes the plan.

    Raises:
        PlanError: If a plan or one of the smoke directories exists, the
            summary names no survivor, or a counted pass, config or
            follow-up is refused.
    """
    plan_path = out_dir / PLAN_NAME
    if plan_path.exists():
        raise PlanError(
            f"{_relative(plan_path)} exists; the smokes are prepared. Remove"
            f" {_relative(out_dir)} only if no smoke request was ever sent"
        )
    data, summary, source_root = _read_summary(summary_path)
    survivors = _passing(summary)
    if not survivors:
        raise PlanError("the summary lists no candidate passing the run gates")
    date = _now()[:10]
    bases = [
        _smoke_base(record, source_root, config_dir or ROOT / CONFIG_DIR, date)
        for record in survivors
    ]
    _refuse_taken(out_dir, [str(base["smoke_id"]) for base in bases])
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        smokes = tuple(_prepare_smoke(b, out_dir, revision) for b in bases)
        for smoke in smokes:
            if smoke.status == "prepared":
                check_cap(smoke)
    except BaseException:
        # None of these existed before this call, which has no plan yet, so
        # no call can have used them and nothing else is removed.
        for base in bases:
            shutil.rmtree(out_dir / str(base["smoke_id"]), ignore_errors=True)
        raise
    plan = PlanV1(
        written_at=datetime.now(timezone.utc),
        source_revision=revision,
        prepare_date=date,
        summary_path=summary_path.resolve().as_posix(),
        summary_sha256=_sha256(data),
        follow_up_text_sha256=_sha256(FOLLOW_UP_TEXT.encode("utf-8")),
        smokes=smokes,
    )
    _write_json(plan_path, plan)
    return plan


def load_plan(out_dir: Path) -> PlanV1:
    """Reads the plan ``prepare`` wrote.

    Raises:
        PlanError: If there is none or it is not usable.
    """
    path = out_dir / PLAN_NAME
    if not path.is_file():
        raise PlanError(f"{_relative(path)} is missing; run prepare first")
    try:
        return PlanV1.model_validate_json(path.read_bytes())
    except ValidationError:
        raise PlanError(f"{_relative(path)} is not usable") from None


# Reading one run.


class _Unreadable(Exception):
    """A run directory that cannot be read as the call step wrote it."""


Kind = Literal["pass", "fail", "rerun", "resume", "unreadable"]


@dataclass(frozen=True)
class Assessment:
    """What one smoke run shows under the note's rule."""

    run_id: str
    kind: Kind
    reasons: tuple[str, ...]
    items: dict[str, dict[str, Any]] = field(
        default_factory=dict[str, dict[str, Any]]
    )
    record: dict[str, Any] = field(default_factory=dict[str, Any])

    def document(self) -> dict[str, Any]:
        """Returns the assessment as a verdict file spells it."""
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "reasons": list(self.reasons),
            **self.record,
            "items": self.items,
        }


def _read_run(
    run_dir: Path,
) -> tuple[RunManifestV1, str, tuple[Any, ...], bool]:
    """Reads a run's manifest, the digest of its bytes and its attempts.

    Returns:
        The manifest, its digest, every attempt in log order, and whether
        the log still has the digest the manifest recorded.

    Raises:
        _Unreadable: With the problem as its message.
    """
    path = run_dir / "run_manifest.json"
    if not path.is_file():
        raise _Unreadable("manifest_missing")
    data = path.read_bytes()
    try:
        manifest = RunManifestV1.model_validate_json(data)
    except ValidationError:
        raise _Unreadable("manifest_invalid") from None
    if manifest.run_id != run_dir.name:
        raise _Unreadable("manifest_run_id")
    if [condition.label for condition in manifest.conditions] != [LABEL]:
        raise _Unreadable("not_a_c4_run")
    condition = manifest.conditions[0]
    log = run_dir / condition.attempts_path
    raw = log.read_bytes() if log.is_file() else b""
    if raw and not raw.endswith(b"\n"):
        raise _Unreadable("attempt_log_torn")
    try:
        attempts = tuple(
            model_run.AttemptV1.model_validate_json(line)
            for line in raw.split(b"\n")
            if line
        )
    except ValidationError:
        raise _Unreadable("attempt_log_invalid") from None
    current = _sha256(raw) == condition.attempts_sha256
    return manifest, _sha256(data), attempts, current


def _config_problems(smoke: SmokeV1, manifest: RunManifestV1) -> list[str]:
    """Names every way a run was not configured as its smoke requires."""
    problems: list[str] = []
    prepared = manifest.prepare.conditions
    if manifest.prepare.split != "dev" or [c.label for c in prepared] != [
        LABEL
    ]:
        problems.append("not_a_dev_c4_prompt_set")
    elif (prepared[0].sha256, manifest.prepare.item_ids) != (
        smoke.c4_sha256,
        smoke.items,
    ):
        problems.append("prompts_not_the_prepared_ones")
    if (manifest.settings, manifest.prices, manifest.endpoint_host) != (
        smoke.settings,
        smoke.prices,
        smoke.endpoint_host,
    ):
        problems.append("settings_not_the_counted_pass")
    if (manifest.max_attempts, manifest.min_interval_seconds) != (
        MAX_ATTEMPTS,
        MIN_INTERVAL_SECONDS,
    ):
        problems.append("call_options_not_registered")
    if any(i.max_usd != float(MAX_USD) for i in manifest.invocations):
        problems.append("cap_not_registered")
    return problems


def _parses(output_contract: OutputContractV1, text: str | None) -> bool:
    """Reports whether a reply parses under the contract, as scoring does."""
    try:
        parse_response(output_contract, text or "")
    except GenerationError:
        return False
    return True


ItemState = Literal["ok", "fail", "harness", "pending"]
ItemRead = tuple[ItemState, str | None, dict[str, Any]]


def _completed(
    last: CompletionV1, parses: bool
) -> tuple[ItemState, str | None]:
    """Reads a completed reply: it must stop and parse.

    The finish reason is provider metadata, bounded in size only, and a
    reason is printed to the owner. So a reason names it only when it is
    a short code, as recorded error codes must be; anything else reads
    ``other``, and the raw value stays in the item record, JSON-escaped.
    """
    if last.finish_reason != "stop":
        shown = last.finish_reason
        if shown is None or CODE_PATTERN.fullmatch(shown) is None:
            shown = "other"
        return "fail", f"finish_reason_{shown}"
    return ("ok", None) if parses else ("fail", "no_parse")


def _failed(last: CompletionV1, attempts: int) -> tuple[ItemState, str]:
    """Reads a failed last attempt by the call step's own retry classes."""
    kind = str(db.attempt_kind(last))
    if kind == "final":
        return "fail", f"final_{last.error_code}_{last.http_status}"
    if kind == "account":
        return "harness", f"account_refused_{last.http_status}"
    if attempts >= MAX_ATTEMPTS:
        return "harness", "only_transient_failures"
    return "pending", "transient_pending"


def _item(
    entries: Sequence[Any], output_contract: OutputContractV1
) -> ItemRead:
    """Reads one item's counted (last) attempt by the note's rule.

    Returns:
        The item's state, the reason when it is not ``ok``, and a record.
    """
    if not entries:
        return "pending", "not_sent", {"attempts": 0}
    last = cast(CompletionV1, entries[-1].completion)
    record: dict[str, Any] = {
        "attempts": len(entries),
        "status": last.status.value,
        "http_status": last.http_status,
        "error_code": last.error_code,
        "finish_reason": last.finish_reason,
        "provider": last.provider,
        "response_model": last.response_model,
        "reasoning_tokens": last.reasoning_tokens,
        "reasoning_present": last.reasoning_present,
    }
    if last.status is CompletionStatusV1.COMPLETED:
        record["parses"] = _parses(output_contract, last.response_text)
        return (*_completed(last, record["parses"]), record)
    return (*_failed(last, len(entries)), record)


def assess(smoke: SmokeV1, path: Path) -> Assessment:
    """Reads one smoke run under the note's rule.

    A run whose configuration is not the smoke's owes a re-run whatever
    it holds. Otherwise an observed model failure fails the smoke, then a
    harness failure owes a re-run, then a pending item owes a resume, and
    only a complete run of two good replies can pass.
    """
    try:
        manifest, digest, attempts, current = _read_run(path)
    except _Unreadable as problem:
        return Assessment(path.name, "unreadable", (str(problem),))
    # Flags only, by the owner's 2026-09-27 ruling: what the provider
    # served is recorded against the counted pass's model and pinned
    # route, and no verdict turns on it.
    values = served_values((a.completion for a in attempts), smoke.settings)
    record: dict[str, Any] = {
        "run_manifest_sha256": digest,
        "status": manifest.status,
        "invocations": len(manifest.invocations),
        "stop_reasons": [i.stop_reason for i in manifest.invocations],
        "requests": len(attempts),
        "charged_usd_upper_bound": manifest.charged_usd_upper_bound,
        "providers": list(values.providers),
        "provider_changed": values.provider_changed,
        "served_models": list(values.models),
        "model_changed": values.model_changed,
    }
    problems = _config_problems(smoke, manifest)
    if problems:
        return Assessment(path.name, "rerun", tuple(problems), {}, record)
    if not current:
        if manifest.status == "incomplete":
            return Assessment(path.name, "resume", ("log_ahead",), {}, record)
        return Assessment(path.name, "unreadable", ("attempt_log_digest",))
    return _rule(smoke, manifest, attempts, record)


def _read_items(
    smoke: SmokeV1, manifest: RunManifestV1, attempts: Sequence[Any]
) -> dict[str, ItemRead]:
    """Reads every item of a run, in the smoke's item order."""
    contract = manifest.prepare.conditions[0].output_contract
    by_item: dict[str, list[Any]] = {item: [] for item in smoke.items}
    for attempt in attempts:
        by_item.setdefault(attempt.completion.item_id, []).append(attempt)
    return {item: _item(entries, contract) for item, entries in by_item.items()}


def _rule(
    smoke: SmokeV1,
    manifest: RunManifestV1,
    attempts: Sequence[Any],
    record: dict[str, Any],
) -> Assessment:
    """Applies the pass rule to a run configured as its smoke requires."""
    read = _read_items(smoke, manifest, attempts)
    state = thinking_state([a.completion for a in attempts])[0]
    record["thinking"] = state if attempts else None
    items = {item: detail for item, (_, _, detail) in read.items()}

    def ending(kind: Kind, reasons: Sequence[str]) -> Assessment:
        return Assessment(manifest.run_id, kind, tuple(reasons), items, record)

    def named(wanted: ItemState) -> list[str]:
        return [f"{i}:{r}" for i, (s, r, _) in read.items() if s == wanted]

    shown = ["reasoning_shown"] if state == "not_honoured" else []
    if shown or named("fail"):
        return ending("fail", shown + named("fail"))
    stops = {invocation.stop_reason for invocation in manifest.invocations}
    harness = named("harness") + [
        f"{stop}_stop" for stop in ("fatal_http", "budget") if stop in stops
    ]
    if harness:
        return ending("rerun", harness)
    if named("pending") or manifest.status != "complete":
        return ending("resume", named("pending"))
    if smoke.reasoning_switch is not None and state == "uncontrolled":
        return ending("fail", ["thinking_uncontrolled"])
    return ending("pass", [])


# One smoke across its runs.


Verdict = Literal[
    "pass", "fail", "rerun_owed", "resume_owed", "not_run", "unjudgeable"
]
_VERDICTS: dict[Kind, Verdict] = {
    "pass": "pass",
    "fail": "fail",
    "rerun": "rerun_owed",
    "resume": "resume_owed",
    "unreadable": "unjudgeable",
}


@dataclass(frozen=True)
class SmokeState:
    """A smoke's verdict, drawn from its runs in order."""

    smoke: SmokeV1
    verdict: Verdict
    reasons: tuple[str, ...]
    runs: tuple[Assessment, ...] = ()

    @property
    def final(self) -> bool:
        """Reports whether nothing more is owed."""
        return self.verdict in ("pass", "fail")


def smoke_run_dir(out_dir: Path, smoke: SmokeV1, run_id: str) -> Path:
    """Locates one run of a smoke."""
    return out_dir / smoke.smoke_id / "runs" / run_id


def existing_runs(out_dir: Path, smoke: SmokeV1) -> list[str]:
    """Lists the runs a smoke has on disk, first run first."""
    found: list[str] = []
    for run_id in run_ids(smoke.smoke_id):
        if not smoke_run_dir(out_dir, smoke, run_id).exists():
            break
        found.append(run_id)
    return found


def smoke_state(out_dir: Path, smoke: SmokeV1) -> SmokeState:
    """Draws one smoke's verdict from its runs.

    Every run before the last must be a harness failure it re-ran; the
    last run decides.
    """
    if smoke.status == "ready_answers_missing":
        return SmokeState(smoke, "fail", (READY_ANSWERS_MISSING,))
    runs = tuple(
        assess(smoke, smoke_run_dir(out_dir, smoke, run_id))
        for run_id in existing_runs(out_dir, smoke)
    )
    if not runs:
        return SmokeState(smoke, "not_run", ())
    for earlier in runs[:-1]:
        if earlier.kind != "rerun":
            reason = f"{earlier.run_id}:{earlier.kind}_but_re_run"
            return SmokeState(smoke, "unjudgeable", (reason,), runs)
    last = runs[-1]
    return SmokeState(smoke, _VERDICTS[last.kind], last.reasons, runs)


def next_call(out_dir: Path, state: SmokeState) -> tuple[str, bool] | None:
    """Returns the run id to call next and whether it is a resume.

    Raises:
        BatchStop: If a re-run is owed but the run ids are used up.
    """
    smoke = state.smoke
    if state.verdict == "not_run":
        return smoke.smoke_id, False
    if state.verdict == "resume_owed":
        return state.runs[-1].run_id, True
    if state.verdict != "rerun_owed":
        return None
    used = existing_runs(out_dir, smoke)
    fresh = [r for r in run_ids(smoke.smoke_id) if r not in used]
    if not fresh or db.RESULT_DIR.fullmatch(fresh[0]) is None:
        raise BatchStop(f"{smoke.smoke_id}: no usable re-run id is left")
    return fresh[0], False


# Judging.


def _verify_source(smoke: SmokeV1) -> str | None:
    """Rebuilds a smoke's prompts from its source run, offline.

    Returns:
        None when the rebuilt prompt file and item choice are the plan's,
        or when a smoke the plan found without ready answers still has
        none; else the reason. A source run that is missing, edited or
        refused for any other reason is a reason, never a match.
    """
    with TemporaryDirectory(prefix="dfilterforge-smoke-judge-") as scratch:
        report, code = follow_up(
            Path(smoke.source_run_dir), Path(scratch) / "rebuilt", "judge"
        )
    if report is None:
        still_missing = code == READY_ANSWERS_MISSING
        if still_missing and smoke.status == "ready_answers_missing":
            return None
        return f"source_refused_{code}"
    if smoke.status != "prepared":
        return "source_now_has_ready_answers"
    rebuilt = (
        report["source_run_manifest_sha256"],
        tuple(cast(list[str], report["items"])),
        cast(dict[str, Any], report["conditions"])[LABEL],
    )
    if rebuilt != (
        smoke.source_run_manifest_sha256,
        smoke.items,
        smoke.c4_sha256,
    ):
        return "prompts_not_rebuilt"
    return None


def judge(out_dir: Path, plan: PlanV1) -> tuple[list[SmokeState], Path]:
    """Judges every smoke and writes its verdict and the summary.

    Returns:
        Every smoke's state, in plan order, and the plain-text summary.
    """
    states: list[SmokeState] = []
    for smoke in plan.smokes:
        problem = _verify_source(smoke)
        state = smoke_state(out_dir, smoke)
        if problem is not None:
            state = SmokeState(smoke, "unjudgeable", (problem,), state.runs)
        states.append(state)
        _write_json(
            out_dir / VERDICT_DIR / f"{smoke.smoke_id}.json",
            verdict_document(plan, state),
        )
    return states, write_summary(out_dir, plan, states)


def _served_over(state: SmokeState) -> dict[str, Any]:
    """Collects what served a smoke's runs, and whether any run changed.

    A flag, never a verdict: the owner ruled on 2026-09-27 that a smoke
    served by another provider or model than the counted pass's is read
    as any other, and only shows it.
    """
    records = [run.record for run in state.runs if "providers" in run.record]
    return {
        "providers": sorted({p for r in records for p in r["providers"]}),
        "provider_changed": any(r["provider_changed"] for r in records),
        "served_models": sorted(
            {m for r in records for m in r["served_models"]}
        ),
        "model_changed": any(r["model_changed"] for r in records),
    }


def _served_marker(state: SmokeState) -> str:
    """Spells the served providers and flags for one summary line.

    Provider names are provider metadata, so one that is not a plain
    name reads ``other`` there; the verdict file keeps it, JSON-escaped.
    """
    values = _served_over(state)
    names = sorted(
        {
            name if SHOWN_NAME.fullmatch(name) else "other"
            for name in values["providers"]
        }
    )
    marker = f"; served {','.join(names) or '-'}"
    if values["provider_changed"]:
        marker += " PROVIDER CHANGED"
    if values["model_changed"]:
        marker += " MODEL CHANGED"
    return marker


def verdict_document(plan: PlanV1, state: SmokeState) -> dict[str, Any]:
    """Spells one smoke's verdict; the same runs give the same bytes."""
    smoke = state.smoke
    return {
        "schema_version": "two-turn-smoke-verdict/1.0",
        "smoke_id": smoke.smoke_id,
        "slot": smoke.slot,
        "rank": smoke.rank,
        "candidate": smoke.candidate,
        "informational": smoke.informational,
        "model_id": smoke.settings.model_id,
        "reasoning_switch": smoke.reasoning_switch,
        "source_run_id": smoke.source_run_id,
        "source_run_manifest_sha256": smoke.source_run_manifest_sha256,
        "config": smoke.config,
        "config_sha256": smoke.config_sha256,
        "follow_up_text_sha256": plan.follow_up_text_sha256,
        "items": list(smoke.items),
        "verdict": state.verdict,
        "reasons": list(state.reasons),
        **_served_over(state),
        "runs": [run.document() for run in state.runs],
        "evidence": [
            f"{run.run_id}/{name}"
            for run in state.runs
            for name in ("run_manifest.json", f"attempts/{LABEL}.jsonl")
        ],
    }


def slot_lines(states: Sequence[SmokeState]) -> list[str]:
    """States what each ranked slot's smokes leave for the selection."""
    lines: list[str] = []
    for slot in RANKED_SLOTS:
        own = [s for s in states if s.smoke.slot in (slot, f"reserve-{slot}")]
        passed = [s.smoke.candidate for s in own if s.verdict == "pass"]
        if not own:
            continue
        if passed:
            lines.append(f"{slot}: smoke passed by {', '.join(passed)}")
        elif not all(s.final for s in own):
            lines.append(f"{slot}: not every smoke has a verdict yet")
        elif any(s.smoke.slot != slot for s in own):
            lines.append(f"{slot}: the reserve failed its smoke too")
        else:
            lines.append(
                f"{slot}: every run-gate survivor failed its smoke; run"
                f" scripts/dev_bakeoff.py --only reserve-{slot}"
                " --after-smoke-failures from the main checkout, then"
                f" two_turn_smoke.py prepare --reserve {slot} --summary"
                " <main checkout>/artifacts/bakeoff/summary-<date>.json"
                " here"
            )
    return lines


def write_summary(
    out_dir: Path, plan: PlanV1, states: Sequence[SmokeState]
) -> Path:
    """Writes the JSON and plain-text summaries of every smoke."""
    stamp = _now()
    lines = [
        f"{s.smoke.slot} {s.smoke.rank} {s.smoke.candidate}"
        f" {s.smoke.smoke_id}: {s.verdict}"
        + (" (informational)" if s.smoke.informational else "")
        + (f" [{', '.join(s.reasons)}]" if s.reasons else "")
        + f"; items {', '.join(s.smoke.items) or '-'}"
        + f"; runs {', '.join(r.run_id for r in s.runs) or '-'}"
        + _served_marker(s)
        for s in states
    ]
    slots = slot_lines(states)
    document = {
        "written_at": stamp,
        "plan_source_revision": plan.source_revision,
        "prepare_date": plan.prepare_date,
        "verdicts": {s.smoke.smoke_id: s.verdict for s in states},
        "slots": slots,
    }
    _write_json(out_dir / f"summary-{stamp[:10]}.json", document)
    text = out_dir / f"summary-{stamp[:10]}.txt"
    text.write_text(
        "\n".join([*lines, "", *slots]).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return text


def judge_exit(states: Sequence[SmokeState]) -> int:
    """Returns 0 when every smoke has a verdict, 2 if one cannot be judged."""
    if any(state.verdict == "unjudgeable" for state in states):
        return EXIT_REFUSED
    return EXIT_OK if all(state.final for state in states) else EXIT_STOPPED


# A reserve's smoke, added to the plan by rule 6.


def _reserve_record(
    plan: PlanV1, summary: dict[str, Any], slot: str
) -> dict[str, Any]:
    """Returns the slot's reserve record, which must still need its smoke.

    Raises:
        PlanError: If the plan already holds the reserve's smoke, or the
            summary lists no reserve of the slot passing the run gates.
    """
    reserve_slot = f"reserve-{slot}"
    if any(entry.slot == reserve_slot for entry in plan.smokes):
        raise PlanError(f"the plan already holds the {reserve_slot} smoke")
    records = [r for r in _passing(summary) if r["slot"] == reserve_slot]
    if len(records) != 1:
        raise PlanError(
            f"the summary lists no {reserve_slot} candidate passing the run"
            " gates"
        )
    return records[0]


def _check_survivors_failed(
    out_dir: Path, plan: PlanV1, summary: dict[str, Any], slot: str
) -> None:
    """Requires that every run-gate survivor of the slot failed its smoke.

    Each smoke is read as ``judge`` reads it, source rebuild included,
    and every survivor the new summary names must be one the plan
    smoked, so a reserve can never give a survivor a second smoke.

    Raises:
        PlanError: If a survivor of the slot has no failed smoke.
    """
    ranked = [s for s in plan.smokes if s.slot == slot]
    open_smokes: list[str] = []
    for entry in ranked:
        verdict = smoke_state(out_dir, entry).verdict
        if _verify_source(entry) is not None:
            verdict = "unjudgeable"
        if verdict != "fail":
            open_smokes.append(f"{entry.candidate} {verdict}")
    if open_smokes:
        raise PlanError(
            f"rule 6 runs the {slot} reserve only once every run-gate survivor"
            f" of the slot failed its smoke: {', '.join(open_smokes)}"
        )
    smoked = {(entry.candidate, entry.source_run_id) for entry in ranked}
    unsmoked = [
        str(record["candidate"])
        for record in _passing(summary)
        if record["slot"] == slot
        and (record["candidate"], record["qualifying_pass"]["run_id"])
        not in smoked
    ]
    if unsmoked:
        raise PlanError(
            f"{', '.join(unsmoked)} passes the run gates in the summary but"
            " the plan holds no smoke of that pass"
        )


def prepare_reserve(
    summary_path: Path,
    out_dir: Path,
    revision: str,
    slot: str,
    config_dir: Path | None = None,
) -> PlanV1:
    """Appends the slot's reserve smoke to the plan, offline (rule 6).

    The smoke is named after today's date, as a smoke is named after its
    prepare's. Existing smokes, their runs and their verdicts are left as
    they are, and the plan records the summary the smoke was read from.

    Returns:
        The plan with the reserve's smoke appended.

    Raises:
        PlanError: If there is no plan, a survivor of the slot has no
            failed smoke, the slot's reserve does not pass the run gates
            or already has a smoke, its directory exists, or its counted
            pass, config or follow-up is refused.
    """
    if slot not in RANKED_SLOTS:
        raise PlanError(f"{slot}: not a ranked slot")
    plan = load_plan(out_dir)
    data, summary, source_root = _read_summary(summary_path)
    record = _reserve_record(plan, summary, slot)
    _check_survivors_failed(out_dir, plan, summary, slot)
    date = _now()[:10]
    base = _smoke_base(
        record, source_root, config_dir or ROOT / CONFIG_DIR, date
    )
    smoke_id = str(base["smoke_id"])
    if any(entry.smoke_id == smoke_id for entry in plan.smokes):
        raise PlanError(f"the plan already holds {smoke_id}")
    _refuse_taken(out_dir, [smoke_id])
    try:
        smoke = _prepare_smoke(base, out_dir, revision)
        if smoke.status == "prepared":
            check_cap(smoke)
        extended = plan.model_copy(
            update={
                "smokes": (*plan.smokes, smoke),
                "reserves": (
                    *plan.reserves,
                    ReserveV1(
                        smoke_id=smoke_id,
                        prepare_date=date,
                        source_revision=revision,
                        summary_path=summary_path.resolve().as_posix(),
                        summary_sha256=_sha256(data),
                    ),
                ),
            }
        )
        _replace_json(out_dir / PLAN_NAME, extended)
    except BaseException:
        # Only the new smoke's directory: _refuse_taken made sure this call
        # created it, and every other one may hold paid runs.
        shutil.rmtree(out_dir / smoke_id, ignore_errors=True)
        raise
    return extended


# The paid batch.


Invoker = Callable[[Sequence[str], bool], Any]


def _print(line: str) -> None:
    print(line, flush=True)


def pause(seconds: float) -> None:
    """Waits before a resume; the tests replace this seam."""
    db.pause(seconds)


@dataclass
class Context:
    """Everything one execution of the batch shares."""

    out_dir: Path
    plan: PlanV1
    source_revision: str
    invoke: Invoker
    changes: Callable[[], list[str]] = lambda: uncommitted(TOOLING)
    out: Callable[[str], None] = _print

    def log(self, record: dict[str, Any]) -> None:
        """Appends one step record; argv and codes only, never the env."""
        path = self.out_dir / "steps.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(json.dumps({"at": _now(), **record}, sort_keys=True))
            log.write("\n")


def subprocess_invoke(out: Callable[[str], None]) -> Invoker:
    """Returns the real invoker: the bake-off's, one child per call step."""
    wait = INTERRUPT_GRACE_SECONDS + 120.0

    def invoke(argv: Sequence[str], with_key: bool) -> Any:
        prepare_dir = _resolve(argv[argv.index("--prepare-dir") + 1])
        return db.subprocess_invoker(prepare_dir, out, wait)(argv, with_key)

    return invoke


def call_argv(
    ctx: Context, smoke: SmokeV1, run_id: str, resume: bool
) -> list[str]:
    """Builds one call step's argument list; nothing here is a shell."""
    options = {
        "--prepare-dir": _relative(ctx.out_dir / smoke.smoke_id),
        "--run-id": run_id,
        "--config": smoke.config_path,
        "--max-usd": MAX_USD,
        "--source-revision": ctx.source_revision,
        "--min-interval-seconds": f"{MIN_INTERVAL_SECONDS}",
        "--max-attempts": f"{MAX_ATTEMPTS}",
    }
    argv = [sys.executable, MODEL_RUN, "call"]
    for flag, value in options.items():
        argv.extend((flag, value))
    argv.append("--gate-first")
    if resume:
        argv.append("--resume")
    return argv


def _changed_code(prepare_bytes: bytes) -> tuple[str, list[str]]:
    """Compares the model-side files a prompt set recorded with today's.

    These are the digests the call step checks before any request, so a
    file listed here would stop the call at ``prepare_code_mismatch``.

    Returns:
        The revision the prompt set was prepared at, and every recorded
        file that is missing, outside the repository or changed.

    Raises:
        PlanError: If prepare.json is not a prompt set's manifest.
    """
    try:
        manifest = PrepareManifestV1.model_validate_json(prepare_bytes)
    except ValidationError:
        raise PlanError("prepare.json is not a prepare manifest") from None
    changed: list[str] = []
    for name, digest in sorted(manifest.source_files.items()):
        path = (ROOT / name).resolve()
        if (
            ROOT not in path.parents
            or not path.is_file()
            or file_sha256(path) != digest
        ):
            changed.append(name)
    return manifest.source_revision, changed


def _code_advice(
    ctx: Context, smoke: SmokeV1, revision: str, changed: Sequence[str]
) -> str:
    """Says what to do about a prompt set the code no longer matches.

    A smoke with a runs/ directory may hold paid evidence, and removing
    the out dir would take it with it; only with none may it go.
    """
    problem = (
        f"{smoke.smoke_id}: {', '.join(changed)} changed since its prompts"
        f" were prepared at {revision}, so its call would stop at"
        " prepare_code_mismatch before any request."
    )
    if any(
        (ctx.out_dir / s.smoke_id / "runs").exists() for s in ctx.plan.smokes
    ):
        return (
            f"{problem} Smokes here have runs/ directories that may hold paid"
            " evidence, so delete nothing: restore those files with git"
            f" checkout {revision} -- {' '.join(changed)}, commit, then run"
            " the same command"
        )
    return (
        f"{problem} No smoke has a runs/ directory, so no smoke request was"
        f" sent: remove {_relative(ctx.out_dir)}, then run prepare --summary"
        f" {ctx.plan.summary_path}; the new smoke ids carry that day's date"
    )


def check_inputs(ctx: Context) -> None:
    """Ties every prepared smoke to the files the plan recorded.

    The same checks guard ``run`` and ``run --dry-run``, so the free
    check also refuses a prompt set the call step would refuse for its
    code. A smoke with a verdict needs no call, so only one still owed a
    call must match the model-side code its prompt set recorded.

    Raises:
        PlanError: If a prompt set or config file changed, the cap cannot
            cover a smoke, or the model-side code changed under a smoke
            that is still owed a call.
    """
    for smoke in ctx.plan.smokes:
        if smoke.status != "prepared":
            continue
        prepare_json = ctx.out_dir / smoke.smoke_id / "prepare.json"
        prepare_bytes = (
            prepare_json.read_bytes() if prepare_json.is_file() else b""
        )
        if _sha256(prepare_bytes) != smoke.prepare_sha256:
            raise PlanError(f"{smoke.smoke_id}: prepare.json is not the plan's")
        config = _resolve(smoke.config_path)
        if not config.is_file() or _sha256(config.read_bytes()) != (
            smoke.config_sha256
        ):
            raise PlanError(f"{smoke.config}: the config file changed")
        check_cap(smoke)
        if smoke_state(ctx.out_dir, smoke).final:
            continue
        revision, changed = _changed_code(prepare_bytes)
        if changed:
            raise PlanError(_code_advice(ctx, smoke, revision, changed))


def _unjudgeable_advice(out_dir: Path, state: SmokeState) -> str:
    """Names the run that cannot be judged and what may be done with it.

    Running the same command again cannot clear it. A call step writes
    run_manifest.json before its first request, so a run without one and
    with no attempt line sent nothing; any other may hold paid evidence.
    """
    smoke = state.smoke
    where = out_dir / smoke.smoke_id
    if state.runs:
        where = smoke_run_dir(out_dir, smoke, state.runs[-1].run_id)
    return (
        f"{smoke.smoke_id}: {', '.join(state.reasons)}. {_relative(where)}"
        " cannot be judged, and running the same command again will not"
        " change that. If it has no run_manifest.json and every"
        " attempts/*.jsonl in it is empty or missing, nothing was sent:"
        " delete that directory, then run the same command. Otherwise it"
        " may hold paid evidence: delete nothing and inspect it"
    )


def _pending_calls(ctx: Context) -> list[tuple[SmokeV1, str, bool]]:
    """Lists the call each smoke needs next, in plan order.

    Raises:
        BatchStop: If a smoke's runs cannot be judged.
    """
    calls: list[tuple[SmokeV1, str, bool]] = []
    for smoke in ctx.plan.smokes:
        state = smoke_state(ctx.out_dir, smoke)
        if state.verdict == "unjudgeable":
            raise BatchStop(_unjudgeable_advice(ctx.out_dir, state))
        step = next_call(ctx.out_dir, state)
        if step is not None:
            calls.append((smoke, *step))
    return calls


def preflight(ctx: Context, calls: Sequence[tuple[SmokeV1, str, bool]]) -> None:
    """Makes every next call once with the key withheld.

    Raises:
        PlanError: If any stops anywhere but at ``api_key_missing``.
    """
    for smoke, run_id, resume in calls:
        argv = call_argv(ctx, smoke, run_id, resume)
        result = ctx.invoke(argv, False)
        ctx.log(
            {
                "phase": "preflight",
                "smoke_id": smoke.smoke_id,
                "run_id": run_id,
                "argv": ["python", *argv[1:]],
                "exit_code": result.exit_code,
                "error_code": result.error_code,
            }
        )
        if (result.exit_code, result.error_code) != (2, "api_key_missing"):
            raise PlanError(
                f"preflight: {run_id} stopped at {result.error_code}"
                f" (exit {result.exit_code})"
            )
        ctx.out(f"  preflight ok: {run_id} -> api_key_missing")


def _call(ctx: Context, smoke: SmokeV1, run_id: str, resume: bool) -> None:
    """Makes one paid call step.

    Raises:
        BatchAbort: If the key was missing or the account refused.
        BatchStop: If the call step ended with an error envelope.
    """
    argv = call_argv(ctx, smoke, run_id, resume)
    phase = "resume" if resume else "start"
    ctx.out(f"  {_now()} {run_id}: {phase}")
    result = ctx.invoke(argv, True)
    report = cast(dict[str, Any], result.report or {})
    record = {key: report.get(key) for key in REPORT_KEYS}
    record.update(exit_code=result.exit_code, error_code=result.error_code)
    ctx.log(
        {
            "phase": phase,
            "smoke_id": smoke.smoke_id,
            "run_id": run_id,
            "argv": ["python", *argv[1:]],
            **record,
        }
    )
    missing_key = result.error_code == "api_key_missing"
    if result.report is None and missing_key:
        raise BatchAbort(f"{run_id}: the call step found no key")
    if result.report is None and result.error_code == "endpoint_invalid":
        # The call step builds its client before any request, from a config
        # check_inputs pinned to the counted pass's, which built one with
        # the same client code; so only the credential is left to blame.
        raise BatchStop(
            f"{run_id}: the call step could not build its client"
            f" (endpoint_invalid, exit {result.exit_code}), so nothing was"
            " sent and nothing is owed. The config is the counted pass's own"
            f" file, pinned by hash: check that {API_KEY_ENV} holds the bare"
            " key, with no CR, newline or other control character (as"
            " $(cat file) gives from a CRLF file), then run the same command"
        )
    if result.report is None:
        raise BatchStop(
            f"{run_id}: the call step ended with an error"
            f" ({result.error_code}, exit {result.exit_code})"
        )
    if report.get("stop_reason") == "fatal_http":
        raise BatchAbort(
            f"{run_id}: the account refused a request (HTTP 401, 402 or"
            " 403); fix the key, the credit or the guardrail, then run the"
            " same command: this smoke is owed a re-run"
        )


def drive(ctx: Context, smoke: SmokeV1) -> SmokeState:
    """Makes at most one new run for one smoke and settles it.

    Raises:
        BatchAbort: If the key was missing or the account refused.
        BatchStop: If a run cannot be judged or keeps pending.
    """
    state = smoke_state(ctx.out_dir, smoke)
    step = next_call(ctx.out_dir, state)
    if step is None:
        return state
    run_id, resume = step
    _call(ctx, smoke, run_id, resume)
    for _ in range(MAX_ATTEMPTS):
        outcome = assess(smoke, smoke_run_dir(ctx.out_dir, smoke, run_id))
        if outcome.kind != "resume":
            break
        ctx.out(
            f"  {run_id}: {', '.join(outcome.reasons) or 'pending'};"
            f" resuming in {RESUME_WAIT_SECONDS:.0f} s"
        )
        pause(RESUME_WAIT_SECONDS)
        _call(ctx, smoke, run_id, True)
    state = smoke_state(ctx.out_dir, smoke)
    if state.verdict == "unjudgeable":
        raise BatchStop(_unjudgeable_advice(ctx.out_dir, state))
    if state.verdict == "resume_owed":
        raise BatchStop(f"{run_id}: {state.verdict} {', '.join(state.reasons)}")
    return state


def run_batch(ctx: Context) -> int:
    """Runs every smoke that needs a call, after the preflight.

    Raises:
        PlanError: If an input changed, the preflight fails or the
            tooling is uncommitted.
        BatchAbort: If the key variable is absent or the account refused.
        BatchStop: If a run needs the owner.
    """
    check_inputs(ctx)
    calls = _pending_calls(ctx)
    ctx.out(f"source revision {ctx.source_revision}; {len(calls)} calls due")
    preflight(ctx, calls)
    if API_KEY_ENV not in os.environ:
        raise BatchAbort(f"{API_KEY_ENV} is not set; nothing was sent")
    changes = ctx.changes()
    if changes:
        raise PlanError("commit the tooling first: " + "; ".join(changes))
    owed = False
    for smoke in ctx.plan.smokes:
        state = drive(ctx, smoke)
        ctx.out(f"{smoke.smoke_id}: {state.verdict} {', '.join(state.reasons)}")
        owed = owed or not state.final
    return EXIT_STOPPED if owed else EXIT_OK


def dry_run(ctx: Context) -> None:
    """Prints every smoke's state and the call it would make next."""
    for smoke in ctx.plan.smokes:
        state = smoke_state(ctx.out_dir, smoke)
        line = f"{smoke.smoke_id}: {state.verdict}"
        if smoke.informational:
            line += " (informational)"
        if smoke.status == "prepared":
            worst = worst_case_micro_usd(smoke) / MICRO
            line += (
                f"; items {', '.join(smoke.items)}; worst request"
                f" {worst:.6f} USD; cap {MAX_USD} USD"
            )
        ctx.out(line)
        step = next_call(ctx.out_dir, state)
        if step is not None:
            argv = call_argv(ctx, smoke, *step)
            ctx.out("    " + " ".join(["python", *argv[1:]]))


# How each way the batch can stop is printed and exits.
ENDINGS: tuple[tuple[type[BaseException], str, int], ...] = (
    (PlanError, "REFUSED", EXIT_REFUSED),
    (subprocess.CalledProcessError, "REFUSED", EXIT_REFUSED),
    (BatchStop, "STOPPED", EXIT_STOPPED),
    (BatchAbort, "ABORTED", EXIT_ABORTED),
)


def _log_interrupt(ctx: Context, reason: str) -> None:
    """Records an interrupt in the step log, so the evidence shows it.

    The call step's own records cannot: a request it had in flight is in
    no attempt log. A step log that cannot be written is not fatal here.
    """
    with contextlib.suppress(OSError):
        ctx.log({"phase": "interrupted", "reason": reason})


def locked_run(ctx: Context) -> int:
    """Runs the batch under the lock and always judges afterwards.

    An error the batch does not expect stops it with exit 1, never a
    refusal's 2, since requests may have been sent before it.
    """
    lock = ctx.out_dir / LOCK_NAME
    keep_lock = False
    try:
        db.acquire_lock(lock)
    except db.PlanError as error:
        print(f"plan refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        code = run_batch(ctx)
    except (
        PlanError,
        subprocess.CalledProcessError,
        BatchStop,
        BatchAbort,
    ) as error:
        label, code = next(
            (label, code)
            for kind, label, code in ENDINGS
            if isinstance(error, kind)
        )
        ctx.out(f"{label}: {error}")
    except db.ChildStillRunning:
        # Its text names the bake-off's lock, not this batch's.
        keep_lock = True
        ctx.out(
            "INTERRUPTED: the call step whose pid is printed above is still"
            " running, and its request may be billed but not recorded; let"
            f" it exit, then delete {_relative(lock)} and run the same command"
        )
        _log_interrupt(ctx, "call_step_still_running")
        code = EXIT_INTERRUPTED
    except KeyboardInterrupt:
        ctx.out(
            "INTERRUPTED: run the same command again to resume; the"
            " interrupted request may be billed but not recorded"
        )
        _log_interrupt(ctx, "ctrl_c")
        code = EXIT_INTERRUPTED
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Never a refusal: it may follow a paid call. After the clause
        # above, since ChildStillRunning is an Exception too.
        ctx.out(
            f"STOPPED: unexpected {type(error).__name__}: {error}; requests"
            " may have been sent (see steps.jsonl), so fix the cause, then"
            " run the same command again"
        )
        code = EXIT_STOPPED
    finally:
        if not keep_lock:
            lock.unlink(missing_ok=True)
    try:
        _report(ctx)
    except KeyboardInterrupt:
        ctx.out(
            "INTERRUPTED: judging stopped; it sends nothing, so run the"
            " judge subcommand for the verdicts"
        )
        code = EXIT_INTERRUPTED
    ctx.out(f"exit {code}")
    return code


def _report(ctx: Context) -> None:
    """Judges after a batch, so its one command leaves the verdicts."""
    try:
        _, text = judge(ctx.out_dir, ctx.plan)
        ctx.out(text.read_text(encoding="utf-8").rstrip())
    except (PlanError, OSError, ValueError) as error:
        ctx.out(f"judge failed ({error}); run the judge subcommand")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / OUT_DIR, help=argparse.SUPPRESS
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_command = commands.add_parser(
        "prepare", help="build every survivor's smoke prompts, offline"
    )
    prepare_command.add_argument("--summary", type=Path, required=True)
    prepare_command.add_argument(
        "--reserve",
        choices=RANKED_SLOTS,
        help="append this slot's reserve smoke to the plan (rule 6)",
    )
    run_command = commands.add_parser("run", help="the one paid command")
    run_command.add_argument("--dry-run", action="store_true")
    commands.add_parser("judge", help="write the verdicts, offline")
    return parser


def _command(arguments: argparse.Namespace) -> int:
    """Runs one parsed subcommand.

    Raises:
        PlanError: If the plan, an input or the tooling is refused.
    """
    out_dir = cast(Path, arguments.out_dir)
    if arguments.command == "prepare":
        changes = uncommitted(TOOLING)
        if changes:
            raise PlanError("commit the tooling first: " + "; ".join(changes))
        revision = db.head_revision()
        if arguments.reserve is None:
            plan = prepare(arguments.summary, out_dir, revision)
            written = plan.smokes
        else:
            plan = prepare_reserve(
                arguments.summary, out_dir, revision, arguments.reserve
            )
            written = plan.smokes[-1:]
        for smoke in written:
            items = ", ".join(smoke.items) or smoke.status
            print(f"{smoke.smoke_id} from {smoke.source_run_id}: {items}")
        return EXIT_OK
    plan = load_plan(out_dir)
    if arguments.command == "judge":
        states, text = judge(out_dir, plan)
        print(text.read_text(encoding="utf-8").rstrip())
        return judge_exit(states)
    ctx = Context(out_dir, plan, db.head_revision(), subprocess_invoke(_print))
    if not arguments.dry_run:
        return locked_run(ctx)
    check_inputs(ctx)
    dry_run(ctx)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Runs one subcommand and returns a process exit code."""
    arguments = _parser().parse_args(argv)
    try:
        return _command(arguments)
    except (
        PlanError,
        db.PlanError,
        subprocess.CalledProcessError,
        OSError,
        ValueError,
    ) as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
