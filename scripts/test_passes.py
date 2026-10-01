"""Owner batch for the registered hosted test passes.

Run from the repository root of the main checkout, in the one shell that
holds the key, once the registration (docs/decisions/test-runs.md and its
registry) is merged:

    uv run --frozen python scripts/test_passes.py [--dry-run]

The batch reads docs/decisions/evidence/test-runs.json and runs, one run
at a time, the A/A pair's pass A, pass B straight after it, then the
small, mid and frontier slot winners. A pass is one ``scripts/model_run.py
call`` started as an argument list with no shell, over the ignored copy
of the frozen test prompts the registry names (``call_prepare_dir``),
with the row's config, run id and cap and the registry's call options
(``--gate-first``, ``--max-attempts 3``, ``--min-interval-seconds 1.0``).
Items it leaves pending after a transient failure (HTTP 5xx, 408 or 429, a
timeout or a transport error) are sent again by ``--resume`` with the same
options after a 60 s wait, within the same execution, until every item is
settled. The run directories, the registry and the bake-off runner's own
reading of a run (scripts/dev_bakeoff.py) decide every step, so running
the same command again skips finished runs and resumes unfinished ones.
The key is inherited from the environment by the paid calls only; this
script never reads, prints or writes it.

What follows a pass, by the registry (rules 3 and 7 of the bake-off note):

- Gate stop: a pass whose first completed answer shows thinking not
  honoured is never resumed. A slot winner's listed fallback row then
  runs once; if it stops at the gate too, the slot's row is not run. A
  pass whose resumed pass stops at the gate is not run and gets no
  fallback. The anchor has no fallback, so either way at the gate, on
  pass A, pass B or the re-run of either, reports the A/A pair not run,
  and after pass A's, pass B is not sent.
- Outage: a pass that ends with no completed answer and is not a refusal
  is re-run once from scratch under its ``-r2`` row after a 60 s wait; if
  that is an outage too, the row is not run.
- A complete pass with no completed answer whose every lasting failure is
  HTTP 400 or 404, a refusal, has no registered fallback or re-run, so it
  is not run.
- Pass B is sent whatever pass A shows but the gate (docs/protocol.md): a
  pass A that is complete, refused, or an outage on its re-run too.
- A row the registry marks ``not_run``, or ``unused`` with a reason, is
  the owner's ruling and is never sent; a ``published`` row is never sent
  again. A run ruled ``not_run`` after it left a directory still triggers
  what that directory shows, its fallback after a gate stop or its
  ``-r2`` row after an outage, so committing the statuses a stop's
  summary gives never drops a triggered run. A conditional row the
  registry registers, or that left a directory, is never called unused;
  if no chain reaches it, the batch stops for the owner.

HTTP 401, 402 or 403 aborts. A budget stop after an answer stops the batch
until the row's cap is raised above the last invocation's ``max_usd`` in
the registry and its note and committed. So does anything the batch
cannot read as a pass: the invocation limit, a call step that ended with
an error, or an unreadable run directory. Pass B must start within 24
hours of the counted pass A's first invocation (docs/protocol.md), the
counted pass A being its ``-r2`` row once that has a run manifest, else
pass A, whatever it showed; if that window has closed before pass B
started, or no pass A run has a manifest, the batch stops for the owner.

The batch refuses to start unless the prompt copy exists, its prepare.json
is a prompt set the freeze record admits, and it and every prompt file are
byte-identical to the committed copy the registry names; the refusal for
a missing copy prints the commands that restore it. Before the first paid
call every row this execution may send is called once with the key
withheld and must stop at ``api_key_missing``, which proves that the run
id, cap, prompt set, source digests and config pass the call step's own
checks while no request is possible. Paid calls start only when the key
variable is present and the registration and tooling are committed, so
the HEAD each call records covers them. The batch never publishes or
scores; its summary names, for every registry row, the state, status,
reason, commit and target directory the maintainer's publish step
records.

The step log, the summary and the lock are written under
artifacts/test-passes/.

Exit codes:
    0    Every registry row has a final state: done, not run or unused.
    1    The batch stopped for the owner (the summary names the row and
         the reason), or an error it did not expect stopped it after a
         paid call may have been sent: read steps.jsonl, fix the cause,
         then run the same command.
    2    Refused before any request: the registry, the prompt copy (a
         missing copy prints its restore commands), a config, the lock,
         git, uncommitted tooling or the keyless preflight.
    3    Aborted: the key variable is not set (after the keyless
         preflight; nothing was sent), or the account refused a request
         (HTTP 401, 402 or 403). Fix it and run the same command.
    130  Interrupted with Ctrl-C, after the in-flight request finished. An
         interrupted request may be billed but not recorded.
"""

# The registry checks, the chains, the sending and the summary share one
# file so that the one commit every call records covers all of them, as
# scripts/dev_bakeoff.py keeps its plan and decisions together.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import contextlib
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import ModuleType
from typing import Any, Literal, NamedTuple

from pydantic import Field

from dfilterforge.completions import PrepareManifestV1
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.held_out import load_record
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.model_client import API_KEY_ENV

ROOT = Path(__file__).resolve().parents[1]


def _sibling(name: str) -> ModuleType:
    """Loads one sibling script for its public contract.

    Raises:
        RuntimeError: If the script cannot be loaded.
    """
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_passes_{name}", path)
    loader = None if spec is None else spec.loader
    if spec is None or loader is None:
        raise RuntimeError(f"scripts/{name}.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


# The bake-off runner's reading of a run, its invoker, lock and exit codes,
# and the call step itself: one definition of each, shared with the dev
# passes they decided.
db = _sibling("dev_bakeoff")
model_run = db.load_model_run()
EXIT_OK: int = db.EXIT_OK
EXIT_STOPPED: int = db.EXIT_STOPPED
EXIT_REFUSED: int = db.EXIT_REFUSED
EXIT_ABORTED: int = db.EXIT_ABORTED
EXIT_INTERRUPTED: int = db.EXIT_INTERRUPTED

REGISTRY = "docs/decisions/evidence/test-runs.json"
NOTE = "docs/decisions/test-runs.md"
OUT_DIR = "artifacts/test-passes"
LOCK_NAME = ".lock"
STEP_LOG = "steps.jsonl"
# Where a run that is not published (a gate stop, an outage, a refusal)
# leaves its manifest and attempt logs, as the bake-off's did.
EVIDENCE_DIR = "docs/decisions/evidence/test-runs"
# Paths whose committed state each call's recorded HEAD must cover: the
# registration, the reused bake-off reading and configs, the unhashed
# thinking rule, and the freeze record the call step admits prompts by.
TOOLING = (
    "scripts/test_passes.py",
    "scripts/dev_bakeoff.py",
    db.CONFIG_DIR,
    REGISTRY,
    NOTE,
    "docs/protocol.md",
    "docs/decisions/model-bakeoff.md",
    "src/dfilterforge/completions.py",
    "src/dfilterforge/held_out.py",
    "src/dfilterforge/held_out_freeze.json",
)
PLANNED_ROLES = (
    "aa_pass_a",
    "aa_pass_b",
    "winner_small",
    "winner_mid",
    "winner_frontier",
)
CALL_PREPARE_DIR = re.compile(r"artifacts/model-eval/[a-z0-9][a-z0-9.-]{0,63}")
PASS_B_WINDOW = timedelta(hours=24)
# The bake-off reading's reason for a fallback earned by a first answer that
# reasoned, a gate stop; its other fallback reason is a refusal.
GATE_STOP_REASON = "first_answer_reasoned"
TRIGGER_TEXT = {"gate_stop": "a gate stop", "outage": "an outage"}
# How a chain ends at the gate: a gate stop with no fallback left, or a
# resumed pass that stops there. Rule 7 reports the A/A pair not run for
# either; any other end of pass A still leaves pass B due.
GATE_KINDS = frozenset({"gate_stop", "reasoned"})
FINAL_STATES = frozenset({"done", "not_run", "unused"})
OPEN_STATES = frozenset({"owed", "waiting"})
STAMP = "%Y-%m-%dT%H:%M:%SZ"


class PlanError(RuntimeError):
    """Refused before any request: the batch cannot run as it stands."""


class BatchStop(RuntimeError):
    """The owner has to resume, rule on or fix something first."""


class BatchAbort(RuntimeError):
    """The key or the account stops every run alike."""


class SettingsV1(FrozenModel):
    """The request settings every registered run sends."""

    temperature: float
    seed: int
    max_output_tokens: int
    timeout_seconds: float
    json_mode: bool
    require_parameters: bool
    allow_fallbacks: bool
    data_collection: Literal["allow", "deny"] | None


class CallV1(FrozenModel):
    """The call options every registered pass and resume uses."""

    gate_first: bool
    max_attempts: int
    min_interval_seconds: float


class RunRowV1(FrozenModel):
    """One registered run, with its status."""

    role: str
    run_id: str
    model_id: str
    slug: str
    quant: str
    reasoning_switch: Literal["enabled_false", "effort_none"] | None
    config: str
    cap_usd: float
    prepare: str
    conditional_on: str | None
    trigger: Literal["gate_stop", "outage"] | None
    status: Literal["registered", "unused", "published", "not_run"]
    reason: str | None
    commit: str | None


class RegistryV1(FrozenModel):
    """The hosted test-run registry, schema test-runs/1.0."""

    schema_version: Literal["test-runs/1.0"] = Field(alias="schema")
    registered_on: str
    note: str
    ruling: str
    call_prepare_dir: str
    settings: SettingsV1
    call: CallV1
    repair_arms: dict[str, Any]
    runs: tuple[RunRowV1, ...]


@dataclass(frozen=True)
class Plan:
    """The checked registry, with the run each failure triggers."""

    registry: RegistryV1
    sha256: str
    planned: tuple[RunRowV1, ...]
    fallback_of: dict[str, RunRowV1]
    rerun_of: dict[str, RunRowV1]

    @property
    def rows(self) -> tuple[RunRowV1, ...]:
        """Returns every registered run, in registry order."""
        return self.registry.runs

    @property
    def prepare(self) -> str:
        """Returns the committed prompt directory every run answers."""
        return self.registry.runs[0].prepare

    def row(self, run_id: str) -> RunRowV1:
        """Returns the registered run with this id."""
        return next(row for row in self.rows if row.run_id == run_id)


def load_registry(path: Path) -> tuple[RegistryV1, str]:
    """Reads the registry and the digest of its exact bytes.

    Raises:
        ValueError: If the file does not parse as test-runs/1.0.
    """
    data = path.read_bytes()
    registry = RegistryV1.model_validate_json(data)
    return registry, hashlib.sha256(data).hexdigest()


def _check_call(registry: RegistryV1) -> None:
    """Holds the registry's call options to the bake-off's.

    Raises:
        PlanError: If the prompt copy or a call option is not the one
            every bake-off pass used.
    """
    call = registry.call
    if CALL_PREPARE_DIR.fullmatch(registry.call_prepare_dir) is None:
        raise PlanError("call_prepare_dir is not under artifacts/model-eval")
    if (call.gate_first, call.max_attempts, call.min_interval_seconds) != (
        True,
        db.MAX_ATTEMPTS,
        db.MIN_INTERVAL_SECONDS,
    ):
        raise PlanError("the registered call options are not the bake-off's")


def _check_row(row: RunRowV1, registry: RegistryV1) -> None:
    """Refuses a row the call step or the chain rules cannot use.

    Raises:
        PlanError: If its run id, cap, prompts, config or status is not
            usable.
    """
    name = row.run_id
    if db.RESULT_DIR.fullmatch(name) is None or not name.startswith("test-"):
        raise PlanError(f"{name}: not a test result name")
    if not 0 < row.cap_usd <= db.MAX_USD:
        raise PlanError(f"{name}: cap outside the call step's bound")
    if row.prepare != registry.runs[0].prepare or (
        Path(row.prepare).name != Path(registry.call_prepare_dir).name
    ):
        raise PlanError(f"{name}: answers another prompt set")
    if Path(row.config).parent.as_posix() != db.CONFIG_DIR:
        raise PlanError(f"{name}: not a committed bake-off config")
    if row.status == "not_run" and not row.reason:
        raise PlanError(f"{name}: not_run without a reason")
    if row.trigger is None and (row.status == "unused" or row.conditional_on):
        raise PlanError(f"{name}: a planned run cannot be conditional")
    if row.trigger is not None and row.conditional_on is None:
        raise PlanError(f"{name}: a conditional run names no run")


def _check_condition(row: RunRowV1, named: RunRowV1) -> None:
    """Refuses a conditional row its named run cannot trigger.

    Raises:
        PlanError: If an outage re-run does not repeat its run's role and
            config or repeats a re-run, or a fallback is not a slot
            winner's.
    """
    if row.trigger == "outage":
        if named.trigger == "outage" or (row.role, row.config) != (
            named.role,
            named.config,
        ):
            raise PlanError(f"{row.run_id}: not a re-run of {named.run_id}")
        return
    slot = named.role.removeprefix("winner_")
    if named.trigger is not None or row.role != f"fallback_{slot}":
        raise PlanError(f"{row.run_id}: not the fallback of {named.run_id}")


def plan_from(registry: RegistryV1, sha256: str) -> Plan:
    """Checks the registry and links each run to what it triggers.

    Raises:
        PlanError: If a run id repeats, the planned runs are not the A/A
            pair and the three winners in order, pass A is not named
            after its prompts, or a row or condition is not usable.
    """
    _check_call(registry)
    rows = registry.runs
    by_id = {row.run_id: row for row in rows}
    if not rows or len(by_id) != len(rows):
        raise PlanError("the registry repeats a run id or names none")
    for row in rows:
        _check_row(row, registry)
    planned = tuple(row for row in rows if row.trigger is None)
    if tuple(row.role for row in planned) != PLANNED_ROLES:
        raise PlanError(f"the planned runs are not {', '.join(PLANNED_ROLES)}")
    if planned[0].run_id != Path(registry.call_prepare_dir).name:
        raise PlanError("pass A's run id is not its prompt set's id")
    triggered: dict[tuple[str, str], RunRowV1] = {}
    for row in rows:
        if row.trigger is None or row.conditional_on is None:
            continue
        named = by_id.get(row.conditional_on)
        if named is None:
            raise PlanError(f"{row.run_id}: names an unregistered run")
        _check_condition(row, named)
        key = (named.run_id, row.trigger)
        if key in triggered:
            raise PlanError(f"{named.run_id}: two rows for {row.trigger}")
        triggered[key] = row
    return Plan(
        registry=registry,
        sha256=sha256,
        planned=planned,
        fallback_of={
            run: row
            for (run, kind), row in triggered.items()
            if kind != "outage"
        },
        rerun_of={
            run: row
            for (run, kind), row in triggered.items()
            if kind == "outage"
        },
    )


class Prompts(NamedTuple):
    """The checked prompt copy every call answers."""

    sha256: str
    requests: int
    sizes: dict[str, tuple[int, ...]]


def restore_commands(call_dir: str, committed: str) -> str:
    """Spells the commands that copy the committed prompts, in both shells.

    Both leave any ``runs/`` already in the copy as it is.
    """
    return (
        f"from the repository root, in Git Bash: mkdir -p {call_dir} && cp"
        f" -r {committed}/prepare.json {committed}/prepared {call_dir}/"
        " ; in PowerShell: New-Item -ItemType Directory -Force -Path"
        f" {call_dir} | Out-Null; Copy-Item -Recurse -Force -Path"
        f" {committed}/prepare.json,{committed}/prepared -Destination"
        f" {call_dir}"
    )


def check_prepare(
    prepare_dir: Path,
    committed_dir: Path,
    admitted: frozenset[str],
    names: tuple[str, str],
) -> Prompts:
    """Ties the prompt copy to the admitted, committed test prompts.

    ``names`` spells the copy and the committed directory for messages.

    Raises:
        PlanError: If the copy is missing, its prepare.json is not one the
            freeze record admits, or a file differs from the committed
            copy.
    """
    call_dir, committed = names
    restore = restore_commands(call_dir, committed)
    if not (prepare_dir / "prepare.json").is_file():
        raise PlanError(
            f"{call_dir} is missing (it is ignored by git); restore it"
            f" {restore}"
        )
    data = (prepare_dir / "prepare.json").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest not in admitted:
        raise PlanError(
            f"{call_dir}/prepare.json (sha256 {digest[:12]}) is not a prompt"
            f" set the freeze record admits; restore it {restore}"
        )
    manifest = PrepareManifestV1.model_validate_json(data)
    for name in ("prepare.json", *(c.path for c in manifest.conditions)):
        if (prepare_dir / name).read_bytes() != (
            committed_dir / name
        ).read_bytes():
            raise PlanError(
                f"{call_dir}/{name} differs from {committed}; restore it"
                f" {restore}"
            )
    sizes: dict[str, tuple[int, ...]] = {}
    for condition in manifest.conditions:
        batch = PreparedBatchV1.model_validate_json(
            (prepare_dir / condition.path).read_bytes()
        )
        sizes[condition.label] = tuple(
            sum(len(m.content.encode("utf-8")) for m in prompt.messages)
            for prompt in batch.prompts
        )
    requests = sum(len(values) for values in sizes.values())
    return Prompts(digest, requests, sizes)


def _check_endpoint(row: RunRowV1, endpoint: Any, settings: SettingsV1) -> None:
    """Holds a config to its row and to the registered settings.

    Raises:
        PlanError: If the config sends another model, slug, switch or
            setting.
    """
    sent = endpoint.settings
    options = endpoint.options
    if (sent.model_id, endpoint.route, options.reasoning) != (
        row.model_id,
        row.slug,
        row.reasoning_switch,
    ):
        raise PlanError(f"{row.run_id}: {row.config} sends another route")
    recorded = SettingsV1(
        temperature=sent.temperature,
        seed=sent.seed,
        max_output_tokens=sent.max_output_tokens,
        timeout_seconds=sent.timeout_seconds,
        json_mode=sent.json_mode,
        require_parameters=options.require_parameters,
        allow_fallbacks=options.allow_fallbacks,
        data_collection=options.data_collection,
    )
    if recorded != settings:
        raise PlanError(f"{row.run_id}: {row.config} sends other settings")


def load_endpoints(
    plan: Plan, root: Path, sizes: dict[str, tuple[int, ...]]
) -> dict[str, Any]:
    """Loads and prices each registered config, keyed by its path.

    Raises:
        PlanError: If a config is missing or does not send its row's
            route and the registered settings.
    """
    endpoints: dict[str, Any] = {}
    for row in plan.rows:
        if row.config not in endpoints:
            path = root / row.config
            endpoints[row.config] = db.load_endpoint(
                path.stem, path.parent, model_run, sizes
            )
        _check_endpoint(row, endpoints[row.config], plan.registry.settings)
    return endpoints


def _print(line: str) -> None:
    print(line, flush=True)


def pause(seconds: float) -> None:
    """Waits before a resume or a re-run; the tests replace this seam."""
    time.sleep(seconds)


def utc_now() -> datetime:
    """Reads the clock pass B's window is held to; the tests replace it."""
    return datetime.now(timezone.utc)


def _now() -> str:
    return utc_now().strftime(STAMP)


def _micro(usd: float) -> int:
    return round(usd * db.MICRO)


class Layout(NamedTuple):
    """Where the batch reads the registry and prompts and writes its log."""

    root: Path
    out_dir: Path
    admitted: frozenset[str]


@dataclass
class Context:
    """Everything one execution of the batch shares."""

    layout: Layout
    plan: Plan
    prompts: Prompts
    source_revision: str
    endpoints: dict[str, Any]
    invoke: Callable[[Sequence[str], bool], Any]
    out: Callable[[str], None] = _print

    @property
    def prepare_dir(self) -> Path:
        """Returns the prompt copy every call reads and writes runs under."""
        return self.layout.root / self.plan.registry.call_prepare_dir

    def view(self, run_id: str) -> Any:
        """Reads one run's directory without changing it."""
        return db.load_run(self.prepare_dir, run_id, model_run)

    def decide(self, row: RunRowV1) -> Any:
        """Reads what one run's directory says comes next."""
        return db.decide(self.view(row.run_id), _micro(row.cap_usd))

    def read(self, row: RunRowV1) -> Any | None:
        """Reads a run's action as its directory stands; None without one."""
        view = self.view(row.run_id)
        return db.decide(view, _micro(row.cap_usd)) if view.exists else None

    def log(self, record: dict[str, Any]) -> None:
        """Appends one step record; argv and codes only, never the env."""
        path = self.layout.out_dir / STEP_LOG
        with path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(json.dumps({"at": _now(), **record}, sort_keys=True))
            log.write("\n")


def call_argv(row: RunRowV1, ctx: Context, resume: bool) -> list[str]:
    """Builds one call step's argument list; nothing here is a shell."""
    registry = ctx.plan.registry
    argv = [
        sys.executable,
        db.MODEL_RUN,
        "call",
        "--prepare-dir",
        registry.call_prepare_dir,
        "--run-id",
        row.run_id,
        "--config",
        row.config,
        "--max-usd",
        f"{row.cap_usd:.6f}",
        "--source-revision",
        ctx.source_revision,
        "--min-interval-seconds",
        f"{registry.call.min_interval_seconds}",
        "--max-attempts",
        f"{registry.call.max_attempts}",
        "--gate-first",
    ]
    if resume:
        argv.append("--resume")
    return argv


def _log_argv(argv: Sequence[str]) -> list[str]:
    return ["python", *argv[1:]]


def call_record(
    phase: str, row: RunRowV1, argv: Sequence[str], result: Any
) -> dict[str, Any]:
    """Spells one call step for the step log: argv and codes, never the env.

    A paid call also records what its report says it sent and charged.
    """
    record: dict[str, Any] = {
        "phase": phase,
        "role": row.role,
        "run_id": row.run_id,
        "config": row.config,
        "argv": _log_argv(argv),
        "exit_code": result.exit_code,
        "error_code": result.error_code,
    }
    if phase != "preflight":
        report: dict[str, Any] = result.report or {}
        for key in ("stop_reason", "requests_sent", "charged_usd_upper_bound"):
            record[key] = report.get(key)
    return record


# What the chains read.


class RowState(NamedTuple):
    """Where one registry row stands.

    ``state`` is ``done`` (complete; publish it), ``not_run`` (final, never
    to be published), ``unused`` (its condition did not occur), ``owed``
    (a call or the owner is due) or ``waiting`` (behind an owed run).
    ``action`` keeps an owed run's next step.
    """

    state: str
    reason: str | None
    action: Any = None


def _no_wait(_: RunRowV1) -> None:
    """Reads a re-run without waiting, as a summary or dry run does."""


@dataclass
class Walk:
    """One pass over the registry's chains, sending or only reading.

    ``settle`` returns a run's action once no call is due in this pass:
    the read-only one returns it as the directory stands, the sending one
    after its calls. ``read`` returns it as the directory stands, or None
    when the run has none, and never sends. ``before_rerun`` runs before
    an outage re-run.
    """

    plan: Plan
    settle: Callable[[RunRowV1], Any]
    read: Callable[[RunRowV1], Any | None]
    before_rerun: Callable[[RunRowV1], None] = _no_wait
    states: dict[str, RowState] = field(default_factory=dict[str, RowState])


def ruling(row: RunRowV1) -> RowState | None:
    """Returns the registry's own final word on a row, if any."""
    if row.status == "published":
        return RowState("done", "published")
    if row.status == "not_run":
        return RowState("not_run", f"ruled not run: {row.reason}")
    if row.status == "unused" and row.reason is not None:
        return RowState("unused", f"ruled unused: {row.reason}")
    return None


def _classify(action: Any) -> tuple[str, RowState]:
    """Reads a run's action as its chain kind and its row's state."""
    kind, reason = str(action.kind), str(action.reason)
    if kind == "fallback" and reason == GATE_STOP_REASON:
        return "gate_stop", RowState("not_run", "gate stop on its first answer")
    if kind == "fallback":
        return "refused", RowState(
            "not_run",
            f"refused ({reason}); no fallback or re-run is registered",
        )
    if kind == "reasoned":
        return "reasoned", RowState(
            "not_run", "its resumed pass stopped at the gate"
        )
    if kind in ("done", "outage"):
        state = "done" if kind == "done" else "not_run"
        return kind, RowState(state, f"{kind} ({reason})")
    return "owed", RowState("owed", f"{kind} ({reason})", action)


def _ruled_kind(row: RunRowV1, ruled: RowState, walk: Walk) -> str:
    """Reads what a ruled run triggers: its directory decides, not the ruling.

    At a stop the summary proposes a run's ``not_run`` while its fallback or
    outage re-run is still owed, and the owner commits both. So a run ruled
    ``not_run`` that left a directory triggers whatever that directory
    shows; the ruling fixes only the row's own state, and nothing is sent
    for it.
    """
    if ruled.state == "not_run":
        action = walk.read(row)
        if action is not None:
            kind = _classify(action)[0]
            if kind not in ("done", "owed"):
                return kind
    return ruled.state


def _outcome(row: RunRowV1, walk: Walk) -> tuple[str, str]:
    """Settles one run and records its row; returns its kind and why."""
    ruled = ruling(row)
    if ruled is not None:
        walk.states[row.run_id] = ruled
        return _ruled_kind(row, ruled, walk), str(ruled.reason)
    kind, state = _classify(walk.settle(row))
    walk.states[row.run_id] = state
    return kind, str(state.reason)


def _attempt(row: RunRowV1, walk: Walk) -> tuple[str, str]:
    """Settles a run and, after an outage, its one re-run."""
    kind, why = _outcome(row, walk)
    if kind != "outage":
        return kind, why
    rerun = walk.plan.rerun_of.get(row.run_id)
    if rerun is None:
        return "not_run", f"{why}; no re-run is registered"
    walk.before_rerun(rerun)
    again, again_why = _outcome(rerun, walk)
    if again == "outage":
        return "not_run", f"{why}; {rerun.run_id} met an outage too"
    if again == "unused":
        return "not_run", f"{why}; {rerun.run_id} {again_why}"
    return again, again_why


def _role(row: RunRowV1, walk: Walk) -> tuple[str, str]:
    """Settles a planned run, its re-run, then its fallback chain.

    A chain that ends at the gate keeps a kind in ``GATE_KINDS``.
    """
    kind, why = _attempt(row, walk)
    if kind != "gate_stop":
        return kind, why
    fallback = walk.plan.fallback_of.get(row.run_id)
    if fallback is None:
        return "gate_stop", f"{why}; no fallback is listed"
    again, again_why = _attempt(fallback, walk)
    if again == "gate_stop":
        return "gate_stop", f"{why}; {fallback.run_id} stopped at the gate too"
    if again == "unused":
        return "not_run", f"{why}; {fallback.run_id} {again_why}"
    return again, again_why


def _pair(walk: Walk) -> RowState:
    """Settles pass A, then pass B whatever pass A shows but the gate.

    docs/protocol.md sends pass B whatever pass A shows unless the A/A
    pair is reported not run, which rule 7 does only for a chain that
    ends at the gate. So a refused pass A, or one that met an outage on
    its re-run too, still leaves pass B due.
    """
    pass_a, pass_b = walk.plan.planned[:2]
    kind_a, why_a = _role(pass_a, walk)
    if kind_a == "owed":
        return RowState("owed", f"pass A: {why_a}")
    if kind_a in GATE_KINDS:
        reason = f"the A/A pair is reported not run: pass A {why_a}"
        walk.states[pass_b.run_id] = RowState("not_run", f"not sent; {reason}")
        return RowState("not_run", reason)
    kind_b, why_b = _role(pass_b, walk)
    if kind_b == "owed":
        return RowState("owed", f"pass B: {why_b}")
    if kind_b in GATE_KINDS:
        return RowState(
            "not_run", f"the A/A pair is reported not run: pass B {why_b}"
        )
    failed = [
        f"pass {name} {why}"
        for name, kind, why in (("A", kind_a, why_a), ("B", kind_b, why_b))
        if kind != "done"
    ]
    if failed:
        return RowState(
            "not_run", "the A/A pair is incomplete: " + "; ".join(failed)
        )
    return RowState("done", "both passes are complete")


def _closed(row: RunRowV1, walk: Walk) -> RowState:
    """States a row the chains did not reach, from the run it waits on.

    A conditional row the registry registers, or one that left a run
    directory, is never called unused: the owner rules on it.
    """
    ruled = ruling(row)
    if ruled is not None:
        return ruled
    if row.conditional_on is None or row.trigger is None:
        return RowState("waiting", "after pass A")
    named = walk.plan.row(row.conditional_on)
    state = walk.states.get(named.run_id) or _closed(named, walk)
    if state.state in OPEN_STATES:
        return RowState("waiting", f"after {named.run_id}")
    missing = TRIGGER_TEXT[row.trigger]
    if row.status == "registered" or walk.read(row) is not None:
        held = (
            "is registered"
            if row.status == "registered"
            else "left a run directory"
        )
        return RowState(
            "owed",
            f"it {held}, but {named.run_id} ended {state.state} without"
            f" {missing}; the owner rules on it",
        )
    if state.state in ("done", "unused"):
        # Its condition can no longer occur, and the guard asks a reason
        # only of a row whose named run is not run.
        return RowState("unused", None)
    return RowState(
        "unused", f"{named.run_id} ended {state.state} without {missing}"
    )


def walk_all(walk: Walk) -> dict[str, RowState]:
    """Settles the A/A pair, then each winner; states every row.

    Returns:
        The A/A pair's and each slot winner's outcome, by role.
    """
    outcomes = {"aa_pair": _pair(walk)}
    for row in walk.plan.planned[2:]:
        kind, why = _role(row, walk)
        state = kind if kind in ("done", "owed") else "not_run"
        outcomes[row.role] = RowState(state, why)
    for row in walk.plan.rows:
        if row.run_id not in walk.states:
            walk.states[row.run_id] = _closed(row, walk)
    return outcomes


def read_walk(ctx: Context) -> Walk:
    """Walks the chains from the run directories alone, sending nothing."""
    walk = Walk(ctx.plan, ctx.decide, ctx.read)
    walk_all(walk)
    return walk


def _may_send(state: RowState) -> bool:
    """Says whether a row's state may still lead to a call.

    An owed row with no call to make waits for the owner's ruling.
    """
    return state.state == "waiting" or (
        state.state == "owed" and state.action is not None
    )


def sendable(walk: Walk) -> list[RunRowV1]:
    """Lists the rows this execution may still send, in registry order."""
    return [
        row
        for row in walk.plan.rows
        if _may_send(walk.states[row.run_id]) and ruling(row) is None
    ]


# What the batch sends.


def counted_start(row: RunRowV1, ctx: Context) -> datetime | None:
    """Returns when a run's counted pass first started, whatever it showed.

    The counted pass is the run's outage re-run once that has a run
    manifest, since only an outage starts it, else the run itself; None
    when neither has one.
    """
    for each in (ctx.plan.rerun_of.get(row.run_id), row):
        if each is None:
            continue
        manifest = ctx.view(each.run_id).manifest
        if manifest is not None and manifest.invocations:
            return manifest.invocations[0].started_at
    return None


def pass_a_started(ctx: Context) -> datetime | None:
    """Returns when the counted pass A's first invocation started."""
    return counted_start(ctx.plan.planned[0], ctx)


def check_pass_b_window(ctx: Context) -> None:
    """Lets pass B start only within 24 hours of the counted pass A.

    Raises:
        BatchStop: If the window has closed, or no pass A run has a run
            manifest to time it from.
    """
    started = pass_a_started(ctx)
    if started is None:
        raise BatchStop(
            "pass B is due but no pass A run has a run manifest to time its"
            " 24 hours from; the owner rules first: record pass B's rows as"
            f" not_run with a reason in {REGISTRY} and {NOTE}, commit, and"
            " run the same command again"
        )
    deadline = started + PASS_B_WINDOW
    now = utc_now()
    if now > deadline:
        raise BatchStop(
            f"pass B has not started and the 24 hours after pass A's first"
            f" invocation ({started:{STAMP}}) ended at {deadline:{STAMP}};"
            " docs/protocol.md requires pass B to start within them, so the"
            " owner rules first: record pass B's rows as not_run with a"
            f" reason in {REGISTRY} and {NOTE}, commit, and run the same"
            " command again"
        )
    ctx.out(
        f"  pass B starts at {now:{STAMP}}, within 24 hours of pass A's"
        f" first invocation at {started:{STAMP}} (until {deadline:{STAMP}})"
    )


def drive(row: RunRowV1, ctx: Context) -> Any:
    """Makes at most one call for one run and returns its action after it.

    Raises:
        BatchAbort: If the call step found no key, or the account or a
            guardrail refused (401, 402 or 403).
        BatchStop: If the call step ended with an error envelope, or pass
            B's window has closed.
    """
    action = ctx.decide(row)
    if action.kind not in ("start", "resume"):
        return action
    if action.kind == "start" and row.role == "aa_pass_b":
        check_pass_b_window(ctx)
    argv = call_argv(row, ctx, action.kind == "resume")
    ctx.out(
        f"  {_now()} {row.run_id}: {action.kind}"
        f" (cap {row.cap_usd:.2f} USD, {action.reason})"
    )
    result = ctx.invoke(argv, True)
    ctx.log(call_record(action.kind, row, argv, result))
    report: dict[str, Any] | None = result.report
    if report is None:
        if result.error_code == "api_key_missing":
            raise BatchAbort(f"{row.run_id}: the call step found no key")
        raise BatchStop(
            f"{row.run_id}: the call step ended with an error"
            f" ({result.error_code}, exit {result.exit_code})"
        )
    view = ctx.view(row.run_id)
    ctx.out(f"  {row.run_id}: {db.run_digest(view)}")
    blocked = db.account_blocked(view)
    if report.get("stop_reason") == "fatal_http" and blocked:
        raise BatchAbort(
            f"HTTP {blocked} on {row.run_id}: fix the key, the credit or the"
            " account's guardrail, then run the same command again"
        )
    return ctx.decide(row)


def _stop_message(row: RunRowV1, action: Any) -> str:
    """Says what the owner does about a run stopped for them."""
    if action.reason == "budget":
        return (
            f"{row.run_id}: budget stop after an answer; raise its cap_usd in"
            f" {REGISTRY} and {NOTE} above the last invocation's max_usd,"
            " commit both and run the same command again"
        )
    if action.kind == "start":
        return f"{row.run_id}: the call step left no run directory"
    return (
        f"{row.run_id}: {action.reason}; read its run directory and"
        f" {OUT_DIR}/{STEP_LOG} before running the same command again"
    )


def settle(row: RunRowV1, ctx: Context) -> Any:
    """Drives one run until it needs no further call in this execution.

    Raises:
        BatchStop: If the run stopped for the owner.
        BatchAbort: If the key or the account stops the batch.
    """
    action = drive(row, ctx)
    while action.kind == "resume":
        ctx.out(
            f"  {row.run_id}: {action.reason}; resuming in"
            f" {db.RESUME_WAIT_SECONDS:.0f} s"
        )
        pause(db.RESUME_WAIT_SECONDS)
        action = drive(row, ctx)
    ctx.out(f"  {row.role} {row.run_id}: {action.kind} ({action.reason})")
    if action.kind in ("stopped", "start"):
        raise BatchStop(_stop_message(row, action))
    return action


def _wait_for_rerun(rerun: RunRowV1, ctx: Context) -> None:
    """Waits before an outage re-run this execution is about to start."""
    if ruling(rerun) is None and not ctx.view(rerun.run_id).exists:
        ctx.out(
            f"  outage: re-running once from scratch as {rerun.run_id} in"
            f" {db.RESUME_WAIT_SECONDS:.0f} s"
        )
        pause(db.RESUME_WAIT_SECONDS)


def preflight(rows: Sequence[RunRowV1], ctx: Context) -> None:
    """Makes every call this execution may send once, key withheld.

    Raises:
        PlanError: If any stops anywhere but at ``api_key_missing``.
    """
    for row in rows:
        argv = call_argv(row, ctx, ctx.view(row.run_id).exists)
        result = ctx.invoke(argv, False)
        ctx.log(call_record("preflight", row, argv, result))
        if (result.exit_code, result.error_code) != (2, "api_key_missing"):
            raise PlanError(
                f"preflight: {row.run_id} stopped at {result.error_code}"
                f" (exit {result.exit_code})"
            )
        ctx.out(f"  preflight ok: {row.run_id} -> api_key_missing")


def tooling_changes() -> list[str]:
    """Lists uncommitted changes to the registration and the tooling.

    Raises:
        subprocess.CalledProcessError: If git fails.
    """
    status = subprocess.check_output(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *TOOLING,
        ],
        cwd=ROOT,
        encoding="utf-8",
    )
    return status.splitlines()


def run_batch(ctx: Context) -> int:
    """Runs every registered pass due, after the preflight and checks.

    Raises:
        PlanError: If the preflight fails or the tooling is uncommitted.
        BatchAbort: If the key variable is absent or the account refused.
        BatchStop: If a run needs the owner.
    """
    for line in header(ctx) + cap_table(ctx):
        ctx.out(line)
    ctx.log(
        {
            "phase": "batch",
            "source_revision": ctx.source_revision,
            "registry_sha256": ctx.plan.sha256,
            "prepare_sha256": ctx.prompts.sha256,
        }
    )
    due = sendable(read_walk(ctx))
    ctx.out(f"{len(due)} runs may be sent; keyless preflight:")
    preflight(due, ctx)
    if API_KEY_ENV not in os.environ:
        raise BatchAbort(
            f"the keyless preflight passed and nothing was sent: {API_KEY_ENV}"
            " is not set in this shell; set it and run the same command"
        )
    uncommitted = tooling_changes()
    if uncommitted:
        raise PlanError(
            "commit the registration and the tooling before a paid call: "
            + "; ".join(uncommitted)
        )
    walk = Walk(
        ctx.plan,
        lambda row: settle(row, ctx),
        ctx.read,
        lambda row: _wait_for_rerun(row, ctx),
    )
    walk_all(walk)
    states = read_walk(ctx).states
    held = [
        f"{row.run_id} ({states[row.run_id].reason})"
        for row in ctx.plan.rows
        if states[row.run_id].state not in FINAL_STATES
    ]
    if held:
        raise BatchStop(
            "no run is due, but the owner rules on " + "; ".join(held)
        )
    return EXIT_OK


# What the summary says.


def _first(view: Any) -> tuple[str | None, str | None]:
    """Returns a run's first invocation's start and source revision."""
    if view.manifest is None or not view.manifest.invocations:
        return None, None
    first = view.manifest.invocations[0]
    return first.started_at.strftime(STAMP), first.source_revision


def _registry_update(
    row: RunRowV1, state: RowState, revision: str | None
) -> dict[str, Any]:
    """States the status, reason and commit the row's registry entry gets.

    A row the registry already rules on keeps what the owner committed.
    """
    if ruling(row) is not None:
        return {
            "status": row.status,
            "reason": row.reason,
            "commit": row.commit,
        }
    if state.state == "done":
        return {"status": "published", "reason": None, "commit": revision}
    if state.state in ("not_run", "unused"):
        return {"status": state.state, "reason": state.reason, "commit": None}
    if state.state == "owed":
        return {"status": "registered", "reason": None, "commit": None}
    return {"status": row.status, "reason": row.reason, "commit": row.commit}


def summary_row(
    number: int, row: RunRowV1, state: RowState, ctx: Context
) -> dict[str, Any]:
    """Describes one registry row for the maintainer's publish step."""
    view = ctx.view(row.run_id)
    run: dict[str, Any] = db.run_row(
        view, ctx.endpoints[row.config], _micro(row.cap_usd)
    )
    # The bake-off reading's action and its dev evidence directory; this
    # row's own state and target are the ones below.
    run["action"] = run.pop("state")
    run["action_reason"] = run.pop("why")
    run.pop("commit_to", None)
    started, revision = _first(view)
    commit_to = None
    if state.state == "done":
        commit_to = f"docs/results/{row.run_id}/"
    elif state.state == "not_run" and view.exists:
        commit_to = f"{EVIDENCE_DIR}/{row.run_id}/"
    return {
        "number": number,
        "role": row.role,
        "run_id": row.run_id,
        "cap_usd": row.cap_usd,
        "registry_status": row.status,
        "state": state.state,
        "reason": state.reason,
        "first_started_at": started,
        "first_source_revision": revision,
        "commit_to": commit_to,
        "registry_update": _registry_update(row, state, revision),
        "run": run,
    }


def _pass_b_window(ctx: Context) -> dict[str, Any]:
    """Records how far the counted pass B started after the counted pass A."""
    started_a = pass_a_started(ctx)
    started_b = counted_start(ctx.plan.planned[1], ctx)
    within = None
    if started_a is not None and started_b is not None:
        within = started_b - started_a <= PASS_B_WINDOW
    return {
        "pass_a_first_started_at": (
            None if started_a is None else started_a.strftime(STAMP)
        ),
        "pass_b_first_started_at": (
            None if started_b is None else started_b.strftime(STAMP)
        ),
        "within_24_hours": within,
    }


def summarize(ctx: Context) -> dict[str, Any]:
    """Reads every registry row's state from the run directories."""
    walk = Walk(ctx.plan, ctx.decide, ctx.read)
    outcomes = walk_all(walk)
    rows = [
        summary_row(number, row, walk.states[row.run_id], ctx)
        for number, row in enumerate(ctx.plan.rows, start=1)
    ]
    spend = sum(
        float(row["run"].get("charged_usd_upper_bound", 0.0)) for row in rows
    )
    return {
        "written_at": _now(),
        "source_revision": ctx.source_revision,
        "registry": REGISTRY,
        "registry_sha256": ctx.plan.sha256,
        "prepare_dir": ctx.plan.registry.call_prepare_dir,
        "prepare_sha256": ctx.prompts.sha256,
        "requests_per_pass": ctx.prompts.requests,
        "final": all(row["state"] in FINAL_STATES for row in rows),
        "outcomes": {
            role: {"state": state.state, "reason": state.reason}
            for role, state in outcomes.items()
        },
        "pass_b_window": _pass_b_window(ctx),
        "charged_usd_upper_bound_total": round(spend, 6),
        "rows": rows,
    }


def _row_line(row: dict[str, Any], total: int) -> str:
    """Spells one row of the summary on one line."""
    line = (
        f"#{row['number']} {row['role']} {row['run_id']}: {row['state']}"
        f" ({row['reason']})"
    )
    run = row["run"]
    if "completed" in run:
        served = ",".join(sorted(run["served_by"])) or "-"
        line += (
            f"; {run['completed']}/{total} completed; reasoning"
            f" {run['reasoning_state']}; served {served}; last stop"
            f" {run['stop_reasons'][-1]}; {run['charged_usd_upper_bound']:.4f}"
            " USD charged at most"
        )
    if row["commit_to"] is not None:
        line += f"; commit to {row['commit_to']}"
    update = row["registry_update"]
    return line + f"; registry: {json.dumps(update, sort_keys=True)}"


def write_summary(ctx: Context) -> tuple[Path, Path]:
    """Writes the JSON and plain-text summaries of every registry row."""
    document = summarize(ctx)
    stamp = str(document["written_at"])[:10]
    json_path = ctx.layout.out_dir / f"summary-{stamp}.json"
    json_path.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    total = int(document["requests_per_pass"])
    lines = [_row_line(row, total) for row in document["rows"]]
    lines.append("")
    for role, outcome in document["outcomes"].items():
        lines.append(f"{role}: {outcome['state']} ({outcome['reason']})")
    window = document["pass_b_window"]
    lines.append(
        f"pass B window: pass A {window['pass_a_first_started_at']}, pass B"
        f" {window['pass_b_first_started_at']}, within 24 hours"
        f" {window['within_24_hours']}"
    )
    lines.append(
        "total charged upper bound:"
        f" {document['charged_usd_upper_bound_total']:.4f} USD"
    )
    text_path = ctx.layout.out_dir / f"summary-{stamp}.txt"
    text_path.write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    return json_path, text_path


# The owner command.


def header(ctx: Context) -> list[str]:
    """States what every call of this execution answers and records."""
    return [
        f"source revision {ctx.source_revision}; registry {REGISTRY}"
        f" ({ctx.plan.sha256[:12]})",
        f"prompts {ctx.plan.registry.call_prepare_dir}: prepare.json"
        f" {ctx.prompts.sha256[:12]}, {ctx.prompts.requests} requests per pass",
    ]


def cap_table(ctx: Context) -> list[str]:
    """Shows each row's bounds against its cap."""
    lines = ["# | run id | slug | worst request | full-pass worst | cap"]
    for number, row in enumerate(ctx.plan.rows, start=1):
        endpoint = ctx.endpoints[row.config]
        lines.append(
            f"{number} | {row.run_id} | {row.slug} |"
            f" {endpoint.worst_micro_usd / db.MICRO:.6f} |"
            f" {endpoint.pass_worst_micro_usd / db.MICRO:.4f} |"
            f" {row.cap_usd:.2f}"
        )
    lines.append(
        "the call step stops a pass (budget) before a request whose worst"
        " case would pass its cap; each cap follows the note's cap rule"
    )
    return lines


def dry_run(ctx: Context) -> None:
    """Prints each row's state and every call the batch would make next."""
    for line in header(ctx) + cap_table(ctx):
        ctx.out(line)
    walk = read_walk(ctx)
    ctx.out("")
    ctx.out("preflight (key withheld; each must stop at api_key_missing):")
    for row in sendable(walk):
        argv = call_argv(row, ctx, ctx.view(row.run_id).exists)
        ctx.out("  " + " ".join(_log_argv(argv)))
    ctx.out("")
    for number, row in enumerate(ctx.plan.rows, start=1):
        state = walk.states[row.run_id]
        ctx.out(
            f"#{number} {row.role} {row.run_id}: {state.state} ({state.reason})"
        )
        action = state.action
        if action is not None and action.kind in ("start", "resume"):
            argv = call_argv(row, ctx, action.kind == "resume")
            ctx.out("    " + " ".join(_log_argv(argv)))


def default_layout() -> Layout:
    """Returns the repository's own layout and the committed admissions.

    Raises:
        ValueError: If the freeze record is unusable.
    """
    record = load_record()
    admitted = (
        frozenset[str]()
        if record is None
        else frozenset(record.admitted_prepares)
    )
    return Layout(ROOT, ROOT / OUT_DIR, admitted)


def build_context(
    layout: Layout | None = None, revision: str | None = None
) -> Context:
    """Loads and checks the registry, the prompt copy and every config.

    Raises:
        PlanError: If the registry, the prompt copy or a config is not
            usable.
        ValueError: If a file does not parse.
        OSError: If a file cannot be read.
    """
    layout = layout or default_layout()
    registry, sha256 = load_registry(layout.root / REGISTRY)
    plan = plan_from(registry, sha256)
    call_dir = registry.call_prepare_dir
    prompts = check_prepare(
        layout.root / call_dir,
        layout.root / plan.prepare,
        layout.admitted,
        (call_dir, plan.prepare),
    )
    endpoints = load_endpoints(plan, layout.root, prompts.sizes)
    wait = db.INTERRUPT_GRACE_SECONDS + max(
        endpoint.settings.timeout_seconds for endpoint in endpoints.values()
    )
    return Context(
        layout=layout,
        plan=plan,
        prompts=prompts,
        source_revision=revision or db.head_revision(),
        endpoints=endpoints,
        invoke=db.subprocess_invoker(layout.root / call_dir, _print, wait),
    )


# How each way the batch can stop is printed and exits.
ENDINGS: tuple[tuple[type[BaseException], str, int], ...] = (
    (PlanError, "REFUSED", EXIT_REFUSED),
    (subprocess.CalledProcessError, "REFUSED", EXIT_REFUSED),
    (BatchStop, "STOPPED", EXIT_STOPPED),
    (BatchAbort, "ABORTED", EXIT_ABORTED),
)


def _log_interrupt(ctx: Context, reason: str) -> None:
    """Records an interrupt in the step log; a failed write is not fatal."""
    with contextlib.suppress(OSError):
        ctx.log({"phase": "interrupted", "reason": reason})


def locked_run(ctx: Context) -> int:
    """Runs the batch under the lock and always writes the summary.

    An error the batch does not expect stops it with exit 1, never a
    refusal's 2, since requests may have been sent before it.
    """
    lock = ctx.layout.out_dir / LOCK_NAME
    keep_lock = False
    try:
        db.acquire_lock(lock)
    except db.PlanError as error:
        print(f"refused: {error}", file=sys.stderr)
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
        _log_interrupt(ctx, "call_step_still_running")
        ctx.out(
            "INTERRUPTED: the call step whose pid is printed above is still"
            " running, and its request may be billed but not recorded; let"
            f" it exit, then delete {OUT_DIR}/{LOCK_NAME} and run the same"
            " command"
        )
        code = EXIT_INTERRUPTED
    except KeyboardInterrupt:
        _log_interrupt(ctx, "ctrl_c")
        ctx.out(
            "INTERRUPTED: the request in flight may be billed but not"
            " recorded; run the same command again to resume"
        )
        code = EXIT_INTERRUPTED
    except Exception as error:  # pylint: disable=broad-exception-caught
        # Never a refusal: it may follow a paid call. After the clause
        # above, since ChildStillRunning is an Exception too.
        ctx.out(
            f"STOPPED: unexpected {type(error).__name__}: {error}; requests"
            f" may have been sent (see {OUT_DIR}/{STEP_LOG}), so fix the"
            " cause, then run the same command again"
        )
        code = EXIT_STOPPED
    finally:
        if not keep_lock:
            lock.unlink(missing_ok=True)
    try:
        json_path, text_path = write_summary(ctx)
        ctx.out(text_path.read_text(encoding="utf-8").rstrip())
        ctx.out(f"summary: {json_path.name}, {text_path.name} in {OUT_DIR}")
    except (OSError, ValueError) as error:
        ctx.out(f"the summary could not be written ({error})")
    ctx.out(f"exit {code}")
    return code


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the registered test passes and returns a process exit code."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter, description=__doc__
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="send nothing and start no call step; print the next calls",
    )
    arguments = parser.parse_args(argv)
    try:
        ctx = build_context()
    except (
        PlanError,
        db.PlanError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    if arguments.dry_run:
        dry_run(ctx)
        return EXIT_OK
    return locked_run(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
