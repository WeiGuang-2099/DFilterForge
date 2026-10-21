"""Owner runner for the judge study: dry run, call, publish and table.

``docs/protocol.md`` (Judge study) and ``docs/decisions/judge-study.md``
register the study, and the note's Commands section gives each owner
command; :mod:`dfilterforge.judge` builds the answer set, requests,
verdicts and table. Where this file and that text differ, the text holds.

``dry-run`` and ``call`` take a split, a config with the settings and
prices of one of the note's two, whose one provider slug is the route, and
a cap that funds the dearest request and does not pass the note's cap for
the split. ``dry-run`` needs no key, opens no socket and writes nothing.
``call`` refuses before any client exists when the key variable is unset.
It refuses a test call on a route J2 does not leave standing, or once the
other route holds a test run. It sends one request at a time
with scripts/model_run.py's client, bound, charge and retry classes, paced
at 1 s. A completed reply is final. A timeout, a transport error or HTTP
408, 429 or 5xx is sent again in a later sweep, 60 s on, at most three
attempts in all; HTTP 401, 402 or 403, a first reply that shows thinking,
or an attempt whose bound would take the spend past the cap stops the run.
Three attempts in a row that end in a timeout or a transport error end the
call with their requests pending, since the charge counts each at its
whole bound: an outage would otherwise spend the cap on bounds alone.
Every attempt is fsynced to artifacts/judge-v2/<split>-<route>/attempts.jsonl
beside manifest.json, which names the endpoint's host, never its URL or the
key. ``--resume`` continues a run sent with the same settings, host and
requests, unless the gate stopped it. ``publish`` copies a complete run to
docs/results/judge-v2/<split>/, and ``table`` writes or checks
docs/results/judge-v2/table.json from the published test run. Each path is
named for the prompt version; the judge-v1 dev check is published in
docs/results/judge-v1/dev/ and read by nothing here.

Exit codes: 0 done; 1 requests left pending (interrupted with Ctrl-C,
three timeouts or transport errors in a row, or an attempt log that could
not be written), or a table that differs from its rebuild; 2 refused
before any request; 3 stopped by HTTP 401, 402 or 403, the thinking gate or
the cap.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from types import ModuleType
from typing import Any, Literal, NamedTuple, TextIO

from pydantic import Field
from pydantic import ValidationError

from dfilterforge import judge
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import thinking_state
from dfilterforge.completions import TokenPricesV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.score_summary import OutcomeV1

ROOT = Path(__file__).resolve().parents[1]
RESULTS = Path("docs", "results")
PUBLISHED = Path("docs", "results", judge.PROMPT_VERSION)
RUNS = Path("artifacts", judge.PROMPT_VERSION)
CONFIGS = Path("docs", "decisions", "evidence", "judge", "configs")
TABLE = Path(judge.PROMPT_VERSION, "table.json")
ATTEMPTS = "attempts.jsonl"
MANIFEST = "manifest.json"
# J7: the note's caps, which a call may lower but never raise.
CAPS = {"dev": 0.40, "test": 1.50}
MAX_ATTEMPTS = 3
PACE_SECONDS = 1.0
SWEEP_WAIT_SECONDS = 60.0
# Timeouts and transport errors in a row that end a call, pending.
FAULT_LIMIT = 3
MICRO = 1_000_000
# The note's estimate, used for nothing else: the deepseek test replies'
# prompt tokens fitted by least squares on their prompt bytes, and 172
# reply tokens, the mean of the judge-v1 dev check's replies.
TOKENS_PER_BYTE = 0.2679
TOKENS_OFFSET = -48.8
REPLY_TOKENS = 172
# J2: the route and its fallback, as the two configs name them, and where
# the maintainer moves a DeepInfra dev check that sends the study on.
ROUTES = ("deepinfra", "gmicloud")
MOVED = Path("docs", "decisions", "evidence", "judge", "dev-deepinfra")
EXIT_PENDING = 1
EXIT_DIFFERS = 1
EXIT_REFUSED = 2
EXIT_STOPPED = 3
StopReason = Literal[
    "budget",
    "fatal_http",
    "thinking_not_honoured",
    "interrupted",
    "unreachable",
    "io_error",
]
# The stops that end a run for the owner; an interrupt, an outage or a
# failed write leaves it pending.
STOPS = frozenset({"budget", "fatal_http", "thinking_not_honoured"})


def _load_model_run() -> ModuleType:
    """Loads scripts/model_run.py by path, for the call rules it defines."""
    spec = importlib.util.spec_from_file_location(
        "judge_study_model_run", ROOT / "scripts" / "model_run.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("scripts/model_run.py cannot be loaded")
    loaded = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


model_run = _load_model_run()
# The call step's own rules, reused rather than restated: the config and
# attempt records, the client, the pre-request bound and the charge, the
# retry classes and prompt states, the attempt log and the secret scan.
# They are private to scripts/model_run.py by name only. That file is
# hashed into every prepared prompt set, so it is read here, not edited.
# pylint: disable=protected-access
AttemptV1 = model_run.AttemptV1
_read_config = model_run._read_config
_client = model_run._backend
_worst_case = model_run._worst_case_micro_usd
_charge = model_run._charge_micro_usd
# The error codes of an attempt that got no reply, which the charge counts
# at the attempt's whole bound: a timeout and a transport error.
_FAULTS: frozenset[str] = model_run._RETRY_CODES
_retry_class = model_run._retry_class
_settled = model_run._is_settled
_state_of = model_run._prompt_state
_append_attempt = model_run._append_attempt
_attempt_records = model_run._attempt_records
_endpoint_host = model_run._endpoint_host
_prompt_bytes = model_run._prompt_bytes
_recorded_usd = model_run._recorded_usd
_regular_file = model_run._regular_file
_scan_for_secrets = model_run._scan_for_secrets
_print_error = model_run._print_error
TOKEN_BOUND_RULE: str = model_run._TOKEN_BOUND_RULE
MAX_RUN_FILE_BYTES: int = model_run._MAX_PUBLISHED_BYTES
# pylint: enable=protected-access


class InvocationV1(FrozenModel):
    """One call: when it ran, its cap, what it sent and why it ended."""

    started_at: datetime
    finished_at: datetime | None = None
    max_usd: float = Field(gt=0)
    attempts_sent: int = Field(ge=0)
    stop_reason: StopReason | None = None


class JudgeRunV1(FrozenModel):
    """A judge run's settings, requests, invocations, census and spend.

    The endpoint is recorded by its host alone, never by its URL or key.
    """

    schema_version: Literal["judge-run/1.0"] = "judge-run/1.0"
    prompt_version: str
    split: judge.Split
    route: str
    endpoint_host: str
    settings: RequestSettingsV1
    prices: TokenPricesV1
    max_attempts: int
    min_interval_seconds: float
    sweep_wait_seconds: float
    token_bound_rule: str
    system_prompt_sha256: dict[str, str]
    request_set_sha256: str
    requests: int
    answer_set: dict[str, str]
    created_at: datetime
    invocations: tuple[InvocationV1, ...]
    status: Literal["complete", "incomplete"]
    completed: int
    failed: int
    pending: int
    attempts_sha256: str
    charged_usd_upper_bound: float
    provider_reported_usd: float | None = None


class _Plan(NamedTuple):
    """What a dry run or a call checked before anything else."""

    requests: judge.RequestSet
    config: Any
    route: str
    cap: int
    run_dir: Path


@dataclass
class _Sending:
    """What a call has spent and sent, and why it stopped, if it did.

    ``gated`` records that the call's first completed reply has been read
    by the thinking gate, which reads that reply alone; ``faults`` counts
    the attempts in a row that ended in a timeout or a transport error.
    """

    spent: int
    sent: int = 0
    stop: StopReason | None = None
    last_start: float | None = None
    gated: bool = False
    faults: int = 0


def _monotonic() -> float:
    """Reads the pacing clock through a seam the tests replace."""
    return time.monotonic()


def _sleep(seconds: float) -> None:
    """Waits through a seam the tests replace."""
    time.sleep(seconds)


def _route(config: Any) -> str:
    """Returns the slug of the registered config ``config`` sends as.

    Raises:
        DFilterForgeError: Its settings or prices are no registered one's.
    """
    for path in sorted((ROOT / CONFIGS).glob("*.json")):
        registered = _read_config(path)
        if (registered.settings, registered.prices) == (
            config.settings,
            config.prices,
        ):
            return str(registered.settings.openrouter.provider_order[0])
    raise DFilterForgeError(
        "config_not_registered", "The judge note registers no such config"
    )


def _plan(arguments: argparse.Namespace) -> _Plan:
    """Builds the split's requests and checks the config and the cap.

    Raises:
        DFilterForgeError: The answer set, the config or the cap is not
            the registered one.
    """
    split = arguments.split
    requests = judge.build_requests(ROOT / RESULTS, split)
    config = _read_config(arguments.config)
    route = _route(config)
    usd = arguments.max_usd
    cap = round(usd * MICRO) if math.isfinite(usd) else 0
    dearest = max(
        _worst_case(prompt, config.prices, config.settings)
        for prompt in requests.batch.prompts
    )
    if not dearest <= cap <= round(CAPS[split] * MICRO):
        raise DFilterForgeError(
            "cap_invalid",
            f"--max-usd must fund one request and stay within {CAPS[split]}",
        )
    run_dir = ROOT / RUNS / f"{split}-{route}"
    return _Plan(requests, config, route, cap, run_dir)


def _fixed(plan: _Plan) -> dict[str, Any]:
    """The manifest fields every invocation of one run must share."""
    split = plan.requests.split
    return {
        "prompt_version": judge.PROMPT_VERSION,
        "split": split,
        "route": plan.route,
        "endpoint_host": _endpoint_host(plan.config),
        "settings": plan.config.settings,
        "prices": plan.config.prices,
        "max_attempts": MAX_ATTEMPTS,
        "min_interval_seconds": PACE_SECONDS,
        "sweep_wait_seconds": SWEEP_WAIT_SECONDS,
        "token_bound_rule": TOKEN_BOUND_RULE,
        "system_prompt_sha256": {
            mode: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for mode, text in judge.SYSTEM_PROMPTS.items()
        },
        "request_set_sha256": plan.requests.sha256,
        "requests": len(plan.requests.batch.prompts),
        "answer_set": judge.ANSWER_SETS[split],
    }


def _dry_run(arguments: argparse.Namespace) -> int:
    """Prints the answer set, the requests and their spend; sends nothing."""
    plan = _plan(arguments)
    prompts = plan.requests.batch.prompts
    sizes = [_prompt_bytes(prompt) for prompt in prompts]
    prices = plan.config.prices
    worst = [_worst_case(p, prices, plan.config.settings) for p in prompts]
    expected = sum(
        max(0.0, TOKENS_PER_BYTE * size + TOKENS_OFFSET)
        * prices.usd_per_million_input
        + REPLY_TOKENS * prices.usd_per_million_output
        for size in sizes
    )
    answers = plan.requests.answers
    silent = [a for a in answers if a.outcome is OutcomeV1.SILENT_WRONG]
    report = {
        "split": plan.requests.split,
        "route": plan.route,
        "endpoint_host": _endpoint_host(plan.config),
        "answers": len(answers),
        "outcomes": Counter(a.outcome.value for a in answers),
        "answers_by_run": Counter(a.run for a in answers),
        "silent_wrong_by_run": Counter(a.run for a in silent),
        "answers_by_condition": Counter(a.condition for a in answers),
        "items_and_filters": len(prompts) // len(judge.MODES),
        "of_them_silent_wrong": len(
            {(a.item_id, a.candidate_filter) for a in silent}
        ),
        "requests": len(prompts),
        "request_set_sha256": plan.requests.sha256,
        "mean_prompt_bytes": round(sum(sizes) / len(sizes), 1),
        "max_prompt_bytes": max(sizes),
        "expected_usd": round(expected / MICRO, 4),
        "worst_request_usd": max(worst) / MICRO,
        "worst_sweep_usd": sum(worst) / MICRO,
        "max_usd": arguments.max_usd,
        "run_dir": plan.run_dir.relative_to(ROOT).as_posix(),
        "run_dir_exists": plan.run_dir.exists(),
    }
    print(json.dumps(report, indent=2))
    return 0


def _read_run(path: Path) -> JudgeRunV1 | None:
    """Reads a run manifest, or returns None when there is none."""
    if not path.is_file():
        return None
    return JudgeRunV1.model_validate_json(path.read_bytes())


def _previous(plan: _Plan, resume: bool) -> JudgeRunV1 | None:
    """Reads the run a resume continues, or checks a fresh call has none.

    Raises:
        DFilterForgeError: A fresh call finds a run, a resume finds none,
            or the run was sent otherwise or stopped at the gate.
    """
    if not resume:
        if plan.run_dir.exists():
            raise DFilterForgeError("run_exists", "Resume the existing run")
        return None
    previous = _read_run(plan.run_dir / MANIFEST)
    if previous is None:
        raise DFilterForgeError("run_missing", "There is no run to resume")
    fixed = _fixed(plan)
    sent = {name: getattr(previous, name) for name in fixed}
    if canonical_json(sent) != canonical_json(fixed):
        raise DFilterForgeError(
            "settings_changed", "The run was sent otherwise"
        )
    if previous.invocations[-1].stop_reason == "thinking_not_honoured":
        raise DFilterForgeError("run_gated", "The thinking gate ended this run")
    return previous


def _history(plan: _Plan, log: Path) -> dict[str, list[Any]]:
    """Every attempt the run has recorded, by request, oldest first.

    Raises:
        DFilterForgeError: The log is torn or names an unknown request.
    """
    history: dict[str, list[Any]] = {
        prompt.item_id: [] for prompt in plan.requests.batch.prompts
    }
    for attempt in _attempt_records(log.read_bytes()):
        entries = history.get(attempt.completion.item_id)
        if entries is None:
            raise DFilterForgeError(
                "attempt_log_invalid", "The attempt log names no request"
            )
        entries.append(attempt)
    return history


class _Sender:
    """Sends one run's owed requests, sweep after sweep, within its cap.

    ``history`` holds every attempt already recorded and grows in place;
    each new attempt is appended to ``log`` and fsynced before the next.
    """

    def __init__(
        self,
        plan: _Plan,
        client: Any,
        history: dict[str, list[Any]],
        log: TextIO,
    ) -> None:
        self.plan = plan
        self.client = client
        self.history = history
        self.log = log
        self.state = _Sending(spent=_charged(history))

    def sweeps(self) -> None:
        """Sends until no request is owed or the run stops.

        A request is owed while it has no final reply and attempts left,
        so none is sent more than three times. The least tried go first,
        so calls that an outage ends spread its faults over requests
        rather than spend one request's three attempts.
        """
        prompts = self.plan.requests.batch.prompts
        sweep = 0
        while self.state.stop is None:
            owed = sorted(
                (
                    prompt
                    for prompt in prompts
                    if not _settled(self.history[prompt.item_id], MAX_ATTEMPTS)
                ),
                key=lambda prompt: len(self.history[prompt.item_id]),
            )
            if not owed:
                return
            if sweep:
                _sleep(SWEEP_WAIT_SECONDS)
            sweep += 1
            for prompt in owed:
                if not self._send(prompt):
                    return

    def _send(self, prompt: PreparedPromptV1) -> bool:
        """Sends one attempt within the cap; False when the run stops."""
        config, state = self.plan.config, self.state
        worst = _worst_case(prompt, config.prices, config.settings)
        if state.spent + worst > self.plan.cap:
            state.stop = "budget"
            return False
        if state.last_start is not None:
            _sleep(max(0.0, PACE_SECONDS - (_monotonic() - state.last_start)))
        state.last_start = _monotonic()
        sent_at = datetime.now(timezone.utc)
        single = PreparedBatchV1(
            output_contract=prompt.output_contract,
            retrieval=prompt.retrieval,
            prompts=(prompt,),
        )
        reply: CompletionV1 = self.client.complete(single).completions[0]
        entries = self.history[prompt.item_id]
        attempt = AttemptV1(
            attempt=len(entries) + 1,
            sent_at=sent_at,
            charged_micro_usd=_charge(reply, prompt, config, worst),
            completion=reply,
        )
        _append_attempt(self.log, attempt)
        entries.append(attempt)
        state.spent += attempt.charged_micro_usd
        state.sent += 1
        state.faults = state.faults + 1 if reply.error_code in _FAULTS else 0
        if _retry_class(reply) == "stop":
            state.stop = "fatal_http"
        elif state.faults >= FAULT_LIMIT:
            state.stop = "unreachable"
        elif reply.status is CompletionStatusV1.COMPLETED and not state.gated:
            state.gated = True
            if thinking_state((reply,))[0] == "not_honoured":
                state.stop = "thinking_not_honoured"
        return state.stop is None


def _charged(history: dict[str, list[Any]]) -> int:
    """What every recorded attempt was charged, in micro-USD."""
    return sum(
        attempt.charged_micro_usd
        for entries in history.values()
        for attempt in entries
    )


def _record(
    plan: _Plan,
    previous: JudgeRunV1 | None,
    history: dict[str, list[Any]],
    invocation: InvocationV1,
) -> JudgeRunV1:
    """Replaces the run manifest whole, by one rename, and returns it."""
    states = [_state_of(entries, MAX_ATTEMPTS) for entries in history.values()]
    finished = invocation.finished_at is not None
    costs = [
        attempt.completion.cost_usd
        for entries in history.values()
        for attempt in entries
        if attempt.completion.cost_usd is not None
    ]
    manifest = JudgeRunV1(
        **_fixed(plan),
        created_at=(
            invocation.started_at if previous is None else previous.created_at
        ),
        invocations=(*(previous.invocations if previous else ()), invocation),
        # A gate stop ends the run even when it read the last owed reply.
        status=(
            "complete"
            if finished
            and "pending" not in states
            and invocation.stop_reason != "thinking_not_honoured"
            else "incomplete"
        ),
        completed=states.count("completed"),
        failed=states.count("failed"),
        pending=states.count("pending"),
        attempts_sha256=file_sha256(plan.run_dir / ATTEMPTS),
        charged_usd_upper_bound=_recorded_usd(_charged(history) / MICRO),
        provider_reported_usd=(
            _recorded_usd(math.fsum(costs)) if costs else None
        ),
    )
    staging = plan.run_dir / f".{MANIFEST}.partial"
    staging.write_bytes((canonical_json(manifest) + "\n").encode("utf-8"))
    os.replace(staging, plan.run_dir / MANIFEST)
    return manifest


def _standing_route() -> str | None:
    """Returns the route J2 leaves standing for the test study, if any yet.

    DeepInfra stands once its published dev check gave every request a
    completed reply. GMICloud stands once its own gave one to any request
    (none is J3's case, which a correction decides), and only after the
    DeepInfra check, moved to the evidence, left a request without one.
    """
    dev = _read_run(ROOT / PUBLISHED / "dev" / MANIFEST)
    if dev is None or dev.status != "complete" or not dev.completed:
        return None
    if dev.route == ROUTES[0]:
        return None if dev.failed else ROUTES[0]
    moved = _read_run(ROOT / MOVED / MANIFEST)
    if moved is None or (moved.split, moved.route) != ("dev", ROUTES[0]):
        return None
    rerun = dev.route == ROUTES[1] and moved.status == "complete"
    return ROUTES[1] if rerun and moved.failed else None


def _require_standing_route(plan: _Plan) -> None:
    """Refuses a test call J2 does not allow.

    Raises:
        DFilterForgeError: The other route holds a test run, or the
            published dev checks do not leave this route standing.
    """
    if plan.requests.split != "test":
        return
    other = ROUTES[1] if plan.route == ROUTES[0] else ROUTES[0]
    published = _read_run(ROOT / PUBLISHED / "test" / MANIFEST)
    if (ROOT / RUNS / f"test-{other}").exists() or (
        published is not None and published.route != plan.route
    ):
        raise DFilterForgeError(
            "route_fixed", "A test run on the other route exists"
        )
    standing = _standing_route()
    if standing != plan.route:
        raise DFilterForgeError(
            "route_not_standing",
            f"The published dev checks leave {standing or 'no route'} standing",
        )


def _report(plan: _Plan, manifest: JudgeRunV1) -> None:
    """Prints the call that just ended and the run's census on one line."""
    census = {"status", "completed", "failed", "pending"}
    counts = manifest.model_dump(include=census | {"charged_usd_upper_bound"})
    run = plan.run_dir.relative_to(ROOT).as_posix()
    last = manifest.invocations[-1].model_dump(mode="json")
    print(canonical_json({"run": run, **last, **counts}))


def _call(arguments: argparse.Namespace) -> int:
    """Sends every owed request of one run within the cap.

    Raises:
        DFilterForgeError: A check before the first request refuses.
    """
    plan = _plan(arguments)
    _require_standing_route(plan)
    previous = _previous(plan, arguments.resume)
    if not os.environ.get(API_KEY_ENV):
        raise DFilterForgeError(
            "api_key_missing", "The model API credential is not set"
        )
    client = _client(plan.config)
    log = plan.run_dir / ATTEMPTS
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch()
    history = _history(plan, log)
    started = InvocationV1(
        started_at=datetime.now(timezone.utc),
        max_usd=arguments.max_usd,
        attempts_sent=0,
    )
    _record(plan, previous, history, started)
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        sender = _Sender(plan, client, history, handle)
        try:
            sender.sweeps()
        except KeyboardInterrupt:
            sender.state.stop = "interrupted"
        except OSError:
            # Requests may already be billed: keep the run for a resume.
            sender.state.stop = "io_error"
    ended = InvocationV1(
        started_at=started.started_at,
        finished_at=datetime.now(timezone.utc),
        max_usd=started.max_usd,
        attempts_sent=sender.state.sent,
        stop_reason=sender.state.stop,
    )
    manifest = _record(plan, previous, history, ended)
    _report(plan, manifest)
    if sender.state.stop == "io_error":
        _print_error("io_error", "The attempt log could not be written")
    if sender.state.stop in STOPS:
        return EXIT_STOPPED
    return EXIT_PENDING if manifest.pending else 0


def _publish(arguments: argparse.Namespace) -> int:
    """Copies one complete run to docs/results/judge-v2/<split>/.

    It prints the run's census and each mode's verdicts, which the note's
    Order step 4 checks before any test request.

    Raises:
        DFilterForgeError: The run is not a complete one of that split and
            route, its log is not the one its manifest records or holds a
            credential, or another run is published there.
    """
    run_dir = ROOT / RUNS / f"{arguments.split}-{arguments.route}"
    files = {
        name: _regular_file(run_dir / name, MAX_RUN_FILE_BYTES)
        for name in (ATTEMPTS, MANIFEST)
    }
    manifest = JudgeRunV1.model_validate_json(files[MANIFEST])
    recorded = (manifest.status, manifest.split, manifest.route)
    digest = hashlib.sha256(files[ATTEMPTS]).hexdigest()
    if recorded != ("complete", arguments.split, arguments.route) or (
        digest != manifest.attempts_sha256
    ):
        raise DFilterForgeError(
            "run_incomplete", "That run is not complete as its manifest says"
        )
    # What the note's Order step 4 checks: how each completed reply parses.
    ratings: dict[str, Counter[str]] = {mode: Counter() for mode in judge.MODES}
    for attempt in _attempt_records(files[ATTEMPTS]):
        reply = attempt.completion
        if reply.status is CompletionStatusV1.COMPLETED:
            rating = judge.parse_verdict(reply) or "none"
            ratings[reply.item_id.split("-", 1)[0]][rating] += 1
    _scan_for_secrets(files)
    target = ROOT / PUBLISHED / arguments.split
    for name, data in files.items():
        if (target / name).is_file() and (target / name).read_bytes() != data:
            raise DFilterForgeError(
                "output_exists", "Another run is published there; remove it"
            )
    target.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (target / name).write_bytes(data)
    published = {
        "output": target.relative_to(ROOT).as_posix(),
        "completed": manifest.completed,
        "failed": manifest.failed,
        "ratings": ratings,
    }
    print(canonical_json(published))
    return 0


def _published_test(
    results: Path,
) -> tuple[judge.RequestSet, dict[str, CompletionV1], dict[str, str]]:
    """Reads the published test run against the requests built now.

    Returns:
        The requests, each one's final completed reply by request id, and
        the inputs' SHA-256 digests by repository path.

    Raises:
        DFilterForgeError: The published run is not a complete run of the
            requests the committed code builds now.
    """
    published = results / judge.PROMPT_VERSION / "test"
    files = {
        name: _regular_file(published / name, MAX_RUN_FILE_BYTES)
        for name in (ATTEMPTS, MANIFEST)
    }
    manifest = JudgeRunV1.model_validate_json(files[MANIFEST])
    requests = judge.build_requests(results, "test")
    sources = {
        f"docs/results/{run}/scored/outcomes.jsonl": pin
        for run, pin in judge.ANSWER_SETS["test"].items()
    }
    for name, data in files.items():
        sources[(PUBLISHED / "test" / name).as_posix()] = hashlib.sha256(
            data
        ).hexdigest()
    log = sources[(PUBLISHED / "test" / ATTEMPTS).as_posix()]
    if (manifest.status, manifest.request_set_sha256, log) != (
        "complete",
        requests.sha256,
        manifest.attempts_sha256,
    ):
        raise DFilterForgeError(
            "run_mismatch", "The published run answers other requests"
        )
    replies: dict[str, CompletionV1] = {}
    for attempt in _attempt_records(files[ATTEMPTS]):
        if attempt.completion.status is CompletionStatusV1.COMPLETED:
            replies.setdefault(attempt.completion.item_id, attempt.completion)
    return requests, replies, sources


def _table(arguments: argparse.Namespace) -> int:
    """Writes or checks the table from the published test run.

    Raises:
        DFilterForgeError: The published run is not a complete run of the
            requests the committed code builds now.
    """
    results: Path = arguments.results
    table = judge.build_table(*_published_test(results))
    rebuilt = (canonical_json(table) + "\n").encode("utf-8")
    target = results / TABLE
    if arguments.check:
        current = target.read_bytes() if target.is_file() else None
        if current != rebuilt:
            print(f"{TABLE.as_posix()} is not its rebuild", file=sys.stderr)
            return EXIT_DIFFERS
        return 0
    target.write_bytes(rebuilt)
    return 0


def _parser() -> argparse.ArgumentParser:
    """The runner's four steps and their arguments."""
    parser = argparse.ArgumentParser(description="Run the judge study.")
    steps = parser.add_subparsers(dest="name", required=True)
    for name, step in (("dry-run", _dry_run), ("call", _call)):
        sending = steps.add_parser(name)
        sending.add_argument("--split", choices=("dev", "test"), required=True)
        sending.add_argument("--config", type=Path, required=True)
        sending.add_argument("--max-usd", type=float, required=True)
        if step is _call:
            sending.add_argument("--resume", action="store_true")
        sending.set_defaults(step=step)
    publish = steps.add_parser("publish")
    publish.add_argument("--split", choices=("dev", "test"), required=True)
    publish.add_argument("--route", choices=ROUTES, required=True)
    publish.set_defaults(step=_publish)
    table = steps.add_parser("table")
    table.add_argument("--results", type=Path, default=ROOT / RESULTS)
    table.add_argument("--check", action="store_true")
    table.set_defaults(step=_table)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs one step and returns its exit code."""
    arguments = _parser().parse_args(argv)
    try:
        return int(arguments.step(arguments))
    except DFilterForgeError as error:
        refusal = (error.code, str(error))
    except ValidationError:
        refusal = ("schema_invalid", "An input does not match its schema")
    except OSError:
        refusal = ("io_error", "A file operation failed")
    _print_error(*refusal)
    return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
