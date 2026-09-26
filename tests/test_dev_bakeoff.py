"""The bake-off batch decides from run directories and never guesses.

Every run directory here is written from the real contracts
(``RunManifestV1``, ``AttemptV1``, ``CompletionV1``) over a synthetic
160-prompt dev set, and the call step is replaced by a scripted fake, so
nothing is sent anywhere. The tests of the committed configurations skip
where the test image carries no docs/ tree.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import dataclasses
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import ModuleType
from typing import Any, Literal

import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.generation import ChatMessageV1
from dfilterforge.generation import ConditionLabel
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1

_ROOT = Path(__file__).resolve().parents[1]
Fields = dict[str, Any]
Answers = list[tuple[str, int, Fields]]
Step = Callable[["Synth", list[str]], Any]
StopReason = Literal["budget", "fatal_http", "thinking_not_honoured"] | None


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


db = _load("dev_bakeoff")
dbc = _load("dev_bakeoff_configs")
_TEST_KEY = "DFILTERFORGE_BAKEOFF_TEST_ONLY"
_LABELS: tuple[ConditionLabel, ...] = ("C1", "C2", "C3", "C4")
_CONDITIONS: dict[ConditionLabel, tuple[OutputContractV1, RetrievalV1]] = {
    "C1": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    "C2": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    "C3": (OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    "C4": (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
}
_ITEM_IDS = tuple(
    f"mei-{index:04d}" for index in (*range(1, 25), *range(501, 517))
)
ANCHOR = db.ANCHOR
SMALL_1 = db.PLAN["small"][0]
SMALL_2 = db.PLAN["small"][1]
SMALL_3 = db.PLAN["small"][2]
MID_2 = db.PLAN["mid"][1]
RESERVE_SMALL = db.PLAN["reserve-small"][0]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_prepare(directory: Path) -> None:
    """Writes a 160-prompt dev set shaped like the committed one."""
    conditions: list[PreparedConditionV1] = []
    for label in _LABELS:
        contract, retrieval = _CONDITIONS[label]
        user: dict[str, object] = {"request": "dns queries"}
        if retrieval is RetrievalV1.LEXICAL:
            user["retrieved_fields"] = []
        batch = PreparedBatchV1(
            output_contract=contract,
            retrieval=retrieval,
            prompts=tuple(
                PreparedPromptV1(
                    item_id=item,
                    split="dev",
                    output_contract=contract,
                    retrieval=retrieval,
                    messages=(
                        ChatMessageV1(role="system", content="S" * (400 + i)),
                        ChatMessageV1(
                            role="user",
                            content="INPUT_JSON\n" + canonical_json(user),
                        ),
                    ),
                )
                for i, item in enumerate(_ITEM_IDS)
            ),
        )
        path = directory / "prepared" / f"{label}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (canonical_json(batch) + "\n").encode("utf-8")
        path.write_bytes(data)
        conditions.append(
            PreparedConditionV1(
                label=label,
                output_contract=contract,
                retrieval=retrieval,
                path=f"prepared/{label}.json",
                sha256=_sha256(data),
                system_prompt_sha256="0" * 64,
                prompt_count=len(_ITEM_IDS),
            )
        )
    manifest = PrepareManifestV1(
        prepare_id="dev-synthetic-2026-09-26",
        created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        source_revision="test",
        source_files={},
        split="dev",
        item_ids=_ITEM_IDS,
        model_inputs_sha256="0" * 64,
        catalog=CatalogIdentityV1(
            file_name="catalog.sqlite3",
            file_sha256="0" * 64,
            sqlite_sha256="0" * 64,
            catalog_hash="0" * 64,
            tshark_version="4.6.8",
        ),
        top_k=16,
        conditions=tuple(conditions),
    )
    (directory / "prepare.json").write_bytes(
        (canonical_json(manifest) + "\n").encode("utf-8")
    )


def _endpoint(tag: str, **extra: Any) -> dict[str, Any]:
    """One endpoint as OpenRouter's keyless metadata lists it."""
    return {
        "tag": tag,
        "provider_name": tag.split("/", 1)[0].title(),
        "quantization": "bf16",
        "status": 0,
        "max_completion_tokens": 8192,
        "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
        "supported_parameters": [*dbc.SENT_PARAMETERS, "reasoning"],
    } | extra


def _metadata(spec: Any) -> dict[str, Any]:
    """Endpoints under which each spec's slug keeps the note's rule."""
    provider = spec.route.split("/", 1)[0]
    if "/" in spec.route:
        tags = [spec.route, f"{provider}/fast"]
    elif spec.spans_endpoints:
        tags = [provider, f"{provider}/zdr", f"{provider}/eu"]
    else:
        tags = [f"{provider}/bf16"]
    return {"endpoints": [_endpoint(tag) for tag in tags]}


@pytest.fixture(name="template", scope="module")
def fixture_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A synthetic prompt set and one configuration per spec."""
    root = tmp_path_factory.mktemp("bakeoff")
    _write_prepare(root / "prepare")
    config_dir = root / "configs"
    config_dir.mkdir()
    for spec in dbc.SPECS:
        config, _ = dbc.build_config(
            spec, _metadata(spec), "2026-09-26T00:00:00Z"
        )
        (config_dir / f"{spec.name}.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
    return root


@pytest.fixture(name="ctx")
def fixture_ctx(
    template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """A context over a private copy of the prompts; nothing is invoked.

    The wait before a resume is recorded in ``ctx.slept`` instead.
    """
    prepare = tmp_path / "prepare"
    shutil.copytree(template / "prepare", prepare)
    layout = db.Layout(
        prepare,
        template / "prepare",
        template / "configs",
        tmp_path / "out",
        _sha256((prepare / "prepare.json").read_bytes())[:12],
    )
    context = db.build_context(layout, "test-rev")
    context.out_dir.mkdir()
    printed: list[str] = []
    context.printed = printed
    context.out = printed.append
    context.invoke = _no_invoke
    slept: list[float] = []
    context.slept = slept
    monkeypatch.setattr(db, "pause", slept.append)
    return context


def _no_invoke(argv: Sequence[str], with_key: bool) -> Any:
    raise AssertionError(f"unexpected call {argv} {with_key}")


def ok(provider: str = "DeepInfra", **extra: Any) -> Fields:
    """A completed answer with a reported zero reasoning count."""
    return {
        "status": "completed",
        "response_text": "{}",
        "latency_ms": 1.0,
        "http_status": 200,
        "provider": provider,
        "finish_reason": "stop",
        "reasoning_tokens": 0,
        "reasoning_present": False,
        "prompt_tokens": 300,
        "completion_tokens": 100,
        "cost_usd": 0.00001,
    } | extra


REASONED = ok(reasoning_tokens=40)
BARE = ok(reasoning_tokens=None, reasoning_present=None)
TIMEOUT: Fields = {
    "status": "failed",
    "error_code": "timeout",
    "latency_ms": 1.0,
}
# A final failure the model gave, which no resume sends again.
PROVIDER_ERROR: Fields = {
    "status": "failed",
    "error_code": "provider_error",
    "latency_ms": 1.0,
    "http_status": 200,
    "provider_error_code": "upstream_refused",
}


def http(status: int) -> Fields:
    """A non-2xx reply as the client records it."""
    return {
        "status": "failed",
        "error_code": "http_error",
        "latency_ms": 1.0,
        "http_status": status,
    }


class Synth:
    """Writes one run directory exactly as the call step shapes it."""

    def __init__(self, ctx: Any, run_id: str, config: str) -> None:
        self.model_run = ctx.model_run
        self.run_dir = ctx.prepare_dir / "runs" / run_id
        self.run_id = run_id
        self.prepare_bytes = (ctx.prepare_dir / "prepare.json").read_bytes()
        self.prepare = PrepareManifestV1.model_validate_json(self.prepare_bytes)
        self.config = self.model_run.CallConfigV1.model_validate_json(
            Path(ctx.endpoints[config].config_path).read_bytes()
        )
        self.attempts: dict[str, dict[str, list[Any]]] = {
            label: {item: [] for item in _ITEM_IDS} for label in _LABELS
        }
        self.invocations: list[InvocationV1] = []
        self.clock = datetime(2026, 9, 27, tzinfo=timezone.utc)
        if (self.run_dir / "run_manifest.json").exists():
            self._reload()

    def _reload(self) -> None:
        manifest = RunManifestV1.model_validate_json(
            (self.run_dir / "run_manifest.json").read_bytes()
        )
        self.invocations = list(manifest.invocations)
        for label in _LABELS:
            path = self.run_dir / "attempts" / f"{label}.jsonl"
            for line in path.read_bytes().split(b"\n"):
                if line:
                    attempt = self.model_run.AttemptV1.model_validate_json(line)
                    item = attempt.completion.item_id
                    self.attempts[label][item].append(attempt)
                    self.clock = max(self.clock, attempt.sent_at)
        for invocation in self.invocations:
            self.clock = max(self.clock, invocation.finished_at)

    def _tick(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    def unsettled(self) -> list[tuple[str, int]]:
        """Lists the prompts a further pass would still send, in order."""
        return [
            (label, index)
            for label in _LABELS
            for index, item in enumerate(_ITEM_IDS)
            if not self.model_run._is_settled(
                self.attempts[label][item], db.MAX_ATTEMPTS
            )
        ]

    def invoke(
        self, max_usd: float, stop_reason: StopReason, answers: Answers
    ) -> dict[str, Any]:
        """Records one invocation and returns the report it would print."""
        started = self._tick()
        for label, index, fields in answers:
            item = _ITEM_IDS[index]
            entries = self.attempts[label][item]
            entries.append(
                self.model_run.AttemptV1(
                    attempt=len(entries) + 1,
                    sent_at=self._tick(),
                    charged_micro_usd=10,
                    completion=CompletionV1(item_id=item, **fields),
                )
            )
        self.invocations.append(
            InvocationV1(
                source_revision="test",
                source_files={},
                started_at=started,
                finished_at=self._tick(),
                max_usd=max_usd,
                requests_sent=len(answers),
                stop_reason=stop_reason,
            )
        )
        manifest = self.write()
        return {
            "run_id": self.run_id,
            "status": manifest.status,
            "requests_sent": len(answers),
            "charged_usd_upper_bound": manifest.charged_usd_upper_bound,
            "stop_reason": stop_reason,
        }

    def write(self) -> RunManifestV1:
        """Writes the logs and the manifest, census included."""
        (self.run_dir / "attempts").mkdir(parents=True, exist_ok=True)
        census: dict[ConditionLabel, tuple[list[str], Path]] = {}
        for label in _LABELS:
            log = self.run_dir / "attempts" / f"{label}.jsonl"
            log.write_text(
                "".join(
                    attempt.model_dump_json() + "\n"
                    for item in _ITEM_IDS
                    for attempt in self.attempts[label][item]
                ),
                encoding="utf-8",
                newline="\n",
            )
            census[label] = (
                [
                    self.model_run._prompt_state(
                        self.attempts[label][item], db.MAX_ATTEMPTS
                    )
                    for item in _ITEM_IDS
                ],
                log,
            )
        complete = all("pending" not in states for states, _ in census.values())
        conditions: list[ConditionRunV1] = []
        for label, (states, log) in census.items():
            digest = None
            if complete:
                path = self.run_dir / "completions" / f"{label}.json"
                path.parent.mkdir(exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
                digest = _sha256(path.read_bytes())
            conditions.append(
                ConditionRunV1(
                    label=label,
                    attempts_path=f"attempts/{label}.jsonl",
                    attempts_sha256=_sha256(log.read_bytes()),
                    completions_path=(
                        f"completions/{label}.json" if complete else None
                    ),
                    completions_sha256=digest,
                    attempts={
                        item: len(self.attempts[label][item])
                        for item in _ITEM_IDS
                    },
                    completed=states.count("completed"),
                    failed=states.count("failed"),
                    pending=states.count("pending"),
                )
            )
        manifest = RunManifestV1(
            run_id=self.run_id,
            created_at=self.invocations[0].started_at,
            prepare=self.prepare,
            prepare_sha256=_sha256(self.prepare_bytes),
            endpoint_host="openrouter.ai",
            settings=self.config.settings,
            prices=self.config.prices,
            max_attempts=db.MAX_ATTEMPTS,
            min_interval_seconds=db.MIN_INTERVAL_SECONDS,
            invocations=tuple(self.invocations),
            status="complete" if complete else "incomplete",
            charged_usd_upper_bound=sum(
                attempt.charged_micro_usd
                for history in self.attempts.values()
                for entries in history.values()
                for attempt in entries
            )
            / db.MICRO,
            provider_reported_usd=None,
            conditions=tuple(conditions),
        )
        (self.run_dir / "run_manifest.json").write_text(
            manifest.model_dump_json() + "\n", encoding="utf-8"
        )
        return manifest


def first(count: int, fields: Fields) -> Answers:
    """Answers the first ``count`` prompts in protocol order."""
    order = [(label, index) for label in _LABELS for index in range(40)]
    return [(label, index, fields) for label, index in order[:count]]


def rest(synth: Synth, fields: Fields) -> Answers:
    """Answers every prompt the run still owes an attempt."""
    return [(label, index, fields) for label, index in synth.unsettled()]


def with_first(synth: Synth, head: Fields, tail: Fields) -> Answers:
    """Answers what is owed, the first one with ``head``."""
    answers = rest(synth, tail)
    answers[0] = (answers[0][0], answers[0][1], head)
    return answers


def _synth(ctx: Any, target: Any) -> Synth:
    return Synth(ctx, target.run_id, target.config)


def _decide(ctx: Any, target: Any, cap_usd: float = 0.1) -> Any:
    return db.decide(ctx.view(target), db._micro(cap_usd))


class FakeCalls:
    """Plays scripted call-step invocations and records their argv."""

    def __init__(self, ctx: Any, script: list[Step]) -> None:
        self.ctx = ctx
        self.script = list(script)
        self.calls: list[tuple[list[str], bool]] = []

    def __call__(self, argv: Sequence[str], with_key: bool) -> Any:
        argv = list(argv)
        self.calls.append((argv, with_key))
        step = self.script.pop(0)
        run_id = argv[argv.index("--run-id") + 1]
        config = Path(argv[argv.index("--config") + 1]).stem
        return step(Synth(self.ctx, run_id, config), argv)

    def run_ids(self) -> list[str]:
        """Returns the run id of every recorded call, in order."""
        return [argv[argv.index("--run-id") + 1] for argv, _ in self.calls]


def _cap(argv: list[str]) -> float:
    return float(argv[argv.index("--max-usd") + 1])


def play(stop: StopReason, answers: Callable[[Synth], Answers]) -> Step:
    """A call step that records ``answers`` and stops with ``stop``."""

    def step(synth: Synth, argv: list[str]) -> Any:
        report = synth.invoke(_cap(argv), stop, answers(synth))
        return db.Invocation(
            0 if report["status"] == "complete" else 1, report, None
        )

    return step


def refuse(code: str) -> Step:
    """A call step that refuses before sending anything."""
    return lambda synth, argv: db.Invocation(2, None, code)


def raises(error: BaseException) -> Step:
    """A call step during which ``error`` reaches the batch."""

    def step(synth: Synth, argv: list[str]) -> Any:
        raise error

    return step


def _complete(ctx: Any, target: Any, fields: Fields = ok()) -> None:
    synth = _synth(ctx, target)
    synth.invoke(1.0, None, rest(synth, fields))


def _gate_stop(ctx: Any, target: Any) -> None:
    """Writes a pass whose first answer reasoned, which the gate stopped."""
    _synth(ctx, target).invoke(0.1, "thinking_not_honoured", first(1, REASONED))


def _outage(ctx: Any, target: Any) -> None:
    """Writes a pass whose every item met a 503 on all three attempts."""
    synth = _synth(ctx, target)
    for _ in range(db.MAX_ATTEMPTS):
        synth.invoke(0.1, None, rest(synth, http(503)))


def _drop_slot(ctx: Any, slot: str, keep: Sequence[Any] = ()) -> None:
    """Gate-stops every run of a slot's candidates but those in ``keep``."""
    for candidate in db.PLAN[slot]:
        if candidate not in keep:
            for target in db.targets(candidate):
                _gate_stop(ctx, target)


# The plan.


def test_run_ids_follow_the_registered_names(ctx: Any) -> None:
    model_run = ctx.model_run
    assert db.RESULT_DIR.pattern == model_run._RESULT_DIR.pattern
    assert db.MAX_USD == model_run._MAX_USD
    assert db.MAX_ATTEMPTS == model_run._MAX_ATTEMPTS
    assert ANCHOR.primary.run_id == "dev-qwen3-32b-2026-09-26"
    assert ANCHOR.primary.run_id == Path(db.PREPARE_DIR).name
    run_ids: list[str] = []
    for candidate in db.all_candidates():
        assert candidate.primary.run_id == f"dev-{candidate.name}-2026-09-26"
        if candidate.fallback is not None:
            assert candidate.fallback.run_id == (
                f"dev-{candidate.name}-fb-2026-09-26"
            )
        run_ids.extend(target.run_id for target in db.targets(candidate))
    assert len(run_ids) == len(set(run_ids)) == 21
    assert all(model_run._RESULT_DIR.fullmatch(r) for r in run_ids)


def test_outage_re_runs_have_registered_ids(ctx: Any) -> None:
    assert db.rerun_of(SMALL_1.primary) == db.Target(
        SMALL_1.primary.config, "dev-qwen3.5-9b-r2-2026-09-26"
    )
    assert db.rerun_of(SMALL_1.fallback) == db.Target(
        SMALL_1.fallback.config, "dev-qwen3.5-9b-fb-r2-2026-09-26"
    )
    assert db.rerun_of(ANCHOR.primary).run_id == "dev-qwen3-32b-r2-2026-09-26"
    registered = [
        target.run_id
        for candidate in db.all_candidates()
        for target in db.registered_targets(candidate)
    ]
    assert len(registered) == len(set(registered)) == 42
    assert "dev-nemotron-3-super-120b-a12b-fb-r2-2026-09-26" in registered
    assert all(ctx.model_run._RESULT_DIR.fullmatch(r) for r in registered)


def test_fallbacks_are_the_listed_ones(ctx: Any) -> None:
    specs = {spec.name: spec for spec in dbc.SPECS}
    planned = {t.config for c in db.all_candidates() for t in db.targets(c)}
    assert planned == set(specs)
    assert SMALL_2.name == "ministral-8b-2512" and SMALL_2.fallback is None
    primary = specs[MID_2.primary.config]
    fallback = specs[MID_2.fallback.config]
    assert (primary.model_id, primary.route, primary.reasoning) == (
        "mistralai/mistral-medium-3-5",
        "mistral",
        "effort_none",
    )
    assert (fallback.model_id, fallback.route, fallback.reasoning) == (
        "mistralai/mistral-medium-3-5",
        "mistral",
        "enabled_false",
    )
    for slot in ("anchor", "reserve-small", "reserve-mid", "reserve-frontier"):
        assert all(c.fallback is None for c in db.PLAN[slot])
    assert ctx.endpoints[SMALL_2.primary.config].route == "mistral"


def test_call_argv_pins_one_pass_at_the_cap(ctx: Any) -> None:
    endpoint = ctx.endpoints[SMALL_1.primary.config]
    argv = db.call_argv(SMALL_1.primary, endpoint, 100_000, False, "abc")
    assert argv[1:3] == [db.MODEL_RUN, "call"]
    pairs = dict(zip(argv[3:-1:2], argv[4::2]))
    assert pairs == {
        "--prepare-dir": db.PREPARE_DIR,
        "--run-id": SMALL_1.primary.run_id,
        "--config": endpoint.config_path,
        "--max-usd": "0.100000",
        "--source-revision": "abc",
        "--min-interval-seconds": "1.0",
        "--max-attempts": "3",
    }
    assert argv[-1] == "--gate-first"
    resumed = db.call_argv(SMALL_1.primary, endpoint, 100_000, True, "abc")
    assert resumed == [*argv, "--resume"]


def test_worst_case_matches_the_call_step(ctx: Any, template: Path) -> None:
    model_run = ctx.model_run
    for name, endpoint in ctx.endpoints.items():
        config = model_run.CallConfigV1.model_validate_json(
            (template / "configs" / f"{name}.json").read_bytes()
        )
        worst: list[int] = []
        for label in _LABELS:
            batch = PreparedBatchV1.model_validate_json(
                (ctx.prepare_dir / "prepared" / f"{label}.json").read_bytes()
            )
            for prompt in batch.prompts:
                expected = model_run._worst_case_micro_usd(
                    prompt, config.prices, config.settings
                )
                assert expected == db.worst_case_micro_usd(
                    model_run._prompt_bytes(prompt),
                    endpoint.prices.usd_per_million_input,
                    endpoint.prices.usd_per_million_output,
                )
                worst.append(expected)
        assert endpoint.worst_micro_usd == max(worst)
        assert endpoint.pass_worst_micro_usd == sum(worst)


def test_plan_refuses_a_tight_cap_and_a_repeated_run(ctx: Any) -> None:
    tight = db.Candidate(
        "small", "1", "x", SMALL_1.primary, None, SMALL_1.cap_usd / 1000
    )
    with pytest.raises(db.PlanError, match="too tight"):
        db.check_plan([tight], ctx.endpoints)
    with pytest.raises(db.PlanError, match="used twice"):
        db.check_plan([SMALL_1, SMALL_1], ctx.endpoints)
    undated = db.Candidate(
        "small",
        "1",
        "x",
        db.Target(SMALL_1.primary.config, "dev-x-2026-09-27"),
        None,
        0.1,
    )
    with pytest.raises(db.PlanError, match="prepare's date"):
        db.check_plan([undated], ctx.endpoints)
    with pytest.raises(db.PlanError, match="CLI bound"):
        db.check_plan(
            [db.Candidate("s", "1", "x", SMALL_1.primary, None, 13)],
            ctx.endpoints,
        )
    too_long = db.Candidate(
        "small",
        "1",
        "x",
        db.Target(SMALL_1.primary.config, f"dev-{'a' * 30}-2026-09-26"),
        None,
        0.1,
    )
    with pytest.raises(db.PlanError, match="-r2-2026-09-26: not a result"):
        db.check_plan([too_long], ctx.endpoints)


def test_prompt_set_must_be_the_committed_one(ctx: Any, template: Path) -> None:
    committed = template / "prepare"
    prefix = _sha256((committed / "prepare.json").read_bytes())[:12]
    db.check_prepare(ctx.prepare_dir, committed, prefix)
    with pytest.raises(db.PlanError, match="does not hash"):
        db.check_prepare(ctx.prepare_dir, committed, "c7cfabf91dd1")
    path = ctx.prepare_dir / "prepared" / "C3.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(db.PlanError, match="C3.json differs"):
        db.check_prepare(ctx.prepare_dir, committed, prefix)


def test_tooling_covers_the_pre_registration_and_thinking_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for path in (
        "docs/protocol.md",
        "docs/decisions/model-bakeoff.md",
        "src/dfilterforge/completions.py",
    ):
        assert path in db.TOOLING
    asked: list[tuple[str, ...]] = []

    def git(*args: str) -> str:
        asked.append(args)
        return " M docs/protocol.md\n?? docs/decisions/model-bakeoff.md\n"

    monkeypatch.setattr(db, "_git", git)
    assert db.tooling_changes() == [
        " M docs/protocol.md",
        "?? docs/decisions/model-bakeoff.md",
    ]
    assert asked == [
        ("status", "--porcelain", "--untracked-files=all", "--", *db.TOOLING)
    ]


def test_the_attempt_classes_are_the_call_steps(ctx: Any) -> None:
    classes = {"answer": "final", "account": "stop", "transient": "retry"}
    transport: Fields = {
        "status": "failed",
        "error_code": "transport_error",
        "latency_ms": 1.0,
    }
    cases: list[Fields] = [
        ok(),
        TIMEOUT,
        PROVIDER_ERROR,
        transport,
        *(http(code) for code in (400, 401, 402, 403, 404, 408, 413, 422)),
        *(http(code) for code in (429, 500, 502, 503, 504, 599)),
    ]
    for fields in cases:
        completion = CompletionV1(item_id="mei-0001", **fields)
        kind = db.attempt_kind(completion)
        assert classes.get(kind, "final") == ctx.model_run._retry_class(
            completion
        )
    assert db.ACCOUNT_STATUSES == ctx.model_run._STOP_STATUSES
    assert db.TRANSIENT_STATUSES == ctx.model_run._RETRY_STATUSES
    assert db.TRANSIENT_CODES == ctx.model_run._RETRY_CODES


# What one run's directory says comes next.


def test_absent_run_starts(ctx: Any) -> None:
    assert _decide(ctx, SMALL_1.primary) == ("start", "not_started")


@pytest.mark.parametrize(
    ("stop", "answers", "reason"),
    [
        ("thinking_not_honoured", first(1, REASONED), "first_answer_reasoned"),
        (
            "thinking_not_honoured",
            first(1, http(503)) + [("C1", 1, ok(reasoning_present=True))],
            "first_answer_reasoned",
        ),
        (None, first(3, http(503)) + first(5, REASONED)[3:], "first_answer_"),
        (None, first(160, http(404)), "no_answer_refused_http_404"),
        (
            None,
            first(80, http(400)) + first(160, http(404))[80:],
            "no_answer_refused_http_400_404",
        ),
    ],
)
def test_fallback_follows_only_a_reasoned_first_answer_or_refusal(
    ctx: Any, stop: StopReason, answers: Answers, reason: str
) -> None:
    _synth(ctx, SMALL_1.primary).invoke(0.1, stop, answers)
    action = _decide(ctx, SMALL_1.primary)
    assert action.kind == "fallback" and action.reason.startswith(reason)


@pytest.mark.parametrize(
    ("stop", "answers", "expected"),
    [
        (None, first(1, http(503)) + first(160, ok())[1:], "resume"),
        (None, first(2, TIMEOUT) + first(160, ok())[2:], "resume"),
        (None, first(1, http(429)) + first(160, ok())[1:], "resume"),
        ("fatal_http", first(1, http(402)), "resume"),
        ("fatal_http", first(1, http(403)), "resume"),
        ("fatal_http", [("C1", 0, http(429)), ("C1", 1, http(403))], "resume"),
        ("fatal_http", first(5, ok()) + [("C1", 5, http(403))], "resume"),
        ("budget", first(12, ok()), "stopped"),
        (None, first(1, http(404)) + first(160, http(500))[1:], "resume"),
        (None, first(160, PROVIDER_ERROR), "outage"),
        (None, first(159, http(404)) + [("C4", 39, PROVIDER_ERROR)], "outage"),
        ("budget", first(20, TIMEOUT), "outage"),
        (None, first(160, ok(provider="Parasail")), "done"),
        (None, first(159, ok()) + [("C4", 39, http(400))], "done"),
    ],
)
def test_other_anomalies_never_earn_a_fallback(
    ctx: Any, stop: StopReason, answers: Answers, expected: str
) -> None:
    _synth(ctx, SMALL_1.primary).invoke(0.1, stop, answers)
    assert _decide(ctx, SMALL_1.primary).kind == expected


def test_only_transient_failures_make_an_outage(ctx: Any) -> None:
    _outage(ctx, SMALL_1.primary)
    assert ctx.view(SMALL_1.primary).manifest.status == "complete"
    assert _decide(ctx, SMALL_1.primary) == (
        "outage",
        "no_answer_only_transient_failures",
    )
    synth = _synth(ctx, SMALL_2.primary)
    synth.invoke(0.1, "fatal_http", first(1, http(403)))
    for _ in range(db.MAX_ATTEMPTS):
        synth.invoke(0.1, None, rest(synth, http(503)))
    assert _decide(ctx, SMALL_2.primary) == (
        "outage",
        "no_answer_other_failures",
    )


def test_a_budget_spent_on_timeouts_is_an_outage_not_a_budget_stop(
    ctx: Any,
) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(SMALL_1.cap_usd, "budget", first(20, TIMEOUT))
    assert ctx.view(SMALL_1.primary).manifest.status != "complete"
    assert _decide(ctx, SMALL_1.primary, 0.1) == (
        "outage",
        "no_answer_budget_spent_on_failures",
    )
    row = db.run_row(
        ctx.view(SMALL_1.primary),
        ctx.endpoints[SMALL_1.primary.config],
        db._micro(SMALL_1.cap_usd),
    )
    assert row["commit_to"] == (
        f"docs/decisions/evidence/bakeoff/{SMALL_1.primary.run_id}/"
    )


def test_a_complete_pass_without_answers_is_evidence_not_a_result(
    ctx: Any,
) -> None:
    for target, answers in (
        (SMALL_1.primary, first(160, PROVIDER_ERROR)),
        (SMALL_2.primary, first(160, http(404))),
    ):
        _synth(ctx, target).invoke(0.1, None, answers)
        assert ctx.view(target).manifest.status == "complete"
        row = db.run_row(
            ctx.view(target),
            ctx.endpoints[target.config],
            db._micro(0.1),
        )
        assert row["commit_to"] == (
            f"docs/decisions/evidence/bakeoff/{target.run_id}/"
        )


def test_a_later_answer_that_reasons_is_a_drop(ctx: Any) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(0.1, None, with_first(synth, ok(), http(503)))
    synth.invoke(
        0.1, "thinking_not_honoured", with_first(synth, REASONED, ok())[:1]
    )
    assert _decide(ctx, SMALL_1.primary) == (
        "reasoned",
        "a_later_answer_reasoned",
    )


def test_a_budget_stop_resumes_only_under_a_raised_cap(ctx: Any) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(SMALL_1.cap_usd, "budget", first(12, ok()))
    assert _decide(ctx, SMALL_1.primary, 0.1) == ("stopped", "budget")
    ctx.invoke = FakeCalls(ctx, [])
    with pytest.raises(db.BatchStop, match="raise the candidate's cap"):
        db.run_candidate(SMALL_1, ctx)
    assert not ctx.invoke.calls
    assert _decide(ctx, SMALL_1.primary, 0.15) == (
        "resume",
        "148_items_pending_cap_raised",
    )
    raised = dataclasses.replace(SMALL_1, cap_usd=0.15)
    ctx.invoke = FakeCalls(ctx, [play(None, lambda s: rest(s, ok()))])
    assert db.run_candidate(raised, ctx) == ("done", "complete")
    ((argv, _),) = ctx.invoke.calls
    assert "--resume" in argv and _cap(argv) == 0.15
    assert not ctx.slept


def test_unreadable_runs_stop_for_the_owner(ctx: Any) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(0.1, None, first(3, http(503)))
    log = synth.run_dir / "attempts" / "C1.jsonl"
    log.write_bytes(log.read_bytes() + b'{"attempt": 1')
    assert _decide(ctx, SMALL_1.primary) == ("stopped", "attempt_log_torn")
    log.write_bytes(b"{}\n")
    assert _decide(ctx, SMALL_1.primary) == ("stopped", "attempt_log_invalid")
    manifest = synth.run_dir / "run_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    assert _decide(ctx, SMALL_1.primary) == ("stopped", "manifest_invalid")
    manifest.unlink()
    assert _decide(ctx, SMALL_1.primary) == ("stopped", "manifest_missing")


def test_invocation_limit_stops_for_the_owner(ctx: Any) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(0.1, None, first(1, http(503)))
    for _ in range(db.MAX_RUN_INVOCATIONS - 1):
        synth.invoke(0.1, None, [])
    assert _decide(ctx, SMALL_1.primary) == ("stopped", "invocation_limit")


# The batch with a fake call step.


def test_one_invocation_per_pass(ctx: Any) -> None:
    ctx.invoke = FakeCalls(ctx, [play(None, lambda s: rest(s, ok()))])
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    ((argv, with_key),) = ctx.invoke.calls
    assert with_key and "--resume" not in argv
    assert _cap(argv) == SMALL_1.cap_usd
    records = ctx.log_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["phase"] for line in records] == ["start"]
    assert json.loads(records[0])["argv"][0] == "python"
    assert not ctx.slept


def test_pending_items_resume_after_a_wait(ctx: Any) -> None:
    ctx.invoke = FakeCalls(
        ctx,
        [
            play(None, lambda s: with_first(s, http(503), ok())),
            play(None, lambda s: rest(s, TIMEOUT)),
            play(None, lambda s: rest(s, ok())),
        ],
    )
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    assert ctx.slept == [db.RESUME_WAIT_SECONDS] * 2 == [60.0, 60.0]
    assert ctx.invoke.run_ids() == [SMALL_1.primary.run_id] * 3
    first_argv, *resumes = [argv for argv, _ in ctx.invoke.calls]
    assert all(argv == [*first_argv, "--resume"] for argv in resumes)
    assert any("resuming in 60 s" in line for line in ctx.printed)
    records = ctx.log_path.read_text(encoding="utf-8").splitlines()
    phases = [json.loads(line)["phase"] for line in records]
    assert phases == ["start", "resume", "resume"]


def test_an_item_that_never_completes_counts_as_failed(ctx: Any) -> None:
    head = play(None, lambda s: with_first(s, http(429), ok()))
    again = play(None, lambda s: rest(s, http(429)))
    ctx.invoke = FakeCalls(ctx, [head, again, again])
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    row = db.candidate_summary(SMALL_1, ctx)["runs"][0]
    assert (row["completed"], row["failed"], row["pending"]) == (159, 1, 0)
    assert len(ctx.invoke.calls) == 3


def test_first_answer_reasoning_runs_the_fallback_once(ctx: Any) -> None:
    ctx.invoke = FakeCalls(
        ctx,
        [
            play("thinking_not_honoured", lambda s: first(1, REASONED)),
            play(None, lambda s: rest(s, ok("Parasail"))),
        ],
    )
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    assert ctx.invoke.run_ids() == [
        SMALL_1.primary.run_id,
        SMALL_1.fallback.run_id,
    ]
    configs = [argv[argv.index("--config") + 1] for argv, _ in ctx.invoke.calls]
    assert configs[1].endswith(f"/{SMALL_1.fallback.config}.json")
    summary = db.candidate_summary(SMALL_1, ctx)
    assert summary["passes"] and summary["verdict"] == "passes the run gates"
    assert summary["qualifying_pass"] == {
        "role": "fallback",
        "run_id": SMALL_1.fallback.run_id,
        "config": SMALL_1.fallback.config,
        "model_id": "qwen/qwen3.5-9b",
        "slug": "parasail",
        "reasoning_switch": "enabled_false",
    }
    runs = summary["runs"]
    assert runs[0]["commit_to"] == (
        f"docs/decisions/evidence/bakeoff/{SMALL_1.primary.run_id}/"
    )
    assert runs[1]["commit_to"] == f"docs/results/{SMALL_1.fallback.run_id}/"


def test_a_reasoned_first_answer_without_a_gate_stop_is_not_resumed(
    ctx: Any,
) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(0.1, None, first(3, http(503)) + first(5, REASONED)[3:])
    ctx.invoke = FakeCalls(ctx, [play(None, lambda s: rest(s, ok("P")))])
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    assert ctx.invoke.run_ids() == [SMALL_1.fallback.run_id]
    assert not ctx.slept
    summary = db.candidate_summary(SMALL_1, ctx)
    assert summary["runs"][0]["why"] == "first_answer_reasoned"
    assert summary["qualifying_pass"]["role"] == "fallback"


@pytest.mark.parametrize(
    "tail",
    [
        [play(None, lambda s: rest(s, http(404)))],
        [play(None, lambda s: rest(s, http(429)))] * 2,
    ],
)
def test_refusals_with_one_transient_failure_run_the_fallback(
    ctx: Any, tail: list[Step]
) -> None:
    head = play(
        None, lambda s: [("C1", 0, http(429))] + first(160, http(404))[1:]
    )
    fallback = play(None, lambda s: rest(s, ok("Parasail")))
    ctx.invoke = FakeCalls(ctx, [head, *tail, fallback])
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    assert ctx.slept == [60.0] * len(tail)
    assert ctx.invoke.run_ids() == [SMALL_1.primary.run_id] * (
        1 + len(tail)
    ) + [SMALL_1.fallback.run_id]
    assert db.candidate_summary(SMALL_1, ctx)["runs"][0]["why"] == (
        "no_answer_refused_http_404"
    )


def test_a_refused_pass_runs_the_fallback(ctx: Any) -> None:
    ctx.invoke = FakeCalls(
        ctx,
        [
            play(None, lambda s: rest(s, http(404))),
            play(None, lambda s: rest(s, ok("Parasail"))),
        ],
    )
    assert db.run_candidate(SMALL_1, ctx).kind == "done"
    assert len(ctx.invoke.calls) == 2


def test_the_fallback_gets_no_fallback_of_its_own(ctx: Any) -> None:
    gated = play("thinking_not_honoured", lambda s: first(1, REASONED))
    ctx.invoke = FakeCalls(ctx, [gated, gated])
    assert db.run_candidate(SMALL_1, ctx) == (
        "fallback",
        "first_answer_reasoned",
    )
    assert len(ctx.invoke.calls) == 2
    summary = db.candidate_summary(SMALL_1, ctx)
    assert summary["final"] and not summary["passes"]
    assert summary["verdict"] == (
        "dropped (pass: first_answer_reasoned; fallback: first_answer_reasoned)"
    )


def test_no_listed_fallback_means_a_drop(ctx: Any) -> None:
    ctx.invoke = FakeCalls(
        ctx, [play("thinking_not_honoured", lambda s: first(1, REASONED))]
    )
    assert db.run_candidate(SMALL_2, ctx).kind == "fallback"
    assert len(ctx.invoke.calls) == 1
    summary = db.candidate_summary(SMALL_2, ctx)
    assert summary["verdict"] == "dropped (pass: first_answer_reasoned)"


def test_a_resume_that_reasons_first_drops_without_a_fallback(
    ctx: Any,
) -> None:
    ctx.invoke = FakeCalls(
        ctx,
        [
            play(None, lambda s: with_first(s, ok(), http(503))),
            play(
                "thinking_not_honoured",
                lambda s: with_first(s, REASONED, ok())[:1],
            ),
        ],
    )
    assert db.run_candidate(SMALL_1, ctx).kind == "reasoned"
    assert ctx.invoke.run_ids() == [SMALL_1.primary.run_id] * 2
    assert ctx.slept == [60.0]
    assert db.candidate_summary(SMALL_1, ctx)["verdict"] == (
        "dropped (pass: a_later_answer_reasoned)"
    )


def test_an_outage_waits_for_the_owner_ruling(ctx: Any) -> None:
    _outage(ctx, SMALL_1.primary)
    ctx.invoke = FakeCalls(ctx, [])
    rerun = db.rerun_of(SMALL_1.primary).run_id
    with pytest.raises(db.BatchStop, match=re.escape(f"as {rerun}, or with")):
        db.run_candidate(SMALL_1, ctx)
    summary = db.candidate_summary(SMALL_1, ctx)
    assert not summary["final"]
    assert f"--rerun {SMALL_1.primary.run_id}" in summary["verdict"]
    ctx.rulings = db.Rulings(not_measured=frozenset({SMALL_1.primary.run_id}))
    assert db.run_candidate(SMALL_1, ctx) == (
        "not_measured",
        "owner_ruling_after_an_outage",
    )
    summary = db.candidate_summary(SMALL_1, ctx)
    assert summary["final"] and not summary["passes"]
    assert summary["verdict"] == "not measured (owner ruling after an outage)"
    assert not ctx.invoke.calls


def test_a_ruled_re_run_starts_from_scratch_under_its_id(ctx: Any) -> None:
    _outage(ctx, SMALL_1.primary)
    rerun = db.rerun_of(SMALL_1.primary)
    ctx.rulings = db.Rulings(rerun=frozenset({SMALL_1.primary.run_id}))
    ctx.invoke = FakeCalls(ctx, [play(None, lambda s: rest(s, ok()))])
    assert db.run_candidate(SMALL_1, ctx) == ("done", "complete")
    ((argv, _),) = ctx.invoke.calls
    assert ctx.invoke.run_ids() == [rerun.run_id] and "--resume" not in argv
    assert argv[argv.index("--config") + 1].endswith(f"/{rerun.config}.json")
    ctx.rulings = db.Rulings()
    summary = db.candidate_summary(SMALL_1, ctx)
    assert [r["role"] for r in summary["runs"]] == [
        "pass",
        "pass re-run",
        "fallback",
    ]
    assert summary["qualifying_pass"]["run_id"] == rerun.run_id
    assert summary["qualifying_pass"]["role"] == "pass re-run"


def test_an_outage_on_the_re_run_is_not_measured(ctx: Any) -> None:
    _outage(ctx, SMALL_2.primary)
    ctx.rulings = db.Rulings(rerun=frozenset({SMALL_2.primary.run_id}))
    ctx.invoke = FakeCalls(ctx, [play(None, lambda s: rest(s, http(503)))] * 3)
    assert db.run_candidate(SMALL_2, ctx) == (
        "not_measured",
        "outage_on_the_re_run_too",
    )
    assert ctx.slept == [60.0, 60.0]
    summary = db.candidate_summary(SMALL_2, ctx)
    assert summary["final"] and not summary["passes"]
    assert summary["verdict"] == "not measured (outage on the re-run too)"


@pytest.mark.parametrize(
    ("step", "match"),
    [
        (play("budget", lambda s: first(12, ok())), "budget stop"),
        (play(None, lambda s: rest(s, PROVIDER_ERROR)), "outage .*--rerun"),
        (refuse("settings_changed"), "error .settings_changed, exit 2"),
    ],
)
def test_anything_else_stops_the_batch(
    ctx: Any, step: Step, match: str
) -> None:
    ctx.invoke = FakeCalls(ctx, [step])
    with pytest.raises(db.BatchStop, match=match):
        db.run_candidate(SMALL_1, ctx)
    assert len(ctx.invoke.calls) == 1 and not ctx.slept


@pytest.mark.parametrize(
    "step",
    [
        play("fatal_http", lambda s: first(1, http(401))),
        play("fatal_http", lambda s: first(3, ok()) + [("C1", 3, http(402))]),
        play("fatal_http", lambda s: first(1, http(403))),
        play(
            "fatal_http", lambda s: [("C1", 0, http(429)), ("C1", 1, http(403))]
        ),
        refuse("api_key_missing"),
    ],
)
def test_the_key_or_the_account_aborts(ctx: Any, step: Step) -> None:
    ctx.invoke = FakeCalls(ctx, [step])
    with pytest.raises(db.BatchAbort):
        db.run_candidate(SMALL_1, ctx)
    assert len(ctx.invoke.calls) == 1 and not ctx.slept
    summary = db.candidate_summary(SMALL_1, ctx)
    assert not summary["final"] and not summary["passes"]


def test_preflight_withholds_the_key_and_requires_key_missing(
    ctx: Any,
) -> None:
    ctx.invoke = FakeCalls(ctx, [refuse("api_key_missing")] * 3)
    db.preflight([ANCHOR, SMALL_1], ctx)
    assert [with_key for _, with_key in ctx.invoke.calls] == [False] * 3
    ctx.invoke = FakeCalls(ctx, [refuse("prepare_code_mismatch")])
    with pytest.raises(db.PlanError, match="prepare_code_mismatch"):
        db.preflight([ANCHOR], ctx)
    ctx.rulings = db.Rulings(rerun=frozenset({SMALL_2.primary.run_id}))
    ctx.invoke = FakeCalls(ctx, [refuse("api_key_missing")] * 2)
    db.preflight([SMALL_2], ctx)
    assert ctx.invoke.run_ids() == [
        SMALL_2.primary.run_id,
        db.rerun_of(SMALL_2.primary).run_id,
    ]


# What the summary says.


@pytest.mark.parametrize(
    ("fields", "overrides", "verdict"),
    [
        (ok(), {}, "passes the run gates"),
        (
            ok(),
            {i: http(400) for i in range(9)},
            "dropped (completed 151 < 152)",
        ),
        (ok(), {i: http(400) for i in range(8)}, "passes the run gates"),
        (BARE, {}, "dropped (hybrid reported no reasoning-token count)"),
        (ok(), {-1: ok(reasoning_tokens=5)}, "dropped (an answer reasoned)"),
        (
            ok(),
            {-1: ok(reasoning_present=True)},
            "dropped (an answer reasoned)",
        ),
    ],
)
def test_summary_applies_the_run_gates(
    ctx: Any, fields: Fields, overrides: dict[int, Fields], verdict: str
) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    answers = rest(synth, fields)
    for index, value in overrides.items():
        answers[index] = (answers[index][0], answers[index][1], value)
    synth.invoke(0.1, None, answers)
    assert db.candidate_summary(SMALL_1, ctx)["verdict"] == verdict


def test_a_non_hybrid_may_be_uncontrolled(ctx: Any) -> None:
    _complete(ctx, SMALL_2.primary, ok("Mistral", reasoning_tokens=None))
    summary = db.candidate_summary(SMALL_2, ctx)
    assert summary["runs"][0]["reasoning_state"] == "uncontrolled"
    assert summary["passes"]


def test_slot_lines_send_the_owner_to_the_reserve(ctx: Any) -> None:
    _drop_slot(ctx, "small")
    records = [db.candidate_summary(c, ctx) for c in db.all_candidates()]
    lines = db.slot_lines(records)
    assert lines == [
        "small: no candidate passes the run gates; run --only reserve-small",
        "mid: not finished",
        "frontier: not finished",
    ]
    _gate_stop(ctx, RESERVE_SMALL.primary)
    records = [db.candidate_summary(c, ctx) for c in db.all_candidates()]
    assert db.slot_lines(records)[0] == (
        "small: the reserve llama-3.1-8b-instruct is out (dropped (pass:"
        " first_answer_reasoned)); the slot stays empty"
    )


def test_a_passing_reserve_is_the_slot_survivor(ctx: Any) -> None:
    _complete(ctx, SMALL_1.primary)
    records = [db.candidate_summary(c, ctx) for c in db.all_candidates()]
    assert db.slot_lines(records)[0] == (
        "small: run-gate survivors qwen3.5-9b; the score and the two-turn"
        " smoke decide; if every survivor fails its smoke, run --only"
        " reserve-small --after-smoke-failures"
    )
    _complete(ctx, RESERVE_SMALL.primary)
    records = [db.candidate_summary(c, ctx) for c in db.all_candidates()]
    lines = db.slot_lines(records)
    assert lines[0] == (
        "small: run-gate survivor llama-3.1-8b-instruct (the reserve); its"
        " own two-turn smoke decides"
    )
    assert not any("run --only" in line for line in lines)


def test_write_summary_lists_every_planned_run(ctx: Any) -> None:
    _complete(ctx, SMALL_1.primary)
    synth = _synth(ctx, SMALL_2.primary)
    synth.invoke(0.1, None, with_first(synth, http(503), ok("Mistral")))
    _complete(ctx, SMALL_3.primary, PROVIDER_ERROR)
    json_path, text_path = db.write_summary(ctx)
    document = json.loads(json_path.read_text(encoding="utf-8"))
    runs = [run for record in document["candidates"] for run in record["runs"]]
    assert len(runs) == 21
    assert document["source_revision"] == "test-rev"
    assert document["rulings"] == db.Rulings().record()
    assert "small: run-gate survivors qwen3.5-9b" in document["slots"][0]
    granite = document["candidates"][3]["runs"][0]
    assert granite["provider_error_codes"] == {"upstream_refused": 160}
    text = text_path.read_text(encoding="utf-8")
    assert f"160/{db.TOTAL_ITEMS}" in text and "159/160" in text
    assert f"qualifying pass {SMALL_1.primary.run_id}" in text
    assert "resume (1_items_pending)" in text
    assert '"after_smoke_failures": false' in text


def test_dry_run_prints_what_would_be_sent(ctx: Any) -> None:
    synth = _synth(ctx, SMALL_1.primary)
    synth.invoke(0.1, None, with_first(synth, http(503), ok()))
    db.dry_run(db.PLAN["small"], ctx)
    text = "\n".join(ctx.printed)
    assert "headroom" in text and "first completed answer reasoned" in text
    assert f"--run-id {SMALL_1.primary.run_id}" in text
    assert "--gate-first --resume" in text


# The owner command.


def _main(
    monkeypatch: pytest.MonkeyPatch,
    ctx: Any,
    script: list[Step],
    argv: list[str],
    key: bool = True,
    changes: Sequence[str] = (),
) -> int:
    monkeypatch.setattr(db, "build_context", lambda: ctx)
    monkeypatch.setattr(db, "tooling_changes", lambda: list(changes))
    monkeypatch.setattr(db, "API_KEY_ENV", _TEST_KEY)
    if key:
        monkeypatch.setenv(_TEST_KEY, "not-a-credential")
    else:
        monkeypatch.delenv(_TEST_KEY, raising=False)
    ctx.invoke = FakeCalls(ctx, script)
    return db.main(argv)


def _preflights(slots: Sequence[str]) -> list[Step]:
    count = sum(len(db.targets(c)) for s in slots for c in db.PLAN[s])
    return [refuse("api_key_missing")] * count


def _paid(ctx: Any) -> int:
    return [with_key for _, with_key in ctx.invoke.calls].count(True)


def _steps(ctx: Any, phase: str) -> list[dict[str, Any]]:
    lines = ctx.log_path.read_text(encoding="utf-8").splitlines()
    return [r for r in map(json.loads, lines) if r["phase"] == phase]


def test_absent_key_aborts_after_the_preflight(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    code = _main(monkeypatch, ctx, _preflights(db.DEFAULT_SLOTS), [], key=False)
    assert code == db.EXIT_ABORTED == 3
    assert len(ctx.invoke.calls) == 18
    assert not any(with_key for _, with_key in ctx.invoke.calls)
    assert any(line.startswith("ABORTED: ") for line in ctx.printed)
    assert not (ctx.out_dir / db.LOCK_NAME).exists()
    assert list(ctx.out_dir.glob("summary-*.txt"))
    (batch,) = _steps(ctx, "batch")
    assert batch["slots"] == list(db.DEFAULT_SLOTS)


@pytest.mark.parametrize(
    "change",
    [
        " M scripts/dev_bakeoff.py",
        " M docs/protocol.md",
        "?? docs/decisions/model-bakeoff.md",
        " M src/dfilterforge/completions.py",
    ],
)
def test_uncommitted_tooling_is_refused_before_a_paid_call(
    monkeypatch: pytest.MonkeyPatch, ctx: Any, change: str
) -> None:
    code = _main(
        monkeypatch,
        ctx,
        _preflights(["anchor"]),
        ["--only", "anchor"],
        changes=[change],
    )
    assert code == db.EXIT_REFUSED and not _paid(ctx)
    assert any(change in line for line in ctx.printed)


@pytest.mark.parametrize(
    ("step", "verdict"),
    [
        (
            play("thinking_not_honoured", lambda s: first(1, REASONED)),
            "dropped (pass: first_answer_reasoned)",
        ),
        (
            play(
                None,
                lambda s: rest(s, ok())[9:]
                + [(label, i, http(400)) for label, i in s.unsettled()[:9]],
            ),
            "dropped (completed 151 < 152)",
        ),
    ],
)
def test_a_failed_anchor_stops_before_any_candidate(
    monkeypatch: pytest.MonkeyPatch, ctx: Any, step: Step, verdict: str
) -> None:
    script = _preflights(db.DEFAULT_SLOTS) + [step]
    assert _main(monkeypatch, ctx, script, []) == db.EXIT_STOPPED
    assert ctx.invoke.run_ids()[-1] == ANCHOR.primary.run_id
    assert _paid(ctx) == 1
    (line,) = [x for x in ctx.printed if x.startswith("ANCHOR FAILED: ")]
    assert line.startswith(f"ANCHOR FAILED: {verdict}; the owner's decision")
    assert "A/A pair" in line


def test_a_resumable_anchor_stop_is_not_an_anchor_failure(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    script = _preflights(["anchor", "small"]) + [
        play("budget", lambda s: first(12, ok()))
    ]
    code = _main(
        monkeypatch, ctx, script, ["--only", "anchor", "--only", "small"]
    )
    assert code == db.EXIT_STOPPED and _paid(ctx) == 1
    assert any(
        line.startswith(f"STOPPED: {ANCHOR.primary.run_id}: budget stop")
        for line in ctx.printed
    )
    assert not any("ANCHOR FAILED" in line for line in ctx.printed)


def test_an_anchor_outage_fails_only_once_ruled_not_measured(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    _outage(ctx, ANCHOR.primary)
    anchor = ANCHOR.primary.run_id
    script = _preflights(["anchor"])
    assert _main(monkeypatch, ctx, script, ["--only", "anchor"]) == 1
    assert any(
        line.startswith(f"STOPPED: {anchor}: outage") for line in ctx.printed
    )
    assert not any("ANCHOR FAILED" in line for line in ctx.printed)
    code = _main(
        monkeypatch, ctx, script, ["--only", "anchor", "--not-measured", anchor]
    )
    assert code == db.EXIT_STOPPED and not _paid(ctx)
    assert any(
        line.startswith("ANCHOR FAILED: not measured") for line in ctx.printed
    )
    assert _steps(ctx, "batch")[-1]["not_measured"] == [anchor]


def test_a_selection_without_the_anchor_needs_it_passed(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    code = _main(monkeypatch, ctx, _preflights(["small"]), ["--only", "small"])
    assert code == db.EXIT_STOPPED and not _paid(ctx)
    assert any(
        line.startswith(f"STOPPED: the anchor {ANCHOR.primary.run_id} has no")
        for line in ctx.printed
    )
    assert not any("ANCHOR FAILED" in line for line in ctx.printed)


def test_candidates_run_after_a_passing_anchor(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    _complete(ctx, ANCHOR.primary)
    script = _preflights(["small"]) + [
        play(None, lambda s: rest(s, ok())),
        play(None, lambda s: rest(s, ok("Mistral"))),
        play("thinking_not_honoured", lambda s: first(1, REASONED)),
        play(None, lambda s: rest(s, ok("CoreWeave"))),
    ]
    assert _main(monkeypatch, ctx, script, ["--only", "small"]) == db.EXIT_OK
    assert ctx.invoke.run_ids()[-4:] == [
        SMALL_1.primary.run_id,
        SMALL_2.primary.run_id,
        SMALL_3.primary.run_id,
        SMALL_3.fallback.run_id,
    ]
    assert "exit 0" in ctx.printed
    text = "\n".join(ctx.printed)
    assert "small: run-gate survivors qwen3.5-9b, ministral-8b-2512," in text


def test_a_not_measured_ruling_lets_the_slot_go_on(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    _complete(ctx, ANCHOR.primary)
    _outage(ctx, SMALL_1.primary)
    script = _preflights(["small"])
    assert _main(monkeypatch, ctx, script, ["--only", "small"]) == 1
    assert not _paid(ctx)
    ruling = ["--not-measured", SMALL_1.primary.run_id]
    script = _preflights(["small"]) + [
        play(None, lambda s: rest(s, ok("Mistral"))),
        play(None, lambda s: rest(s, ok())),
    ]
    code = _main(monkeypatch, ctx, script, ["--only", "small", *ruling])
    assert code == db.EXIT_OK
    assert ctx.invoke.run_ids()[-2:] == [
        SMALL_2.primary.run_id,
        SMALL_3.primary.run_id,
    ]
    document = json.loads(
        max(ctx.out_dir.glob("summary-*.json")).read_text(encoding="utf-8")
    )
    assert document["rulings"]["not_measured"] == [SMALL_1.primary.run_id]
    assert document["candidates"][1]["verdict"].startswith("not measured")


@pytest.mark.parametrize(
    ("ruling", "match"),
    [
        (["--rerun", SMALL_2.primary.run_id], "not an outage (start)"),
        (["--not-measured", "dev-x-2026-09-26"], "not a planned pass"),
        (
            [
                "--rerun",
                SMALL_1.primary.run_id,
                "--not-measured",
                SMALL_1.primary.run_id,
            ],
            "both --rerun and --not-measured",
        ),
        (["--rerun", db.rerun_of(SMALL_1.primary).run_id], "not a planned"),
    ],
)
def test_a_ruling_the_runs_do_not_allow_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    ctx: Any,
    capsys: pytest.CaptureFixture[str],
    ruling: list[str],
    match: str,
) -> None:
    _outage(ctx, SMALL_1.primary)
    code = _main(monkeypatch, ctx, [], ["--only", "small", *ruling])
    assert code == db.EXIT_REFUSED and not ctx.invoke.calls
    assert match in capsys.readouterr().err


def test_a_re_run_pass_cannot_be_ruled_not_measured(
    monkeypatch: pytest.MonkeyPatch,
    ctx: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _outage(ctx, SMALL_1.primary)
    _complete(ctx, db.rerun_of(SMALL_1.primary))
    ruling = ["--not-measured", SMALL_1.primary.run_id]
    assert _main(monkeypatch, ctx, [], ["--only", "small", *ruling]) == 2
    assert "its re-run dev-qwen3.5-9b-r2-2026-09-26 exists" in (
        capsys.readouterr().err
    )


def test_a_reserve_waits_for_its_slot(
    monkeypatch: pytest.MonkeyPatch,
    ctx: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _complete(ctx, ANCHOR.primary)
    only = ["--only", "reserve-small"]
    assert _main(monkeypatch, ctx, [], only) == db.EXIT_REFUSED
    assert not ctx.invoke.calls
    assert (
        "no verdict yet for qwen3.5-9b, ministral-8b-2512, granite-4.2-8b"
        in capsys.readouterr().err
    )
    _complete(ctx, SMALL_1.primary)
    _drop_slot(ctx, "small", keep=[SMALL_1])
    assert _main(monkeypatch, ctx, [], only) == db.EXIT_REFUSED
    assert not ctx.invoke.calls
    assert "qwen3.5-9b passed the run gates" in capsys.readouterr().err
    script = _preflights(["reserve-small"]) + [
        play(None, lambda s: rest(s, ok()))
    ]
    code = _main(monkeypatch, ctx, script, [*only, "--after-smoke-failures"])
    assert code == db.EXIT_OK
    assert ctx.invoke.run_ids()[-1] == RESERVE_SMALL.primary.run_id
    assert _steps(ctx, "batch")[-1]["after_smoke_failures"] is True
    document = json.loads(
        max(ctx.out_dir.glob("summary-*.json")).read_text(encoding="utf-8")
    )
    assert document["rulings"]["after_smoke_failures"] is True
    assert document["slots"][0].startswith(
        "small: run-gate survivor llama-3.1-8b-instruct (the reserve)"
    )


def test_a_reserve_runs_once_no_ranked_candidate_passes(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    _complete(ctx, ANCHOR.primary)
    _drop_slot(ctx, "small")
    script = _preflights(["reserve-small"]) + [
        play(None, lambda s: rest(s, ok()))
    ]
    code = _main(monkeypatch, ctx, script, ["--only", "reserve-small"])
    assert code == db.EXIT_OK and _paid(ctx) == 1
    assert _steps(ctx, "batch")[-1]["after_smoke_failures"] is False


def test_an_account_refusal_exits_3(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    for status in (402, 403):
        script = _preflights(["anchor"]) + [
            play("fatal_http", lambda s, code=status: first(1, http(code)))
        ]
        assert _main(monkeypatch, ctx, script, ["--only", "anchor"]) == 3
        assert any(f"HTTP {status} on" in line for line in ctx.printed)


def test_an_interrupt_releases_the_lock_unless_a_child_runs(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    lock = ctx.out_dir / db.LOCK_NAME
    script = _preflights(["anchor"]) + [raises(KeyboardInterrupt())]
    assert _main(monkeypatch, ctx, script, ["--only", "anchor"]) == 130
    assert not lock.exists()
    still = db.ChildStillRunning("call step pid 7 is still running")
    script = _preflights(["anchor"]) + [raises(still)]
    assert _main(monkeypatch, ctx, script, ["--only", "anchor"]) == 130
    assert lock.exists()
    assert _main(monkeypatch, ctx, [], ["--only", "anchor"]) == 2


def test_a_refused_plan_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused() -> Any:
        raise db.PlanError("config x is missing")

    monkeypatch.setattr(db, "build_context", refused)
    assert db.main(["--dry-run"]) == db.EXIT_REFUSED


def test_dry_run_takes_no_lock_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, ctx: Any
) -> None:
    assert _main(monkeypatch, ctx, [], ["--dry-run"]) == 0
    assert not ctx.invoke.calls
    assert not (ctx.out_dir / db.LOCK_NAME).exists()


def test_lock_admits_one_batch(tmp_path: Path) -> None:
    lock = tmp_path / "out" / db.LOCK_NAME
    db.acquire_lock(lock)
    assert lock.read_text(encoding="utf-8").startswith("pid ")
    with pytest.raises(db.PlanError, match="is held"):
        db.acquire_lock(lock)


def test_a_lock_left_half_written_is_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def interrupted() -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(db, "_now", interrupted)
    lock = tmp_path / "out" / db.LOCK_NAME
    with pytest.raises(KeyboardInterrupt):
        db.acquire_lock(lock)
    assert not lock.exists()


# The real child process.


class _Child:
    """Stands in for a call step that does or does not exit in time."""

    pid = 7

    def __init__(self, exits: bool) -> None:
        self.exits = exits
        self.waited: list[float] = []
        self.killed = False

    def wait(self, timeout: float) -> int:
        self.waited.append(timeout)
        if not self.exits:
            raise subprocess.TimeoutExpired("call", timeout)
        return 0

    def poll(self) -> int | None:
        return 0 if self.exits else None

    def kill(self) -> None:
        self.killed = True


def test_an_interrupt_waits_for_the_in_flight_request() -> None:
    printed: list[str] = []
    child = _Child(exits=True)
    db.wait_after_interrupt(child, 150.0, printed.append)
    assert child.waited == [150.0] and "pid 7" in printed[0]
    assert not child.killed
    with pytest.raises(db.ChildStillRunning, match="delete"):
        db.wait_after_interrupt(_Child(exits=False), 1.0, printed.append)
    child = _Child(exits=True)
    db.stop_child(child, 5.0, printed.append)
    assert child.killed and child.waited == [5.0]
    with pytest.raises(db.ChildStillRunning):
        db.stop_child(_Child(exits=False), 1.0, printed.append)


def test_the_invoker_withholds_the_key_and_reads_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(db, "API_KEY_ENV", _TEST_KEY)
    monkeypatch.setattr(db, "PROGRESS_SECONDS", 0.05)
    monkeypatch.setenv(_TEST_KEY, "not-a-credential")
    code = (
        "import json, os, sys, time; time.sleep(0.2);"
        f" print(json.dumps({{'run_id': 'r', 'key': {_TEST_KEY!r} in"
        " os.environ}));"
        " print(json.dumps({'error': {'code': 'x'}}), file=sys.stderr)"
    )
    argv = [sys.executable, "-c", code, "--run-id", "dev-x-2026-09-26"]
    printed: list[str] = []
    invoke = db.subprocess_invoker(tmp_path, printed.append, 5.0)
    withheld = invoke(argv, False)
    assert withheld.report == {"run_id": "r", "key": False}
    assert (withheld.exit_code, withheld.error_code) == (0, "x")
    assert invoke(argv, True).report == {"run_id": "r", "key": True}
    assert any("attempts" in line for line in printed)
    assert db.parse_output("noise\n[1]\n", "{}\n") == (None, None)
    unreadable = tmp_path / "runs" / "dev-x-2026-09-26" / "attempts"
    (unreadable / "C1.jsonl").mkdir(parents=True)
    printed.clear()
    assert invoke(argv, False).report == {"run_id": "r", "key": False}
    assert any("attempt logs unreadable" in line for line in printed)


class _Crash(BaseException):
    """Not an Exception, so only a BaseException handler sees it."""


def test_the_invoker_ends_its_child_when_the_batch_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(db, "PROGRESS_SECONDS", 0.05)
    children: list[Any] = []
    spawn: Any = subprocess.Popen

    def recorded(*args: Any, **kwargs: Any) -> Any:
        child = spawn(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(db.subprocess, "Popen", recorded)
    printed: list[str] = []

    def out(line: str) -> None:
        printed.append(line)
        if line.startswith("    ..."):
            raise _Crash

    argv = [
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        "--run-id",
        "dev-x-2026-09-26",
    ]
    invoke = db.subprocess_invoker(tmp_path, out, 10.0)
    with pytest.raises(_Crash):
        invoke(argv, False)
    (child,) = children
    assert child.poll() is not None
    assert any("ending it" in line for line in printed)


# The configuration builder.


def test_a_base_slug_is_sent_for_a_single_endpoint() -> None:
    spec = dbc.ConfigSpec("m_deepinfra_none", "org/m", "deepinfra", None)
    config, facts = dbc.build_config(
        spec, {"endpoints": [_endpoint("deepinfra/fp8")]}, "T"
    )
    assert config["settings"]["openrouter"]["provider_order"] == ["deepinfra"]
    assert config["prices"]["usd_per_million_input"] == 0.1
    assert "slug deepinfra matches deepinfra/fp8" in config["prices"]["source"]
    assert "fetched T" in config["prices"]["source"]
    assert facts["provider_endpoint_tags"] == ["deepinfra/fp8"]
    tagged = dbc.ConfigSpec("m_x", "org/m", "deepinfra/fp8", None)
    with pytest.raises(dbc.ConfigError, match="send the base slug"):
        dbc.build_config(
            tagged, {"endpoints": [_endpoint("deepinfra/fp8")]}, "T"
        )


def test_a_full_tag_is_sent_where_the_provider_serves_several() -> None:
    data = {"endpoints": [_endpoint("alibaba/fp8"), _endpoint("alibaba/fast")]}
    base = dbc.ConfigSpec("m_alibaba", "org/m", "alibaba", "enabled_false")
    with pytest.raises(dbc.ConfigError, match="send a full tag"):
        dbc.build_config(base, data, "T")
    tagged = dbc.ConfigSpec("m_alibaba-fp8", "org/m", "alibaba/fp8", None)
    config, facts = dbc.build_config(tagged, data, "T")
    assert config["settings"]["openrouter"]["provider_order"] == ["alibaba/fp8"]
    assert [e["tag"] for e in facts["endpoints"]] == ["alibaba/fp8"]


def test_the_mistral_base_slug_records_the_highest_price() -> None:
    data = {
        "endpoints": [
            _endpoint("mistral"),
            _endpoint("mistral/zdr"),
            _endpoint(
                "mistral/eu",
                pricing={"prompt": "0.000000165", "completion": "0.00000033"},
            ),
        ]
    }
    spec = dbc.ConfigSpec("m_mistral", "org/m", "mistral", None, True)
    config, _ = dbc.build_config(spec, data, "T")
    prices = config["prices"]
    assert (
        prices["usd_per_million_input"],
        prices["usd_per_million_output"],
    ) == (
        0.165,
        0.33,
    )
    assert "matches mistral, mistral/eu, mistral/zdr" in prices["source"]
    assert "highest listed price" in prices["source"]


def test_a_discounted_endpoint_records_its_listed_price() -> None:
    discounted = _endpoint(
        "novita/fp8",
        pricing={
            "prompt": "0.0000006496",
            "completion": "0.0000020416",
            "discount": 0.536,
        },
    )
    spec = dbc.ConfigSpec("glm_novita", "z-ai/glm-5.2", "novita", None)
    config, _ = dbc.build_config(spec, {"endpoints": [discounted]}, "T")
    prices = config["prices"]
    assert prices["usd_per_million_input"] == 0.6496
    assert prices["usd_per_million_output"] == 2.0416
    assert "discount 0.536" in prices["source"]
    assert "undiscounted 1.4/4.4" in prices["source"]


@pytest.mark.parametrize(
    ("extra", "match"),
    [
        ({"supported_parameters": ["temperature"]}, "lacks"),
        ({"max_completion_tokens": 1024}, "ceiling"),
        (
            {"pricing": {"prompt": "1", "completion": "1", "request": "1"}},
            "unbounded",
        ),
    ],
)
def test_an_endpoint_that_cannot_carry_the_request_is_refused(
    extra: dict[str, Any], match: str
) -> None:
    spec = dbc.ConfigSpec("m_deepinfra", "org/m", "deepinfra", "enabled_false")
    data = {"endpoints": [_endpoint("deepinfra/fp8", **extra)]}
    with pytest.raises(dbc.ConfigError, match=match):
        dbc.build_config(spec, data, "T")
    with pytest.raises(dbc.ConfigError, match="no endpoint"):
        dbc.build_config(spec, {"endpoints": [_endpoint("novita/fp8")]}, "T")


def test_config_main_writes_explicit_validated_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    by_model: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for spec in dbc.SPECS:
        listed = by_model.setdefault(spec.model_id, {"endpoints": []})
        tags = {endpoint["tag"] for endpoint in listed["endpoints"]}
        listed["endpoints"].extend(
            endpoint
            for endpoint in _metadata(spec)["endpoints"]
            if endpoint["tag"] not in tags
        )
    monkeypatch.setattr(dbc, "ROOT", tmp_path)
    monkeypatch.setattr(dbc, "load_model_run", db.load_model_run)
    monkeypatch.setattr(dbc, "fetch_endpoints", by_model.__getitem__)
    assert dbc.main([]) == 0
    config_dir = tmp_path / dbc.CONFIG_DIR
    written = sorted(path.stem for path in config_dir.glob("*.json"))
    assert written == sorted(spec.name for spec in dbc.SPECS)
    (config_dir / "stale.json").write_text("{}", encoding="utf-8")
    assert dbc.main([]) == 0
    facts = json.loads(
        (tmp_path / dbc.ENDPOINTS_FILE).read_text(encoding="utf-8")
    )
    assert set(facts["configs"]) == set(written)


def test_fetch_reads_the_keyless_endpoint_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Reply:

        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self) -> "_Reply":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, limit: int) -> bytes:
            return self.body[:limit]

    sent: list[Any] = []
    bodies = [
        json.dumps({"data": {"endpoints": [{"tag": "a"}]}}).encode(),
        b'{"data": {}}',
    ]

    def urlopen(request: Any, timeout: float) -> _Reply:
        sent.append((request, timeout))
        return _Reply(bodies.pop(0))

    monkeypatch.setattr(dbc.urllib.request, "urlopen", urlopen)
    assert dbc.fetch_endpoints("org/m")["endpoints"] == [{"tag": "a"}]
    request, timeout = sent[0]
    assert request.full_url.endswith("/models/org/m/endpoints")
    assert "Authorization" not in request.headers and timeout == 30
    with pytest.raises(dbc.ConfigError, match="no endpoint list"):
        dbc.fetch_endpoints("org/m")


# The committed configurations and prompt receipt.


_COMMITTED = _ROOT / db.CONFIG_DIR


@pytest.mark.skipif(
    not _COMMITTED.is_dir(), reason="the test image carries no docs/ tree"
)
def test_committed_configs_are_the_specs_written_out() -> None:
    model_run = db.load_model_run()
    facts = json.loads(
        (_ROOT / dbc.ENDPOINTS_FILE).read_text(encoding="utf-8")
    )["configs"]
    files = sorted(path.stem for path in _COMMITTED.glob("*.json"))
    assert files == sorted(spec.name for spec in dbc.SPECS)
    for spec in dbc.SPECS:
        data = json.loads(
            (_COMMITTED / f"{spec.name}.json").read_text(encoding="utf-8")
        )
        model_run.CallConfigV1.model_validate(data)
        settings = data["settings"]
        assert settings == {
            "model_id": spec.model_id,
            "temperature": 0.0,
            "seed": 17,
            "max_output_tokens": 2048,
            "timeout_seconds": 120.0,
            "json_mode": True,
            "openrouter": {
                "reasoning": spec.reasoning,
                "provider_order": [spec.route],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": None,
            },
        }
        assert "fetched 2026-" in data["prices"]["source"]
        tags = facts[spec.name]["provider_endpoint_tags"]
        if "/" in spec.route:
            assert len(tags) > 1 and spec.route in tags
        else:
            assert len(tags) == 1 or spec.spans_endpoints


@pytest.mark.skipif(
    not (_ROOT / db.COMMITTED_PREPARE_DIR).is_dir(),
    reason="the test image carries no docs/ tree",
)
def test_committed_dev_prompts_have_the_registered_digest() -> None:
    receipt = _ROOT / db.COMMITTED_PREPARE_DIR / "prepare.json"
    assert _sha256(receipt.read_bytes()).startswith(db.PREPARE_SHA256_PREFIX)
