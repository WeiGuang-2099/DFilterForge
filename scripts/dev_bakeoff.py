"""Owner batch for the pre-registered dev bake-off.

Run from the repository root, in the one shell that holds the key, once
docs/protocol.md, the bake-off note, the tooling, the configs and the
endpoint snapshot are committed:

    uv run --frozen python scripts/dev_bakeoff.py [--only SLOT] [--dry-run]

The anchor runs first, then each slot's ranked candidates in order, one
run at a time, each through ``scripts/model_run.py call`` started as an
argument list with no shell. A pass is one call invocation at the
candidate's cap with ``--gate-first``, ``--max-attempts 3`` and
``--min-interval-seconds 1.0``. Items it leaves pending after a transient
failure (HTTP 5xx, 408 or 429, a timeout or a transport error) are sent
again by ``--resume`` with the same options after a 60 s wait, within the
same execution, until every item is settled; an item still not completed
after 3 attempts counts against the 152. The key is inherited from the
environment by the paid calls only; this script never reads, prints or
writes it.

A candidate gets exactly one fallback pass, on its listed fallback, when
its pass's first completed answer reasoned, whatever stop was recorded,
or when the pass ended with no completed answer, at least one HTTP 400 or
404, and every attempt that was not transient a 400 or 404. A pass that
earns the fallback is never resumed; a later answer that reasons is a
drop. A pass that ended with no completed answer only through transient
failures is an outage and stops the batch: the owner re-runs it once from
scratch under its ``-r2`` run id (``--rerun RUN_ID``) or rules the
candidate not measured (``--not-measured RUN_ID``), and a re-run that
ends the same way is not measured too. A budget stop is resumed only
once the candidate's cap below was raised above the last invocation's
``max_usd`` and committed. HTTP 401, 402 or 403 aborts. Anything else
stops the batch and is never a model failure: a pass with no completed
answer for another reason, the invocation limit, a call step that ended
with an error, or a run directory it cannot read. ``--only`` runs the
other slots meanwhile.

The anchor must pass the run gates: a stop that can still be resumed or
ruled on prints STOPPED, a final failure prints ANCHOR FAILED, and the
owner's decision about the A/A pair then goes into the bake-off note
before any test request. A reserve runs only as ``--only reserve-<slot>``
once every ranked candidate of its slot has a verdict and none passes the
run gates, or with ``--after-smoke-failures`` once every run-gate
survivor failed its two-turn smoke. Rulings and flags belong to the
command, so running the same command again repeats them; the step log
and the summary record them.

Every decision is recomputed from the run directories, so running the
script again skips finished runs and resumes unfinished ones. Before the
first paid call every configuration is called once with the key withheld
and must stop at ``api_key_missing``, which proves that the run id, cap,
prompt set, source digests and configuration pass the call step's own
checks while no request is possible. Paid calls start only when the key
variable is present and the tooling is committed, so the HEAD each call
records covers it. This script never publishes or scores; it only names
each run's ``commit_to`` target.

The step log, summary and lock file are written under artifacts/bakeoff/.

Exit codes:
    0    Every selected candidate has a verdict: it passes the run gates,
         it dropped under the rule, or it is not measured.
    1    The batch stopped for the owner (see above; the summary names
         the run and the reason), or ANCHOR FAILED.
    2    Refused before any request: a configuration, the prompt set, the
         lock, git, uncommitted tooling, a ruling or reserve the run
         directories do not allow, or the keyless preflight.
    3    Aborted: the key variable is not set, or the account refused a
         request (HTTP 401, 402 or 403). Fix it and run the same command.
    130  Interrupted with Ctrl-C, after the in-flight request finished. An
         interrupted request may be billed but not recorded, so the
         charged upper bound can miss one request per interrupt.
"""

# The plan, the decisions and the report share one file so that the one
# commit every call records covers all of them; the plan table alone is
# 130 lines. Splitting it would add a loader for a second sibling script.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import ModuleType
from typing import Any, cast, NamedTuple

from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import OpenRouterOptionsV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import thinking_state
from dfilterforge.completions import TokenPricesV1
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.model_client import API_KEY_ENV

ROOT = Path(__file__).resolve().parents[1]
MODEL_RUN = "scripts/model_run.py"
PREPARE_DIR = "artifacts/model-eval/dev-qwen3-32b-2026-09-26"
COMMITTED_PREPARE_DIR = "docs/results/dev-qwen3-32b-2026-09-26"
PREPARE_SHA256_PREFIX = "c7cfabf91dd1"
CONFIG_DIR = "docs/decisions/evidence/bakeoff/configs"
EVIDENCE_DIR = "docs/decisions/evidence/bakeoff"
OUT_DIR = "artifacts/bakeoff"
LOCK_NAME = ".lock"
# Paths whose committed state each call's recorded HEAD must cover: the
# pre-registration, the tooling, and the unhashed thinking rule every
# verdict reads (model_run.py leaves completions.py out of its digests).
TOOLING = (
    "scripts/dev_bakeoff.py",
    "scripts/dev_bakeoff_configs.py",
    CONFIG_DIR,
    f"{EVIDENCE_DIR}/endpoints.json",
    "docs/protocol.md",
    "docs/decisions/model-bakeoff.md",
    "src/dfilterforge/completions.py",
)
RUN_DATE = "2026-09-26"
RERUN_TAG = "r2"
LABELS = ("C1", "C2", "C3", "C4")
TOTAL_ITEMS = 160
MIN_COMPLETED = 152
MAX_ATTEMPTS = 3
MIN_INTERVAL_SECONDS = 1.0
MAX_OUTPUT_TOKENS = 2048
MAX_USD = 12.0
# The run manifest cannot record more than 32 invocations.
MAX_RUN_INVOCATIONS = 30
PROGRESS_SECONDS = 60.0
RESUME_WAIT_SECONDS = 60.0
INTERRUPT_GRACE_SECONDS = 30.0
MICRO = 1_000_000
TOKEN_BOUND_SLACK = 64
# Output tokens per answer by condition, rounded up from the qwen3-32b dev
# run of 2026-09-23 (96, 95, 220 and 186); used only for the spend estimate.
EST_OUTPUT_TOKENS = {"C1": 100, "C2": 100, "C3": 250, "C4": 200}
EST_TOKENS_PER_BYTE = 0.25
RESULT_DIR = re.compile(
    r"(dev|test)-[a-z0-9][a-z0-9.-]{0,31}-[0-9]{4}-[0-9]{2}-[0-9]{2}"
)
SOURCE_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}")
# The call step's own classes (scripts/model_run.py): a refused account or
# guardrail ends an invocation, and a transient failure is sent again by
# a resume while the item has attempts left.
ACCOUNT_STATUSES = frozenset({401, 402, 403})
TRANSIENT_STATUSES = frozenset({408, 429})
TRANSIENT_CODES = frozenset({"timeout", "transport_error"})
# A routing or parameter refusal: the only failures that earn a fallback,
# and only when every attempt that was not transient was one.
REFUSAL_STATUSES = frozenset({400, 404})
FINAL_KINDS = frozenset({"fallback", "reasoned", "done", "not_measured"})
QUALIFYING_KEYS = (
    "role",
    "run_id",
    "config",
    "model_id",
    "slug",
    "reasoning_switch",
)
DEFAULT_SLOTS = ("anchor", "small", "mid", "frontier")
RANKED_SLOTS = ("small", "mid", "frontier")
EXIT_OK = 0
EXIT_STOPPED = 1
EXIT_REFUSED = 2
EXIT_ABORTED = 3
EXIT_INTERRUPTED = 130


@dataclass(frozen=True)
class Target:
    """One configuration and the run id it answers under."""

    config: str
    run_id: str


@dataclass(frozen=True)
class Candidate:
    """One model in one slot, with its listed fallback and run cap."""

    slot: str
    rank: str
    name: str
    primary: Target
    fallback: Target | None
    cap_usd: float


def run_id(middle: str) -> str:
    """Names a bake-off run after the frozen dev prompts' date."""
    return f"dev-{middle}-{RUN_DATE}"


def rerun_of(target: Target) -> Target:
    """Names the one from-scratch re-run of a pass that met an outage."""
    middle = target.run_id.removeprefix("dev-").removesuffix(f"-{RUN_DATE}")
    return Target(target.config, run_id(f"{middle}-{RERUN_TAG}"))


def _candidate(
    slot: str,
    rank: str,
    name: str,
    configs: tuple[str, str | None],
    cap_usd: float,
) -> Candidate:
    fallback = None
    if configs[1] is not None:
        fallback = Target(configs[1], run_id(f"{name}-fb"))
    return Candidate(
        slot, rank, name, Target(configs[0], run_id(name)), fallback, cap_usd
    )


PLAN: dict[str, tuple[Candidate, ...]] = {
    "anchor": (
        _candidate(
            "anchor",
            "A",
            "qwen3-32b",
            ("qwen3-32b_deepinfra_enabled-false", None),
            0.10,
        ),
    ),
    "small": (
        _candidate(
            "small",
            "1",
            "qwen3.5-9b",
            (
                "qwen3.5-9b_deepinfra_enabled-false",
                "qwen3.5-9b_parasail_enabled-false",
            ),
            0.10,
        ),
        _candidate(
            "small",
            "2",
            "ministral-8b-2512",
            ("ministral-8b-2512_mistral_none", None),
            0.10,
        ),
        _candidate(
            "small",
            "3",
            "granite-4.2-8b",
            (
                "granite-4.2-8b_deepinfra_enabled-false",
                "granite-4.2-8b_coreweave_enabled-false",
            ),
            0.10,
        ),
    ),
    "mid": (
        _candidate(
            "mid",
            "1",
            "qwen3.5-122b-a10b",
            (
                "qwen3.5-122b-a10b_novita_enabled-false",
                "qwen3.5-122b-a10b_atlas-cloud_enabled-false",
            ),
            0.40,
        ),
        _candidate(
            "mid",
            "2",
            "mistral-medium-3-5",
            (
                "mistral-medium-3-5_mistral_effort-none",
                "mistral-medium-3-5_mistral_enabled-false",
            ),
            1.10,
        ),
        _candidate(
            "mid",
            "3",
            "nemotron-3-super-120b-a12b",
            (
                "nemotron-3-super-120b-a12b_deepinfra_enabled-false",
                "nemotron-3-super-120b-a12b_dekallm_enabled-false",
            ),
            0.10,
        ),
    ),
    "frontier": (
        _candidate(
            "frontier",
            "1",
            "deepseek-v4-pro-0813",
            (
                "deepseek-v4-pro-0813_deepinfra_enabled-false",
                "deepseek-v4-pro-0813_nextbit_enabled-false",
            ),
            0.70,
        ),
        _candidate(
            "frontier",
            "2",
            "glm-5.2",
            (
                "glm-5.2_alibaba-fp8_enabled-false",
                "glm-5.2_novita_enabled-false",
            ),
            0.60,
        ),
        _candidate(
            "frontier",
            "3",
            "kimi-k2.6",
            (
                "kimi-k2.6_parasail_enabled-false",
                "kimi-k2.6_inceptron_enabled-false",
            ),
            0.60,
        ),
    ),
    "reserve-small": (
        _candidate(
            "reserve-small",
            "R",
            "llama-3.1-8b-instruct",
            ("llama-3.1-8b-instruct_deepinfra_none", None),
            0.40,
        ),
    ),
    "reserve-mid": (
        _candidate(
            "reserve-mid",
            "R",
            "qwen3-next-80b-a3b-instruct",
            ("qwen3-next-80b-a3b-instruct_alibaba_none", None),
            0.40,
        ),
    ),
    "reserve-frontier": (
        _candidate(
            "reserve-frontier",
            "R",
            "kimi-k2-0905",
            ("kimi-k2-0905_novita_none", None),
            0.40,
        ),
    ),
}
ANCHOR = PLAN["anchor"][0]


class PlanError(RuntimeError):
    """Refused before any request: the plan cannot be run as it stands."""


class BatchStop(RuntimeError):
    """The owner has to resume or fix something before the batch goes on."""


class BatchAbort(RuntimeError):
    """The key or the account stops every candidate alike."""


class ChildStillRunning(RuntimeError):
    """A call step outlived the wait after an interrupt."""


@dataclass(frozen=True)
class Endpoint:
    """What one configuration sends and what one request may cost."""

    name: str
    config_path: str
    settings: RequestSettingsV1
    prices: TokenPricesV1
    worst_micro_usd: int
    pass_worst_micro_usd: int
    estimate_micro_usd: int

    @property
    def options(self) -> OpenRouterOptionsV1:
        """Returns the OpenRouter options, which every planned config sets."""
        return cast(OpenRouterOptionsV1, self.settings.openrouter)

    @property
    def route(self) -> str:
        """Returns the one provider slug the request pins."""
        return self.options.provider_order[0]


def load_model_run() -> ModuleType:
    """Loads scripts/model_run.py for its public call contract.

    Raises:
        PlanError: If the script cannot be loaded.
    """
    spec = importlib.util.spec_from_file_location(
        "bakeoff_model_run", ROOT / MODEL_RUN
    )
    if spec is None or spec.loader is None:
        raise PlanError("scripts/model_run.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_prepare(prepare_dir: Path, committed_dir: Path, prefix: str) -> None:
    """Ties the prompt set the calls answer to the committed dev prompts.

    Raises:
        PlanError: If prepare.json has another digest, or it or a prompt
            file differs from the committed copy.
    """
    names = ["prepare.json", *(f"prepared/{label}.json" for label in LABELS)]
    if not _sha256(prepare_dir / "prepare.json").startswith(prefix):
        raise PlanError(f"prepare.json does not hash to {prefix}")
    for name in names:
        if _sha256(prepare_dir / name) != _sha256(committed_dir / name):
            raise PlanError(f"{name} differs from the committed dev prompts")


def prompt_bytes(prepare_dir: Path) -> dict[str, tuple[int, ...]]:
    """Returns every prepared prompt's UTF-8 message bytes, by condition.

    Raises:
        PlanError: If the prompt set is not 160 prompts.
    """
    sizes: dict[str, tuple[int, ...]] = {}
    for label in LABELS:
        batch = PreparedBatchV1.model_validate_json(
            (prepare_dir / "prepared" / f"{label}.json").read_bytes()
        )
        sizes[label] = tuple(
            sum(len(m.content.encode("utf-8")) for m in prompt.messages)
            for prompt in batch.prompts
        )
    if sum(len(values) for values in sizes.values()) != TOTAL_ITEMS:
        raise PlanError("the prepared dev set is not 160 prompts")
    return sizes


def worst_case_micro_usd(size: int, usd_in: float, usd_out: float) -> int:
    """Mirrors the call step's pre-request bound for one prompt."""
    return math.ceil(
        (size + TOKEN_BOUND_SLACK) * usd_in + MAX_OUTPUT_TOKENS * usd_out
    )


def load_endpoint(
    name: str,
    config_dir: Path,
    model_run: ModuleType,
    sizes: dict[str, tuple[int, ...]],
) -> Endpoint:
    """Validates one configuration file and prices it against the prompts.

    Raises:
        PlanError: If the file is missing or sends no OpenRouter options.
    """
    path = config_dir / f"{name}.json"
    if not path.is_file():
        raise PlanError(f"config {name} is missing")
    config = model_run.CallConfigV1.model_validate_json(path.read_bytes())
    options = config.settings.openrouter
    if options is None or len(options.provider_order) != 1:
        raise PlanError(f"config {name} does not pin one OpenRouter slug")
    usd_in = config.prices.usd_per_million_input
    usd_out = config.prices.usd_per_million_output
    worst = [
        worst_case_micro_usd(size, usd_in, usd_out)
        for values in sizes.values()
        for size in values
    ]
    estimate = sum(
        (size + TOKEN_BOUND_SLACK) * EST_TOKENS_PER_BYTE * usd_in
        + EST_OUTPUT_TOKENS[label] * usd_out
        for label, values in sizes.items()
        for size in values
    )
    return Endpoint(
        name=name,
        config_path=_relative(path),
        settings=config.settings,
        prices=config.prices,
        worst_micro_usd=max(worst),
        pass_worst_micro_usd=sum(worst),
        estimate_micro_usd=math.ceil(estimate),
    )


def _relative(path: Path) -> str:
    """Spells a path from the repository root when it lies inside it."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def targets(candidate: Candidate) -> tuple[Target, ...]:
    """Returns the candidate's runs: its pass, then its fallback if any."""
    if candidate.fallback is None:
        return (candidate.primary,)
    return (candidate.primary, candidate.fallback)


def registered_targets(candidate: Candidate) -> tuple[Target, ...]:
    """Returns every run id the candidate may use, outage re-runs included."""
    planned = targets(candidate)
    return (*planned, *(rerun_of(target) for target in planned))


def all_candidates() -> list[Candidate]:
    """Lists every planned candidate, anchor first."""
    return [candidate for slot in PLAN.values() for candidate in slot]


def _micro(usd: float) -> int:
    return round(usd * MICRO)


def headroom_micro_usd(endpoint: Endpoint, cap_micro_usd: int) -> int:
    """Returns what a cap leaves over twice the estimate and one request."""
    estimate = endpoint.estimate_micro_usd
    return cap_micro_usd - 2 * estimate - endpoint.worst_micro_usd


def check_plan(
    candidates: Sequence[Candidate], endpoints: dict[str, Endpoint]
) -> None:
    """Refuses a plan the call step would refuse or could not afford.

    Raises:
        PlanError: If a run id, an outage re-run's included, is unusable,
            repeated or not named after the prompts' date, or a cap is
            outside the call step's bound or below twice the estimated
            pass plus one worst-case request.
    """
    seen: set[str] = set()
    for candidate in candidates:
        cap = _micro(candidate.cap_usd)
        if not 0 < candidate.cap_usd <= MAX_USD:
            raise PlanError(f"{candidate.name}: cap outside the CLI bound")
        for target in registered_targets(candidate):
            if RESULT_DIR.fullmatch(target.run_id) is None:
                raise PlanError(f"{target.run_id}: not a result name")
            if not target.run_id.endswith(f"-{RUN_DATE}"):
                raise PlanError(f"{target.run_id}: not the prepare's date")
            if target.run_id in seen:
                raise PlanError(f"{target.run_id}: used twice")
            seen.add(target.run_id)
            if headroom_micro_usd(endpoints[target.config], cap) < 0:
                raise PlanError(f"{target.config}: the cap is too tight")


@dataclass(frozen=True)
class RunView:
    """What one run directory holds, read without changing it."""

    run_id: str
    exists: bool
    problem: str | None = None
    manifest: RunManifestV1 | None = None
    attempts: tuple[Any, ...] = ()


class _Unreadable(Exception):
    """A run directory the call step itself could not resume."""


def _read_run(
    run_dir: Path, run: str, model_run: ModuleType
) -> tuple[RunManifestV1, tuple[Any, ...]]:
    """Reads one run's manifest and attempts, or names what is wrong.

    Raises:
        _Unreadable: With the problem as its message.
    """
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise _Unreadable("manifest_missing")
    try:
        manifest = RunManifestV1.model_validate_json(manifest_path.read_bytes())
    except ValueError:
        raise _Unreadable("manifest_invalid") from None
    if manifest.run_id != run:
        raise _Unreadable("manifest_run_id")
    attempts: list[Any] = []
    for condition in manifest.conditions:
        log = run_dir / condition.attempts_path
        data = log.read_bytes() if log.is_file() else b""
        if data and not data.endswith(b"\n"):
            raise _Unreadable("attempt_log_torn")
        try:
            attempts.extend(
                model_run.AttemptV1.model_validate_json(line)
                for line in data.split(b"\n")
                if line
            )
        except ValueError:
            raise _Unreadable("attempt_log_invalid") from None
    return manifest, tuple(attempts)


def load_run(prepare_dir: Path, run: str, model_run: ModuleType) -> RunView:
    """Reads one run's manifest and every attempt it logged.

    A directory that the call step itself could not resume is reported
    with a ``problem`` rather than guessed at.
    """
    run_dir = prepare_dir / "runs" / run
    if not run_dir.exists():
        return RunView(run, exists=False)
    try:
        manifest, attempts = _read_run(run_dir, run, model_run)
    except _Unreadable as problem:
        return RunView(run, exists=True, problem=str(problem))
    return RunView(run, True, None, manifest, attempts)


def completed_answers(view: RunView) -> list[CompletionV1]:
    """Returns the run's completed answers, oldest first."""
    ordered = sorted(view.attempts, key=lambda attempt: attempt.sent_at)
    return [
        attempt.completion
        for attempt in ordered
        if attempt.completion.status is CompletionStatusV1.COMPLETED
    ]


class Action(NamedTuple):
    """The state of one run and what follows from it.

    ``kind`` is ``start`` or ``resume`` (a call to make), ``done`` (the
    pass is complete), ``fallback`` (the listed fallback takes over, or
    the candidate drops if it has none or this was the fallback),
    ``reasoned`` (a later answer reasoned; the candidate drops),
    ``outage`` (no completed answer and not a refusal; the owner rules on
    a re-run), ``not_measured`` (after an outage), or
    ``stopped`` (the owner has to look).
    """

    kind: str
    reason: str


def attempt_kind(completion: CompletionV1) -> str:
    """Classifies one attempt by the call step's own retry rule.

    Returns:
        ``answer`` for a completed answer, ``account`` for a refused
        account or guardrail, ``transient`` for a failure a resume sends
        again, and ``final`` for any other failure.
    """
    if completion.status is CompletionStatusV1.COMPLETED:
        return "answer"
    status = completion.http_status
    if status in ACCOUNT_STATUSES:
        return "account"
    if completion.error_code in TRANSIENT_CODES:
        return "transient"
    if status is not None and (status in TRANSIENT_STATUSES or status >= 500):
        return "transient"
    return "final"


def _unfinished(
    manifest: RunManifestV1, answered: bool, cap_micro_usd: int
) -> Action:
    """Reads an incomplete run: resumable, an outage, or stopped.

    Timeouts and transport errors are charged their worst case, so an
    endpoint that hangs ends at the cap before any answer arrives; that
    budget stop is an outage. Any other budget stop is resumable only
    under a cap above the one the last invocation ran with, which the
    owner raised and committed.
    """
    last = manifest.invocations[-1]
    if not answered and last.stop_reason == "budget":
        return Action("outage", "no_answer_budget_spent_on_failures")
    if len(manifest.invocations) >= MAX_RUN_INVOCATIONS:
        return Action("stopped", "invocation_limit")
    pending = sum(condition.pending for condition in manifest.conditions)
    if last.stop_reason == "budget":
        if cap_micro_usd > _micro(last.max_usd):
            return Action("resume", f"{pending}_items_pending_cap_raised")
        return Action("stopped", "budget")
    return Action("resume", f"{pending}_items_pending")


def _without_answers(view: RunView) -> Action:
    """Reads a complete pass that holds no completed answer.

    Every attempt that was not transient a 400 or 404 earns the fallback.
    Anything else is an outage the owner rules on, never a model failure:
    only transient failures, or a mix such as final provider errors or a
    refused account the owner has since fixed.
    """
    completions = [attempt.completion for attempt in view.attempts]
    kinds = [attempt_kind(completion) for completion in completions]
    lasting = {
        completion.http_status
        for completion, kind in zip(completions, kinds)
        if kind != "transient"
    }
    if lasting and lasting <= REFUSAL_STATUSES:
        codes = "_".join(str(code) for code in sorted(cast(set[int], lasting)))
        return Action("fallback", f"no_answer_refused_http_{codes}")
    if kinds and all(kind == "transient" for kind in kinds):
        return Action("outage", "no_answer_only_transient_failures")
    return Action("outage", "no_answer_other_failures")


def _reasoned(
    manifest: RunManifestV1, answers: Sequence[CompletionV1]
) -> Action | None:
    """Reads a run that reasoned; None when no answer did so yet.

    The run's first completed answer earns the fallback when it reasoned,
    whatever stop reason was recorded; a gate stop on any later answer,
    a resume's first included, is a drop.
    """
    if answers and thinking_state(answers[:1])[0] == "not_honoured":
        return Action("fallback", "first_answer_reasoned")
    stops = [invocation.stop_reason for invocation in manifest.invocations]
    if "thinking_not_honoured" in stops:
        return Action("reasoned", "a_later_answer_reasoned")
    return None


def decide(view: RunView, cap_micro_usd: int) -> Action:
    """Reads what one run's directory says comes next.

    The same disk state and cap always give the same action.
    """
    if not view.exists:
        return Action("start", "not_started")
    manifest = view.manifest
    if view.problem is not None or manifest is None:
        return Action("stopped", view.problem or "unreadable")
    answers = completed_answers(view)
    reasoned = _reasoned(manifest, answers)
    if reasoned is not None:
        return reasoned
    if manifest.status != "complete":
        return _unfinished(manifest, bool(answers), cap_micro_usd)
    if not answers:
        return _without_answers(view)
    return Action("done", "complete")


def account_blocked(view: RunView) -> int | None:
    """Returns 401, 402 or 403 when the newest attempt was refused so."""
    if not view.attempts:
        return None
    newest = max(view.attempts, key=lambda attempt: attempt.sent_at)
    status = newest.completion.http_status
    return status if status in ACCOUNT_STATUSES else None


def run_digest(view: RunView) -> str:
    """Summarizes what a run has recorded so far, for the console."""
    completions = [attempt.completion for attempt in view.attempts]
    answers = completed_answers(view)
    state = thinking_state(answers)[0] if answers else "no_answer"
    return (
        f"{len(completions)} sent, {len(answers)} completed;"
        f" http {dict(Counter(str(c.http_status) for c in completions))};"
        f" served {dict(Counter(str(c.provider) for c in answers))};"
        f" finish {dict(Counter(str(c.finish_reason) for c in answers))};"
        f" reasoning {state},"
        f" tokens {sum(c.reasoning_tokens or 0 for c in answers)}"
    )


class Invocation(NamedTuple):
    """What one call step printed and returned."""

    exit_code: int
    report: dict[str, Any] | None
    error_code: str | None


Invoker = Callable[[Sequence[str], bool], Invocation]


def call_argv(
    target: Target,
    endpoint: Endpoint,
    cap_micro_usd: int,
    resume: bool,
    source_revision: str,
) -> list[str]:
    """Builds one call step's argument list; nothing here is a shell."""
    argv = [
        sys.executable,
        MODEL_RUN,
        "call",
        "--prepare-dir",
        PREPARE_DIR,
        "--run-id",
        target.run_id,
        "--config",
        endpoint.config_path,
        "--max-usd",
        f"{cap_micro_usd / MICRO:.6f}",
        "--source-revision",
        source_revision,
        "--min-interval-seconds",
        f"{MIN_INTERVAL_SECONDS}",
        "--max-attempts",
        f"{MAX_ATTEMPTS}",
        "--gate-first",
    ]
    if resume:
        argv.append("--resume")
    return argv


def parse_output(
    stdout: str, stderr: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Reads the call step's one-line report or its error envelope."""
    report: dict[str, Any] | None = None
    for line in reversed(stdout.strip().splitlines()):
        value = _json_object(line)
        if value is not None and "run_id" in value:
            report = value
            break
    code: str | None = None
    for line in reversed(stderr.strip().splitlines()):
        value = _json_object(line)
        error = None if value is None else value.get("error")
        if isinstance(error, dict):
            code = str(cast(dict[str, Any], error).get("code"))
            break
    return report, code


def _json_object(line: str) -> dict[str, Any] | None:
    """Parses one output line, keeping it only when it is a JSON object."""
    try:
        value = json.loads(line)
    except ValueError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def wait_after_interrupt(
    child: subprocess.Popen[str],
    wait_seconds: float,
    out: Callable[[str], None],
) -> None:
    """Lets the in-flight request finish before the batch exits.

    Raises:
        ChildStillRunning: If the call step is still running afterwards.
    """
    out(
        f"interrupted: waiting up to {wait_seconds:.0f} s for the in-flight"
        f" request of call step pid {child.pid}"
    )
    _await_exit(child, wait_seconds)


def stop_child(
    child: subprocess.Popen[str],
    wait_seconds: float,
    out: Callable[[str], None],
) -> None:
    """Ends a call step the batch can no longer follow.

    Its request in flight may be billed but not recorded.

    Raises:
        ChildStillRunning: If the call step is still running afterwards.
    """
    out(f"the batch failed while call step pid {child.pid} ran; ending it")
    child.kill()
    _await_exit(child, wait_seconds)


def _await_exit(child: subprocess.Popen[str], wait_seconds: float) -> None:
    """Waits a bounded time for a call step to end.

    Raises:
        ChildStillRunning: If it is still running afterwards.
    """
    try:
        child.wait(timeout=wait_seconds)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        pass
    if child.poll() is None:
        raise ChildStillRunning(
            f"call step pid {child.pid} is still running; let it exit,"
            f" then delete {OUT_DIR}/{LOCK_NAME} and run the same command"
        )


def _progress(run: str, attempts_dir: Path, started: float) -> str:
    """Counts the attempts a running call step has logged so far."""
    minutes = (time.monotonic() - started) / 60
    try:
        lines = sum(
            path.read_bytes().count(b"\n")
            for path in attempts_dir.glob("C*.jsonl")
        )
    except OSError:
        return f"    ... {run}: attempt logs unreadable, {minutes:.0f} min"
    return f"    ... {run}: {lines} attempts, {minutes:.0f} min"


def subprocess_invoker(
    prepare_dir: Path, out: Callable[[str], None], wait_seconds: float
) -> Invoker:
    """Returns the real invoker: one child process per call step.

    With ``with_key`` false the child's environment has no key at all, so
    that call cannot send a request. Progress is read from the attempt
    logs, which the child appends to and fsyncs one line at a time. On
    Ctrl-C the child, which shares the console, is given ``wait_seconds``
    to finish its request before the interrupt goes on. Any other
    exception while it runs ends the child before it goes on, so no call
    step outlives the lock unattended.
    """

    def invoke(argv: Sequence[str], with_key: bool) -> Invocation:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        if not with_key:
            env.pop(API_KEY_ENV, None)
        run = argv[argv.index("--run-id") + 1]
        attempts_dir = prepare_dir / "runs" / run / "attempts"
        # Not a with block: its exit waits for the child without a bound,
        # and a call step that outlives the interrupt wait must be left
        # running, with the lock kept, rather than waited on here.
        child = subprocess.Popen(  # pylint: disable=consider-using-with
            list(argv),
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        started = time.monotonic()
        try:
            while True:
                try:
                    stdout, stderr = child.communicate(timeout=PROGRESS_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    out(_progress(run, attempts_dir, started))
        except KeyboardInterrupt:
            wait_after_interrupt(child, wait_seconds, out)
            raise
        except BaseException:
            stop_child(child, wait_seconds, out)
            raise
        for text in (stdout, stderr):
            for line in text.strip().splitlines():
                out(f"    | {line}")
        report, code = parse_output(stdout, stderr)
        return Invocation(child.returncode, report, code)

    return invoke


def _print(line: str) -> None:
    print(line, flush=True)


def pause(seconds: float) -> None:
    """Waits before a resume; the tests replace this seam."""
    time.sleep(seconds)


class Layout(NamedTuple):
    """Where the batch reads its inputs and writes its log."""

    prepare_dir: Path
    committed_dir: Path
    config_dir: Path
    out_dir: Path
    prepare_prefix: str = PREPARE_SHA256_PREFIX


@dataclass(frozen=True)
class Rulings:
    """The owner's rulings and flags for one execution.

    ``rerun`` and ``not_measured`` name outage passes by run id; the step
    log and the summary record all three.
    """

    rerun: frozenset[str] = frozenset()
    not_measured: frozenset[str] = frozenset()
    after_smoke_failures: bool = False

    def record(self) -> dict[str, Any]:
        """Returns the rulings as the log and the summary spell them."""
        return {
            "rerun": sorted(self.rerun),
            "not_measured": sorted(self.not_measured),
            "after_smoke_failures": self.after_smoke_failures,
        }


@dataclass
class Context:
    """Everything one execution of the batch shares."""

    layout: Layout
    source_revision: str
    endpoints: dict[str, Endpoint]
    model_run: ModuleType
    invoke: Invoker
    rulings: Rulings = Rulings()
    out: Callable[[str], None] = _print

    @property
    def prepare_dir(self) -> Path:
        """Returns the dev prepare directory the runs live under."""
        return self.layout.prepare_dir

    @property
    def out_dir(self) -> Path:
        """Returns the directory of the step log, summary and lock."""
        return self.layout.out_dir

    @property
    def log_path(self) -> Path:
        """Returns the step log, one JSON record per call step."""
        return self.out_dir / "steps.jsonl"

    def view(self, target: Target) -> RunView:
        """Reads one target's run directory."""
        return load_run(self.prepare_dir, target.run_id, self.model_run)

    def with_rerun(self, target: Target) -> list[Target]:
        """Returns a run, then its outage re-run once ruled or started."""
        rerun = rerun_of(target)
        if target.run_id in self.rulings.rerun or self.view(rerun).exists:
            return [target, rerun]
        return [target]

    def log(self, record: dict[str, Any]) -> None:
        """Appends one step record; argv and codes only, never the env."""
        record = {"at": _now(), **record}
        with self.log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(json.dumps(record, sort_keys=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_argv(argv: Sequence[str]) -> list[str]:
    return ["python", *argv[1:]]


def batch_targets(candidate: Candidate, ctx: Context) -> list[Target]:
    """Returns the runs this execution may drive for one candidate."""
    return [each for t in targets(candidate) for each in ctx.with_rerun(t)]


def drive(target: Target, candidate: Candidate, ctx: Context) -> Action:
    """Makes at most one call for one run and returns its state after it.

    Raises:
        BatchAbort: If the call step found no key, or the account or a
            guardrail refused (401, 402 or 403).
        BatchStop: If the call step ended with an error envelope.
    """
    cap = _micro(candidate.cap_usd)
    action = decide(ctx.view(target), cap)
    if action.kind not in ("start", "resume"):
        return action
    endpoint = ctx.endpoints[target.config]
    argv = call_argv(
        target, endpoint, cap, action.kind == "resume", ctx.source_revision
    )
    ctx.out(
        f"  {_now()} {target.run_id}: {action.kind}"
        f" (cap {cap / MICRO:.2f} USD, {action.reason})"
    )
    result = ctx.invoke(argv, True)
    report = result.report or {}
    ctx.log(
        {
            "candidate": candidate.name,
            "run_id": target.run_id,
            "config": target.config,
            "phase": action.kind,
            "argv": _log_argv(argv),
            "exit_code": result.exit_code,
            "error_code": result.error_code,
            "stop_reason": report.get("stop_reason"),
            "requests_sent": report.get("requests_sent"),
            "charged_usd_upper_bound": report.get("charged_usd_upper_bound"),
        }
    )
    if result.report is None:
        if result.error_code == "api_key_missing":
            raise BatchAbort(f"{target.run_id}: the call step found no key")
        raise BatchStop(
            f"{target.run_id}: the call step ended with an error"
            f" ({result.error_code}, exit {result.exit_code})"
        )
    view = ctx.view(target)
    ctx.out(f"  {target.run_id}: {run_digest(view)}")
    blocked = account_blocked(view)
    if report.get("stop_reason") == "fatal_http" and blocked:
        raise BatchAbort(
            f"HTTP {blocked} on {target.run_id}: fix the key, the credit or"
            " the account's guardrail, then run the same command again"
        )
    return decide(view, cap)


def _stop_message(target: Target, outcome: Action) -> str:
    """Says what the owner does about a run stopped for them."""
    if outcome.reason == "budget":
        return (
            f"{target.run_id}: budget stop; raise the candidate's cap in"
            " scripts/dev_bakeoff.py above the last invocation's max_usd,"
            " commit it and run the same command again"
        )
    return f"{target.run_id}: {outcome.reason}"


def _settle(
    role: str, target: Target, candidate: Candidate, ctx: Context
) -> Action:
    """Drives one run until it needs no further call in this execution.

    Items left pending by transient failures are resumed after a wait;
    ``max_attempts`` settles each of them within three attempts.

    Raises:
        BatchStop: If the run stopped for the owner.
    """
    outcome = drive(target, candidate, ctx)
    while outcome.kind == "resume":
        ctx.out(
            f"  {target.run_id}: {outcome.reason}; resuming in"
            f" {RESUME_WAIT_SECONDS:.0f} s"
        )
        pause(RESUME_WAIT_SECONDS)
        outcome = drive(target, candidate, ctx)
    ctx.out(f"  {role} {target.run_id}: {outcome.kind} ({outcome.reason})")
    if outcome.kind == "stopped":
        raise BatchStop(_stop_message(target, outcome))
    return outcome


def _counted_run(
    role: str, target: Target, candidate: Candidate, ctx: Context
) -> Action:
    """Settles one run, or after an outage the re-run the owner ruled.

    Raises:
        BatchStop: If a run stopped for the owner, or an outage awaits
            the owner's ruling.
    """
    outcome = _settle(role, target, candidate, ctx)
    if outcome.kind != "outage":
        return outcome
    chain = ctx.with_rerun(target)
    if len(chain) == 1 and target.run_id in ctx.rulings.not_measured:
        return Action("not_measured", "owner_ruling_after_an_outage")
    if len(chain) == 1:
        rerun = rerun_of(target).run_id
        raise BatchStop(
            f"{target.run_id}: outage (no completed answer, not a refusal:"
            f" {outcome.reason}); run the same command with --rerun"
            f" {target.run_id}"
            f" to re-run it once from scratch as {rerun}, or with"
            f" --not-measured {target.run_id}"
        )
    again = _settle(f"{role} re-run", chain[1], candidate, ctx)
    if again.kind == "outage":
        return Action("not_measured", "outage_on_the_re_run_too")
    return again


def run_candidate(candidate: Candidate, ctx: Context) -> Action:
    """Runs a candidate's pass, then its one fallback pass if earned.

    Raises:
        BatchStop: If a run stopped for the owner.
        BatchAbort: If the key or the account stops the batch.
    """
    ctx.out(f"{candidate.slot} {candidate.rank} {candidate.name}")
    outcome = _counted_run("pass", candidate.primary, candidate, ctx)
    if outcome.kind != "fallback" or candidate.fallback is None:
        return outcome
    return _counted_run("fallback", candidate.fallback, candidate, ctx)


def preflight(candidates: Sequence[Candidate], ctx: Context) -> None:
    """Calls every configuration once with the key withheld.

    Raises:
        PlanError: If any configuration stops anywhere but at
            ``api_key_missing``.
    """
    for candidate in candidates:
        for target in batch_targets(candidate, ctx):
            argv = call_argv(
                target,
                ctx.endpoints[target.config],
                _micro(candidate.cap_usd),
                False,
                ctx.source_revision,
            )
            result = ctx.invoke(argv, False)
            ctx.log(
                {
                    "candidate": candidate.name,
                    "run_id": target.run_id,
                    "config": target.config,
                    "phase": "preflight",
                    "argv": _log_argv(argv),
                    "exit_code": result.exit_code,
                    "error_code": result.error_code,
                }
            )
            if (result.exit_code, result.error_code) != (2, "api_key_missing"):
                raise PlanError(
                    f"preflight: {target.config} stopped at"
                    f" {result.error_code} (exit {result.exit_code})"
                )
            ctx.out(f"  preflight ok: {target.run_id} -> api_key_missing")


def run_row(
    view: RunView, endpoint: Endpoint, cap_micro_usd: int
) -> dict[str, Any]:
    """Describes one run for the summary, from its directory alone."""
    action = decide(view, cap_micro_usd)
    row: dict[str, Any] = {
        "run_id": view.run_id,
        "config": endpoint.name,
        "model_id": endpoint.settings.model_id,
        "slug": endpoint.route,
        "reasoning_switch": endpoint.options.reasoning,
        "exists": view.exists,
        "state": action.kind,
        "why": action.reason,
        "commit_to": None,
    }
    manifest = view.manifest
    if manifest is None:
        return row
    completions = [attempt.completion for attempt in view.attempts]
    answers = completed_answers(view)
    state, evidence = thinking_state(answers)
    row.update(
        {
            "status": manifest.status,
            "commit_to": (
                f"docs/results/{view.run_id}/"
                if manifest.status == "complete"
                and answers
                and action.kind != "outage"
                else f"{EVIDENCE_DIR}/{view.run_id}/"
            ),
            "completed": sum(c.completed for c in manifest.conditions),
            "failed": sum(c.failed for c in manifest.conditions),
            "pending": sum(c.pending for c in manifest.conditions),
            "requests": len(view.attempts),
            "invocations": len(manifest.invocations),
            "stop_reasons": [i.stop_reason for i in manifest.invocations],
            "reasoning_state": state,
            "reasoning_evidence": evidence,
            "reasoning_tokens_total": sum(
                c.reasoning_tokens or 0 for c in answers
            ),
            "served_by": dict(Counter(str(c.provider) for c in answers)),
            "finish_reasons": dict(
                Counter(str(c.finish_reason) for c in answers)
            ),
            "http_statuses": dict(
                Counter(str(c.http_status) for c in completions)
            ),
            "error_codes": dict(
                Counter(c.error_code for c in completions if c.error_code)
            ),
            "provider_error_codes": dict(
                Counter(
                    c.provider_error_code
                    for c in completions
                    if c.provider_error_code
                )
            ),
            "charged_usd_upper_bound": manifest.charged_usd_upper_bound,
            "provider_reported_usd": manifest.provider_reported_usd,
        }
    )
    return row


def run_gate_drops(row: dict[str, Any]) -> list[str]:
    """Applies the measurable drop rules to one complete pass."""
    drops: list[str] = []
    if row["completed"] < MIN_COMPLETED:
        drops.append(f"completed {row['completed']} < {MIN_COMPLETED}")
    if row["reasoning_state"] == "not_honoured":
        drops.append("an answer reasoned")
    if row["reasoning_switch"] is not None and (
        row["reasoning_state"] == "uncontrolled"
    ):
        drops.append("hybrid reported no reasoning-token count")
    return drops


def _role_rows(
    role: str, target: Target, candidate: Candidate, ctx: Context
) -> list[dict[str, Any]]:
    """Describes one role's run, then its outage re-run if there is one."""
    rows: list[dict[str, Any]] = []
    for name, each in zip((role, f"{role} re-run"), ctx.with_rerun(target)):
        row = run_row(
            ctx.view(each),
            ctx.endpoints[each.config],
            _micro(candidate.cap_usd),
        )
        row["role"] = name
        rows.append(row)
    return rows


def _stage(
    rows: Sequence[dict[str, Any]], ctx: Context
) -> tuple[str, str, dict[str, Any]]:
    """Reads one role's state, following an outage to its re-run."""
    first = rows[0]
    if first["state"] != "outage":
        return first["state"], first["why"], first
    if len(rows) > 1:
        rerun = rows[1]
        if rerun["state"] == "outage":
            return "not_measured", "outage on the re-run too", rerun
        return rerun["state"], rerun["why"], rerun
    if first["run_id"] in ctx.rulings.not_measured:
        return "not_measured", "owner ruling after an outage", first
    return "outage", first["why"], first


_WAITING = {
    "resume": "pending ({why}): run the same command again",
    "stopped": "stopped for the owner ({why})",
    "outage": (
        "stopped for the owner (outage on {run}): run the same command with"
        " --rerun {run} or --not-measured {run}"
    ),
    "not_measured": "not measured ({why})",
}


def _verdict(
    kind: str,
    why: str,
    active: dict[str, Any],
    rows: Sequence[dict[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    """Spells a candidate's verdict and its qualifying pass, if any."""
    if kind == "done":
        drops = run_gate_drops(active)
        if drops:
            return f"dropped ({'; '.join(drops)})", None
        qualifying = {key: active[key] for key in QUALIFYING_KEYS}
        return "passes the run gates", qualifying
    history = "; ".join(f"{r['role']}: {r['why']}" for r in rows if r["exists"])
    if kind in ("fallback", "reasoned"):
        return f"dropped ({history})", None
    if kind == "start":
        started = f"{active['role']} not started ({history})"
        return (started if history else "not started"), None
    return _WAITING[kind].format(why=why, run=active["run_id"]), None


def candidate_summary(candidate: Candidate, ctx: Context) -> dict[str, Any]:
    """Judges one candidate from its run directories and rulings alone.

    The ranking needs strong-exact counts from the offline scorer, and
    the two-turn smoke is a later owner command; neither is decided
    here. A candidate that passes names the pass that qualified it, whose
    model, slug and switch its test passes use.
    """
    by_role = {
        role: _role_rows(role, target, candidate, ctx)
        for role, target in zip(("pass", "fallback"), targets(candidate))
    }
    kind, why, active = _stage(by_role["pass"], ctx)
    if kind == "fallback" and "fallback" in by_role:
        kind, why, active = _stage(by_role["fallback"], ctx)
    rows = [row for role_rows in by_role.values() for row in role_rows]
    verdict, qualifying = _verdict(kind, why, active, rows)
    return {
        "slot": candidate.slot,
        "rank": candidate.rank,
        "candidate": candidate.name,
        "cap_usd": candidate.cap_usd,
        "final": kind in FINAL_KINDS,
        "passes": qualifying is not None,
        "verdict": verdict,
        "qualifying_pass": qualifying,
        "runs": rows,
    }


def _slot_line(
    slot: str, ranked: Sequence[dict[str, Any]], reserve: dict[str, Any]
) -> str:
    """States what one slot needs next, from its verdicts."""
    name = reserve["candidate"]
    if reserve["runs"][0]["exists"]:
        if reserve["passes"]:
            return (
                f"{slot}: run-gate survivor {name} (the reserve); its own"
                " two-turn smoke decides"
            )
        if reserve["final"]:
            return (
                f"{slot}: the reserve {name} is out ({reserve['verdict']});"
                " the slot stays empty"
            )
        return f"{slot}: the reserve {name} is not finished"
    survivors = [r["candidate"] for r in ranked if r["passes"]]
    if survivors:
        return (
            f"{slot}: run-gate survivors {', '.join(survivors)}; the score"
            " and the two-turn smoke decide; if every survivor fails its"
            f" smoke, run --only reserve-{slot} --after-smoke-failures"
        )
    if all(r["final"] for r in ranked):
        return (
            f"{slot}: no candidate passes the run gates; run"
            f" --only reserve-{slot}"
        )
    return f"{slot}: not finished"


def slot_lines(records: Sequence[dict[str, Any]]) -> list[str]:
    """States what each slot needs next, from the candidate verdicts."""
    lines: list[str] = []
    for slot in RANKED_SLOTS:
        ranked = [r for r in records if r["slot"] == slot]
        reserve = [r for r in records if r["slot"] == f"reserve-{slot}"]
        lines.append(_slot_line(slot, ranked, reserve[0]))
    return lines


def _row_line(row: dict[str, Any]) -> str:
    """Spells one run of the summary on one line."""
    line = f"{row['role']} {row['run_id']}: {row['state']} ({row['why']})"
    if "completed" not in row:
        return line
    served = ",".join(sorted(row["served_by"])) or "-"
    return (
        f"{line}; {row['completed']}/{TOTAL_ITEMS} completed; reasoning"
        f" {row['reasoning_state']}; served {served}; last stop"
        f" {row['stop_reasons'][-1]}; {row['charged_usd_upper_bound']:.4f}"
        " USD charged at most"
    )


def write_summary(ctx: Context) -> tuple[Path, Path]:
    """Writes the JSON and plain-text summaries of every planned run."""
    records = [candidate_summary(c, ctx) for c in all_candidates()]
    slots = slot_lines(records)
    spend = sum(
        row.get("charged_usd_upper_bound", 0.0)
        for record in records
        for row in record["runs"]
    )
    stamp = _now()
    document = {
        "written_at": stamp,
        "source_revision": ctx.source_revision,
        "prepare_dir": PREPARE_DIR,
        "total_items": TOTAL_ITEMS,
        "min_completed": MIN_COMPLETED,
        "rulings": ctx.rulings.record(),
        "charged_usd_upper_bound_total": round(spend, 6),
        "slots": slots,
        "candidates": records,
    }
    json_path = ctx.out_dir / f"summary-{stamp[:10]}.json"
    json_path.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    text: list[str] = []
    for record in records:
        text.append(
            f"{record['slot']} {record['rank']} {record['candidate']}:"
            f" {record['verdict']}"
        )
        text.extend(f"    {_row_line(row)}" for row in record["runs"])
        qualifying = record["qualifying_pass"]
        if qualifying is not None:
            text.append(
                f"    qualifying pass {qualifying['run_id']}:"
                f" {qualifying['model_id']} on {qualifying['slug']},"
                f" reasoning {qualifying['reasoning_switch']}"
            )
    text.append("")
    text.extend(slots)
    text.append(f"rulings: {json.dumps(ctx.rulings.record(), sort_keys=True)}")
    text.append(f"total charged upper bound: {spend:.4f} USD")
    text_path = ctx.out_dir / f"summary-{stamp[:10]}.txt"
    text_path.write_text(
        "\n".join(text).rstrip() + "\n", encoding="utf-8", newline="\n"
    )
    return json_path, text_path


def cap_table(
    candidates: Sequence[Candidate], endpoints: dict[str, Endpoint]
) -> list[str]:
    """Shows each configuration's bounds against its candidate's cap."""
    lines = [
        "config | slug | in/out USD per M | worst/request | full-pass worst"
        " | estimate | cap | headroom"
    ]
    for candidate in candidates:
        cap = _micro(candidate.cap_usd)
        for target in targets(candidate):
            e = endpoints[target.config]
            prices = e.prices
            lines.append(
                f"{e.name} | {e.route} | {prices.usd_per_million_input:g}"
                f"/{prices.usd_per_million_output:g} |"
                f" {e.worst_micro_usd / MICRO:.6f} |"
                f" {e.pass_worst_micro_usd / MICRO:.4f} |"
                f" {e.estimate_micro_usd / MICRO:.4f} |"
                f" {candidate.cap_usd:.2f} |"
                f" {headroom_micro_usd(e, cap) / MICRO:.4f}"
            )
    lines.append(
        "headroom = cap - 2 x estimate - worst request; the plan refuses a"
        " negative one"
    )
    return lines


def dry_run(candidates: Sequence[Candidate], ctx: Context) -> None:
    """Prints every argument list the batch would start from this state."""
    for line in cap_table(candidates, ctx.endpoints):
        ctx.out(line)
    ctx.out("")
    ctx.out(
        "preflight (key withheld from the child; each must stop at"
        " api_key_missing):"
    )
    for candidate in candidates:
        for target in batch_targets(candidate, ctx):
            argv = call_argv(
                target,
                ctx.endpoints[target.config],
                _micro(candidate.cap_usd),
                False,
                ctx.source_revision,
            )
            ctx.out("  " + " ".join(_log_argv(argv)))
    ctx.out("")
    for candidate in candidates:
        _dry_run_candidate(candidate, ctx)


def _dry_run_candidate(candidate: Candidate, ctx: Context) -> None:
    """Prints one candidate's runs and the call each would make next."""
    cap = _micro(candidate.cap_usd)
    ctx.out(f"{candidate.slot} {candidate.rank} {candidate.name}:")
    for target in batch_targets(candidate, ctx):
        if candidate.fallback is not None and target == candidate.fallback:
            ctx.out(
                "  only if the pass's first completed answer reasoned, or"
                " it ended with no completed answer and every attempt that"
                " was not transient refused with HTTP 400 or 404:"
            )
        action = decide(ctx.view(target), cap)
        ctx.out(f"  {target.run_id}: {action.kind} ({action.reason})")
        if action.kind in ("start", "resume"):
            argv = call_argv(
                target,
                ctx.endpoints[target.config],
                cap,
                action.kind == "resume",
                ctx.source_revision,
            )
            ctx.out("    " + " ".join(_log_argv(argv)))


def _git(*args: str) -> str:
    """Runs one read-only git command at the repository root."""
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def head_revision() -> str:
    """Returns the checked-out commit, which every call records.

    Raises:
        PlanError: If git prints something that is not a revision.
    """
    value = _git("rev-parse", "--short", "HEAD").strip()
    if SOURCE_REVISION.fullmatch(value) is None:
        raise PlanError("source revision is not a safe revision string")
    return value


def tooling_changes() -> list[str]:
    """Lists uncommitted changes to the pre-registration and the tooling."""
    status = _git(
        "status", "--porcelain", "--untracked-files=all", "--", *TOOLING
    )
    return status.splitlines()


def default_layout() -> Layout:
    """Returns the repository's own layout."""
    return Layout(
        ROOT / PREPARE_DIR,
        ROOT / COMMITTED_PREPARE_DIR,
        ROOT / CONFIG_DIR,
        ROOT / OUT_DIR,
    )


def build_context(
    layout: Layout | None = None, revision: str | None = None
) -> Context:
    """Loads and checks every configuration the plan names.

    Raises:
        PlanError: If the prompt set, a configuration or the plan is not
            usable.
    """
    layout = layout or default_layout()
    model_run = load_model_run()
    check_prepare(
        layout.prepare_dir, layout.committed_dir, layout.prepare_prefix
    )
    sizes = prompt_bytes(layout.prepare_dir)
    names = sorted({t.config for c in all_candidates() for t in targets(c)})
    endpoints = {
        name: load_endpoint(name, layout.config_dir, model_run, sizes)
        for name in names
    }
    check_plan(all_candidates(), endpoints)
    wait = INTERRUPT_GRACE_SECONDS + max(
        e.settings.timeout_seconds for e in endpoints.values()
    )
    return Context(
        layout=layout,
        source_revision=revision or head_revision(),
        endpoints=endpoints,
        model_run=model_run,
        invoke=subprocess_invoker(layout.prepare_dir, _print, wait),
    )


def _check_rulings(ctx: Context) -> None:
    """Admits a ruling only on a planned pass that ended in an outage.

    Raises:
        PlanError: If a ruling names another run, both rulings name one
            run, or a pass already re-run is ruled not measured.
    """
    rulings = ctx.rulings
    planned = {
        target.run_id: (candidate, target)
        for candidate in all_candidates()
        for target in targets(candidate)
    }
    for run in sorted(rulings.rerun | rulings.not_measured):
        if run in rulings.rerun and run in rulings.not_measured:
            raise PlanError(f"{run}: both --rerun and --not-measured")
        if run not in planned:
            raise PlanError(f"{run}: not a planned pass or fallback run id")
        candidate, target = planned[run]
        action = decide(ctx.view(target), _micro(candidate.cap_usd))
        if action.kind != "outage":
            raise PlanError(f"{run}: not an outage ({action.kind})")
        rerun = rerun_of(target)
        if run in rulings.not_measured and ctx.view(rerun).exists:
            raise PlanError(f"{run}: its re-run {rerun.run_id} exists")


def _check_reserve(slot: str, ctx: Context) -> None:
    """Admits a reserve only once its slot's ranked candidates allow it.

    Raises:
        PlanError: If a ranked candidate of the slot has no verdict, or
            one passes the run gates without ``--after-smoke-failures``.
    """
    ranked = [
        candidate_summary(candidate, ctx)
        for candidate in PLAN[slot.removeprefix("reserve-")]
    ]
    unfinished = [r["candidate"] for r in ranked if not r["final"]]
    if unfinished:
        raise PlanError(
            f"--only {slot}: no verdict yet for {', '.join(unfinished)}"
        )
    survivors = [r["candidate"] for r in ranked if r["passes"]]
    if survivors and not ctx.rulings.after_smoke_failures:
        raise PlanError(
            f"--only {slot}: {', '.join(survivors)} passed the run gates;"
            " the reserve runs only after every run-gate survivor failed"
            " its two-turn smoke (--after-smoke-failures)"
        )


def check_selection(slots: Sequence[str], ctx: Context) -> None:
    """Refuses rulings and reserves the run directories do not allow.

    Raises:
        PlanError: If a ruling or a selected reserve is not admitted.
    """
    _check_rulings(ctx)
    for slot in slots:
        if slot.startswith("reserve-"):
            _check_reserve(slot, ctx)


def acquire_lock(path: Path) -> None:
    """Takes the single-instance lock, so no two batches drive one run.

    A lock this call created is removed again if anything, an interrupt
    included, stops it before it returns.

    Raises:
        PlanError: If another batch holds it, or a crashed one left it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        held = path.read_text(encoding="utf-8").strip()
        raise PlanError(
            f"{_relative(path)} is held ({held}); if no batch or call step"
            " is running, delete it and run the same command again"
        ) from None
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as lock:
            lock.write(f"pid {os.getpid()} since {_now()}\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _anchor_gate(ctx: Context) -> int | None:
    """Returns EXIT_STOPPED on a final anchor failure, None if it passed.

    Raises:
        BatchStop: If the anchor has no verdict yet.
    """
    anchor = candidate_summary(ANCHOR, ctx)
    if not anchor["final"]:
        raise BatchStop(
            f"the anchor {ANCHOR.primary.run_id} has no verdict yet"
            f" ({anchor['verdict']}); it runs first, in the default"
            " selection or with --only anchor"
        )
    if anchor["passes"]:
        return None
    ctx.out(
        f"ANCHOR FAILED: {anchor['verdict']}; the owner's decision about"
        " the A/A pair is written into the bake-off note before any test"
        " request"
    )
    return EXIT_STOPPED


def _run(slots: Sequence[str], ctx: Context) -> int:
    """Runs the selected slots after the preflight and the paid-call checks.

    Raises:
        PlanError: If the preflight fails or the tooling is uncommitted.
        BatchAbort: If the key variable is absent or the account refused.
        BatchStop: If a candidate's run, or the anchor, needs the owner.
    """
    candidates = [c for slot in slots for c in PLAN[slot]]
    ctx.out(f"source revision {ctx.source_revision}; slots {', '.join(slots)}")
    ctx.log({"phase": "batch", "slots": list(slots), **ctx.rulings.record()})
    for line in cap_table(candidates, ctx.endpoints):
        ctx.out(line)
    preflight(candidates, ctx)
    if API_KEY_ENV not in os.environ:
        raise BatchAbort(
            f"{API_KEY_ENV} is not set in this shell; nothing was sent"
        )
    changes = tooling_changes()
    if changes:
        raise PlanError(
            "commit the pre-registration and the tooling before a paid"
            " call: " + "; ".join(changes)
        )
    if "anchor" in slots:
        run_candidate(ANCHOR, ctx)
    code = _anchor_gate(ctx)
    if code is not None:
        return code
    for candidate in candidates:
        if candidate.slot != "anchor":
            run_candidate(candidate, ctx)
    return EXIT_OK


def _locked_run(slots: Sequence[str], ctx: Context) -> int:
    """Runs the batch under the lock and always writes the summary."""
    lock = ctx.out_dir / LOCK_NAME
    keep_lock = False
    try:
        acquire_lock(lock)
    except PlanError as error:
        print(f"plan refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        code = _run(slots, ctx)
    except (PlanError, subprocess.CalledProcessError) as error:
        ctx.out(f"REFUSED: {error}")
        code = EXIT_REFUSED
    except BatchStop as stop:
        ctx.out(f"STOPPED: {stop}")
        code = EXIT_STOPPED
    except BatchAbort as abort:
        ctx.out(f"ABORTED: {abort}")
        code = EXIT_ABORTED
    except ChildStillRunning as error:
        ctx.out(f"INTERRUPTED: {error}")
        keep_lock = True
        code = EXIT_INTERRUPTED
    except KeyboardInterrupt:
        ctx.out(
            "INTERRUPTED: run the same command again to resume; the"
            " interrupted request may be billed but not recorded"
        )
        code = EXIT_INTERRUPTED
    finally:
        try:
            json_path, text_path = write_summary(ctx)
            ctx.out(text_path.read_text(encoding="utf-8"))
            ctx.out(f"summary: {_relative(json_path)}, {_relative(text_path)}")
        finally:
            if not keep_lock:
                lock.unlink(missing_ok=True)
    ctx.out(f"exit {code}")
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=tuple(PLAN),
        help="run only this slot; repeatable; reserves run only this way",
    )
    parser.add_argument(
        "--rerun",
        action="append",
        default=[],
        metavar="RUN_ID",
        help="re-run this outage pass once from scratch under its -r2 id",
    )
    parser.add_argument(
        "--not-measured",
        action="append",
        default=[],
        metavar="RUN_ID",
        help="rule the candidate of this outage pass not measured",
    )
    parser.add_argument(
        "--after-smoke-failures",
        action="store_true",
        help="admit a reserve once every run-gate survivor failed its smoke",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the bake-off batch and returns a process exit code."""
    arguments = _parser().parse_args(argv)
    slots = tuple(arguments.only or DEFAULT_SLOTS)
    try:
        ctx = build_context()
        ctx.rulings = Rulings(
            frozenset(arguments.rerun),
            frozenset(arguments.not_measured),
            arguments.after_smoke_failures,
        )
        check_selection(slots, ctx)
    except (
        PlanError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"plan refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    if arguments.dry_run:
        dry_run([c for slot in slots for c in PLAN[slot]], ctx)
        return EXIT_OK
    return _locked_run(slots, ctx)


if __name__ == "__main__":
    raise SystemExit(main())
