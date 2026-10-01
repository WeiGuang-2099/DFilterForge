"""The test-pass batch sends the registered runs in order and nothing else.

Every run directory here is written from the real contracts
(``RunManifestV1``, ``AttemptV1``, ``CompletionV1``) over a synthetic
eight-item test prompt set, the registry is written row by row from the
committed bake-off config specs, and the call step is replaced by a
scripted fake, so nothing is sent anywhere. The test of the committed
registry, prompts and note skips where the test image carries no docs/
tree.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
from types import ModuleType
from typing import Any, Literal

import pytest

from dfilterforge import held_out
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


def _load(name: str, alias: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        alias, _ROOT / "scripts" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tp = _load("test_passes", "test_passes")
# The batch's own copies, so every class and helper here is the one it reads.
db = tp.db
model_run = tp.model_run
dbc = _load("dev_bakeoff_configs", "test_passes_configs")
_BUILD = tp.build_context
_TEST_KEY = "DFILTERFORGE_TEST_PASSES_TEST_ONLY"
_NO_DOCS = "the test image carries no docs/ tree"
_DATE = "2026-09-26"
_PREPARE_ID = f"test-qwen3-32b-{_DATE}"
_COMMITTED = f"docs/results/{_PREPARE_ID}"
_CALL_DIR = f"artifacts/model-eval/{_PREPARE_ID}"
_LABELS: tuple[ConditionLabel, ...] = ("C1", "C2", "C3", "C4")
_CONDITIONS: dict[ConditionLabel, tuple[OutputContractV1, RetrievalV1]] = {
    "C1": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    "C2": (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    "C3": (OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    "C4": (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
}
_ITEMS = tuple(f"mei-{index:04d}" for index in range(1001, 1009))
_REQUESTS = len(_LABELS) * len(_ITEMS)
_T0 = datetime(2026, 10, 2, tzinfo=timezone.utc)
_SETTINGS: Fields = {
    "temperature": 0.0,
    "seed": 17,
    "max_output_tokens": 2048,
    "timeout_seconds": 120.0,
    "json_mode": True,
    "require_parameters": True,
    "allow_fallbacks": False,
    "data_collection": None,
}
# The registered planned runs: role, run id middle, config and cap.
_PLANNED = (
    ("aa_pass_a", "qwen3-32b", "qwen3-32b_deepinfra_enabled-false", 0.10),
    (
        "aa_pass_b",
        "qwen3-32b-passb",
        "qwen3-32b_deepinfra_enabled-false",
        0.10,
    ),
    (
        "winner_small",
        "qwen3.5-9b",
        "qwen3.5-9b_deepinfra_enabled-false",
        0.15,
    ),
    (
        "winner_mid",
        "qwen3.5-122b-a10b",
        "qwen3.5-122b-a10b_novita_enabled-false",
        0.75,
    ),
    (
        "winner_frontier",
        "deepseek-v4-pro-0813",
        "deepseek-v4-pro-0813_deepinfra_enabled-false",
        1.25,
    ),
)
# Each slot winner's listed fallback: its role and config.
_FALLBACKS = {
    "qwen3.5-9b": ("fallback_small", "qwen3.5-9b_parasail_enabled-false"),
    "qwen3.5-122b-a10b": (
        "fallback_mid",
        "qwen3.5-122b-a10b_atlas-cloud_enabled-false",
    ),
    "deepseek-v4-pro-0813": (
        "fallback_frontier",
        "deepseek-v4-pro-0813_nextbit_enabled-false",
    ),
}


def _run(middle: str) -> str:
    return f"test-{middle}-{_DATE}"


def _r2(run_id: str) -> str:
    return _run(run_id.removeprefix("test-").removesuffix(f"-{_DATE}") + "-r2")


PASS_A = _run("qwen3-32b")
PASS_B = _run("qwen3-32b-passb")
SMALL = _run("qwen3.5-9b")
MID = _run("qwen3.5-122b-a10b")
FRONTIER = _run("deepseek-v4-pro-0813")
SMALL_FB = _run("qwen3.5-9b-fb")
MID_FB = _run("qwen3.5-122b-a10b-fb")
FRONTIER_FB = _run("deepseek-v4-pro-0813-fb")
PLANNED = [PASS_A, PASS_B, SMALL, MID, FRONTIER]
FALLBACKS = [SMALL_FB, MID_FB, FRONTIER_FB]
CONDITIONAL = FALLBACKS + [_r2(run) for run in PLANNED + FALLBACKS]
ALL_RUNS = PLANNED + CONDITIONAL


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_prepare(directory: Path) -> None:
    """Writes an eight-item test prompt set shaped like the frozen one."""
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
                    split="test",
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
                for i, item in enumerate(_ITEMS)
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
                prompt_count=len(_ITEMS),
            )
        )
    manifest = PrepareManifestV1(
        prepare_id=_PREPARE_ID,
        created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        source_revision="test",
        source_files={},
        split="test",
        item_ids=_ITEMS,
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


def _metadata(spec: Any) -> dict[str, Any]:
    """One bf16 endpoint per slug, as OpenRouter's metadata lists it."""
    provider = spec.route.split("/", 1)[0]
    return {
        "endpoints": [
            {
                "tag": f"{provider}/bf16",
                "provider_name": provider.title(),
                "quantization": "bf16",
                "status": 0,
                "max_completion_tokens": 8192,
                "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
                "supported_parameters": [*dbc.SENT_PARAMETERS, "reasoning"],
            }
        ]
    }


def _registry_rows() -> list[Fields]:
    """The 16 registered rows over the synthetic prompts, in order."""
    specs = {spec.name: spec for spec in dbc.SPECS}
    rows: list[Fields] = []

    def add(
        role: str,
        middle: str,
        config: str,
        cap: float,
        named: str | None = None,
        trigger: str | None = None,
    ) -> None:
        spec = specs[config]
        rows.append(
            {
                "role": role,
                "run_id": _run(middle),
                "model_id": spec.model_id,
                "slug": spec.route,
                "quant": "bf16",
                "reasoning_switch": spec.reasoning,
                "config": f"{db.CONFIG_DIR}/{config}.json",
                "cap_usd": cap,
                "prepare": _COMMITTED,
                "conditional_on": None if named is None else _run(named),
                "trigger": trigger,
                "status": "registered" if trigger is None else "unused",
                "reason": None,
                "commit": None,
            }
        )

    caps = {middle: cap for _, middle, _, cap in _PLANNED}
    for role, middle, config, cap in _PLANNED:
        add(role, middle, config, cap)
    for named, (role, config) in _FALLBACKS.items():
        add(role, f"{named}-fb", config, caps[named], named, "gate_stop")
    for row in list(rows):
        middle = str(row["run_id"]).removeprefix("test-")
        middle = middle.removesuffix(f"-{_DATE}")
        config = Path(row["config"]).stem
        add(
            row["role"],
            f"{middle}-r2",
            config,
            row["cap_usd"],
            middle,
            "outage",
        )
    return rows


def _registry() -> Fields:
    return {
        "schema": "test-runs/1.0",
        "registered_on": "2026-10-01",
        "note": tp.NOTE,
        "ruling": "docs/decisions/evidence/bakeoff/ruling-2026-10-01.json",
        "call_prepare_dir": _CALL_DIR,
        "settings": dict(_SETTINGS),
        "call": {
            "gate_first": True,
            "max_attempts": 3,
            "min_interval_seconds": 1.0,
        },
        "repair_arms": {},
        "runs": _registry_rows(),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


@pytest.fixture(name="template", scope="module")
def fixture_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository tree with the prompts, the configs and the registry."""
    root = tmp_path_factory.mktemp("test-passes")
    _write_prepare(root / _COMMITTED)
    used = {Path(row["config"]).stem for row in _registry_rows()}
    for spec in dbc.SPECS:
        if spec.name in used:
            config, _ = dbc.build_config(
                spec, _metadata(spec), "2026-09-26T00:00:00Z"
            )
            _write_json(root / db.CONFIG_DIR / f"{spec.name}.json", config)
    _write_json(root / tp.REGISTRY, _registry())
    return root


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
TIMEOUT: Fields = {
    "status": "failed",
    "error_code": "timeout",
    "latency_ms": 1.0,
}


def http(status: int) -> Fields:
    """A non-2xx reply as the client records it."""
    return {
        "status": "failed",
        "error_code": "http_error",
        "latency_ms": 1.0,
        "http_status": status,
    }


def _flag(argv: Sequence[str], name: str) -> str:
    return argv[list(argv).index(name) + 1]


class Bench:
    """A private repository tree, a fake call step and a fake clock.

    The clock moves one second per recorded attempt or invocation, and
    ``now`` is what the batch reads as the time; the waits before a
    resume or a re-run are recorded in ``slept`` instead.
    """

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.monkeypatch = monkeypatch
        digest = _sha256((root / _CALL_DIR / "prepare.json").read_bytes())
        self.layout = tp.Layout(root, root / tp.OUT_DIR, frozenset({digest}))
        self.printed: list[str] = []
        self.slept: list[float] = []
        self.now = _T0
        self.calls: list[tuple[list[str], bool]] = []
        self.script: list[Step] = []
        monkeypatch.setattr(tp, "pause", self.slept.append)
        monkeypatch.setattr(tp, "utc_now", lambda: self.now)

    def tick(self) -> datetime:
        """Moves the clock on by one second."""
        self.now += timedelta(seconds=1)
        return self.now

    def context(self) -> Any:
        """Builds the batch's context from the tree as it now stands."""
        ctx = _BUILD(self.layout, "test-rev")
        ctx.out = self.printed.append
        ctx.invoke = self.invoke
        return ctx

    def invoke(self, argv: Sequence[str], with_key: bool) -> Any:
        """Plays the next scripted call step."""
        argv = list(argv)
        self.calls.append((argv, with_key))
        assert self.script, f"unexpected call {argv}"
        step = self.script.pop(0)
        synth = Synth(self, _flag(argv, "--run-id"), _flag(argv, "--config"))
        return step(synth, argv)

    def config_of(self, run_id: str) -> str:
        """Returns the config the registry gives a run."""
        return str(self.row(run_id)["config"])

    def row(self, run_id: str) -> Fields:
        """Returns a run's registry row as it now stands."""
        registry = json.loads(
            (self.root / tp.REGISTRY).read_text(encoding="utf-8")
        )
        return next(r for r in registry["runs"] if r["run_id"] == run_id)

    def edit_registry(self, edit: Callable[[Fields], object]) -> None:
        """Rewrites the registry file through ``edit``."""
        path = self.root / tp.REGISTRY
        registry = json.loads(path.read_text(encoding="utf-8"))
        edit(registry)
        _write_json(path, registry)

    def edit_row(self, run_id: str, **fields: Any) -> None:
        """Changes one registry row's fields, as an owner commit would."""

        def edit(registry: Fields) -> None:
            for row in registry["runs"]:
                if row["run_id"] == run_id:
                    row.update(fields)

        self.edit_registry(edit)

    def keyless(self) -> list[Step]:
        """The preflight steps one execution makes from this state."""
        due = tp.sendable(tp.read_walk(self.context()))
        return [refuse("api_key_missing")] * len(due)

    def run(
        self,
        script: list[Step],
        argv: Sequence[str] = (),
        key: bool = True,
        changes: Sequence[str] = (),
    ) -> int:
        """Runs the owner command once; ``calls`` holds only its calls."""
        self.calls = []
        self.printed.clear()
        self.script = list(script)
        monkeypatch = self.monkeypatch
        monkeypatch.setattr(tp, "build_context", self.context)
        monkeypatch.setattr(tp, "tooling_changes", lambda: list(changes))
        monkeypatch.setattr(tp, "API_KEY_ENV", _TEST_KEY)
        if key:
            monkeypatch.setenv(_TEST_KEY, "not-a-credential")
        else:
            monkeypatch.delenv(_TEST_KEY, raising=False)
        return tp.main(list(argv))

    def paid(self) -> list[str]:
        """Returns the run id of every call made with the key, in order."""
        return [_flag(argv, "--run-id") for argv, key in self.calls if key]

    def paid_argv(self) -> list[list[str]]:
        """Returns every argument list sent with the key, in order."""
        return [argv for argv, key in self.calls if key]

    def summary(self) -> Fields:
        """Reads the newest JSON summary."""
        path = max((self.root / tp.OUT_DIR).glob("summary-*.json"))
        return json.loads(path.read_text(encoding="utf-8"))

    def rows(self) -> dict[str, Fields]:
        """Returns the newest summary's rows by run id."""
        return {row["run_id"]: row for row in self.summary()["rows"]}

    def steps(self, phase: str) -> list[Fields]:
        """Returns the step log's records of one phase."""
        log = self.root / tp.OUT_DIR / tp.STEP_LOG
        records = map(json.loads, log.read_text(encoding="utf-8").splitlines())
        return [record for record in records if record["phase"] == phase]


@pytest.fixture(name="bench")
def fixture_bench(
    template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Bench:
    """A private tree with the owner's prompt copy; nothing is invoked."""
    root = tmp_path / "repo"
    shutil.copytree(template, root)
    shutil.copytree(root / _COMMITTED, root / _CALL_DIR)
    return Bench(root, monkeypatch)


class Synth:
    """Writes one run directory exactly as the call step shapes it."""

    def __init__(self, bench: Bench, run_id: str, config: str) -> None:
        self.bench = bench
        prepare_dir = bench.root / _CALL_DIR
        self.run_dir = prepare_dir / "runs" / run_id
        self.run_id = run_id
        self.prepare_bytes = (prepare_dir / "prepare.json").read_bytes()
        self.prepare = PrepareManifestV1.model_validate_json(self.prepare_bytes)
        self.config = model_run.CallConfigV1.model_validate_json(
            (bench.root / config).read_bytes()
        )
        self.attempts: dict[str, dict[str, list[Any]]] = {
            label: {item: [] for item in _ITEMS} for label in _LABELS
        }
        self.invocations: list[InvocationV1] = []
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
                    attempt = model_run.AttemptV1.model_validate_json(line)
                    item = attempt.completion.item_id
                    self.attempts[label][item].append(attempt)

    def unsettled(self) -> list[tuple[str, int]]:
        """Lists the prompts a further pass would still send, in order."""
        return [
            (label, index)
            for label in _LABELS
            for index, item in enumerate(_ITEMS)
            if not model_run._is_settled(
                self.attempts[label][item], db.MAX_ATTEMPTS
            )
        ]

    def invoke(
        self,
        max_usd: float,
        stop_reason: StopReason,
        answers: Answers,
        revision: str = "test-rev",
    ) -> dict[str, Any]:
        """Records one invocation and returns the report it would print."""
        started = self.bench.tick()
        for label, index, fields in answers:
            item = _ITEMS[index]
            entries = self.attempts[label][item]
            entries.append(
                model_run.AttemptV1(
                    attempt=len(entries) + 1,
                    sent_at=self.bench.tick(),
                    charged_micro_usd=10,
                    completion=CompletionV1(item_id=item, **fields),
                )
            )
        self.invocations.append(
            InvocationV1(
                source_revision=revision,
                source_files={},
                started_at=started,
                finished_at=self.bench.tick(),
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
                    for item in _ITEMS
                    for attempt in self.attempts[label][item]
                ),
                encoding="utf-8",
                newline="\n",
            )
            census[label] = (
                [
                    model_run._prompt_state(
                        self.attempts[label][item], db.MAX_ATTEMPTS
                    )
                    for item in _ITEMS
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
                        item: len(self.attempts[label][item]) for item in _ITEMS
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
    order = [(label, i) for label in _LABELS for i in range(len(_ITEMS))]
    return [(label, index, fields) for label, index in order[:count]]


def rest(synth: Synth, fields: Fields) -> Answers:
    """Answers every prompt the run still owes an attempt."""
    return [(label, index, fields) for label, index in synth.unsettled()]


def with_first(synth: Synth, head: Fields, tail: Fields) -> Answers:
    """Answers what is owed, the first one with ``head``."""
    answers = rest(synth, tail)
    answers[0] = (answers[0][0], answers[0][1], head)
    return answers


def play(stop: StopReason, answers: Callable[[Synth], Answers]) -> Step:
    """A call step that records ``answers`` and stops with ``stop``."""

    def step(synth: Synth, argv: list[str]) -> Any:
        report = synth.invoke(
            float(_flag(argv, "--max-usd")),
            stop,
            answers(synth),
            _flag(argv, "--source-revision"),
        )
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


COMPLETE = play(None, lambda s: rest(s, ok()))
GATED = play("thinking_not_honoured", lambda s: first(1, REASONED))
# Timeouts are charged their worst case, so a cap spent on them before
# any answer is an outage.
OUTAGE = play("budget", lambda s: first(2, TIMEOUT))
REFUSED = play(None, lambda s: rest(s, http(404)))


def _complete(bench: Bench, run_id: str) -> None:
    synth = Synth(bench, run_id, bench.config_of(run_id))
    synth.invoke(1.0, None, rest(synth, ok()))


def _evidence(run_id: str) -> str:
    return f"{tp.EVIDENCE_DIR}/{run_id}/"


# The order, the argument lists and the summary.


def test_registered_runs_are_sent_in_order_after_a_keyless_preflight(
    bench: Bench,
) -> None:
    preflight = bench.keyless()
    assert len(preflight) == len(ALL_RUNS) == 16
    assert bench.run(preflight + [COMPLETE] * 5) == tp.EXIT_OK == 0
    keyless = [argv for argv, key in bench.calls if not key]
    assert [argv for argv, _ in bench.calls[:16]] == keyless
    assert [_flag(argv, "--run-id") for argv in keyless] == ALL_RUNS
    assert bench.paid() == PLANNED
    assert bench.paid_argv()[1] == [
        sys.executable,
        "scripts/model_run.py",
        "call",
        "--prepare-dir",
        _CALL_DIR,
        "--run-id",
        PASS_B,
        "--config",
        f"{db.CONFIG_DIR}/qwen3-32b_deepinfra_enabled-false.json",
        "--max-usd",
        "0.100000",
        "--source-revision",
        "test-rev",
        "--min-interval-seconds",
        "1.0",
        "--max-attempts",
        "3",
        "--gate-first",
    ]
    assert [_flag(argv, "--max-usd") for argv in bench.paid_argv()] == [
        "0.100000",
        "0.100000",
        "0.150000",
        "0.750000",
        "1.250000",
    ]
    for argv, (_, _, config, _) in zip(bench.paid_argv(), _PLANNED):
        assert _flag(argv, "--config") == f"{db.CONFIG_DIR}/{config}.json"
    assert "exit 0" in bench.printed
    assert any(line.startswith("  pass B starts at ") for line in bench.printed)
    assert [s["run_id"] for s in bench.steps("start")] == PLANNED
    assert all(s["argv"][0] == "python" for s in bench.steps("preflight"))


def test_the_summary_names_what_the_publish_step_records(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [COMPLETE] * 5) == 0
    summary = bench.summary()
    assert summary["final"] is True
    assert summary["requests_per_pass"] == _REQUESTS
    assert summary["source_revision"] == "test-rev"
    assert summary["outcomes"] == {
        "aa_pair": {"state": "done", "reason": "both passes are complete"},
        "winner_small": {"state": "done", "reason": "done (complete)"},
        "winner_mid": {"state": "done", "reason": "done (complete)"},
        "winner_frontier": {"state": "done", "reason": "done (complete)"},
    }
    rows = bench.rows()
    assert [row["number"] for row in summary["rows"]] == list(range(1, 17))
    for run_id in PLANNED:
        row = rows[run_id]
        assert row["state"] == "done"
        assert row["commit_to"] == f"docs/results/{run_id}/"
        assert row["first_source_revision"] == "test-rev"
        assert row["registry_update"] == {
            "status": "published",
            "reason": None,
            "commit": "test-rev",
        }
        assert row["run"]["completed"] == _REQUESTS
    for run_id in CONDITIONAL:
        assert rows[run_id]["state"] == "unused"
        assert rows[run_id]["commit_to"] is None
        assert rows[run_id]["registry_update"] == {
            "status": "unused",
            "reason": None,
            "commit": None,
        }
    window = summary["pass_b_window"]
    assert window["within_24_hours"] is True
    assert window["pass_a_first_started_at"] < window["pass_b_first_started_at"]
    text = (bench.root / tp.OUT_DIR / "summary-2026-10-02.txt").read_text(
        encoding="utf-8"
    )
    assert f"#3 winner_small {SMALL}: done (done (complete)); 32/32" in text
    assert "commit to docs/results/" in text
    assert "pass B window: pass A 2026-10-02T" in text


def test_pending_items_are_resumed_after_a_wait_before_pass_b(
    bench: Bench,
) -> None:
    pending = play(None, lambda s: with_first(s, http(503), ok()))
    script = bench.keyless() + [pending] + [COMPLETE] * 5
    assert bench.run(script) == 0
    assert bench.paid() == [PASS_A, *PLANNED]
    first_call, resumed = bench.paid_argv()[:2]
    assert "--resume" not in first_call and resumed[-1] == "--resume"
    assert resumed[:-1] == first_call
    assert bench.slept == [60.0]


# Rule 7: a gate stop.


def test_a_gate_stop_runs_the_listed_fallback_once(bench: Bench) -> None:
    script = bench.keyless() + [COMPLETE, COMPLETE, GATED] + [COMPLETE] * 3
    assert bench.run(script) == 0
    assert bench.paid() == [PASS_A, PASS_B, SMALL, SMALL_FB, MID, FRONTIER]
    fallback = bench.paid_argv()[3]
    assert _flag(fallback, "--config").endswith(
        "/qwen3.5-9b_parasail_enabled-false.json"
    )
    assert _flag(fallback, "--max-usd") == "0.150000"
    assert "--resume" not in fallback and not bench.slept
    summary = bench.summary()
    assert summary["outcomes"]["winner_small"] == {
        "state": "done",
        "reason": "done (complete)",
    }
    rows = bench.rows()
    assert rows[SMALL]["state"] == "not_run"
    assert rows[SMALL]["reason"] == "gate stop on its first answer"
    assert rows[SMALL]["commit_to"] == _evidence(SMALL)
    assert rows[SMALL]["registry_update"] == {
        "status": "not_run",
        "reason": "gate stop on its first answer",
        "commit": None,
    }
    assert rows[SMALL_FB]["registry_update"]["status"] == "published"
    assert rows[SMALL_FB]["commit_to"] == f"docs/results/{SMALL_FB}/"
    assert rows[_r2(SMALL)]["registry_update"] == {
        "status": "unused",
        "reason": f"{SMALL} ended not_run without an outage",
        "commit": None,
    }
    assert summary["final"] is True


def test_a_fallback_that_stops_at_the_gate_too_reports_the_slot_not_run(
    bench: Bench,
) -> None:
    script = bench.keyless() + [COMPLETE, COMPLETE, GATED, GATED]
    assert bench.run(script + [COMPLETE] * 2) == 0
    assert bench.paid() == [PASS_A, PASS_B, SMALL, SMALL_FB, MID, FRONTIER]
    assert bench.summary()["outcomes"]["winner_small"] == {
        "state": "not_run",
        "reason": (
            f"gate stop on its first answer; {SMALL_FB} stopped at the gate"
            " too"
        ),
    }
    rows = bench.rows()
    assert rows[SMALL_FB]["commit_to"] == _evidence(SMALL_FB)
    assert rows[_r2(SMALL_FB)]["registry_update"]["reason"] == (
        f"{SMALL_FB} ended not_run without an outage"
    )


@pytest.mark.parametrize(
    ("script", "paid", "reason"),
    [
        (
            [GATED, COMPLETE, COMPLETE, COMPLETE],
            [PASS_A, SMALL, MID, FRONTIER],
            "pass A gate stop on its first answer; no fallback is listed",
        ),
        (
            [COMPLETE, GATED, COMPLETE, COMPLETE, COMPLETE],
            PLANNED,
            "pass B gate stop on its first answer; no fallback is listed",
        ),
    ],
)
def test_an_anchor_gate_stop_reports_the_aa_pair_not_run(
    bench: Bench, script: list[Step], paid: list[str], reason: str
) -> None:
    assert bench.run(bench.keyless() + script) == 0
    assert bench.paid() == paid
    summary = bench.summary()
    assert summary["final"] is True
    assert summary["outcomes"]["aa_pair"] == {
        "state": "not_run",
        "reason": f"the A/A pair is reported not run: {reason}",
    }
    assert summary["outcomes"]["winner_small"]["state"] == "done"
    rows = bench.rows()
    if PASS_B not in paid:
        assert rows[PASS_B]["state"] == "not_run"
        assert rows[PASS_B]["reason"].startswith("not sent; the A/A pair")
        assert rows[PASS_B]["commit_to"] is None
        assert rows[PASS_B]["registry_update"]["status"] == "not_run"


def test_a_resumed_pass_that_reasons_is_not_run_without_a_fallback(
    bench: Bench,
) -> None:
    pending = play(None, lambda s: with_first(s, ok(), http(503)))
    reasons = play(
        "thinking_not_honoured",
        lambda s: with_first(s, REASONED, ok())[:1],
    )
    script = bench.keyless() + [COMPLETE, COMPLETE, pending, reasons]
    assert bench.run(script + [COMPLETE] * 2) == 0
    assert bench.paid() == [PASS_A, PASS_B, SMALL, SMALL, MID, FRONTIER]
    assert bench.summary()["outcomes"]["winner_small"] == {
        "state": "not_run",
        "reason": "its resumed pass stopped at the gate",
    }
    assert bench.rows()[SMALL_FB]["registry_update"]["reason"] == (
        f"{SMALL} ended not_run without a gate stop"
    )


def test_a_refusal_has_no_registered_fallback_or_re_run(bench: Bench) -> None:
    script = bench.keyless() + [COMPLETE, COMPLETE, REFUSED, COMPLETE, COMPLETE]
    assert bench.run(script) == 0
    assert bench.paid() == PLANNED
    assert bench.summary()["outcomes"]["winner_small"] == {
        "state": "not_run",
        "reason": (
            "refused (no_answer_refused_http_404); no fallback or re-run is"
            " registered"
        ),
    }


# Rule 3: an outage.


def test_an_outage_is_re_run_once_from_scratch_under_its_r2_row(
    bench: Bench,
) -> None:
    script = bench.keyless() + [OUTAGE] + [COMPLETE] * 5
    assert bench.run(script) == 0
    assert bench.paid() == [PASS_A, _r2(PASS_A), PASS_B, SMALL, MID, FRONTIER]
    rerun = bench.paid_argv()[1]
    assert "--resume" not in rerun
    assert _flag(rerun, "--config") == _flag(bench.paid_argv()[0], "--config")
    assert _flag(rerun, "--max-usd") == "0.100000"
    assert bench.slept == [60.0]
    assert (
        f"  outage: re-running once from scratch as {_r2(PASS_A)} in 60 s"
        in bench.printed
    )
    summary = bench.summary()
    assert summary["outcomes"]["aa_pair"]["state"] == "done"
    rows = bench.rows()
    assert rows[PASS_A]["reason"] == (
        "outage (no_answer_budget_spent_on_failures)"
    )
    assert rows[PASS_A]["commit_to"] == _evidence(PASS_A)
    assert rows[_r2(PASS_A)]["registry_update"]["status"] == "published"
    started = summary["pass_b_window"]["pass_a_first_started_at"]
    assert started == rows[_r2(PASS_A)]["first_started_at"]


def test_an_outage_on_the_re_run_reports_the_row_not_run(
    bench: Bench,
) -> None:
    script = bench.keyless() + [COMPLETE] * 3 + [OUTAGE, OUTAGE, COMPLETE]
    assert bench.run(script) == 0
    assert bench.paid() == [PASS_A, PASS_B, SMALL, MID, _r2(MID), FRONTIER]
    assert bench.slept == [60.0]
    summary = bench.summary()
    assert summary["outcomes"]["winner_mid"] == {
        "state": "not_run",
        "reason": (
            "outage (no_answer_budget_spent_on_failures);"
            f" {_r2(MID)} met an outage too"
        ),
    }
    rows = bench.rows()
    assert rows[MID_FB]["registry_update"] == {
        "status": "unused",
        "reason": f"{MID} ended not_run without a gate stop",
        "commit": None,
    }
    assert rows[_r2(MID)]["commit_to"] == _evidence(_r2(MID))


# Stops for the owner, and running the same command again.


@pytest.mark.parametrize("status", [401, 402, 403])
def test_an_account_refusal_aborts_the_batch(bench: Bench, status: int) -> None:
    refused = play(
        "fatal_http",
        lambda s: first(3, ok()) + [("C1", 3, http(status))],
    )
    assert bench.run(bench.keyless() + [COMPLETE, refused]) == 3
    assert bench.paid() == [PASS_A, PASS_B]
    assert any(
        line.startswith(f"ABORTED: HTTP {status} on {PASS_B}")
        for line in bench.printed
    )
    assert not (bench.root / tp.OUT_DIR / tp.LOCK_NAME).exists()
    assert bench.summary()["outcomes"]["aa_pair"]["state"] == "owed"


def test_a_budget_stop_waits_for_a_raised_and_committed_cap(
    bench: Bench,
) -> None:
    budget = play("budget", lambda s: first(5, ok()))
    assert bench.run(bench.keyless() + [COMPLETE, COMPLETE, budget]) == 1
    assert bench.paid() == [PASS_A, PASS_B, SMALL]
    message = (
        f"STOPPED: {SMALL}: budget stop after an answer; raise its cap_usd in"
        f" {tp.REGISTRY} and {tp.NOTE} above the last invocation's max_usd"
    )
    assert any(line.startswith(message) for line in bench.printed)
    assert bench.run(bench.keyless()) == 1
    assert not bench.paid()
    assert any(line.startswith(message) for line in bench.printed)
    bench.edit_row(SMALL, cap_usd=0.2)
    assert bench.run(bench.keyless() + [COMPLETE] * 3) == 0
    assert bench.paid() == [SMALL, MID, FRONTIER]
    resumed = bench.paid_argv()[0]
    assert resumed[-1] == "--resume" and _flag(resumed, "--max-usd") == (
        "0.200000"
    )


def test_a_call_step_error_stops_and_the_same_command_resumes(
    bench: Bench,
) -> None:
    script = bench.keyless() + [COMPLETE, refuse("settings_changed")]
    assert bench.run(script) == 1
    assert bench.paid() == [PASS_A, PASS_B]
    assert (
        f"STOPPED: {PASS_B}: the call step ended with an error"
        " (settings_changed, exit 2)"
    ) in bench.printed
    preflight = bench.keyless()
    assert len(preflight) == 14
    assert bench.run(preflight + [COMPLETE] * 4) == 0
    assert bench.paid() == [PASS_B, SMALL, MID, FRONTIER]
    assert bench.summary()["final"] is True


def test_a_call_step_that_leaves_no_run_directory_stops(bench: Bench) -> None:
    def silent(synth: Synth, argv: list[str]) -> Any:
        return db.Invocation(0, {"run_id": synth.run_id}, None)

    assert bench.run(bench.keyless() + [silent]) == 1
    assert (
        f"STOPPED: {PASS_A}: the call step left no run directory"
        in bench.printed
    )


@pytest.mark.parametrize(
    ("delay", "code", "paid"),
    [
        (timedelta(hours=24), 0, [PASS_B, SMALL, MID, FRONTIER]),
        (timedelta(hours=24, seconds=1), 1, []),
    ],
)
def test_pass_b_starts_only_within_24_hours_of_pass_a(
    bench: Bench, delay: timedelta, code: int, paid: list[str]
) -> None:
    _complete(bench, PASS_A)
    manifest = RunManifestV1.model_validate_json(
        (
            bench.root / _CALL_DIR / "runs" / PASS_A / "run_manifest.json"
        ).read_bytes()
    )
    bench.now = manifest.invocations[0].started_at + delay
    assert bench.run(bench.keyless() + [COMPLETE] * len(paid)) == code
    assert bench.paid() == paid
    if code:
        assert any(
            line.startswith("STOPPED: pass B has not started and the 24 hours")
            for line in bench.printed
        )


def test_an_owner_ruling_on_pass_b_lets_the_winners_go_on(
    bench: Bench,
) -> None:
    _complete(bench, PASS_A)
    bench.now += timedelta(hours=30)
    assert bench.run(bench.keyless()) == 1
    reason = "pass B could not start within 24 hours of pass A"
    bench.edit_row(PASS_B, status="not_run", reason=reason)
    assert bench.run(bench.keyless() + [COMPLETE] * 3) == 0
    assert bench.paid() == [SMALL, MID, FRONTIER]
    summary = bench.summary()
    assert summary["outcomes"]["aa_pair"] == {
        "state": "not_run",
        "reason": (
            f"the A/A pair is reported not run: pass B ruled not run: {reason}"
        ),
    }
    assert bench.rows()[_r2(PASS_B)]["registry_update"]["reason"] == (
        f"{PASS_B} ended not_run without an outage"
    )


def test_registry_rulings_are_never_sent(bench: Bench) -> None:
    bench.edit_row(MID, status="not_run", reason="ruled for the test")
    bench.edit_row(SMALL_FB, reason="ruled for the test")
    preflight = bench.keyless()
    assert len(preflight) == 10
    assert bench.run(preflight + [COMPLETE] * 4) == 0
    assert bench.paid() == [PASS_A, PASS_B, SMALL, FRONTIER]
    summary = bench.summary()
    assert summary["outcomes"]["winner_mid"] == {
        "state": "not_run",
        "reason": "ruled not run: ruled for the test",
    }
    rows = bench.rows()
    assert rows[SMALL_FB]["reason"] == "ruled unused: ruled for the test"
    # The owner's committed word is what the registry keeps.
    assert rows[MID]["registry_update"] == {
        "status": "not_run",
        "reason": "ruled for the test",
        "commit": None,
    }


BUDGET = play("budget", lambda s: first(5, ok()))


def _commit_summary(bench: Bench, keep: Sequence[str] = ()) -> None:
    """Commits the registry update the summary gives each row but ``keep``."""
    for run_id, row in bench.rows().items():
        if run_id not in keep:
            bench.edit_row(run_id, **row["registry_update"])


@pytest.mark.parametrize(
    ("script", "stopped", "updates", "keep", "paid"),
    [
        (
            [OUTAGE, COMPLETE, BUDGET],
            PASS_B,
            {PASS_A: "not_run", _r2(PASS_A): "published"},
            (),
            [PASS_B, SMALL, MID, FRONTIER],
        ),
        (
            [COMPLETE, COMPLETE, GATED, BUDGET],
            SMALL_FB,
            {SMALL: "not_run", SMALL_FB: "registered"},
            (),
            [SMALL_FB, MID, FRONTIER],
        ),
        (
            [COMPLETE, COMPLETE, GATED, BUDGET],
            SMALL_FB,
            {SMALL: "not_run", SMALL_FB: "registered"},
            (SMALL_FB,),
            [SMALL_FB, MID, FRONTIER],
        ),
        (
            [OUTAGE, BUDGET],
            _r2(PASS_A),
            {PASS_A: "not_run", _r2(PASS_A): "registered"},
            (),
            [_r2(PASS_A), PASS_B, SMALL, MID, FRONTIER],
        ),
    ],
    ids=[
        "pass-b-after-pass-a-re-run",
        "fallback-registered",
        "fallback-left-unused",
        "pass-a-re-run",
    ],
)
def test_committing_a_stops_statuses_never_drops_a_triggered_run(
    bench: Bench,
    script: list[Step],
    stopped: str,
    updates: dict[str, str],
    keep: tuple[str, ...],
    paid: list[str],
) -> None:
    assert bench.run(bench.keyless() + script) == 1
    rows = bench.rows()
    assert {
        run: rows[run]["registry_update"]["status"] for run in updates
    } == updates
    # The owner commits what the summary gives (here leaving ``keep``
    # unused) and the raised cap, then runs the same command.
    _commit_summary(bench, keep)
    bench.edit_row(stopped, cap_usd=0.2)
    assert bench.run(bench.keyless() + [COMPLETE] * len(paid)) == 0
    assert bench.paid() == paid
    assert bench.paid_argv()[0][-1] == "--resume"
    assert _flag(bench.paid_argv()[0], "--run-id") == stopped
    summary = bench.summary()
    assert summary["final"] is True
    assert summary["rows"][ALL_RUNS.index(stopped)]["state"] == "done"
    for row in summary["rows"]:
        assert row["state"] != "unused" or not row["run"]["exists"]


@pytest.mark.parametrize("held", ["is registered", "left a run directory"])
def test_a_conditional_row_whose_condition_did_not_occur_waits_for_the_owner(
    bench: Bench, held: str
) -> None:
    if held == "is registered":
        bench.edit_row(SMALL_FB, status="registered")
    else:
        _complete(bench, SMALL_FB)
    assert bench.run(bench.keyless() + [COMPLETE] * 5) == 1
    assert bench.paid() == PLANNED
    reason = (
        f"it {held}, but {SMALL} ended done without a gate stop; the owner"
        " rules on it"
    )
    assert bench.rows()[SMALL_FB]["state"] == "owed"
    assert bench.rows()[SMALL_FB]["reason"] == reason
    assert (
        f"STOPPED: no run is due, but the owner rules on {SMALL_FB} ({reason});"
        f" {_r2(SMALL_FB)} (after {SMALL_FB})"
    ) in bench.printed
    assert SMALL_FB not in [
        row.run_id for row in tp.sendable(tp.read_walk(bench.context()))
    ]


def test_a_published_pass_a_without_its_run_stops_pass_b(
    bench: Bench,
) -> None:
    bench.edit_row(PASS_A, status="published", commit="abc1234")
    assert bench.run(bench.keyless()) == 1
    assert not bench.paid()
    assert "STOPPED: pass B is due but no pass A run is complete" in (
        bench.printed
    )


# Refusals before any request.


def test_absent_key_aborts_after_the_keyless_preflight(bench: Bench) -> None:
    assert bench.run(bench.keyless(), key=False) == tp.EXIT_ABORTED == 3
    assert len(bench.calls) == 16 and not bench.paid()
    assert (
        "ABORTED: the keyless preflight passed and nothing was sent:"
        f" {_TEST_KEY} is not set in this shell; set it and run the same"
        " command"
    ) in bench.printed
    preflight = bench.steps("preflight")
    assert [s["error_code"] for s in preflight] == ["api_key_missing"] * 16
    assert not (bench.root / tp.OUT_DIR / tp.LOCK_NAME).exists()
    assert bench.summary()["final"] is False
    assert not (bench.root / _CALL_DIR / "runs").exists()


def test_preflight_must_stop_at_the_missing_key(bench: Bench) -> None:
    assert bench.run([refuse("prepare_code_mismatch")]) == 2
    assert not bench.paid()
    assert (
        f"REFUSED: preflight: {PASS_A} stopped at prepare_code_mismatch"
        " (exit 2)"
    ) in bench.printed


def test_uncommitted_tooling_is_refused_before_a_paid_call(
    bench: Bench,
) -> None:
    change = "?? scripts/test_passes.py"
    assert bench.run(bench.keyless(), changes=[change]) == 2
    assert not bench.paid()
    assert any(change in line for line in bench.printed)
    assert {
        "scripts/test_passes.py",
        "scripts/dev_bakeoff.py",
        db.CONFIG_DIR,
        tp.REGISTRY,
        tp.NOTE,
        "docs/protocol.md",
        "src/dfilterforge/held_out_freeze.json",
    } <= set(tp.TOOLING)


def test_a_missing_prompt_copy_is_refused_with_the_restore_commands(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.rmtree(bench.root / _CALL_DIR)
    assert bench.run([]) == tp.EXIT_REFUSED == 2
    assert not bench.calls
    error = capsys.readouterr().err
    assert f"refused: {_CALL_DIR} is missing (it is ignored by git)" in error
    assert (
        f"in Git Bash: mkdir -p {_CALL_DIR} && cp -r {_COMMITTED}/prepare.json"
        f" {_COMMITTED}/prepared {_CALL_DIR}/ ;"
    ) in error
    assert (
        f"in PowerShell: New-Item -ItemType Directory -Force -Path {_CALL_DIR}"
        f" | Out-Null; Copy-Item -Recurse -Force -Path"
        f" {_COMMITTED}/prepare.json,{_COMMITTED}/prepared -Destination"
        f" {_CALL_DIR}"
    ) in error
    (bench.root / _CALL_DIR).mkdir(parents=True)
    shutil.copy(
        bench.root / _COMMITTED / "prepare.json", bench.root / _CALL_DIR
    )
    shutil.copytree(
        bench.root / _COMMITTED / "prepared",
        bench.root / _CALL_DIR / "prepared",
    )
    assert bench.context().prompts.requests == _REQUESTS


def test_a_prompt_set_the_freeze_does_not_admit_is_refused(
    bench: Bench,
) -> None:
    admitted = bench.layout.admitted
    bench.layout = bench.layout._replace(admitted=frozenset({"0" * 64}))
    with pytest.raises(tp.PlanError, match="not a prompt set the freeze"):
        bench.context()
    bench.layout = bench.layout._replace(admitted=admitted)
    prompts = bench.root / _CALL_DIR / "prepared" / "C2.json"
    prompts.write_bytes(prompts.read_bytes() + b" ")
    with pytest.raises(tp.PlanError, match="prepared/C2.json differs from"):
        bench.context()


def test_dry_run_takes_no_lock_and_sends_nothing(bench: Bench) -> None:
    synth = Synth(bench, PASS_A, bench.config_of(PASS_A))
    synth.invoke(0.1, None, with_first(synth, http(503), ok()))
    assert bench.run([], ["--dry-run"]) == 0
    assert not bench.calls
    assert not (bench.root / tp.OUT_DIR).exists()
    text = "\n".join(bench.printed)
    assert "# | run id | slug | worst request | full-pass worst | cap" in text
    assert f"--run-id {PASS_A}" in text and "--gate-first --resume" in text
    assert f"#2 aa_pass_b {PASS_B}: waiting (after pass A)" in text
    assert f"#6 fallback_small {SMALL_FB}: waiting (after {SMALL})" in text


# Interrupts and errors after a paid call may have been sent.


def test_an_interrupt_releases_the_lock_unless_a_child_runs(
    bench: Bench,
) -> None:
    lock = bench.root / tp.OUT_DIR / tp.LOCK_NAME
    assert bench.run(bench.keyless() + [raises(KeyboardInterrupt())]) == 130
    assert not lock.exists()
    assert bench.steps("interrupted")[-1]["reason"] == "ctrl_c"
    still = db.ChildStillRunning("call step pid 7 is still running")
    assert bench.run(bench.keyless() + [raises(still)]) == 130
    assert lock.exists()
    assert bench.steps("interrupted")[-1]["reason"] == (
        "call_step_still_running"
    )
    assert bench.run([]) == 2 and not bench.calls


def test_an_unexpected_error_is_a_stop_never_a_refusal(bench: Bench) -> None:
    script = bench.keyless() + [raises(RuntimeError("boom"))]
    assert bench.run(script) == tp.EXIT_STOPPED == 1
    assert any(
        line.startswith("STOPPED: unexpected RuntimeError: boom; requests")
        for line in bench.printed
    )
    assert not (bench.root / tp.OUT_DIR / tp.LOCK_NAME).exists()


# The registry the batch accepts.


def _plan(registry: Fields) -> Any:
    return tp.plan_from(tp.RegistryV1.model_validate(registry), "0" * 64)


def _runs(registry: Fields) -> dict[str, Fields]:
    return {row["run_id"]: row for row in registry["runs"]}


Edit = Callable[[Fields], object]


def _edit(change: Edit) -> Edit:
    """Types one registry edit for a parameter list."""
    return change


def _set(target: str, **fields: Any) -> Edit:
    return lambda registry: _runs(registry)[target].update(fields)


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (
            _edit(lambda r: r["runs"].append(dict(r["runs"][0]))),
            "repeats a run id",
        ),
        (
            _edit(lambda r: r["runs"].insert(0, r["runs"].pop(1))),
            "planned runs are",
        ),
        (
            _edit(lambda r: r["call"].update(max_attempts=2)),
            "call options are not the bake-off's",
        ),
        (
            _edit(lambda r: r.update(call_prepare_dir=_COMMITTED)),
            "call_prepare_dir is not under artifacts/model-eval",
        ),
        (
            _edit(
                lambda r: r.update(call_prepare_dir="artifacts/model-eval/x")
            ),
            "answers another prompt set",
        ),
        (_set(PASS_A, run_id=_run("qwen3-32b-a")), "pass A's run id is not"),
        (_set(SMALL, run_id="dev-qwen3.5-9b-2026-09-26"), "not a test result"),
        (_set(SMALL, cap_usd=12.5), "cap outside the call step's bound"),
        (_set(SMALL, config="docs/x/y.json"), "not a committed bake-off"),
        (_set(SMALL, status="not_run"), "not_run without a reason"),
        (_set(SMALL, status="unused"), "a planned run cannot be conditional"),
        (_set(SMALL_FB, conditional_on=None), "a conditional run names no"),
        (_set(SMALL_FB, conditional_on="test-x-2026-09-26"), "unregistered"),
        (_set(_r2(SMALL), config=f"{db.CONFIG_DIR}/x.json"), "not a re-run"),
        (_set(_r2(SMALL_FB), conditional_on=_r2(SMALL)), "not a re-run"),
        (_set(SMALL_FB, conditional_on=MID), "not the fallback of"),
        (
            _set(MID_FB, role="fallback_small", conditional_on=SMALL),
            "two rows for gate_stop",
        ),
    ],
)
def test_a_registry_the_chains_cannot_use_is_refused(
    edit: Edit, match: str
) -> None:
    registry = _registry()
    assert len(_plan(registry).rows) == 16
    edit(registry)
    with pytest.raises(tp.PlanError, match=match):
        _plan(registry)


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (_set(PASS_A, slug="novita"), "sends another route"),
        (_set(SMALL, model_id="qwen/qwen3.5-27b"), "sends another route"),
        (_set(MID, reasoning_switch="effort_none"), "sends another route"),
        (
            _edit(lambda r: r["settings"].update(seed=18)),
            "sends other settings",
        ),
    ],
)
def test_a_config_that_sends_another_route_is_refused(
    bench: Bench, edit: Edit, match: str
) -> None:
    bench.edit_registry(edit)
    with pytest.raises(tp.PlanError, match=match):
        bench.context()


def test_the_chains_link_each_run_to_what_it_triggers() -> None:
    plan = _plan(_registry())
    assert [row.run_id for row in plan.planned] == PLANNED
    assert {run: row.run_id for run, row in plan.fallback_of.items()} == {
        SMALL: SMALL_FB,
        MID: MID_FB,
        FRONTIER: FRONTIER_FB,
    }
    assert {run: row.run_id for run, row in plan.rerun_of.items()} == {
        run: _r2(run) for run in [*PLANNED, SMALL_FB, MID_FB, FRONTIER_FB]
    }


# The committed registry, prompts and note.


@pytest.mark.skipif(not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS)
def test_the_committed_registry_is_a_plan_the_batch_runs() -> None:
    registry, digest = tp.load_registry(_ROOT / tp.REGISTRY)
    plan = tp.plan_from(registry, digest)
    assert registry.call_prepare_dir == _CALL_DIR
    assert plan.prepare == _COMMITTED
    assert [row.run_id for row in plan.planned] == PLANNED
    assert [row.run_id for row in plan.rows] == ALL_RUNS
    assert {run: row.run_id for run, row in plan.fallback_of.items()} == {
        SMALL: SMALL_FB,
        MID: MID_FB,
        FRONTIER: FRONTIER_FB,
    }
    assert len(plan.rerun_of) == 8
    record = held_out.load_record()
    assert record is not None
    committed = _ROOT / _COMMITTED
    prompts = tp.check_prepare(
        committed,
        committed,
        frozenset(record.admitted_prepares),
        (_CALL_DIR, _COMMITTED),
    )
    assert prompts.requests == 448
    endpoints = tp.load_endpoints(plan, _ROOT, prompts.sizes)
    assert set(endpoints) == {row.config for row in plan.rows}


@pytest.mark.skipif(not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS)
def test_the_note_gives_the_owner_command_in_both_shells() -> None:
    note = (_ROOT / tp.NOTE).read_text(encoding="utf-8")
    for text in (
        "uv run --frozen python scripts/test_passes.py",
        "--dry-run",
        "Read-Host -AsSecureString",
        '$env:PYTHONIOENCODING = "utf-8"',
        "exit code: $LASTEXITCODE",
        tp.EVIDENCE_DIR,
    ):
        assert text in note
    for code in (0, 1, 2, 3, 130):
        assert re.search(rf"^\| {code} \|", note, re.MULTILINE)
