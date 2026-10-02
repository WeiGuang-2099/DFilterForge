"""Owner batch for the registered repair arm runs.

Run from the repository root of the main checkout, in the one shell that
holds the key, once ``repair-arms`` is merged into main:

    uv run --frozen python scripts/repair_arms.py --split dev|test [--dry-run]

The protocol's Repair section and the repair note
(docs/decisions/repair-round.md) fix every row. The repaired passes are,
for dev, the four counted 2026-09-26 dev passes, and for test, the
test-run registry's ``published`` rows in a repaired role, one per slot:
pass A and each slot's winner or fallback, an outage re-run included.
Pass B is never repaired. They go anchor, 8B, 120B, then frontier, and
each pass's arms go resample, bare, then counterexample, each after the
one before has a final state, as the note orders them. A row's run id is
the pass's with ``-res``, ``-bare`` or ``-cx`` before its date. Its config
is the committed bake-off config the pass sent, checked against the
pass's run manifest. Its cap is the slot's registered cap for the split,
read from the note's caps table, which a raise never edits. A run whose
budget stop is resumed takes the cap the note's raised caps table gives
that run alone; a raise for a run with no budget stop to resume, or one
not above the slot's cap, is refused, so no other arm and no outage
re-run starts above the registered cap.

Each row's prompt set is ``artifacts/repair/<arm run id>`` (ignored by
git), where the call step also writes ``runs/<arm run id>``. Before
anything is sent, ``scripts/model_run.py follow-up --from-run
docs/results/<pass> --plan docs/results/<pass>/repair/plan.json --arm
<arm>`` builds each owed row's prompt set again, in process and in a
temporary directory: no socket, no key, no gold, the plan read as data.
- dev: a missing prompt set is that build; an existing one must equal it,
  its creation time and source revision aside, or the batch refuses.
- test: the committed seed ``docs/results/<arm run id>/prepare.json`` and
  ``prepared/`` must exist, equal that build in the same way, and have a
  ``prepare.json`` the freeze record admits. The ignored copy is that seed
  byte for byte: a missing copy is copied from it, and a copy that differs
  is refused. No seed, no test request: the test round waits for its seed
  and admission commits. While no test arm run has a seed, nothing is
  built and every missing seed is named, since the protocol prepares no
  test repair prompt before the dev round's corrections; a seed's
  admission is checked before its build.
A second turn the follow-up step cannot build (``prompt_too_large`` or
``follow_up_invalid``) refuses every arm of that pass, so its round is not
run, as the protocol says. A plan that triggers no item leaves its rows
unused. A cap below one request's worst case is refused.

Before the first paid call every owed row is called once with the key
withheld and must stop at ``api_key_missing``, which proves the run id,
cap, prompt set, admission, source digests and config pass the call
step's own checks. Paid calls start only when the key variable is present
and the tooling, the note, the plans and any test seeds are committed.
Each call is ``scripts/model_run.py call`` with ``--prepare-dir
artifacts/repair/<run> --run-id <run> --config <config> --max-usd <cap>
--source-revision <HEAD> --min-interval-seconds 1.0 --max-attempts 3
--gate-first``, an argument list started with no shell. The key is
inherited from the environment by the paid calls only; this script never
reads, prints or writes it.

What follows a call, by the bake-off runner's own reading of a run
(scripts/dev_bakeoff.py):
- Items left pending by transient failures (HTTP 5xx, 408 or 429, a
  timeout or a transport error) are resumed with the same options after
  60 s, within the same execution.
- A gate stop (the first answer reasoned) or a resumed pass that stops at
  the gate is not run, and the arm is never moved to another provider.
- An outage (no completed answer and not a refusal) is re-run once from
  scratch under the arm's ``-r2`` run id after 60 s, from its own prompt
  set (and, on test, its own seed and admission). A re-run that is an
  outage too, or a re-run id too long for a result name, is not run.
- A complete pass whose every lasting failure is HTTP 400 or 404 is a
  refusal, not run: an arm has no fallback.
- HTTP 401, 402 or 403 aborts. A budget stop after an answer stops the
  batch until that run's cap is raised in the note's raised caps table
  and committed. So does anything the batch cannot read as a run.

Every step is read back from the run directories, so running the same
command again skips finished rows and resumes unfinished ones.
``--dry-run`` makes the same checks, builds each owed prompt set in a
temporary directory only, prints each row's state and every step the
batch would take next, and sends and writes nothing. The batch
never publishes, scores or reads gold; its summary gives each row's state
and what the maintainer publishes, with each round's ``dfilterforge
repair`` arguments. The step log, the summaries and the lock are written
under artifacts/repair-arms/.

Exit codes:
    0    Every row has a final state: done, not run or unused.
    1    The batch stopped for the owner (the summary names the row and
         the reason), or an error it did not expect stopped it after a
         paid call may have been sent: read steps.jsonl, fix the cause,
         then run the same command.
    2    Refused before any request: a pass, its plan or config, the
         note's caps or raised caps, a prompt set, a test seed or its
         admission, the lock, git, uncommitted tooling or the keyless
         preflight.
    3    Aborted: the key variable is not set (after the keyless
         preflight; nothing was sent), or the account refused a request
         (HTTP 401, 402 or 403). Fix it and run the same command.
    130  Interrupted with Ctrl-C, after the in-flight request finished. An
         interrupted request may be billed but not recorded.
"""

# The rows, the prompt sets, the sending and the summary share one file so
# that the one commit every call records covers all of them, as the other
# owner batches keep theirs together.
# pylint: disable=too-many-lines
# scripts/test_passes.py and scripts/two_turn_smoke.py hold the same
# sibling loader and ending dispatch on purpose: each owner batch is a
# standalone file that loads its siblings by path, so none can share it.
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import contextlib
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import ModuleType
from typing import Any, cast, NamedTuple
from urllib.parse import urlsplit

from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.model_client import API_KEY_ENV

ROOT = Path(__file__).resolve().parents[1]


def _sibling(name: str) -> ModuleType:
    """Loads one sibling script for its public contract.

    Raises:
        RuntimeError: If the script cannot be loaded.
    """
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"repair_arms_{name}", path)
    loader = None if spec is None else spec.loader
    if spec is None or loader is None:
        raise RuntimeError(f"scripts/{name}.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


# The test-pass batch's registry reading, refusals, row states and exit
# codes; through it the bake-off runner's reading of a run, its invoker
# and lock, and the call step itself: one definition of each.
tp = _sibling("test_passes")
db = tp.db
model_run = tp.model_run
EXIT_OK: int = tp.EXIT_OK
EXIT_STOPPED: int = tp.EXIT_STOPPED
EXIT_REFUSED: int = tp.EXIT_REFUSED
EXIT_ABORTED: int = tp.EXIT_ABORTED
EXIT_INTERRUPTED: int = tp.EXIT_INTERRUPTED
PlanError: type[Exception] = tp.PlanError
BatchStop: type[Exception] = tp.BatchStop
BatchAbort: type[Exception] = tp.BatchAbort
RowState = tp.RowState

NOTE = "docs/decisions/repair-round.md"
RESULTS = "docs/results"
PREPARE_ROOT = "artifacts/repair"
OUT_DIR = "artifacts/repair-arms"
# Where a row that left a run directory but is not run keeps that run's
# manifest and attempt logs, as the bake-off and the test passes keep
# theirs.
EVIDENCE_DIR = "docs/decisions/evidence/repair-arms"
LOCK_NAME = ".lock"
STEP_LOG = "steps.jsonl"
PLAN_PATH = "repair/plan.json"
FREEZE_RECORD = "src/dfilterforge/held_out_freeze.json"
LABEL = "C4"
# The note's order: a model's arm runs go resample, bare, counterexample.
ARMS = ("resample", "bare", "counterexample")
# The tag each arm's run id carries before the pass's date, and the one
# re-run tag, as scripts/model_run.py and dfilterforge.repair_round name
# them; a test ties the three.
ARM_TAGS = {"resample": "res", "bare": "bare", "counterexample": "cx"}
RERUN_TAG = "r2"
DATE_LENGTH = 10
# The protocol repairs these counted dev passes first, as a pipeline
# check: the anchor's and each slot winner's (bake-off ruling of
# 2026-10-01), in the note's order.
DEV_PASSES = (
    "dev-qwen3-32b-2026-09-26",
    "dev-qwen3.5-9b-2026-09-26",
    "dev-qwen3.5-122b-a10b-2026-09-26",
    "dev-deepseek-v4-pro-0813-2026-09-26",
)
# The note's caps table names a slot by size class; a bake-off slot or a
# registry role maps onto it, a fallback onto its own row.
SLOT_ORDER = ("anchor", "8B", "120B", "frontier")
BAKEOFF_SLOTS = {
    "anchor": "anchor",
    "small": "8B",
    "mid": "120B",
    "frontier": "frontier",
}
ROLE_SLOTS = {
    "aa_pass_a": "anchor",
    "winner_small": "8B",
    "winner_mid": "120B",
    "winner_frontier": "frontier",
    "fallback_small": "8B fallback",
    "fallback_mid": "120B fallback",
    "fallback_frontier": "frontier fallback",
}
FALLBACK_SUFFIX = " fallback"
CAPS_HEADER = "| Slot | Config | Dev cap | Test cap |"
# The note's table of caps raised for one arm run each, after its budget
# stop; the caps table above it keeps the registered caps.
RAISED_HEADER = "| Arm run | Raised cap |"
CAP_TEXT = re.compile(r"[0-9]+\.[0-9]{2}")
SPLITS = ("dev", "test")
# The follow-up step's codes for a second turn that cannot be built, from
# an empty answer or over the 64 KiB prompt budget: it refuses every arm
# of that pass, and the protocol reports the model's round not run.
ROUND_NOT_RUN = frozenset({"prompt_too_large", "follow_up_invalid"})
PLAN_EMPTY = "plan_empty"
RUN_ID_INVALID = "run_id_invalid"
# Paths whose committed state each call's recorded HEAD must cover: this
# batch and the batches and call step it reuses, the code the call step
# digests and admits by, the configs, the registry, the note's caps and
# the protocol. Each pass's plan and each test seed are added per run.
TOOLING: tuple[str, ...] = (
    "scripts/repair_arms.py",
    "scripts/test_passes.py",
    "scripts/dev_bakeoff.py",
    "scripts/model_run.py",
    "src/dfilterforge",
    db.CONFIG_DIR,
    tp.REGISTRY,
    NOTE,
    "docs/protocol.md",
)
FINAL_STATES = frozenset({"done", "not_run", "unused"})
# How a row's run ended at the gate: its first answer reasoned, or its
# resumed pass stopped there. ``dfilterforge repair --not-run`` records
# only these as an arm not run.
GATE_KINDS = frozenset({"gate_stop", "reasoned"})
STAMP = "%Y-%m-%dT%H:%M:%SZ"

FollowUp = Callable[[Sequence[str]], tuple[dict[str, Any] | None, str | None]]
Invoker = Callable[[Sequence[str], bool], Any]


class SeedMissing(RuntimeError):
    """A test arm's run has no committed seed to answer.

    Not a refusal by itself: the batch names every missing seed at once,
    or stops for the owner when an outage re-run needs one.
    """


class RepairedPass(NamedTuple):
    """One pass a repair round continues, with its slot and config."""

    run_id: str
    slot: str
    config: str


class Cap(NamedTuple):
    """One row of the note's caps table."""

    config: str
    dev: float | None
    test: float | None


class Row(NamedTuple):
    """One arm run of one repaired pass, as the note names and caps it.

    ``cap_usd`` is the slot's registered cap for the split, which both of
    the row's runs take unless the note raises one of them.
    """

    number: int
    slot: str
    base_run: str
    arm: str
    run_id: str
    rerun_id: str
    config: str
    cap_usd: float


class Plan(NamedTuple):
    """The split and its rows, in the order they are sent.

    ``raised`` holds the cap the note raises for one run each, by run id.
    """

    split: str
    rows: tuple[Row, ...]
    wait_seconds: float
    raised: dict[str, float]


@dataclass
class PromptSets:
    """What this execution learned about each arm run's prompt set.

    ``sizes`` holds each checked prompt set's prompt bytes, ``blocked``
    the final state of a run whose prompt set follow-up refuses for a
    reason the protocol reports (a round not run, an empty plan, an
    unusable run id), ``notes`` what was done or would be done to each,
    and ``keyless`` the runs a call step has already refused without a
    key in this execution.
    """

    sizes: dict[str, tuple[int, ...]] = field(
        default_factory=dict[str, tuple[int, ...]]
    )
    blocked: dict[str, Any] = field(default_factory=dict[str, Any])
    notes: dict[str, str] = field(default_factory=dict[str, str])
    keyless: set[str] = field(default_factory=set[str])


class Reading(NamedTuple):
    """Where one row stands: the run it counts, how it ended, its state.

    ``run_id`` is the row's first run, or its re-run once an outage owes
    or gave one. ``kind`` is the chain kind of that run: ``owed``,
    ``done``, ``gate_stop``, ``reasoned``, ``refused``, ``outage`` or
    ``blocked``.
    """

    run_id: str
    kind: str
    state: Any


def _print(line: str) -> None:
    print(line, flush=True)


def pause(seconds: float) -> None:
    """Waits before a resume or a re-run; the tests replace this seam."""
    time.sleep(seconds)


def _now() -> str:
    return datetime.now(timezone.utc).strftime(STAMP)


def _micro(usd: float) -> int:
    return round(usd * db.MICRO)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arm_run_ids(base_run: str, arm: str) -> tuple[str, str]:
    """Names one arm's run and its one outage re-run after the pass."""
    stem = base_run[: -DATE_LENGTH - 1]
    date = base_run[-DATE_LENGTH:]
    tagged = f"{stem}-{ARM_TAGS[arm]}"
    return f"{tagged}-{date}", f"{tagged}-{RERUN_TAG}-{date}"


def fits(run_id: str) -> bool:
    """Says whether a run id is a result name the call step accepts."""
    return db.RESULT_DIR.fullmatch(run_id) is not None


# The rows.


def dev_passes() -> list[RepairedPass]:
    """Returns the four dev passes, each with its bake-off slot and config.

    Raises:
        PlanError: If the bake-off plan does not list a pass once.
    """
    found: list[RepairedPass] = []
    for run_id in DEV_PASSES:
        matches = [
            (candidate, target)
            for candidate in db.all_candidates()
            for target in db.registered_targets(candidate)
            if target.run_id == run_id
        ]
        if len(matches) != 1 or matches[0][0].slot not in BAKEOFF_SLOTS:
            raise PlanError(f"{run_id}: not one bake-off pass of a slot")
        candidate, target = matches[0]
        slot = BAKEOFF_SLOTS[candidate.slot]
        fallback = candidate.fallback
        if fallback is not None and target in (fallback, db.rerun_of(fallback)):
            slot += FALLBACK_SUFFIX
        found.append(
            RepairedPass(run_id, slot, f"{db.CONFIG_DIR}/{target.config}.json")
        )
    return found


def registry_passes(root: Path) -> list[RepairedPass]:
    """Returns the registry's published repaired rows, one per slot.

    Raises:
        PlanError: If the registry is unusable, a baseline row may still
            send, or two published rows repair one slot.
    """
    registry, digest = tp.load_registry(root / tp.REGISTRY)
    tp.plan_from(registry, digest)
    still = [row.run_id for row in registry.runs if row.status == "registered"]
    if still:
        raise PlanError(
            "the test round follows the last baseline request, and"
            f" {', '.join(still)} may still send; rule on it in"
            f" {tp.REGISTRY} first"
        )
    roles = registry.repair_arms.get("repaired_roles")
    if not isinstance(roles, list) or not set(cast(list[Any], roles)) <= set(
        ROLE_SLOTS
    ):
        raise PlanError(f"{tp.REGISTRY}: repair_arms names no usable roles")
    by_slot: dict[str, RepairedPass] = {}
    for row in registry.runs:
        if row.status != "published" or row.role not in roles:
            continue
        slot = ROLE_SLOTS[row.role]
        key = slot.removesuffix(FALLBACK_SUFFIX)
        if key in by_slot:
            raise PlanError(
                f"{by_slot[key].run_id} and {row.run_id} both repair the"
                f" {key} slot"
            )
        by_slot[key] = RepairedPass(row.run_id, slot, row.config)
    return [by_slot[slot] for slot in SLOT_ORDER if slot in by_slot]


def _usd(cell: str, slot: str) -> float | None:
    """Reads one cap cell of the note's caps table; empty is no cap.

    Raises:
        PlanError: If the cell is not a dollar amount with two decimals.
    """
    if not cell:
        return None
    if CAP_TEXT.fullmatch(cell) is None:
        raise PlanError(f"{NOTE}: the {slot} cap {cell!r} is not a USD amount")
    return float(cell)


def _table(text: str, heading: str, name: str) -> list[tuple[str, list[str]]]:
    """Returns the rows of the note's one table under a heading, with cells.

    Raises:
        PlanError: If the note holds no such table, or more than one.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(heading)]
    if len(starts) != 1:
        raise PlanError(f"{NOTE}: no single {name} table ({heading})")
    rows: list[tuple[str, list[str]]] = []
    for line in lines[starts[0] + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append((line, cells))
    return rows


def load_caps(text: str) -> dict[str, Cap]:
    """Reads the note's caps table: each slot's config, dev and test cap.

    These are the registered caps; a raise is a row of the raised caps
    table instead.

    Raises:
        PlanError: If the table is missing or a row is malformed.
    """
    caps: dict[str, Cap] = {}
    for line, cells in _table(text, CAPS_HEADER, "caps"):
        if len(cells) < 4 or cells[0] in caps:
            raise PlanError(f"{NOTE}: unusable caps row {line!r}")
        slot, config = cells[0], cells[1].strip("`")
        caps[slot] = Cap(config, _usd(cells[2], slot), _usd(cells[3], slot))
    return caps


def load_raised(text: str) -> dict[str, float]:
    """Reads the note's raised caps table: one arm run's cap per row.

    Raises:
        PlanError: If the table is missing, or a row is malformed or names
            a run twice.
    """
    raised: dict[str, float] = {}
    for line, cells in _table(text, RAISED_HEADER, "raised caps"):
        run_id = cells[0].strip("`") if cells else ""
        if (
            len(cells) != 2
            or cells[0] != f"`{run_id}`"
            or run_id in raised
            or CAP_TEXT.fullmatch(cells[1]) is None
        ):
            raise PlanError(f"{NOTE}: unusable raised caps row {line!r}")
        raised[run_id] = float(cells[1])
    return raised


def raised_caps(
    rows: Sequence[Row], raised: dict[str, float], split: str
) -> dict[str, float]:
    """Keeps the split's raised caps, each one run's and above its slot's.

    A raise of the other split's run is that split's to check.

    Raises:
        PlanError: If a raise names no arm run of either split or of this
            split's rows, or is not above its slot's registered cap and
            within the call step's bound.
    """
    runs = {
        run_id: row for row in rows for run_id in (row.run_id, row.rerun_id)
    }
    kept: dict[str, float] = {}
    for run_id, usd in raised.items():
        named = run_id.split("-", 1)[0]
        if named in SPLITS and named != split:
            continue
        row = runs.get(run_id)
        if row is None:
            raise PlanError(
                f"{NOTE}: the raised cap of {run_id} names no {split} arm run"
            )
        if not row.cap_usd < usd <= db.MAX_USD:
            raise PlanError(
                f"{NOTE}: the raised cap of {run_id}, {usd:.2f} USD, is not"
                f" above the {row.slot} {split} cap {row.cap_usd:.2f} USD"
            )
        kept[run_id] = usd
    return kept


def rows_for(
    passes: Sequence[RepairedPass], caps: dict[str, Cap], split: str
) -> tuple[Row, ...]:
    """Names, configures and caps each pass's three arm runs, in order.

    Raises:
        PlanError: If the note gives a pass's slot no cap for the split,
            or its caps row names another config, or an arm run id is
            not a result name.
    """
    rows: list[Row] = []
    for repaired in passes:
        cap = caps.get(repaired.slot)
        config = Path(repaired.config).stem
        if cap is None or cap.config != config:
            raise PlanError(
                f"{repaired.run_id}: {NOTE} lists no {repaired.slot} cap"
                f" for {config}"
            )
        usd = cap.dev if split == "dev" else cap.test
        if usd is None or not 0 < usd <= db.MAX_USD:
            raise PlanError(
                f"{repaired.run_id}: {NOTE} gives the {repaired.slot} slot"
                f" no usable {split} cap"
            )
        for arm in ARMS:
            first, rerun = arm_run_ids(repaired.run_id, arm)
            if not fits(first):
                raise PlanError(f"{first}: not a result name")
            rows.append(
                Row(
                    len(rows) + 1,
                    repaired.slot,
                    repaired.run_id,
                    arm,
                    first,
                    rerun,
                    repaired.config,
                    usd,
                )
            )
    return tuple(rows)


def check_pass(root: Path, repaired: RepairedPass) -> Any:
    """Requires a pass's committed plan and the config it sent.

    Returns:
        The config, as the call step reads it.

    Raises:
        PlanError: If the plan is missing, the pass is not complete, or
            the config is not the committed one the pass sent with the
            registered call options.
    """
    base = root / RESULTS / repaired.run_id
    if not (base / PLAN_PATH).is_file():
        raise PlanError(
            f"{repaired.run_id}: no committed {PLAN_PATH}; the plan is"
            " committed before any repair request"
        )
    manifest = RunManifestV1.model_validate_json(
        (base / "run_manifest.json").read_bytes()
    )
    if manifest.run_id != repaired.run_id or manifest.status != "complete":
        raise PlanError(f"{repaired.run_id}: not a complete published pass")
    if Path(repaired.config).parent.as_posix() != db.CONFIG_DIR:
        raise PlanError(f"{repaired.config}: not a committed bake-off config")
    config = model_run.CallConfigV1.model_validate_json(
        (root / repaired.config).read_bytes()
    )
    host = urlsplit(str(config.endpoint_url)).hostname
    if (config.settings, config.prices, host) != (
        manifest.settings,
        manifest.prices,
        manifest.endpoint_host,
    ):
        raise PlanError(
            f"{repaired.config}: not the config {repaired.run_id} sent"
        )
    if (manifest.max_attempts, manifest.min_interval_seconds) != (
        db.MAX_ATTEMPTS,
        db.MIN_INTERVAL_SECONDS,
    ):
        raise PlanError(
            f"{repaired.run_id}: not sent with the registered call options"
        )
    return config


# The run directories.


@dataclass
class Context:
    """Everything one execution of the batch shares."""

    layout: Any
    plan: Plan
    source_revision: str
    invoke: Invoker
    follow_up: FollowUp
    out: Callable[[str], None] = _print
    prompts: PromptSets = field(default_factory=PromptSets)

    @property
    def root(self) -> Path:
        """Returns the repository root every path is spelled from."""
        return cast(Path, self.layout.root)

    def prepare_dir(self, run_id: str) -> Path:
        """Returns one arm run's prompt set, where its run is written."""
        return self.root / PREPARE_ROOT / run_id

    def cap_usd(self, row: Row, run_id: str) -> float:
        """Returns one run's cap: its own raised cap, else the slot's."""
        return self.plan.raised.get(run_id, row.cap_usd)

    def view(self, run_id: str) -> Any:
        """Reads one arm run's directory without changing it."""
        return db.load_run(self.prepare_dir(run_id), run_id, model_run)

    def log(self, record: dict[str, Any]) -> None:
        """Appends one step record; argv and codes only, never the env."""
        out_dir = cast(Path, self.layout.out_dir)
        with (out_dir / STEP_LOG).open(
            "a", encoding="utf-8", newline="\n"
        ) as log:
            log.write(json.dumps({"at": _now(), **record}, sort_keys=True))
            log.write("\n")


def classify(action: Any) -> tuple[str, Any]:
    """Reads a run's action as its chain kind and its row's state."""
    kind, reason = str(action.kind), str(action.reason)
    if kind == "fallback" and reason == tp.GATE_STOP_REASON:
        return "gate_stop", RowState(
            "not_run",
            "stopped at the gate on its first answer; never moved to"
            " another provider",
        )
    if kind == "fallback":
        return "refused", RowState(
            "not_run", f"refused ({reason}); an arm has no fallback"
        )
    if kind == "reasoned":
        return "reasoned", RowState(
            "not_run", "its resumed pass stopped at the gate"
        )
    if kind == "done":
        return "done", RowState("done", "complete")
    if kind == "outage":
        return "outage", RowState("not_run", f"outage ({reason})")
    return "owed", RowState("owed", f"{kind} ({reason})", action)


def read_run(row: Row, run_id: str, ctx: Context) -> Reading:
    """Reads one of a row's runs as its directory stands."""
    view = ctx.view(run_id)
    blocked = ctx.prompts.blocked.get(run_id)
    if not view.exists and blocked is not None:
        return Reading(run_id, "blocked", blocked)
    kind, state = classify(db.decide(view, _micro(ctx.cap_usd(row, run_id))))
    return Reading(run_id, kind, state)


def read_row(row: Row, ctx: Context) -> Reading:
    """Reads a row: its first run, then its re-run after an outage."""
    first = read_run(row, row.run_id, ctx)
    if first.kind != "outage":
        return first
    why = first.state.reason
    if not fits(row.rerun_id):
        return Reading(
            row.run_id,
            "outage",
            RowState(
                "not_run",
                f"{why}; its re-run id {row.rerun_id} is not a result name,"
                " so it cannot be re-run",
            ),
        )
    again = read_run(row, row.rerun_id, ctx)
    if again.kind == "outage":
        return Reading(
            row.rerun_id,
            "outage",
            RowState(
                "not_run", f"{why}; its re-run {row.rerun_id} met an outage too"
            ),
        )
    if again.kind == "owed" and not ctx.view(row.rerun_id).exists:
        state = RowState(
            "owed",
            f"{row.run_id} met an {why}; its re-run is due",
            again.state.action,
        )
        return Reading(row.rerun_id, "owed", state)
    return again


def calls_due(ctx: Context) -> list[tuple[Row, str, Any]]:
    """Lists each row whose counted run owes a call, with that call's kind."""
    due: list[tuple[Row, str, Any]] = []
    for row in ctx.plan.rows:
        reading = read_row(row, ctx)
        action = reading.state.action
        if action is not None and action.kind in ("start", "resume"):
            due.append((row, reading.run_id, action))
    return due


# The prompt sets.


def run_follow_up(
    argv: Sequence[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Runs ``scripts/model_run.py follow-up`` in process, offline.

    Returns:
        The report it printed, or None and the code it refused with.
    """
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = int(model_run.main(list(argv)))
    if code != 0:
        return None, db.parse_output("", stderr.getvalue())[1] or "refused"
    lines = stdout.getvalue().strip().splitlines()
    try:
        report: object = json.loads(lines[-1]) if lines else None
    except ValueError:
        report = None
    if not isinstance(report, dict):
        return None, "report_unreadable"
    return cast(dict[str, Any], report), None


def follow_up_argv(
    base_dir: str, arm: str, output_dir: str, revision: str
) -> list[str]:
    """Builds one follow-up step's arguments; nothing here is a shell."""
    return [
        "follow-up",
        "--from-run",
        base_dir,
        "--plan",
        f"{base_dir}/{PLAN_PATH}",
        "--arm",
        arm,
        "--output-dir",
        output_dir,
        "--source-revision",
        revision,
    ]


def follow_up_line(row: Row, run_id: str, ctx: Context) -> str:
    """Spells the follow-up command that builds a run's prompt set."""
    argv = follow_up_argv(
        f"{RESULTS}/{row.base_run}",
        row.arm,
        f"{PREPARE_ROOT}/{run_id}",
        ctx.source_revision,
    )
    return " ".join(["python", db.MODEL_RUN, *argv])


def differences(built: Path, existing: Path) -> list[str]:
    """Names the files of a prompt set that differ from a fresh build.

    The creation time and the source revision a prepare records are the
    only fields allowed to differ; every prompt file must be equal byte
    for byte.
    """
    try:
        new = PrepareManifestV1.model_validate_json(
            (built / "prepare.json").read_bytes()
        )
        old = PrepareManifestV1.model_validate_json(
            (existing / "prepare.json").read_bytes()
        )
    except (OSError, ValueError):
        return ["prepare.json"]
    kept = {"created_at", "source_revision"}
    names: list[str] = []
    if new.model_dump(exclude=kept) != old.model_dump(exclude=kept):
        names.append("prepare.json")
    for condition in new.conditions:
        path = existing / condition.path
        if (
            not path.is_file()
            or path.read_bytes() != (built / condition.path).read_bytes()
        ):
            names.append(condition.path)
    return names


def read_prompts(prepare_dir: Path, name: str) -> Any:
    """Reads a prompt set's digest and sizes as the test-pass batch does."""
    digest = _sha256(prepare_dir / "prepare.json")
    return tp.check_prepare(
        prepare_dir, prepare_dir, frozenset({digest}), (name, name)
    )


def install(source: Path, target: Path) -> None:
    """Copies a prompt set into place whole, or not at all."""
    staging = target.parent / f".{target.name}.install"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        shutil.copy2(source / "prepare.json", staging / "prepare.json")
        shutil.copytree(source / "prepared", staging / "prepared")
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def admitted_seed(run_id: str, ctx: Context) -> Path | None:
    """Returns a test arm's committed seed once the record admits it.

    It is read before anything is built, so a seed the record does not
    admit is refused without preparing a test repair prompt.

    Returns:
        The seed's directory, or None when no seed is committed.

    Raises:
        PlanError: If the record does not admit it.
    """
    seed = ctx.root / RESULTS / run_id
    if not (seed / "prepare.json").is_file():
        return None
    digest = _sha256(seed / "prepare.json")
    if digest not in ctx.layout.admitted:
        raise PlanError(
            f"{RESULTS}/{run_id}/prepare.json (sha256 {digest[:12]}) is not"
            " admitted; append its digest to admitted_prepares in"
            f" {FREEZE_RECORD} in a commit of its own, then run the same"
            " command"
        )
    return seed


def seeding_begun(ctx: Context) -> bool:
    """Says whether any test arm run of the plan has a committed seed.

    The protocol prepares no test repair prompt before the dev round's
    corrections, and the seeding step is the first to prepare one.
    """
    return any(
        (ctx.root / RESULTS / run_id / "prepare.json").is_file()
        for row in ctx.plan.rows
        for run_id in (row.run_id, row.rerun_id)
    )


def check_seed(row: Row, run_id: str, built: Path, seed: Path) -> None:
    """Requires a test arm's admitted seed to equal a fresh build.

    Raises:
        PlanError: If it differs from what follow-up builds now.
    """
    changed = differences(built, seed)
    if changed:
        raise PlanError(
            f"{RESULTS}/{run_id}: {', '.join(changed)} differ from what"
            f" follow-up builds now from {RESULTS}/{row.base_run} and its plan"
        )


def _blocked(code: str | None, row: Row, run_id: str) -> Any | None:
    """Returns the final state a follow-up refusal gives, if the protocol
    reports one; None for a refusal that stops the batch."""
    if code in ROUND_NOT_RUN:
        return RowState(
            "not_run",
            f"the round is not run: a second turn of {row.base_run} cannot"
            f" be built ({code}), so no arm of it is sent",
        )
    if code == PLAN_EMPTY:
        return RowState(
            "unused", f"the plan of {row.base_run} triggers no item"
        )
    if code == RUN_ID_INVALID:
        return RowState("not_run", f"{run_id} is not a usable result name")
    return None


def build_now(
    row: Row, run_id: str, ctx: Context, scratch: Path
) -> Path | None:
    """Builds a run's prompt set in ``scratch`` as follow-up builds it now.

    Returns:
        The built directory, or None when follow-up refuses for a reason
        the protocol reports; that run's final state is then recorded.

    Raises:
        PlanError: If follow-up refuses for any other reason.
    """
    built = scratch / run_id
    report, code = ctx.follow_up(
        follow_up_argv(
            (ctx.root / RESULTS / row.base_run).as_posix(),
            row.arm,
            built.as_posix(),
            ctx.source_revision,
        )
    )
    if report is not None:
        return built
    blocked = _blocked(code, row, run_id)
    if blocked is None:
        raise PlanError(
            f"{run_id}: follow-up refused ({code}): run"
            f" {follow_up_line(row, run_id, ctx)} to read why"
        )
    ctx.prompts.blocked[run_id] = blocked
    return None


def place(
    row: Row, run_id: str, source: Path, ctx: Context, write: bool
) -> Path:
    """Ties the prompt set a run answers to the one it should answer.

    ``source`` is a fresh build for a dev run, and for a test run its
    committed, admitted seed, already found equal to a fresh build. A
    missing prompt set is a copy of it. With ``write`` false nothing is
    put in place and a missing prompt set is only reported.

    Returns:
        The directory whose prompts the run answers, or would answer.

    Raises:
        PlanError: If a prompt set or copy is not what it should be.
    """
    target = ctx.prepare_dir(run_id)
    spelled = f"{PREPARE_ROOT}/{run_id}"
    notes = ctx.prompts.notes
    seeded = ctx.plan.split == "test"
    if target.exists() and not (target / "prepare.json").is_file():
        raise PlanError(f"{spelled} exists but holds no prepare.json")
    if not target.exists():
        if not write:
            notes[run_id] = (
                "would copy the committed seed" if seeded else "would build"
            )
            return source
        install(source, target)
        notes[run_id] = "copied from the committed seed" if seeded else "built"
    elif seeded:
        # The copy is the admitted seed byte for byte.
        tp.check_prepare(
            target,
            source,
            ctx.layout.admitted,
            (spelled, f"{RESULTS}/{run_id}"),
        )
        notes[run_id] = "the committed seed, byte for byte"
    else:
        changed = differences(source, target)
        if changed:
            raise PlanError(
                f"{spelled}: {', '.join(changed)} differ from what follow-up"
                f" builds now from {RESULTS}/{row.base_run} and its plan;"
                " delete it if it holds no runs/ and run the same command,"
                " else the owner rules on the run in it"
            )
        notes[run_id] = "equal to what follow-up builds now"
    return target


def check_prompts(row: Row, run_id: str, ctx: Context, write: bool) -> None:
    """Builds a run's prompt set now and ties the one it answers to it.

    A test run's seed is read and its admission checked first. A missing
    seed is still built, so that a follow-up refusal the protocol reports
    gives the run its final state; the caller builds one only once the
    seeding has begun.

    Raises:
        SeedMissing: If a test run has no committed seed.
        PlanError: If a test seed is not admitted, follow-up refuses, or
            a prompt set, seed or copy differs from what it should be.
    """
    seeded = ctx.plan.split == "test"
    seed = admitted_seed(run_id, ctx) if seeded else None
    with TemporaryDirectory(prefix="repair-arms-") as scratch:
        built = build_now(row, run_id, ctx, Path(scratch))
        if built is None:
            return
        source = built
        if seeded:
            if seed is None:
                raise SeedMissing(f"{RESULTS}/{run_id}")
            check_seed(row, run_id, built, seed)
            source = seed
        answered = place(row, run_id, source, ctx, write)
        spelled = f"{PREPARE_ROOT}/{run_id}"
        ctx.prompts.sizes[run_id] = read_prompts(answered, spelled).sizes[LABEL]


def endpoint(row: Row, sizes: tuple[int, ...], ctx: Context) -> Any:
    """Prices a row's config against its prompt set's prompts."""
    path = ctx.root / row.config
    return db.load_endpoint(path.stem, path.parent, model_run, {LABEL: sizes})


def check_raise(run_id: str, ctx: Context) -> None:
    """Requires a raised cap to resume its own run's budget stop.

    The protocol resumes a budget stop only under a raised cap, so a
    raise never starts a run, nor sends one that no budget stopped.

    Raises:
        PlanError: If the note raises the run's cap but the run has no
            invocation that stopped at its budget.
    """
    usd = ctx.plan.raised.get(run_id)
    if usd is None:
        return
    manifest = ctx.view(run_id).manifest
    invocations = () if manifest is None else manifest.invocations
    if not any(spent.stop_reason == "budget" for spent in invocations):
        raise PlanError(
            f"{run_id}: {NOTE} raises its cap to {usd:.2f} USD, but it has"
            " no budget stop to resume, and a raised cap only resumes one;"
            " delete that row of the raised caps table, commit it and run"
            " the same command"
        )


def prepare_all(ctx: Context, write: bool) -> None:
    """Checks the prompt set and any raised cap of every run that owes a call.

    On the test split nothing is built until some test arm run has a
    committed seed: before that, every owed run's seed is named at once.

    Raises:
        PlanError: If a prompt set or seed cannot be used, a raised cap
            has no budget stop to resume, or a cap is below one request's
            worst case; every test run without a seed is named at once.
    """
    owed: list[tuple[Row, str]] = []
    for row in ctx.plan.rows:
        reading = read_row(row, ctx)
        action = reading.state.action
        if action is not None and action.kind in ("start", "resume"):
            owed.append((row, reading.run_id))
    if ctx.plan.split == "test" and owed and not seeding_begun(ctx):
        # No test repair prompt is prepared before the seeding step.
        raise PlanError(
            _seeds_first([f"{RESULTS}/{run_id}" for _, run_id in owed])
        )
    missing: list[str] = []
    for row, run_id in owed:
        check_raise(run_id, ctx)
        try:
            check_prompts(row, run_id, ctx, write)
        except SeedMissing as error:
            missing.append(str(error))
            continue
        sizes = ctx.prompts.sizes.get(run_id)
        if sizes is None:
            continue
        worst = endpoint(row, sizes, ctx).worst_micro_usd
        cap = ctx.cap_usd(row, run_id)
        if worst > _micro(cap):
            raise PlanError(
                f"{run_id}: one request may cost"
                f" {worst / db.MICRO:.6f} USD, over its {row.slot}"
                f" {ctx.plan.split} cap {cap:.2f}; the protocol registers"
                " that cap, so the owner rules on it before any request"
            )
    if missing:
        raise PlanError(_seeds_first(missing))


def _seeds_first(missing: Sequence[str]) -> str:
    """Says which test seeds the round waits for, and how to commit them."""
    return (
        "the test round needs its seed and admission commits first: no"
        f" committed seed in {', '.join(missing)}. Seed each with"
        " scripts/model_run.py follow-up --output-dir"
        f" {RESULTS}/<arm run id> and commit it, then append each"
        f" prepare.json digest to admitted_prepares in {FREEZE_RECORD}"
        " in a commit of its own"
    )


# What the batch sends.


def call_argv(row: Row, run_id: str, ctx: Context, resume: bool) -> list[str]:
    """Builds one call step's argument list; nothing here is a shell."""
    argv = [
        sys.executable,
        db.MODEL_RUN,
        "call",
        "--prepare-dir",
        f"{PREPARE_ROOT}/{run_id}",
        "--run-id",
        run_id,
        "--config",
        row.config,
        "--max-usd",
        f"{ctx.cap_usd(row, run_id):.6f}",
        "--source-revision",
        ctx.source_revision,
        "--min-interval-seconds",
        f"{db.MIN_INTERVAL_SECONDS}",
        "--max-attempts",
        f"{db.MAX_ATTEMPTS}",
        "--gate-first",
    ]
    if resume:
        argv.append("--resume")
    return argv


def _log_argv(argv: Sequence[str]) -> list[str]:
    return ["python", *argv[1:]]


def call_record(
    phase: str, row: Row, run_id: str, argv: Sequence[str], result: Any
) -> dict[str, Any]:
    """Spells one call step for the step log: argv and codes, never the env.

    A paid call also records what its report says it sent and charged.
    """
    record: dict[str, Any] = {
        "phase": phase,
        "base_run": row.base_run,
        "arm": row.arm,
        "run_id": run_id,
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


def keyless(row: Row, run_id: str, ctx: Context) -> None:
    """Makes one call with the key withheld, which must find no key.

    Raises:
        PlanError: If it stops anywhere but at ``api_key_missing``.
    """
    argv = call_argv(row, run_id, ctx, ctx.view(run_id).exists)
    result = ctx.invoke(argv, False)
    ctx.log(call_record("preflight", row, run_id, argv, result))
    if (result.exit_code, result.error_code) != (2, "api_key_missing"):
        raise PlanError(
            f"preflight: {run_id} stopped at {result.error_code}"
            f" (exit {result.exit_code})"
        )
    ctx.prompts.keyless.add(run_id)
    ctx.out(f"  preflight ok: {run_id} -> api_key_missing")


def drive(row: Row, run_id: str, ctx: Context) -> Any:
    """Makes at most one call for one run and returns its action after it.

    Raises:
        BatchAbort: If the call step found no key, or the account or a
            guardrail refused (401, 402 or 403).
        BatchStop: If the call step ended with an error envelope.
    """
    usd = ctx.cap_usd(row, run_id)
    cap = _micro(usd)
    action = db.decide(ctx.view(run_id), cap)
    if action.kind not in ("start", "resume"):
        return action
    argv = call_argv(row, run_id, ctx, action.kind == "resume")
    ctx.out(
        f"  {_now()} {run_id}: {action.kind}"
        f" (cap {usd:.2f} USD, {action.reason})"
    )
    result = ctx.invoke(argv, True)
    ctx.log(call_record(action.kind, row, run_id, argv, result))
    report: dict[str, Any] | None = result.report
    if report is None:
        if result.error_code == "api_key_missing":
            raise BatchAbort(f"{run_id}: the call step found no key")
        raise BatchStop(
            f"{run_id}: the call step ended with an error"
            f" ({result.error_code}, exit {result.exit_code})"
        )
    view = ctx.view(run_id)
    ctx.out(f"  {run_id}: {db.run_digest(view)}")
    blocked = db.account_blocked(view)
    if report.get("stop_reason") == "fatal_http" and blocked:
        raise BatchAbort(
            f"HTTP {blocked} on {run_id}: fix the key, the credit or the"
            " account's guardrail, then run the same command again"
        )
    return db.decide(view, cap)


def _stop_message(run_id: str, action: Any, cap_usd: float) -> str:
    """Says what the owner does about a run stopped for them."""
    if action.reason == "budget":
        return (
            f"{run_id}: budget stop after an answer at its cap"
            f" {cap_usd:.2f} USD; raise this run's cap alone, in a row"
            f" `{run_id}` of {NOTE}'s raised caps table above the last"
            " invocation's max_usd, commit it and run the same command again"
        )
    if action.kind == "start":
        return f"{run_id}: the call step left no run directory"
    return (
        f"{run_id}: {action.reason}; read its run directory and"
        f" {OUT_DIR}/{STEP_LOG} before running the same command again"
    )


def settle(row: Row, run_id: str, ctx: Context) -> Any:
    """Drives one run until it needs no further call in this execution.

    Raises:
        BatchStop: If the run stopped for the owner.
        BatchAbort: If the key or the account stops the batch.
    """
    action = drive(row, run_id, ctx)
    while action.kind == "resume":
        ctx.out(
            f"  {run_id}: {action.reason}; resuming in"
            f" {db.RESUME_WAIT_SECONDS:.0f} s"
        )
        pause(db.RESUME_WAIT_SECONDS)
        action = drive(row, run_id, ctx)
    if action.kind in ("stopped", "start"):
        raise BatchStop(_stop_message(run_id, action, ctx.cap_usd(row, run_id)))
    return action


def _ready_rerun(row: Row, ctx: Context) -> bool:
    """Prepares an outage re-run that has not started; False if blocked.

    Raises:
        BatchStop: If its prompt set or seed cannot be used, or its
            keyless call stops anywhere but at ``api_key_missing``.
    """
    rerun = row.rerun_id
    ctx.out(
        f"  outage: re-running {row.run_id} once from scratch as {rerun} in"
        f" {db.RESUME_WAIT_SECONDS:.0f} s"
    )
    pause(db.RESUME_WAIT_SECONDS)
    try:
        check_raise(rerun, ctx)
        if rerun not in ctx.prompts.sizes:
            check_prompts(row, rerun, ctx, True)
        if rerun in ctx.prompts.blocked:
            return False
        if rerun not in ctx.prompts.keyless:
            keyless(row, rerun, ctx)
    except (tp.PlanError, SeedMissing) as error:
        detail = (
            f"no committed seed in {error}; seed and admit it, then"
            if isinstance(error, SeedMissing)
            else f"{error};"
        )
        raise BatchStop(
            f"{rerun} owes the re-run of {row.run_id}'s outage, but"
            f" {detail} run the same command again"
        ) from None
    return True


def settle_row(row: Row, ctx: Context) -> Reading:
    """Settles a row's first run and, after an outage, its one re-run.

    Raises:
        BatchStop: If a run stopped for the owner.
        BatchAbort: If the key or the account stops the batch.
    """
    first = read_run(row, row.run_id, ctx)
    if first.kind == "owed":
        settle(row, row.run_id, ctx)
    if read_run(row, row.run_id, ctx).kind == "outage" and fits(row.rerun_id):
        again = read_run(row, row.rerun_id, ctx)
        if again.kind == "owed":
            started = ctx.view(row.rerun_id).exists
            if started or _ready_rerun(row, ctx):
                settle(row, row.rerun_id, ctx)
    reading = read_row(row, ctx)
    ctx.out(
        f"  {row.arm} {reading.run_id}: {reading.state.state}"
        f" ({reading.state.reason})"
    )
    return reading


def uncommitted(paths: Sequence[str]) -> list[str]:
    """Lists uncommitted changes under the given repository paths.

    Raises:
        subprocess.CalledProcessError: If git fails.
    """
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
        cwd=ROOT,
        encoding="utf-8",
    )
    return status.splitlines()


def tooling(ctx: Context) -> list[str]:
    """Lists the paths every paid call's recorded HEAD must cover."""
    paths = list(TOOLING)
    bases = dict.fromkeys(row.base_run for row in ctx.plan.rows)
    paths.extend(f"{RESULTS}/{base}/{PLAN_PATH}" for base in bases)
    if ctx.plan.split == "test":
        for row in ctx.plan.rows:
            for run_id in (row.run_id, row.rerun_id):
                paths.append(f"{RESULTS}/{run_id}/prepare.json")
                paths.append(f"{RESULTS}/{run_id}/prepared")
    return paths


def tooling_changes(ctx: Context) -> list[str]:
    """Lists uncommitted changes to the tooling, plans and seeds."""
    return uncommitted(tooling(ctx))


def run_batch(ctx: Context) -> int:
    """Sends every arm run due, after the prompt sets and the preflight.

    Raises:
        PlanError: If a prompt set, the preflight or the tooling refuses.
        BatchAbort: If the key variable is absent or the account refused.
        BatchStop: If a run needs the owner.
    """
    prepare_all(ctx, True)
    for line in header(ctx) + cap_table(ctx):
        ctx.out(line)
    ctx.log(
        {
            "phase": "batch",
            "split": ctx.plan.split,
            "source_revision": ctx.source_revision,
            "prompts": dict(ctx.prompts.notes),
        }
    )
    due = calls_due(ctx)
    ctx.out(f"{len(due)} arm runs may be sent; keyless preflight:")
    for row, run_id, _ in due:
        keyless(row, run_id, ctx)
    if API_KEY_ENV not in os.environ:
        raise BatchAbort(
            f"the keyless preflight passed and nothing was sent: {API_KEY_ENV}"
            " is not set in this shell; set it and run the same command"
        )
    changes = tooling_changes(ctx)
    if changes:
        raise PlanError(
            "commit the tooling, the note, the plans and any test seeds"
            " before a paid call: " + "; ".join(changes)
        )
    for row in ctx.plan.rows:
        settle_row(row, ctx)
    held = [
        f"{reading.run_id} ({reading.state.reason})"
        for reading in (read_row(row, ctx) for row in ctx.plan.rows)
        if reading.state.state not in FINAL_STATES
    ]
    if held:
        raise BatchStop(
            "no arm run is due, but the owner rules on " + "; ".join(held)
        )
    return EXIT_OK


# What the summary says.


def _sizes_of(run_id: str, ctx: Context) -> tuple[int, ...] | None:
    """Returns a prompt set's sizes, read now if this execution did not."""
    known = ctx.prompts.sizes.get(run_id)
    if known is not None:
        return known
    prepare_dir = ctx.prepare_dir(run_id)
    try:
        return read_prompts(prepare_dir, run_id).sizes[LABEL]
    except (OSError, ValueError, tp.PlanError):
        return None


def publish_step(row: Row, reading: Reading, ctx: Context) -> dict[str, Any]:
    """States what the maintainer does with a row's run.

    A run the row counts after an outage replaces the first run, whose
    manifest and attempt logs are kept as evidence all the same.
    """
    run_id = reading.run_id
    step: dict[str, Any] = {}
    if reading.state.state == "done":
        step = {
            "commit_to": f"{RESULTS}/{run_id}/",
            "publish": (
                f"python {db.MODEL_RUN} publish --run-dir"
                f" {PREPARE_ROOT}/{run_id}/runs/{run_id} --output"
                f" {RESULTS}/{run_id}"
            ),
        }
    elif reading.state.state == "not_run" and ctx.view(run_id).exists:
        step = {
            "commit_to": f"{EVIDENCE_DIR}/{run_id}/",
            "repair_not_run": row.arm if reading.kind in GATE_KINDS else None,
        }
    if run_id == row.rerun_id and ctx.view(row.run_id).exists:
        step["first_run_evidence"] = f"{EVIDENCE_DIR}/{row.run_id}/"
    return step


def summary_row(row: Row, reading: Reading, ctx: Context) -> dict[str, Any]:
    """Describes one row for the maintainer's publish step."""
    view = ctx.view(reading.run_id)
    sizes = _sizes_of(reading.run_id, ctx)
    cap = ctx.cap_usd(row, reading.run_id)
    run: dict[str, Any] = {"run_id": reading.run_id, "exists": view.exists}
    if sizes is not None:
        run = db.run_row(view, endpoint(row, sizes, ctx), _micro(cap))
        run["action"] = run.pop("state")
        run["action_reason"] = run.pop("why")
        run.pop("commit_to", None)
    return {
        "number": row.number,
        "slot": row.slot,
        "base_run": row.base_run,
        "arm": row.arm,
        "run_id": row.run_id,
        "counted_run_id": reading.run_id,
        "config": row.config,
        "cap_usd": cap,
        "registered_cap_usd": row.cap_usd,
        "items": None if sizes is None else len(sizes),
        "state": reading.state.state,
        "reason": reading.state.reason,
        "kind": reading.kind,
        "maintainer": publish_step(row, reading, ctx),
        "run": run,
    }


def round_line(base: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """States what one pass's round needs next, from its rows."""
    states = [row["state"] for row in rows]
    if any(state not in FINAL_STATES for state in states):
        return {"base_run": base, "final": False, "next": "arm runs owed"}
    done = [row["counted_run_id"] for row in rows if row["state"] == "done"]
    gated = [
        row["arm"]
        for row in rows
        if row["state"] == "not_run" and row["kind"] in GATE_KINDS
    ]
    other = [
        row["arm"]
        for row in rows
        if row["state"] == "not_run" and row["kind"] not in GATE_KINDS
    ]
    if not done:
        reasons = sorted({str(row["reason"]) for row in rows})
        return {
            "base_run": base,
            "final": True,
            "next": f"no arm run to publish ({'; '.join(reasons)})",
        }
    args = [
        "repair",
        "--run-dir",
        f"/workspace/results/{base}",
        "--code-revision",
        "REV",
    ]
    for arm in gated:
        args += ["--not-run", arm]
    text = f"publish and score {', '.join(done)}, then {' '.join(args)}"
    if other:
        text += (
            f"; repair records only gate stops as not run, so the owner"
            f" rules on {', '.join(other)} first"
        )
    return {"base_run": base, "final": True, "next": text, "repair": args}


def summarize(ctx: Context) -> dict[str, Any]:
    """Reads every row's state from the run directories."""
    rows = [summary_row(row, read_row(row, ctx), ctx) for row in ctx.plan.rows]
    bases = dict.fromkeys(row.base_run for row in ctx.plan.rows)
    spend = sum(
        float(row["run"].get("charged_usd_upper_bound", 0.0)) for row in rows
    )
    return {
        "written_at": _now(),
        "split": ctx.plan.split,
        "source_revision": ctx.source_revision,
        "note": NOTE,
        "final": all(row["state"] in FINAL_STATES for row in rows),
        "charged_usd_upper_bound_total": round(spend, 6),
        "rounds": [
            round_line(base, [row for row in rows if row["base_run"] == base])
            for base in bases
        ],
        "rows": rows,
    }


def _row_line(row: dict[str, Any]) -> str:
    """Spells one row of the summary on one line."""
    line = (
        f"#{row['number']} {row['slot']} {row['arm']} {row['counted_run_id']}:"
        f" {row['state']} ({row['reason']})"
    )
    run = row["run"]
    if "completed" in run:
        served = ",".join(sorted(run["served_by"])) or "-"
        line += (
            f"; {run['completed']}/{row['items']} completed; reasoning"
            f" {run['reasoning_state']}; served {served}; last stop"
            f" {run['stop_reasons'][-1]}; {run['charged_usd_upper_bound']:.4f}"
            " USD charged at most"
        )
    maintainer = row["maintainer"]
    if "publish" in maintainer:
        line += f"; publish: {maintainer['publish']}"
    elif "commit_to" in maintainer:
        line += f"; commit its evidence to {maintainer['commit_to']}"
    if "first_run_evidence" in maintainer:
        line += (
            "; commit its first run's evidence to"
            f" {maintainer['first_run_evidence']}"
        )
    return line


def write_summary(ctx: Context) -> tuple[Path, Path]:
    """Writes the JSON and plain-text summaries of every row."""
    document = summarize(ctx)
    stamp = str(document["written_at"])[:10]
    out_dir = cast(Path, ctx.layout.out_dir)
    name = f"summary-{ctx.plan.split}-{stamp}"
    json_path = out_dir / f"{name}.json"
    json_path.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    lines = [_row_line(row) for row in document["rows"]]
    lines.append("")
    for line in document["rounds"]:
        lines.append(f"{line['base_run']}: {line['next']}")
    lines.append(
        "total charged upper bound:"
        f" {document['charged_usd_upper_bound_total']:.4f} USD"
    )
    text_path = out_dir / f"{name}.txt"
    text_path.write_text(
        "\n".join(lines) + "\n", encoding="utf-8", newline="\n"
    )
    return json_path, text_path


# The owner command.


def header(ctx: Context) -> list[str]:
    """States what every call of this execution answers and records."""
    bases = dict.fromkeys(row.base_run for row in ctx.plan.rows)
    return [
        f"split {ctx.plan.split}; source revision {ctx.source_revision};"
        f" {len(ctx.plan.rows)} arm runs of {len(bases)} passes; caps from"
        f" {NOTE}",
    ]


def cap_table(ctx: Context) -> list[str]:
    """Shows each owed run's bounds against its cap."""
    lines = [
        "# | arm run id | config | items | worst request | full-arm worst | cap"
    ]
    for row in ctx.plan.rows:
        reading = read_row(row, ctx)
        sizes = ctx.prompts.sizes.get(reading.run_id)
        if sizes is None:
            bounds = "- | - | -"
        else:
            priced = endpoint(row, sizes, ctx)
            bounds = (
                f"{len(sizes)} | {priced.worst_micro_usd / db.MICRO:.6f} |"
                f" {priced.pass_worst_micro_usd / db.MICRO:.4f}"
            )
        cap = ctx.cap_usd(row, reading.run_id)
        raised = " raised" if cap != row.cap_usd else ""
        lines.append(
            f"{row.number} | {reading.run_id} | {Path(row.config).stem} |"
            f" {bounds} | {cap:.2f}{raised}"
        )
    lines.append(
        "the call step stops an arm run (budget) before a request whose worst"
        " case would pass its cap; full-arm worst is one attempt per item"
    )
    return lines


def dry_run(ctx: Context) -> None:
    """Prints each row's state and every step the batch would take next."""
    for line in header(ctx) + cap_table(ctx):
        ctx.out(line)
    ctx.out("")
    ctx.out("prompt sets (offline, no key; nothing is written by a dry run):")
    for run_id, note in ctx.prompts.notes.items():
        ctx.out(f"  {PREPARE_ROOT}/{run_id}: {note}")
    for row in ctx.plan.rows:
        for run_id in (row.run_id, row.rerun_id):
            if ctx.prompts.notes.get(run_id) == "would build":
                ctx.out(f"    {follow_up_line(row, run_id, ctx)}")
    ctx.out("")
    ctx.out("preflight (key withheld; each must stop at api_key_missing):")
    due = calls_due(ctx)
    for row, run_id, action in due:
        argv = call_argv(row, run_id, ctx, action.kind == "resume")
        ctx.out("  " + " ".join(_log_argv(argv)))
    ctx.out("")
    for row in ctx.plan.rows:
        reading = read_row(row, ctx)
        ctx.out(
            f"#{row.number} {row.slot} {row.arm} {reading.run_id}:"
            f" {reading.state.state} ({reading.state.reason})"
        )


def default_layout() -> Any:
    """Returns the repository's layout and the committed admissions.

    Raises:
        ValueError: If the freeze record is unusable.
    """
    return tp.default_layout()._replace(out_dir=ROOT / OUT_DIR)


def build_context(
    split: str, layout: Any = None, revision: str | None = None
) -> Context:
    """Reads the passes, their plans and configs, and the note's caps.

    Raises:
        PlanError: If a pass, plan, config, cap or raised cap is not usable.
        ValueError: If a file does not parse.
        OSError: If a file cannot be read.
    """
    layout = layout or default_layout()
    root = cast(Path, layout.root)
    passes = dev_passes() if split == "dev" else registry_passes(root)
    if not passes:
        raise PlanError(f"no {split} pass is repaired")
    note = (root / NOTE).read_text(encoding="utf-8")
    caps = load_caps(note)
    configs = [check_pass(root, repaired) for repaired in passes]
    wait = db.INTERRUPT_GRACE_SECONDS + max(
        config.settings.timeout_seconds for config in configs
    )
    rows = rows_for(passes, caps, split)
    plan = Plan(split, rows, wait, raised_caps(rows, load_raised(note), split))
    return Context(
        layout=layout,
        plan=plan,
        source_revision=revision or db.head_revision(),
        invoke=subprocess_invoke(root, _print, wait),
        follow_up=run_follow_up,
    )


def subprocess_invoke(
    root: Path, out: Callable[[str], None], wait_seconds: float
) -> Invoker:
    """Returns the bake-off runner's invoker for each call's prompt set."""

    def invoke(argv: Sequence[str], with_key: bool) -> Any:
        prepare_dir = root / argv[list(argv).index("--prepare-dir") + 1]
        run = db.subprocess_invoker(prepare_dir, out, wait_seconds)
        return run(argv, with_key)

    return invoke


def _log_interrupt(ctx: Context, reason: str) -> None:
    """Records an interrupt in the step log; a failed write is not fatal."""
    with contextlib.suppress(OSError):
        ctx.log({"phase": "interrupted", "reason": reason})


def locked_run(ctx: Context) -> int:
    """Runs the batch under the lock and always writes the summary.

    An error the batch does not expect stops it with exit 1, never a
    refusal's 2, since requests may have been sent before it.
    """
    lock = cast(Path, ctx.layout.out_dir) / LOCK_NAME
    keep_lock = False
    try:
        db.acquire_lock(lock)
    except db.PlanError as error:
        print(f"refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        code = run_batch(ctx)
    except (
        tp.PlanError,
        subprocess.CalledProcessError,
        tp.BatchStop,
        tp.BatchAbort,
    ) as error:
        label, code = next(
            (label, code)
            for kind, label, code in tp.ENDINGS
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
    """Runs one split's repair arm runs and returns a process exit code."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter, description=__doc__
    )
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="send nothing, write nothing; print each row and next step",
    )
    arguments = parser.parse_args(argv)
    try:
        ctx = build_context(arguments.split)
        if arguments.dry_run:
            prepare_all(ctx, False)
    except (
        tp.PlanError,
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
