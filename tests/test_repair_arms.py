"""The repair arm batch sends the registered arm runs in order and nothing else.

Every base pass, config, note and run directory here is written from the
real contracts (``RunManifestV1``, ``PrepareManifestV1``, ``AttemptV1``)
in a private tree. The follow-up step is a scripted fake that writes a
synthetic C4 prompt set, and the call step is a scripted fake that writes
a run directory as the call step shapes it, so nothing is sent anywhere.
The tests of the committed passes, plans and note skip where the test
image carries no docs/ tree; CI runs them in its step that mounts docs/.
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
import sys
from types import ModuleType
from typing import Any, Literal

import pytest

from dfilterforge import repair_round
from dfilterforge import repair_summary
from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.generation import ChatMessageV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.model_client import API_KEY_ENV

_ROOT = Path(__file__).resolve().parents[1]
Fields = dict[str, Any]
Answers = list[tuple[int, Fields]]
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


ra = _load("repair_arms", "repair_arms")
# The batch's own copies, so every class and helper here is the one it reads.
tp = ra.tp
db = ra.db
model_run = ra.model_run
dbc = _load("dev_bakeoff_configs", "repair_arms_configs")
_BUILD = ra.build_context
_TEST_KEY = "DFILTERFORGE_REPAIR_ARMS_TEST_ONLY"
_NO_DOCS = "the test image carries no docs/ tree"
_DATE = "2026-09-26"
_T0 = datetime(2026, 10, 3, tzinfo=timezone.utc)
_LABEL = "C4"
_CATALOG = CatalogIdentityV1(
    file_name="catalog.sqlite3",
    file_sha256="0" * 64,
    sqlite_sha256="0" * 64,
    catalog_hash="0" * 64,
    tshark_version="4.6.8",
)
# The four repaired dev passes, their configs and planned item counts.
_DEV_CONFIGS = {
    "dev-qwen3-32b-2026-09-26": "qwen3-32b_deepinfra_enabled-false",
    "dev-qwen3.5-9b-2026-09-26": "qwen3.5-9b_deepinfra_enabled-false",
    "dev-qwen3.5-122b-a10b-2026-09-26": (
        "qwen3.5-122b-a10b_novita_enabled-false"
    ),
    "dev-deepseek-v4-pro-0813-2026-09-26": (
        "deepseek-v4-pro-0813_deepinfra_enabled-false"
    ),
}
_DEV = list(_DEV_CONFIGS)
_DEV_CAPS = [0.05, 0.05, 0.10, 0.20]
_TEST_CAPS = [0.05, 0.05, 0.30, 0.50]
_FALLBACK_CONFIGS = {
    "small": "qwen3.5-9b_parasail_enabled-false",
    "mid": "qwen3.5-122b-a10b_atlas-cloud_enabled-false",
    "frontier": "deepseek-v4-pro-0813_nextbit_enabled-false",
}
_TEST_PASSES = [base.replace("dev-", "test-", 1) for base in _DEV]
_PASS_B = f"test-qwen3-32b-passb-{_DATE}"
_ITEMS = 2
_CAPS_ROWS = (
    (
        "frontier",
        "deepseek-v4-pro-0813_deepinfra_enabled-false",
        "0.20",
        "0.50",
    ),
    ("frontier fallback", _FALLBACK_CONFIGS["frontier"], "", "0.50"),
    ("120B", "qwen3.5-122b-a10b_novita_enabled-false", "0.10", "0.30"),
    ("120B fallback", _FALLBACK_CONFIGS["mid"], "", "0.30"),
    ("8B", "qwen3.5-9b_deepinfra_enabled-false", "0.05", "0.05"),
    ("8B fallback", _FALLBACK_CONFIGS["small"], "", "0.05"),
    ("anchor", "qwen3-32b_deepinfra_enabled-false", "0.05", "0.05"),
)


def _arms(base: str) -> list[str]:
    stem = base.removesuffix(f"-{_DATE}")
    return [f"{stem}-{tag}-{_DATE}" for tag in ("res", "bare", "cx")]


def _r2(arm_run: str) -> str:
    return arm_run.removesuffix(f"-{_DATE}") + f"-r2-{_DATE}"


def _origin(run_id: str) -> tuple[str, str]:
    """Returns the pass and arm an arm run id, or its re-run id, names."""
    for base in _DEV + _TEST_PASSES:
        for arm, run in zip(ra.ARMS, _arms(base)):
            if run_id in (run, _r2(run)):
                return base, arm
    raise AssertionError(run_id)


DEV_ARMS = [run for base in _DEV for run in _arms(base)]
TEST_ARMS = [run for base in _TEST_PASSES for run in _arms(base)]
ANCHOR_RES, ANCHOR_BARE, ANCHOR_CX = DEV_ARMS[:3]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def _note(
    rows: Sequence[tuple[str, str, str, str]] = _CAPS_ROWS,
    raised: Sequence[tuple[str, str]] = (),
) -> str:
    """A repair note holding the caps and raised caps tables the batch reads."""
    lines = [
        "# Repair round",
        "",
        "## Caps and worst cases",
        "",
        "| Slot | Config | Dev cap | Test cap | Worst request | At 64 KiB |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
        *(f"| {s} | `{c}` | {d} | {t} | 0.01 | 0.09 |" for s, c, d, t in rows),
        "",
        "- Headroom.",
        "",
        "| Arm run | Raised cap |",
        "| --- | ---: |",
        *(f"| `{run}` | {usd} |" for run, usd in raised),
        "",
        "## Order",
    ]
    return "\n".join(lines) + "\n"


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


def _prompt(
    item: str, split: str, arm: str | None, filler: int = 0
) -> PreparedPromptV1:
    """One C4 prompt: a first turn, or one continued as ``arm`` continues it."""
    contract, retrieval = OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL
    user: dict[str, object] = {"request": "dns queries", "retrieved_fields": []}
    messages = [
        ChatMessageV1(role="system", content="S" * (400 + filler)),
        ChatMessageV1(
            role="user", content="INPUT_JSON\n" + canonical_json(user)
        ),
    ]
    if arm in ("bare", "counterexample"):
        turn = "Your filter was incorrect."
        if arm == "counterexample":
            turn += '\nCOUNTEREXAMPLE_JSON\n{"error":"unknown_field"}'
        messages += [
            ChatMessageV1(role="assistant", content="{}"),
            ChatMessageV1(role="user", content=turn),
        ]
    return PreparedPromptV1(
        item_id=item,
        split=split,
        output_contract=contract,
        retrieval=retrieval,
        messages=tuple(messages),
    )


def _write_prompts(
    directory: Path,
    split: str,
    items: Sequence[str],
    arm: str | None,
    stamp: datetime,
    revision: str,
) -> PrepareManifestV1:
    """Writes one C4 prompt set as the prepare and follow-up steps do."""
    batch = PreparedBatchV1(
        output_contract=OutputContractV1.TYPED_IR,
        retrieval=RetrievalV1.LEXICAL,
        prompts=tuple(
            _prompt(item, split, arm, index) for index, item in enumerate(items)
        ),
    )
    path = directory / "prepared" / f"{_LABEL}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (canonical_json(batch) + "\n").encode("utf-8")
    path.write_bytes(data)
    manifest = PrepareManifestV1(
        prepare_id=directory.name,
        created_at=stamp,
        source_revision=revision,
        source_files={},
        split="dev" if split == "dev" else "test",
        item_ids=tuple(items),
        model_inputs_sha256="0" * 64,
        catalog=_CATALOG,
        top_k=16,
        conditions=(
            PreparedConditionV1(
                label=_LABEL,
                output_contract=batch.output_contract,
                retrieval=batch.retrieval,
                path=f"prepared/{_LABEL}.json",
                sha256=_sha256(data),
                system_prompt_sha256="0" * 64,
                prompt_count=len(items),
            ),
        ),
    )
    (directory / "prepare.json").write_bytes(
        (canonical_json(manifest) + "\n").encode("utf-8")
    )
    return manifest


def _write_base(root: Path, run_id: str, config: str) -> None:
    """Writes a complete published pass and its plan, as the batch reads them."""
    directory = root / ra.RESULTS / run_id
    split = run_id.split("-", 1)[0]
    items = [f"mei-{index:04d}" for index in range(1, _ITEMS + 1)]
    prepare = _write_prompts(
        directory, split, items, None, _T0 - timedelta(days=7), "base"
    )
    call = model_run.CallConfigV1.model_validate_json(
        (root / db.CONFIG_DIR / f"{config}.json").read_bytes()
    )
    manifest = RunManifestV1(
        run_id=run_id,
        created_at=_T0 - timedelta(days=7),
        prepare=prepare,
        prepare_sha256=_sha256((directory / "prepare.json").read_bytes()),
        endpoint_host="openrouter.ai",
        settings=call.settings,
        prices=call.prices,
        max_attempts=3,
        min_interval_seconds=1.0,
        invocations=(
            InvocationV1(
                source_revision="base",
                source_files={},
                started_at=_T0 - timedelta(days=7),
                finished_at=_T0 - timedelta(days=7),
                max_usd=1.0,
                requests_sent=len(items),
            ),
        ),
        status="complete",
        charged_usd_upper_bound=0.001,
        conditions=(
            ConditionRunV1(
                label=_LABEL,
                attempts_path=f"attempts/{_LABEL}.jsonl",
                attempts_sha256="0" * 64,
                completions_path=f"completions/{_LABEL}.json",
                completions_sha256="0" * 64,
                attempts={item: 1 for item in items},
                completed=len(items),
                failed=0,
                pending=0,
            ),
        ),
    )
    (directory / "run_manifest.json").write_text(
        manifest.model_dump_json() + "\n", encoding="utf-8"
    )
    plan = directory / ra.PLAN_PATH
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("{}\n", encoding="utf-8")


def _registry_rows() -> list[Fields]:
    """The 16 registered test rows, the five planned ones published."""
    specs = {spec.name: spec for spec in dbc.SPECS}
    rows: list[Fields] = []

    def add(
        role: str,
        run_id: str,
        config: str,
        named: str | None = None,
        trigger: str | None = None,
    ) -> None:
        spec = specs[config]
        rows.append(
            {
                "role": role,
                "run_id": run_id,
                "model_id": spec.model_id,
                "slug": spec.route,
                "quant": "bf16",
                "reasoning_switch": spec.reasoning,
                "config": f"{db.CONFIG_DIR}/{config}.json",
                "cap_usd": 0.5,
                "prepare": f"docs/results/test-qwen3-32b-{_DATE}",
                "conditional_on": named,
                "trigger": trigger,
                "status": "published" if trigger is None else "unused",
                "reason": None,
                "commit": None if trigger else "abc1234",
            }
        )

    configs = list(_DEV_CONFIGS.values())
    add("aa_pass_a", _TEST_PASSES[0], configs[0])
    add("aa_pass_b", _PASS_B, configs[0])
    for role, run_id, config in zip(
        ("winner_small", "winner_mid", "winner_frontier"),
        _TEST_PASSES[1:],
        configs[1:],
    ):
        add(role, run_id, config)
    for slot, run_id in zip(("small", "mid", "frontier"), _TEST_PASSES[1:]):
        fallback = run_id.replace(f"-{_DATE}", f"-fb-{_DATE}")
        add(
            f"fallback_{slot}",
            fallback,
            _FALLBACK_CONFIGS[slot],
            run_id,
            "gate_stop",
        )
    for row in list(rows):
        add(
            row["role"],
            _r2(row["run_id"]),
            Path(row["config"]).stem,
            row["run_id"],
            "outage",
        )
    return rows


def _registry() -> Fields:
    return {
        "schema": "test-runs/1.0",
        "registered_on": "2026-10-01",
        "note": tp.NOTE,
        "ruling": "docs/decisions/evidence/bakeoff/ruling-2026-10-01.json",
        "call_prepare_dir": f"artifacts/model-eval/test-qwen3-32b-{_DATE}",
        "settings": {
            "temperature": 0.0,
            "seed": 17,
            "max_output_tokens": 2048,
            "timeout_seconds": 120.0,
            "json_mode": True,
            "require_parameters": True,
            "allow_fallbacks": False,
            "data_collection": None,
        },
        "call": {
            "gate_first": True,
            "max_attempts": 3,
            "min_interval_seconds": 1.0,
        },
        "repair_arms": {
            "repaired_roles": [
                "aa_pass_a",
                "winner_small",
                "winner_mid",
                "winner_frontier",
                "fallback_small",
                "fallback_mid",
                "fallback_frontier",
            ]
        },
        "runs": _registry_rows(),
    }


@pytest.fixture(name="template", scope="module")
def fixture_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository tree with the configs, the note, passes and registry."""
    root = tmp_path_factory.mktemp("repair-arms")
    used = {*_DEV_CONFIGS.values(), *_FALLBACK_CONFIGS.values()}
    for spec in dbc.SPECS:
        if spec.name in used:
            config, _ = dbc.build_config(
                spec, _metadata(spec), "2026-09-26T00:00:00Z"
            )
            _write_json(root / db.CONFIG_DIR / f"{spec.name}.json", config)
    (root / ra.NOTE).parent.mkdir(parents=True, exist_ok=True)
    (root / ra.NOTE).write_text(_note(), encoding="utf-8")
    for base, config in _DEV_CONFIGS.items():
        _write_base(root, base, config)
    for base, config in zip(_TEST_PASSES, _DEV_CONFIGS.values()):
        _write_base(root, base, config)
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
    """A private repository tree, a fake follow-up and call step, a clock.

    ``items`` gives each base pass's planned item count and ``refusals``
    the code follow-up refuses with, by base pass or by (base pass, arm).
    The waits before a resume or a re-run are recorded in ``slept``.
    """

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.monkeypatch = monkeypatch
        self.split = "dev"
        self.admitted: set[str] = set()
        self.printed: list[str] = []
        self.slept: list[float] = []
        self.now = _T0
        self.calls: list[tuple[list[str], bool]] = []
        self.script: list[Step] = []
        self.follow_ups: list[dict[str, str]] = []
        self.refusals: dict[Any, str] = {}
        monkeypatch.setattr(ra, "pause", self.slept.append)

    def tick(self) -> datetime:
        """Moves the clock on by one second."""
        self.now += timedelta(seconds=1)
        return self.now

    @property
    def layout(self) -> Any:
        """Returns the batch's layout over this tree."""
        return tp.Layout(
            self.root, self.root / ra.OUT_DIR, frozenset(self.admitted)
        )

    def context(self, split: str | None = None) -> Any:
        """Builds the batch's context from the tree as it now stands."""
        ctx = _BUILD(split or self.split, self.layout, "test-rev")
        ctx.out = self.printed.append
        ctx.invoke = self.invoke
        ctx.follow_up = self.follow_up
        return ctx

    def follow_up(
        self, argv: Sequence[str]
    ) -> tuple[Fields | None, str | None]:
        """Plays the follow-up step: writes the arm's synthetic prompt set."""
        args = dict(zip(argv[1::2], argv[2::2]))
        assert argv[0] == "follow-up" and len(argv) == 11
        self.follow_ups.append(args)
        base = Path(args["--from-run"]).name
        arm = args["--arm"]
        assert args["--plan"] == f"{args['--from-run']}/{ra.PLAN_PATH}"
        code = self.refusals.get((base, arm)) or self.refusals.get(base)
        if code is not None:
            return None, code
        output = Path(args["--output-dir"])
        if output.exists():
            return None, "output_exists"
        items = [f"mei-{index:04d}" for index in range(1, _ITEMS + 1)]
        _write_prompts(
            output,
            base.split("-", 1)[0],
            items,
            arm,
            self.tick(),
            args["--source-revision"],
        )
        return {"prepare_id": output.name, "items": items, "arm": arm}, None

    def seed(self, run_id: str, admit: bool = True) -> str:
        """Commits a test arm's seed as the seeding step writes it."""
        base, arm = _origin(run_id)
        report, _ = self.follow_up(
            ra.follow_up_argv(
                (self.root / ra.RESULTS / base).as_posix(),
                arm,
                (self.root / ra.RESULTS / run_id).as_posix(),
                "seed-rev",
            )
        )
        assert report is not None
        digest = _sha256(
            (self.root / ra.RESULTS / run_id / "prepare.json").read_bytes()
        )
        if admit:
            self.admitted.add(digest)
        return digest

    def invoke(self, argv: Sequence[str], with_key: bool) -> Any:
        """Plays the next scripted call step."""
        argv = list(argv)
        self.calls.append((argv, with_key))
        assert self.script, f"unexpected call {argv}"
        step = self.script.pop(0)
        synth = Synth(self, _flag(argv, "--run-id"), _flag(argv, "--config"))
        return step(synth, argv)

    def keyless(self) -> list[Step]:
        """The preflight steps one execution makes from this state."""
        ctx = self.context()
        ra.prepare_all(ctx, False)
        self.follow_ups.clear()
        return [refuse("api_key_missing")] * len(ra.calls_due(ctx))

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

        def changed(ctx: Any) -> list[str]:
            return list(changes)

        monkeypatch.setattr(ra, "build_context", self.context)
        monkeypatch.setattr(ra, "tooling_changes", changed)
        monkeypatch.setattr(ra, "API_KEY_ENV", _TEST_KEY)
        if key:
            monkeypatch.setenv(_TEST_KEY, "not-a-credential")
        else:
            monkeypatch.delenv(_TEST_KEY, raising=False)
        code = ra.main(["--split", self.split, *argv])
        assert not self.script, "a scripted call step was never made"
        return code

    def paid(self) -> list[str]:
        """Returns the run id of every call made with the key, in order."""
        return [_flag(argv, "--run-id") for argv, key in self.calls if key]

    def paid_argv(self) -> list[list[str]]:
        """Returns every argument list sent with the key, in order."""
        return [argv for argv, key in self.calls if key]

    def summary(self) -> Fields:
        """Reads the newest JSON summary of the bench's split."""
        out = self.root / ra.OUT_DIR
        path = max(out.glob(f"summary-{self.split}-*.json"))
        return json.loads(path.read_text(encoding="utf-8"))

    def rows(self) -> dict[str, Fields]:
        """Returns the newest summary's rows by first run id."""
        return {row["run_id"]: row for row in self.summary()["rows"]}

    def steps(self, phase: str) -> list[Fields]:
        """Returns the step log's records of one phase."""
        log = self.root / ra.OUT_DIR / ra.STEP_LOG
        records = map(json.loads, log.read_text(encoding="utf-8").splitlines())
        return [record for record in records if record["phase"] == phase]


@pytest.fixture(name="bench")
def fixture_bench(
    template: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Bench:
    """A private tree; nothing is invoked."""
    root = tmp_path / "repo"
    shutil.copytree(template, root)
    return Bench(root, monkeypatch)


class Synth:
    """Writes one arm run directory exactly as the call step shapes it."""

    def __init__(self, bench: Bench, run_id: str, config: str) -> None:
        self.bench = bench
        prepare_dir = bench.root / ra.PREPARE_ROOT / run_id
        self.run_dir = prepare_dir / "runs" / run_id
        self.run_id = run_id
        self.prepare_bytes = (prepare_dir / "prepare.json").read_bytes()
        self.prepare = PrepareManifestV1.model_validate_json(self.prepare_bytes)
        self.items = self.prepare.item_ids
        self.config = model_run.CallConfigV1.model_validate_json(
            (bench.root / config).read_bytes()
        )
        self.attempts: dict[str, list[Any]] = {item: [] for item in self.items}
        self.invocations: list[InvocationV1] = []
        if (self.run_dir / "run_manifest.json").exists():
            manifest = RunManifestV1.model_validate_json(
                (self.run_dir / "run_manifest.json").read_bytes()
            )
            self.invocations = list(manifest.invocations)
            path = self.run_dir / "attempts" / f"{_LABEL}.jsonl"
            for line in path.read_bytes().split(b"\n"):
                if line:
                    attempt = model_run.AttemptV1.model_validate_json(line)
                    self.attempts[attempt.completion.item_id].append(attempt)

    def unsettled(self) -> list[int]:
        """Lists the prompts a further pass would still send, in order."""
        return [
            index
            for index, item in enumerate(self.items)
            if not model_run._is_settled(self.attempts[item], db.MAX_ATTEMPTS)
        ]

    def invoke(
        self, max_usd: float, stop_reason: StopReason, answers: Answers
    ) -> dict[str, Any]:
        """Records one invocation and returns the report it would print."""
        started = self.bench.tick()
        for index, fields in answers:
            item = self.items[index]
            entries = self.attempts[item]
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
                source_revision="test-rev",
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
        """Writes the log and the manifest, census included."""
        log = self.run_dir / "attempts" / f"{_LABEL}.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "".join(
                attempt.model_dump_json() + "\n"
                for item in self.items
                for attempt in self.attempts[item]
            ),
            encoding="utf-8",
            newline="\n",
        )
        states = [
            model_run._prompt_state(self.attempts[item], db.MAX_ATTEMPTS)
            for item in self.items
        ]
        complete = "pending" not in states
        digest = None
        if complete:
            path = self.run_dir / "completions" / f"{_LABEL}.json"
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
            digest = _sha256(path.read_bytes())
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
                for entries in self.attempts.values()
                for attempt in entries
            )
            / db.MICRO,
            conditions=(
                ConditionRunV1(
                    label=_LABEL,
                    attempts_path=f"attempts/{_LABEL}.jsonl",
                    attempts_sha256=_sha256(log.read_bytes()),
                    completions_path=(
                        f"completions/{_LABEL}.json" if complete else None
                    ),
                    completions_sha256=digest,
                    attempts={
                        item: len(self.attempts[item]) for item in self.items
                    },
                    completed=states.count("completed"),
                    failed=states.count("failed"),
                    pending=states.count("pending"),
                ),
            ),
        )
        (self.run_dir / "run_manifest.json").write_text(
            manifest.model_dump_json() + "\n", encoding="utf-8"
        )
        return manifest


def first(count: int, fields: Fields) -> Answers:
    """Answers the first ``count`` prompts in prepare order."""
    return [(index, fields) for index in range(count)]


def rest(synth: Synth, fields: Fields) -> Answers:
    """Answers every prompt the run still owes an attempt."""
    return [(index, fields) for index in synth.unsettled()]


def play(stop: StopReason, answers: Callable[[Synth], Answers]) -> Step:
    """A call step that records ``answers`` and stops with ``stop``."""

    def step(synth: Synth, argv: list[str]) -> Any:
        report = synth.invoke(
            float(_flag(argv, "--max-usd")), stop, answers(synth)
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
PENDING = play(None, lambda s: [(0, http(503)), (1, ok())])
BUDGET = play("budget", lambda s: first(1, ok()))


# The rows, the order, the argument lists and the summary.


def test_dev_arm_runs_are_sent_in_the_notes_order_after_a_keyless_preflight(
    bench: Bench,
) -> None:
    preflight = bench.keyless()
    assert len(preflight) == len(DEV_ARMS) == 12
    assert bench.run(preflight + [COMPLETE] * 12) == ra.EXIT_OK == 0
    keyless = [argv for argv, key in bench.calls if not key]
    assert [argv for argv, _ in bench.calls[:12]] == keyless
    assert [_flag(argv, "--run-id") for argv in keyless] == DEV_ARMS
    assert bench.paid() == DEV_ARMS
    assert bench.paid_argv()[1] == [
        sys.executable,
        "scripts/model_run.py",
        "call",
        "--prepare-dir",
        f"artifacts/repair/{ANCHOR_BARE}",
        "--run-id",
        ANCHOR_BARE,
        "--config",
        f"{db.CONFIG_DIR}/qwen3-32b_deepinfra_enabled-false.json",
        "--max-usd",
        "0.050000",
        "--source-revision",
        "test-rev",
        "--min-interval-seconds",
        "1.0",
        "--max-attempts",
        "3",
        "--gate-first",
    ]
    caps = [float(_flag(argv, "--max-usd")) for argv in bench.paid_argv()]
    assert caps == [cap for cap in _DEV_CAPS for _ in range(3)]
    configs = [_flag(argv, "--config") for argv in bench.paid_argv()]
    assert configs == [
        f"{db.CONFIG_DIR}/{config}.json"
        for config in _DEV_CONFIGS.values()
        for _ in range(3)
    ]
    # Every prompt set was built by follow-up from its pass and plan before
    # the first call, and each is what its arm builds.
    built = list(bench.follow_ups)
    assert [Path(args["--output-dir"]).name for args in built] == DEV_ARMS
    assert [args["--arm"] for args in built] == list(ra.ARMS) * 4
    assert [Path(args["--from-run"]).name for args in built] == [
        base for base in _DEV for _ in range(3)
    ]
    for run_id in DEV_ARMS:
        prepare = bench.root / ra.PREPARE_ROOT / run_id / "prepare.json"
        assert (
            PrepareManifestV1.model_validate_json(
                prepare.read_bytes()
            ).prepare_id
            == run_id
        )
    assert not list((bench.root / ra.PREPARE_ROOT).glob(".*"))
    assert "exit 0" in bench.printed
    assert all(s["argv"][0] == "python" for s in bench.steps("preflight"))


def test_the_summary_names_what_the_maintainer_publishes(bench: Bench) -> None:
    gated = [GATED] + [COMPLETE] * 11
    assert bench.run(bench.keyless() + gated) == 0
    summary = bench.summary()
    assert summary["final"] is True and summary["split"] == "dev"
    rows = bench.rows()
    assert rows[ANCHOR_RES]["state"] == "not_run"
    assert rows[ANCHOR_RES]["maintainer"] == {
        "commit_to": f"{ra.EVIDENCE_DIR}/{ANCHOR_RES}/",
        "repair_not_run": "resample",
    }
    assert rows[ANCHOR_BARE]["maintainer"] == {
        "commit_to": f"docs/results/{ANCHOR_BARE}/",
        "publish": (
            "python scripts/model_run.py publish --run-dir"
            f" artifacts/repair/{ANCHOR_BARE}/runs/{ANCHOR_BARE} --output"
            f" docs/results/{ANCHOR_BARE}"
        ),
    }
    assert rows[ANCHOR_BARE]["run"]["completed"] == _ITEMS
    assert rows[ANCHOR_BARE]["items"] == _ITEMS
    assert rows[ANCHOR_BARE]["cap_usd"] == 0.05
    rounds = {line["base_run"]: line for line in summary["rounds"]}
    assert rounds[_DEV[0]]["repair"] == [
        "repair",
        "--run-dir",
        f"/workspace/results/{_DEV[0]}",
        "--code-revision",
        "REV",
        "--not-run",
        "resample",
    ]
    assert rounds[_DEV[1]]["repair"][-1] == "REV"
    assert summary["charged_usd_upper_bound_total"] == pytest.approx(
        11 * _ITEMS * 10 / db.MICRO + 10 / db.MICRO
    )
    text = max((bench.root / ra.OUT_DIR).glob("summary-dev-*.txt"))
    lines = text.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith(f"#1 anchor resample {ANCHOR_RES}: not_run")
    assert f"commit its evidence to {ra.EVIDENCE_DIR}/{ANCHOR_RES}/" in lines[0]
    assert lines[1].endswith(f"--output docs/results/{ANCHOR_BARE}")


def test_a_second_execution_finds_every_row_final_and_sends_nothing(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0
    bench.follow_ups.clear()
    assert bench.run([]) == 0
    assert not bench.calls and not bench.follow_ups
    assert "0 arm runs may be sent; keyless preflight:" in bench.printed


def test_pending_items_are_resumed_after_a_wait(bench: Bench) -> None:
    script = bench.keyless() + [PENDING, COMPLETE] + [COMPLETE] * 11
    assert bench.run(script) == 0
    assert bench.paid()[:2] == [ANCHOR_RES, ANCHOR_RES]
    assert _flag(bench.paid_argv()[1], "--max-usd") == "0.050000"
    assert bench.paid_argv()[1][-1] == "--resume"
    assert bench.slept == [db.RESUME_WAIT_SECONDS]
    assert bench.rows()[ANCHOR_RES]["state"] == "done"


def test_a_gate_stop_is_not_run_and_never_moved_to_another_provider(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [GATED] + [COMPLETE] * 11) == 0
    # The bare arm follows the gated resample on the same config.
    assert bench.paid()[:2] == [ANCHOR_RES, ANCHOR_BARE]
    assert len(bench.paid()) == 12
    assert {_flag(argv, "--config") for argv in bench.paid_argv()[:3]} == {
        f"{db.CONFIG_DIR}/qwen3-32b_deepinfra_enabled-false.json"
    }
    row = bench.rows()[ANCHOR_RES]
    assert (row["state"], row["kind"]) == ("not_run", "gate_stop")
    assert "never moved to another provider" in row["reason"]
    assert not bench.slept


def test_a_resumed_pass_that_reasons_is_not_run(bench: Bench) -> None:
    late = play("thinking_not_honoured", lambda s: [(0, REASONED)])
    script = bench.keyless() + [PENDING, late] + [COMPLETE] * 11
    assert bench.run(script) == 0
    row = bench.rows()[ANCHOR_RES]
    assert (row["state"], row["kind"]) == ("not_run", "reasoned")
    assert row["maintainer"]["repair_not_run"] == "resample"


def test_a_refusal_is_not_run_without_a_fallback(bench: Bench) -> None:
    assert bench.run(bench.keyless() + [REFUSED] + [COMPLETE] * 11) == 0
    row = bench.rows()[ANCHOR_RES]
    assert (row["state"], row["kind"]) == ("not_run", "refused")
    assert row["reason"] == (
        "refused (no_answer_refused_http_404); an arm has no fallback"
    )
    assert row["maintainer"]["repair_not_run"] is None
    rounds = {line["base_run"]: line for line in bench.summary()["rounds"]}
    assert "the owner rules on resample first" in rounds[_DEV[0]]["next"]
    assert bench.paid()[1] == ANCHOR_BARE


def test_an_outage_is_re_run_once_from_scratch_under_its_r2_id(
    bench: Bench,
) -> None:
    rerun = _r2(ANCHOR_RES)
    script = (
        bench.keyless()
        + [OUTAGE, refuse("api_key_missing"), COMPLETE]
        + [COMPLETE] * 11
    )
    assert bench.run(script) == 0
    assert bench.paid()[:3] == [ANCHOR_RES, rerun, ANCHOR_BARE]
    # The re-run's own prompt set is built, then checked without the key.
    keyless = [argv for argv, key in bench.calls if not key]
    assert _flag(keyless[-1], "--run-id") == rerun
    assert _flag(keyless[-1], "--prepare-dir") == f"artifacts/repair/{rerun}"
    built = [Path(args["--output-dir"]).name for args in bench.follow_ups]
    assert rerun in built
    assert bench.slept == [db.RESUME_WAIT_SECONDS]
    row = bench.rows()[ANCHOR_RES]
    assert (row["state"], row["counted_run_id"]) == ("done", rerun)
    assert row["maintainer"]["commit_to"] == f"docs/results/{rerun}/"
    assert row["maintainer"]["first_run_evidence"] == (
        f"{ra.EVIDENCE_DIR}/{ANCHOR_RES}/"
    )
    text = max((bench.root / ra.OUT_DIR).glob("summary-dev-*.txt"))
    assert (
        f"; commit its first run's evidence to {ra.EVIDENCE_DIR}/{ANCHOR_RES}/"
    ) in text.read_text(encoding="utf-8").splitlines()[0]


def test_the_summary_counts_the_first_run_an_r2_re_run_replaced(
    bench: Bench,
) -> None:
    script = (
        bench.keyless()
        + [OUTAGE, refuse("api_key_missing"), COMPLETE]
        + [COMPLETE] * 11
    )
    assert bench.run(script) == 0
    # The bound is every run manifest's, the outage's included.
    manifests = list(
        (bench.root / ra.PREPARE_ROOT).glob("*/runs/*/run_manifest.json")
    )
    assert len(manifests) == 13
    read = RunManifestV1.model_validate_json
    charged = sum(
        read(path.read_bytes()).charged_usd_upper_bound for path in manifests
    )
    summary = bench.summary()
    assert summary["charged_usd_upper_bound_total"] == pytest.approx(charged)
    assert charged == pytest.approx(13 * _ITEMS * 10 / db.MICRO)
    row = bench.rows()[ANCHOR_RES]
    assert row["counted_run_id"] == _r2(ANCHOR_RES)
    assert row["first_run"] == {
        "run_id": ANCHOR_RES,
        "charged_usd_upper_bound": pytest.approx(_ITEMS * 10 / db.MICRO),
    }
    assert bench.rows()[ANCHOR_BARE]["first_run"] is None
    text = max((bench.root / ra.OUT_DIR).glob("summary-dev-*.txt"))
    lines = text.read_text(encoding="utf-8").splitlines()
    assert (
        f"; 0.0001 USD charged at most; its first run {ANCHOR_RES} charged"
        " at most 0.0001 USD;"
    ) in lines[0]
    assert lines[-1] == (
        "total charged upper bound: 0.0003 USD, rounded up (0.000260 exact),"
        " every first run an -r2 re-run replaced included"
    )


def test_a_printed_spend_bound_is_rounded_up() -> None:
    assert ra.usd_up(0.00024) == "0.0003"
    assert ra.usd_up(0.00021) == "0.0003"
    assert ra.usd_up(0.0002) == "0.0002"
    assert ra.usd_up(0.547306) == "0.5474"
    assert ra.usd_up(0.0) == "0.0000"


def test_an_outage_on_the_re_run_reports_the_row_not_run(bench: Bench) -> None:
    script = (
        bench.keyless()
        + [OUTAGE, refuse("api_key_missing"), OUTAGE]
        + [COMPLETE] * 11
    )
    assert bench.run(script) == 0
    row = bench.rows()[ANCHOR_RES]
    assert row["state"] == "not_run"
    assert row["maintainer"] == {
        "commit_to": f"{ra.EVIDENCE_DIR}/{_r2(ANCHOR_RES)}/",
        "repair_not_run": None,
        "first_run_evidence": f"{ra.EVIDENCE_DIR}/{ANCHOR_RES}/",
    }
    assert row["reason"].endswith(
        f"its re-run {_r2(ANCHOR_RES)} met an outage too"
    )
    assert len(bench.paid()) == 13


def test_a_re_run_id_too_long_for_a_result_name_is_not_run(
    bench: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ra, "RERUN_TAG", "r2" + "x" * 40)
    assert bench.run(bench.keyless() + [OUTAGE] + [COMPLETE] * 11) == 0
    row = bench.rows()[ANCHOR_RES]
    assert row["state"] == "not_run"
    assert "is not a result name, so it cannot be re-run" in row["reason"]
    assert bench.paid()[1] == ANCHOR_BARE


@pytest.mark.parametrize("status", [401, 402, 403])
def test_an_account_refusal_aborts_the_batch(bench: Bench, status: int) -> None:
    blocked = play("fatal_http", lambda s: first(1, http(status)))
    assert bench.run(bench.keyless() + [blocked]) == ra.EXIT_ABORTED == 3
    assert bench.paid() == [ANCHOR_RES]
    assert any(
        line.startswith(f"ABORTED: HTTP {status} on {ANCHOR_RES}")
        for line in bench.printed
    )


def test_a_budget_stop_waits_for_a_raised_and_committed_cap(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [BUDGET]) == ra.EXIT_STOPPED == 1
    stop = next(line for line in bench.printed if line.startswith("STOPPED"))
    assert stop == (
        f"STOPPED: {ANCHOR_RES}: budget stop after an answer at its cap 0.05"
        f" USD; raise this run's cap alone, in a row `{ANCHOR_RES}` of"
        f" {ra.NOTE}'s raised caps table above the last invocation's max_usd,"
        " commit it and run the same command again"
    )
    assert bench.run(bench.keyless()) == 1
    assert len(bench.paid()) == 0
    note = _note(raised=[(ANCHOR_RES, "0.06")])
    (bench.root / ra.NOTE).write_text(note, encoding="utf-8")
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0
    assert bench.paid()[0] == ANCHOR_RES
    assert bench.paid_argv()[0][-1] == "--resume"
    # The raise is the stopped run's alone: the slot's other arms start at
    # the registered cap.
    caps = [_flag(argv, "--max-usd") for argv in bench.paid_argv()]
    assert caps[:3] == ["0.060000", "0.050000", "0.050000"]
    assert bench.paid()[1:3] == [ANCHOR_BARE, ANCHOR_CX]
    rows = bench.rows()
    assert (rows[ANCHOR_RES]["cap_usd"], rows[ANCHOR_BARE]["cap_usd"]) == (
        0.06,
        0.05,
    )
    assert rows[ANCHOR_RES]["registered_cap_usd"] == 0.05


def test_a_raise_only_resumes_a_budget_stop_of_its_own_run(
    bench: Bench,
) -> None:
    # A raise of a run that has not started would start it above the cap
    # the protocol registers.
    note = _note(raised=[(ANCHOR_BARE, "0.06")])
    (bench.root / ra.NOTE).write_text(note, encoding="utf-8")
    assert bench.run([]) == 2
    assert not bench.calls
    assert (
        f"REFUSED: {ANCHOR_BARE}: {ra.NOTE} raises its cap to 0.06 USD, but it"
        " has no budget stop to resume, and a raised cap only resumes one;"
        " delete that row of the raised caps table, commit it and run the"
        " same command"
    ) in bench.printed
    # Nor does it resume a run that a pending item, not its budget, stopped.
    (bench.root / ra.NOTE).write_text(_note(), encoding="utf-8")
    assert bench.run(bench.keyless() + [PENDING, refuse("io_error")]) == 1
    note = _note(raised=[(ANCHOR_RES, "0.06")])
    (bench.root / ra.NOTE).write_text(note, encoding="utf-8")
    assert bench.run([]) == 2
    assert not bench.calls
    assert any(
        line.startswith(f"REFUSED: {ANCHOR_RES}: {ra.NOTE} raises its cap")
        for line in bench.printed
    )


def test_an_outage_re_run_keeps_the_registered_cap(bench: Bench) -> None:
    rerun = _r2(ANCHOR_RES)
    note = _note(raised=[(rerun, "0.06")])
    (bench.root / ra.NOTE).write_text(note, encoding="utf-8")
    assert bench.run(bench.keyless() + [OUTAGE]) == 1
    assert bench.paid() == [ANCHOR_RES]
    stop = next(line for line in bench.printed if line.startswith("STOPPED"))
    assert stop.startswith(
        f"STOPPED: {rerun} owes the re-run of {ANCHOR_RES}'s outage, but"
        f" {rerun}: {ra.NOTE} raises its cap to 0.06 USD, but it has no budget"
        " stop to resume"
    )
    assert bench.run([]) == 2
    assert not bench.calls
    (bench.root / ra.NOTE).write_text(_note(), encoding="utf-8")
    script = bench.keyless() + [COMPLETE] * 12
    assert bench.run(script) == 0
    assert bench.paid()[0] == rerun
    assert _flag(bench.paid_argv()[0], "--max-usd") == "0.050000"


@pytest.mark.parametrize(
    ("raised", "match"),
    [
        ([(ANCHOR_RES, "0.05")], "is not above the anchor dev cap 0.05 USD"),
        ([(ANCHOR_RES, "13.00")], "is not above the anchor dev cap"),
        (
            [(f"dev-qwen3-32b-xx-{_DATE}", "0.06")],
            f"the raised cap of dev-qwen3-32b-xx-{_DATE} names no dev arm run",
        ),
        ([("other-run", "0.06")], "the raised cap of other-run names no dev"),
    ],
)
def test_a_raise_the_note_cannot_hold_is_refused(
    bench: Bench, raised: list[tuple[str, str]], match: str
) -> None:
    note = _note(raised=raised)
    (bench.root / ra.NOTE).write_text(note, encoding="utf-8")
    with pytest.raises(tp.PlanError, match=re.escape(match)):
        bench.context()


def test_a_raise_of_the_other_split_is_left_to_that_split(
    bench: Bench,
) -> None:
    note = _note(raised=[(TEST_ARMS[0], "0.06")])
    (bench.root / ra.NOTE).write_text(note, encoding="utf-8")
    assert bench.context().plan.raised == {}
    assert bench.context("test").plan.raised == {TEST_ARMS[0]: 0.06}


def _keep(bench: Bench, run_id: str, into: str) -> None:
    """Commits a run's manifest as the maintainer's publish or evidence step."""
    run_dir = bench.root / ra.PREPARE_ROOT / run_id / "runs" / run_id
    target = bench.root / into / run_id
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / "run_manifest.json", target / "run_manifest.json")


def _lost_refusal(bench: Bench) -> str:
    refusal = next(line for line in bench.printed if line.startswith("REFUSED"))
    assert refusal.startswith(
        "REFUSED: the repository records these arm runs, but their run"
        " directories under artifacts/repair are gone, so the batch would"
        " send them again: "
    )
    assert refusal.endswith(
        ". Run the same command from the checkout that sent them, or the"
        " owner rules on each"
    )
    return refusal


def test_a_published_dev_run_whose_directory_is_gone_is_never_sent_again(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0
    for run_id in DEV_ARMS:
        _keep(bench, run_id, ra.RESULTS)
    # Another checkout, a clean or a fresh clone: the ignored copies are gone.
    shutil.rmtree(bench.root / ra.PREPARE_ROOT)
    bench.follow_ups.clear()
    assert bench.run([]) == 2
    assert not bench.calls and not bench.follow_ups
    refusal = _lost_refusal(bench)
    for run_id in DEV_ARMS:
        assert f"{run_id} (docs/results/{run_id}/run_manifest.json)" in refusal
    assert bench.run([], ["--dry-run"]) == 2
    assert not bench.calls and not bench.follow_ups


def test_a_published_test_run_whose_directory_is_gone_is_never_sent_again(
    bench: Bench,
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS:
        bench.seed(run_id)
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0
    # Each run is published beside its committed seed.
    for run_id in TEST_ARMS:
        _keep(bench, run_id, ra.RESULTS)
    shutil.rmtree(bench.root / ra.PREPARE_ROOT)
    assert bench.run([]) == 2
    assert not bench.calls
    refusal = _lost_refusal(bench)
    assert all(run_id in refusal for run_id in TEST_ARMS)
    assert not (bench.root / ra.PREPARE_ROOT).exists()


def test_kept_evidence_or_a_not_run_record_holds_a_run_back_too(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [GATED] + [COMPLETE] * 11) == 0
    _keep(bench, ANCHOR_RES, ra.EVIDENCE_DIR)
    shutil.rmtree(bench.root / ra.PREPARE_ROOT / ANCHOR_RES)
    assert bench.run([]) == 2
    assert not bench.calls
    lost = _lost_refusal(bench).split("send them again: ")[1]
    evidence = f"{ra.EVIDENCE_DIR}/{ANCHOR_RES}/run_manifest.json"
    assert lost.startswith(f"{ANCHOR_RES} ({evidence}).")
    shutil.rmtree(bench.root / ra.EVIDENCE_DIR)
    record = bench.root / ra.RESULTS / _DEV[0] / ra.NOT_RUN_PATH
    record.write_text(
        '{"arms":{"resample":"gate_stop"},'
        '"schema_version":"repair-not-run/1.0"}\n',
        encoding="utf-8",
    )
    assert bench.run([]) == 2
    assert f"{ANCHOR_RES} (docs/results/{_DEV[0]}/repair/not_run.json)" in (
        _lost_refusal(bench)
    )
    # A record the batch cannot read is never taken for no record.
    record.write_text("[", encoding="utf-8")
    assert bench.run([]) == 2
    assert not bench.calls
    # A record naming another arm leaves this one to its directory.
    record.write_text('{"arms":{"bare":"gate_stop"}}\n', encoding="utf-8")
    assert bench.run(bench.keyless() + [COMPLETE]) == 0
    assert bench.paid() == [ANCHOR_RES]


def test_a_call_step_error_stops_and_the_same_command_resumes(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless() + [refuse("io_error")]) == 1
    assert any(
        f"STOPPED: {ANCHOR_RES}: the call step ended with an error (io_error"
        in line
        for line in bench.printed
    )
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0


def test_a_paid_call_that_finds_no_key_aborts(bench: Bench) -> None:
    assert bench.run(bench.keyless() + [refuse("api_key_missing")]) == 3
    assert f"ABORTED: {ANCHOR_RES}: the call step found no key" in bench.printed


def test_an_unreadable_run_directory_stops_for_the_owner(bench: Bench) -> None:
    assert bench.run(bench.keyless(), key=False) == 3
    run_dir = bench.root / ra.PREPARE_ROOT / ANCHOR_RES / "runs" / ANCHOR_RES
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text("{", encoding="utf-8")
    preflight = bench.keyless()
    assert len(preflight) == 11
    assert bench.run(preflight) == 1
    assert (
        f"STOPPED: {ANCHOR_RES}: manifest_invalid; read its run directory and"
        f" {ra.OUT_DIR}/{ra.STEP_LOG} before running the same command again"
    ) in bench.printed
    assert not bench.paid()


def test_an_owed_re_run_left_pending_is_resumed_without_a_new_wait(
    bench: Bench,
) -> None:
    rerun = _r2(ANCHOR_RES)
    first = [OUTAGE, refuse("api_key_missing"), PENDING, refuse("io_error")]
    assert bench.run(bench.keyless() + first) == 1
    assert bench.paid() == [ANCHOR_RES, rerun, rerun]
    waits = len(bench.slept)
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0
    assert bench.paid()[0] == rerun
    assert bench.paid_argv()[0][-1] == "--resume"
    assert bench.slept[waits:] == []
    assert bench.rows()[ANCHOR_RES]["counted_run_id"] == rerun


def test_a_call_step_that_leaves_no_run_directory_stops(bench: Bench) -> None:
    def nothing(synth: Synth, argv: list[str]) -> Any:
        return db.Invocation(0, {"run_id": synth.run_id}, None)

    assert bench.run(bench.keyless() + [nothing]) == 1
    assert f"STOPPED: {ANCHOR_RES}: the call step left no run directory" in (
        bench.printed
    )


def test_absent_key_aborts_after_the_keyless_preflight(bench: Bench) -> None:
    assert bench.run(bench.keyless(), key=False) == 3
    assert not bench.paid() and len(bench.calls) == 12
    assert any(
        line.startswith("ABORTED: the keyless preflight passed and nothing")
        for line in bench.printed
    )
    # The prompt sets are built all the same, so the next run checks them.
    for run_id in DEV_ARMS:
        assert (
            bench.root / ra.PREPARE_ROOT / run_id / "prepare.json"
        ).is_file()


def test_preflight_must_stop_at_the_missing_key(bench: Bench) -> None:
    assert bench.run([refuse("prepare_code_mismatch")]) == 2
    assert not bench.paid()
    assert (
        f"REFUSED: preflight: {ANCHOR_RES} stopped at prepare_code_mismatch"
        " (exit 2)"
    ) in bench.printed


def test_uncommitted_tooling_is_refused_before_a_paid_call(
    bench: Bench,
) -> None:
    change = "?? scripts/repair_arms.py"
    assert bench.run(bench.keyless(), changes=[change]) == 2
    assert not bench.paid()
    assert any(change in line for line in bench.printed)
    ctx = bench.context()
    paths = ra.tooling(ctx)
    assert {
        "scripts/repair_arms.py",
        "scripts/test_passes.py",
        "scripts/dev_bakeoff.py",
        "scripts/model_run.py",
        "src/dfilterforge",
        db.CONFIG_DIR,
        tp.REGISTRY,
        ra.NOTE,
        "docs/protocol.md",
    } <= set(paths)
    assert {f"docs/results/{base}/repair/plan.json" for base in _DEV} <= set(
        paths
    )
    assert not any(path.endswith("/prepared") for path in paths)
    test = ra.tooling(bench.context("test"))
    assert f"docs/results/{TEST_ARMS[0]}/prepare.json" in test
    assert f"docs/results/{_r2(TEST_ARMS[0])}/prepared" in test


# The prompt sets.


def test_dry_run_writes_nothing_and_sends_nothing(bench: Bench) -> None:
    assert bench.run([], ["--dry-run"]) == 0
    assert not bench.calls
    assert not (bench.root / ra.OUT_DIR).exists()
    assert not (bench.root / ra.PREPARE_ROOT).exists()
    text = "\n".join(bench.printed)
    assert "# | arm run id | config | items | worst request" in text
    assert f"  artifacts/repair/{ANCHOR_RES}: would build" in text
    assert (
        f"python scripts/model_run.py follow-up --from-run"
        f" docs/results/{_DEV[0]} --plan"
        f" docs/results/{_DEV[0]}/repair/plan.json --arm resample"
        f" --output-dir artifacts/repair/{ANCHOR_RES} --source-revision"
        " test-rev"
    ) in text
    assert f"--run-id {ANCHOR_CX}" in text
    assert f"#1 anchor resample {ANCHOR_RES}: owed (start (not_started))" in (
        text
    )
    # Twelve builds into a temporary directory, none into the tree.
    assert len(bench.follow_ups) == 12


def test_dry_run_prints_the_resume_of_a_run_left_pending(bench: Bench) -> None:
    assert bench.run(bench.keyless() + [PENDING, refuse("io_error")]) == 1
    assert bench.run([], ["--dry-run"]) == 0
    text = "\n".join(bench.printed)
    assert f"--run-id {ANCHOR_RES}" in text and "--gate-first --resume" in text
    assert f"  artifacts/repair/{ANCHOR_RES}: equal to what follow-up" in text


def test_an_existing_prompt_set_must_be_what_follow_up_builds_now(
    bench: Bench,
) -> None:
    assert bench.run(bench.keyless(), key=False) == 3
    # A rebuild differs only in its creation time and source revision.
    assert bench.run(bench.keyless(), key=False) == 3
    prompts = (
        bench.root / ra.PREPARE_ROOT / ANCHOR_BARE / "prepared" / "C4.json"
    )
    prompts.write_bytes(
        prompts.read_bytes().replace(b"incorrect", b"wrong!!!!")
    )
    assert bench.run([]) == 2
    assert not bench.calls
    refusal = next(line for line in bench.printed if line.startswith("REFUSED"))
    assert refusal.startswith(
        f"REFUSED: artifacts/repair/{ANCHOR_BARE}: prepared/C4.json differ"
        " from what follow-up builds now"
    )
    shutil.rmtree(bench.root / ra.PREPARE_ROOT / ANCHOR_BARE)
    (bench.root / ra.PREPARE_ROOT / ANCHOR_BARE).mkdir()
    assert bench.run([]) == 2
    assert (
        f"REFUSED: artifacts/repair/{ANCHOR_BARE} exists but holds no"
        " prepare.json"
    ) in bench.printed


def test_prompt_sets_may_differ_only_in_time_and_revision(
    tmp_path: Path,
) -> None:
    def manifest(directory: Path, stamp: datetime, revision: str) -> Path:
        _write_prompts(directory, "dev", ["mei-0001"], "bare", stamp, revision)
        return directory

    built = manifest(tmp_path / "a" / "x", _T0, "one")
    other = manifest(tmp_path / "b" / "x", _T0 + timedelta(days=1), "two")
    assert ra.differences(built, other) == []
    renamed = manifest(tmp_path / "c" / "y", _T0, "one")
    assert ra.differences(built, renamed) == ["prepare.json"]
    (other / "prepared" / "C4.json").unlink()
    assert ra.differences(built, other) == ["prepared/C4.json"]
    (other / "prepare.json").write_text("{}", encoding="utf-8")
    assert ra.differences(built, other) == ["prepare.json"]


def test_a_round_whose_second_turn_cannot_be_built_is_not_run(
    bench: Bench,
) -> None:
    bench.refusals[_DEV[1]] = "prompt_too_large"
    preflight = bench.keyless()
    assert len(preflight) == 9
    assert bench.run(preflight + [COMPLETE] * 9) == 0
    assert bench.paid() == DEV_ARMS[:3] + DEV_ARMS[6:]
    rows = bench.rows()
    for run_id in DEV_ARMS[3:6]:
        assert rows[run_id]["state"] == "not_run"
        assert rows[run_id]["reason"] == (
            f"the round is not run: a second turn of {_DEV[1]} cannot be"
            " built (prompt_too_large), so no arm of it is sent"
        )
        assert rows[run_id]["maintainer"] == {}
    rounds = {line["base_run"]: line for line in bench.summary()["rounds"]}
    assert rounds[_DEV[1]]["next"].startswith("no arm run to publish (the")
    assert not (bench.root / ra.PREPARE_ROOT / DEV_ARMS[3]).exists()


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("follow_up_invalid", "the round is not run: a second turn of"),
        ("run_id_invalid", f"{DEV_ARMS[7]} is not a usable result name"),
    ],
)
def test_other_follow_up_refusals_the_protocol_reports_are_not_run(
    bench: Bench, code: str, reason: str
) -> None:
    bench.refusals[(_DEV[2], "bare")] = code
    assert bench.run(bench.keyless() + [COMPLETE] * 11) == 0
    row = bench.rows()[DEV_ARMS[7]]
    assert row["state"] == "not_run"
    assert row["reason"].startswith(reason)
    assert DEV_ARMS[7] not in bench.paid()


def test_a_plan_that_triggers_no_item_leaves_its_rows_unused(
    bench: Bench,
) -> None:
    bench.refusals[_DEV[3]] = "plan_empty"
    assert bench.run(bench.keyless() + [COMPLETE] * 9) == 0
    rows = bench.rows()
    assert [rows[run]["state"] for run in DEV_ARMS[9:]] == ["unused"] * 3
    assert bench.summary()["final"] is True


def test_any_other_follow_up_refusal_is_refused_before_a_request(
    bench: Bench,
) -> None:
    bench.refusals[(_DEV[2], "counterexample")] = "plan_mismatch"
    assert bench.run([]) == 2
    assert not bench.calls
    refusal = next(line for line in bench.printed if line.startswith("REFUSED"))
    assert refusal.startswith(
        f"REFUSED: {DEV_ARMS[8]}: follow-up refused (plan_mismatch): run"
        " python scripts/model_run.py follow-up --from-run"
    )


def test_a_cap_below_one_worst_request_is_refused(bench: Bench) -> None:
    rows = [(s, c, "0.00" if s == "8B" else d, t) for s, c, d, t in _CAPS_ROWS]
    (bench.root / ra.NOTE).write_text(_note(rows), encoding="utf-8")
    with pytest.raises(tp.PlanError, match="no usable dev cap"):
        bench.context()
    (bench.root / ra.NOTE).write_text(_note(), encoding="utf-8")
    priced = ra.endpoint

    def dear(row: Any, sizes: tuple[int, ...], ctx: Any) -> Any:
        found = priced(row, sizes, ctx)
        if row.slot != "8B":
            return found
        return dataclasses.replace(found, worst_micro_usd=50_001)

    bench.monkeypatch.setattr(ra, "endpoint", dear)
    assert bench.run([]) == 2
    assert not bench.calls
    assert (
        f"REFUSED: {DEV_ARMS[3]}: one request may cost 0.050001 USD, over"
        " its 8B dev cap 0.05; the protocol registers that cap, so the owner"
        " rules on it before any request"
    ) in bench.printed


# The test split.


def test_the_test_round_waits_for_its_seed_and_admission_commits(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.split = "test"
    assert bench.run([], ["--dry-run"]) == 2
    error = capsys.readouterr().err
    assert error.startswith(
        "refused: the test round needs its seed and admission commits first:"
        f" no committed seed in docs/results/{TEST_ARMS[0]}, "
    )
    for run_id in TEST_ARMS:
        assert f"docs/results/{run_id}" in error
    assert "held_out_freeze.json in a commit of its own" in error
    assert bench.run([]) == 2
    assert not bench.calls
    assert not (bench.root / ra.PREPARE_ROOT).exists()
    # No test repair prompt was prepared, not even in a temporary directory.
    assert not bench.follow_ups


def test_a_test_seed_is_checked_for_admission_before_it_is_built(
    bench: Bench, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS:
        bench.seed(run_id, admit=run_id != TEST_ARMS[0])
    bench.follow_ups.clear()
    assert bench.run([], ["--dry-run"]) == 2
    assert capsys.readouterr().err.startswith(
        f"refused: docs/results/{TEST_ARMS[0]}/prepare.json (sha256"
    )
    assert not bench.follow_ups


def test_once_seeding_begins_a_round_follow_up_cannot_build_is_not_run(
    bench: Bench,
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS[:3] + TEST_ARMS[6:]:
        bench.seed(run_id)
    # The 8B pass's second turns cannot be built, so it can get no seed.
    bench.refusals[_TEST_PASSES[1]] = "prompt_too_large"
    preflight = bench.keyless()
    assert len(preflight) == 9
    assert bench.run(preflight + [COMPLETE] * 9) == 0
    assert bench.paid() == TEST_ARMS[:3] + TEST_ARMS[6:]
    rows = bench.rows()
    for run_id in TEST_ARMS[3:6]:
        assert rows[run_id]["state"] == "not_run"
        assert rows[run_id]["reason"].startswith("the round is not run")


def test_a_test_arm_answers_its_admitted_seed_byte_for_byte(
    bench: Bench,
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS:
        bench.seed(run_id)
    preflight = bench.keyless()
    assert len(preflight) == 12
    assert bench.run(preflight + [COMPLETE] * 12) == 0
    assert bench.paid() == TEST_ARMS
    caps = [float(_flag(argv, "--max-usd")) for argv in bench.paid_argv()]
    assert caps == [cap for cap in _TEST_CAPS for _ in range(3)]
    for run_id in TEST_ARMS:
        for name in ("prepare.json", "prepared/C4.json"):
            copy = bench.root / ra.PREPARE_ROOT / run_id / name
            seed = bench.root / ra.RESULTS / run_id / name
            assert copy.read_bytes() == seed.read_bytes()
    assert _PASS_B not in {row["base_run"] for row in bench.summary()["rows"]}


def test_a_test_seed_must_be_admitted_and_what_follow_up_builds(
    bench: Bench,
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS:
        bench.seed(run_id, admit=run_id != TEST_ARMS[4])
    assert bench.run([]) == 2
    refusal = next(line for line in bench.printed if line.startswith("REFUSED"))
    assert refusal.startswith(
        f"REFUSED: docs/results/{TEST_ARMS[4]}/prepare.json (sha256"
    )
    assert "is not admitted; append its digest" in refusal
    seed = bench.root / ra.RESULTS / TEST_ARMS[4]
    shutil.rmtree(seed)
    bench.seed(TEST_ARMS[4])
    prompts = seed / "prepared" / "C4.json"
    prompts.write_bytes(prompts.read_bytes().replace(b"SSSS", b"STSS", 1))
    assert bench.run([]) == 2
    assert (
        f"REFUSED: docs/results/{TEST_ARMS[4]}: prepared/C4.json differ from"
        f" what follow-up builds now from docs/results/{_TEST_PASSES[1]} and"
        " its plan"
    ) in bench.printed


def test_a_test_copy_that_differs_from_its_seed_is_refused(
    bench: Bench,
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS:
        bench.seed(run_id)
    assert bench.run(bench.keyless(), key=False) == 3
    copy = bench.root / ra.PREPARE_ROOT / TEST_ARMS[0] / "prepare.json"
    copy.write_bytes(copy.read_bytes() + b"\n")
    assert bench.run([]) == 2
    refusal = next(line for line in bench.printed if line.startswith("REFUSED"))
    assert f"artifacts/repair/{TEST_ARMS[0]}/prepare.json (sha256" in refusal
    assert "in Git Bash: mkdir -p" in refusal


def test_a_test_outage_re_run_without_a_seed_stops_for_the_owner(
    bench: Bench,
) -> None:
    bench.split = "test"
    for run_id in TEST_ARMS:
        bench.seed(run_id)
    assert bench.run(bench.keyless() + [OUTAGE]) == 1
    stop = next(line for line in bench.printed if line.startswith("STOPPED"))
    rerun = _r2(TEST_ARMS[0])
    assert stop == (
        f"STOPPED: {rerun} owes the re-run of {TEST_ARMS[0]}'s outage, but"
        f" no committed seed in docs/results/{rerun}; seed and admit it,"
        " then run the same command again"
    )
    # Before any request, an owed re-run without its seed is a refusal.
    assert bench.run([]) == 2
    bench.seed(rerun)
    assert bench.run(bench.keyless() + [COMPLETE] * 12) == 0
    assert bench.paid()[0] == rerun


def test_the_test_round_repairs_the_published_rows_one_per_slot(
    bench: Bench,
) -> None:
    ctx = bench.context("test")
    bases = list(dict.fromkeys(row.base_run for row in ctx.plan.rows))
    assert bases == _TEST_PASSES
    assert [row.slot for row in ctx.plan.rows][::3] == list(ra.SLOT_ORDER)

    def edit(change: Callable[[Fields], None]) -> None:
        registry = _registry()
        change(registry)
        _write_json(bench.root / tp.REGISTRY, registry)

    def runs(registry: Fields) -> dict[str, Fields]:
        return {row["run_id"]: row for row in registry["runs"]}

    def fallback_published(registry: Fields) -> None:
        rows = runs(registry)
        rows[_TEST_PASSES[3]].update(status="not_run", reason="gate stop")
        fallback = _TEST_PASSES[3].replace(f"-{_DATE}", f"-fb-{_DATE}")
        rows[fallback].update(status="published", commit="abc1234")

    edit(fallback_published)
    fallback = _TEST_PASSES[3].replace(f"-{_DATE}", f"-fb-{_DATE}")
    _write_base(bench.root, fallback, _FALLBACK_CONFIGS["frontier"])
    rows = bench.context("test").plan.rows
    assert [row.base_run for row in rows[9:]] == [fallback] * 3
    assert {row.slot for row in rows[9:]} == {"frontier fallback"}
    assert {row.cap_usd for row in rows[9:]} == {0.50}
    assert rows[9].run_id == f"test-deepseek-v4-pro-0813-fb-res-{_DATE}"

    def both(registry: Fields) -> None:
        fallback_published(registry)
        runs(registry)[_TEST_PASSES[3]].update(status="published", reason=None)

    edit(both)
    with pytest.raises(tp.PlanError, match="both repair the frontier slot"):
        bench.context("test")

    def open_row(registry: Fields) -> None:
        runs(registry)[_TEST_PASSES[2]].update(status="registered")

    edit(open_row)
    with pytest.raises(tp.PlanError, match="may still send"):
        bench.context("test")

    def none_published(registry: Fields) -> None:
        for run_id in _TEST_PASSES:
            runs(registry)[run_id].update(status="not_run", reason="ruled")

    edit(none_published)
    with pytest.raises(tp.PlanError, match="no test pass is repaired"):
        bench.context("test")

    def no_roles(registry: Fields) -> None:
        registry["repair_arms"] = {"repaired_roles": ["aa_pass_b", "x"]}

    edit(no_roles)
    with pytest.raises(tp.PlanError, match="names no usable roles"):
        bench.context("test")


# What the batch refuses before any request.


def test_a_pass_without_its_plan_or_config_is_refused(bench: Bench) -> None:
    plan = bench.root / ra.RESULTS / _DEV[2] / ra.PLAN_PATH
    plan.unlink()
    with pytest.raises(tp.PlanError, match="no committed repair/plan.json"):
        bench.context()
    plan.write_text("{}\n", encoding="utf-8")
    config = bench.root / db.CONFIG_DIR / f"{_DEV_CONFIGS[_DEV[2]]}.json"
    document = json.loads(config.read_text(encoding="utf-8"))
    document["settings"]["seed"] = 18
    _write_json(config, document)
    with pytest.raises(tp.PlanError, match="not the config dev-qwen3.5-122b"):
        bench.context()


def test_a_pass_sent_otherwise_or_incomplete_is_refused(bench: Bench) -> None:
    path = bench.root / ra.RESULTS / _DEV[0] / "run_manifest.json"
    original = path.read_text(encoding="utf-8")
    document = json.loads(original)
    document["min_interval_seconds"] = 2.0
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(tp.PlanError, match="registered call options"):
        bench.context()
    document = json.loads(original)
    document["run_id"] = "dev-other-2026-09-26"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(tp.PlanError, match="not a complete published pass"):
        bench.context()


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("# no table\n", "no single caps table"),
        (_note() + _note(), "no single caps table"),
        (_note().replace("| 0.20 |", "| 0.2 |"), "is not a USD amount"),
        (_note().replace("| 8B |", "| anchor |"), "unusable caps row"),
        (
            _note().replace(
                "`qwen3-32b_deepinfra_enabled-false`", "`qwen3-32b_x`"
            ),
            "lists no anchor cap for qwen3-32b_deepinfra",
        ),
        (_note().replace("| 8B |", "| 9B |"), "lists no 8B cap"),
        (
            _note().replace("| Arm run | Raised cap |", "| Arm run |"),
            "no single raised caps table",
        ),
        (
            _note(raised=[(ANCHOR_RES, "0.06"), (ANCHOR_RES, "0.07")]),
            "unusable raised caps row",
        ),
        (_note(raised=[(ANCHOR_RES, "0.1")]), "unusable raised caps row"),
        (
            _note(raised=[(ANCHOR_RES, "0.06")]).replace(
                f"`{ANCHOR_RES}`", ANCHOR_RES
            ),
            "unusable raised caps row",
        ),
    ],
)
def test_a_caps_table_the_batch_cannot_read_is_refused(
    bench: Bench, text: str, match: str
) -> None:
    (bench.root / ra.NOTE).write_text(text, encoding="utf-8")
    with pytest.raises(tp.PlanError, match=match):
        bench.context()


def test_the_caps_table_gives_each_slot_its_config_and_caps() -> None:
    caps = ra.load_caps(_note())
    assert caps["frontier"] == ra.Cap(
        "deepseek-v4-pro-0813_deepinfra_enabled-false", 0.20, 0.50
    )
    assert caps["8B fallback"] == ra.Cap(_FALLBACK_CONFIGS["small"], None, 0.05)
    assert list(caps) == [slot for slot, *_ in _CAPS_ROWS]
    assert ra.load_raised(_note()) == {}
    raised = [(ANCHOR_RES, "0.06"), (TEST_ARMS[11], "0.75")]
    assert ra.load_raised(_note(raised=raised)) == {
        ANCHOR_RES: 0.06,
        TEST_ARMS[11]: 0.75,
    }


def test_the_dev_passes_are_the_bake_off_anchor_and_slot_winners() -> None:
    passes = ra.dev_passes()
    assert [p.run_id for p in passes] == _DEV
    assert [p.slot for p in passes] == list(ra.SLOT_ORDER)
    assert [Path(p.config).stem for p in passes] == list(_DEV_CONFIGS.values())


def test_an_unplanned_dev_pass_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ra, "DEV_PASSES", ("dev-unknown-2026-09-26",))
    with pytest.raises(tp.PlanError, match="not one bake-off pass of a slot"):
        ra.dev_passes()
    reserve = "dev-kimi-k2-0905-2026-09-26"
    monkeypatch.setattr(ra, "DEV_PASSES", (reserve,))
    with pytest.raises(tp.PlanError, match="not one bake-off pass of a slot"):
        ra.dev_passes()
    fallback = "dev-qwen3.5-9b-fb-2026-09-26"
    monkeypatch.setattr(ra, "DEV_PASSES", (fallback,))
    assert ra.dev_passes()[0].slot == "8B fallback"


def test_the_arms_are_the_call_steps_and_the_rounds() -> None:
    assert ra.ARMS == repair_summary.ARMS
    assert ra.ARM_TAGS == dict(repair_round.ARM_TAGS)
    assert ra.ARM_TAGS == dict(getattr(model_run, "_ARM_TAGS"))
    assert ra.RERUN_TAG == repair_round.ARM_RERUN
    for arm in ra.ARMS:
        assert ra.arm_run_ids(_DEV[0], arm) == repair_round.arm_run_ids(
            _DEV[0], arm
        )


# Interrupts and errors after a paid call may have been sent.


def test_an_interrupt_releases_the_lock_unless_a_child_runs(
    bench: Bench,
) -> None:
    lock = bench.root / ra.OUT_DIR / ra.LOCK_NAME
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
    assert bench.run(script) == ra.EXIT_STOPPED == 1
    assert any(
        line.startswith("STOPPED: unexpected RuntimeError: boom; requests")
        for line in bench.printed
    )
    assert not (bench.root / ra.OUT_DIR / ra.LOCK_NAME).exists()


def test_the_real_invoker_withholds_the_key_from_a_keyless_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a paid call's child sees the key; a preflight child never does.

    Every other test replaces the invoker, so this runs the one the batch
    builds, against a child that reports whether the key reached it.
    """
    monkeypatch.setenv(API_KEY_ENV, "not-a-credential")
    child = "\n".join(
        [
            "import json, os, sys",
            f"seen = {API_KEY_ENV!r} in os.environ",
            "code = 'key_present' if seen else 'api_key_missing'",
            "print(json.dumps({'error': {'code': code}}), file=sys.stderr)",
            "sys.exit(9 if seen else 2)",
        ]
    )
    argv = [
        sys.executable,
        "-c",
        child,
        "--prepare-dir",
        f"{ra.PREPARE_ROOT}/{ANCHOR_RES}",
        "--run-id",
        ANCHOR_RES,
    ]
    printed: list[str] = []
    invoke = ra.subprocess_invoke(tmp_path, printed.append, 5.0)

    withheld = invoke(argv, False)
    sent = invoke(argv, True)

    assert (withheld.exit_code, withheld.error_code) == (2, "api_key_missing")
    assert (sent.exit_code, sent.error_code) == (9, "key_present")
    assert "not-a-credential" not in "\n".join(printed)


def test_the_real_follow_up_reports_a_refusal_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "dev-none-2026-09-26"
    report, code = ra.run_follow_up(
        ra.follow_up_argv(
            missing.as_posix(),
            "bare",
            (tmp_path / "out" / "dev-none-bare-2026-09-26").as_posix(),
            "test",
        )
    )
    assert (report, code) == (None, "plan_invalid")
    assert capsys.readouterr() == ("", "")


# The committed passes, plans and note.


def _committed_layout() -> Any:
    return ra.default_layout()


@pytest.mark.skipif(not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS)
def test_the_committed_passes_give_the_notes_arm_run_ids_and_caps() -> None:
    """Each row takes the protocol's cap, and a raise only goes above it.

    The note's caps table holds the registered caps, which a raise never
    edits, so a budget stop resumed under a raised cap leaves this test
    as it was.
    """
    note = (_ROOT / ra.NOTE).read_text(encoding="utf-8")
    protocol = (_ROOT / "docs" / "protocol.md").read_text(encoding="utf-8")
    listed = re.findall(
        r"^\| `((?:dev|test)-[^`]+)` \| `([^`]+)` \| `([^`]+)` \| `([^`]+)` \|$",
        note,
        re.MULTILINE,
    )
    # The protocol names the caps frontier first; the rows go anchor first.
    assert (
        "Each sends `--max-usd` 0.20, 0.10, 0.05 and 0.05 on dev and 0.50,"
        " 0.30, 0.05 and 0.05 on test for the frontier, about 120B-class,"
        " 8B-class and qwen/qwen3-32b passes"
    ) in " ".join(protocol.split())
    assert (_DEV_CAPS[::-1], _TEST_CAPS[::-1]) == (
        [0.20, 0.10, 0.05, 0.05],
        [0.50, 0.30, 0.05, 0.05],
    )
    for split, caps in (("dev", _DEV_CAPS), ("test", _TEST_CAPS)):
        ctx = ra.build_context(split, _committed_layout(), "test")
        rows = ctx.plan.rows
        table = [row for row in listed if row[0].startswith(f"{split}-")]
        bases = dict.fromkeys(row.base_run for row in rows)
        assert [
            (base, *(row.run_id for row in rows if row.base_run == base))
            for base in bases
        ] == table
        assert [row.cap_usd for row in rows] == [
            c for c in caps for _ in range(3)
        ]
        for row in rows:
            for run_id in (row.run_id, row.rerun_id):
                assert row.cap_usd <= ctx.cap_usd(row, run_id) <= db.MAX_USD
        assert _PASS_B not in {row.base_run for row in rows}


@pytest.mark.skipif(not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS)
def test_the_real_follow_up_builds_every_committed_dev_arm() -> None:
    """The real follow-up step builds each committed plan's three arms.

    Nothing is written outside a temporary directory, and every arm holds
    its plan's items. Each arm is built as the batch builds it, without
    reading the ignored run directories CI never has, so a committed
    raised cap or a published arm run leaves this test as it was.
    """
    ctx = ra.build_context("dev", _committed_layout(), "test")
    printed: list[str] = []
    ctx.out = printed.append
    for row in ctx.plan.rows:
        ra.check_prompts(row, row.run_id, ctx, False)
    planned = {
        base: len(
            json.loads(
                (_ROOT / ra.RESULTS / base / ra.PLAN_PATH).read_text(
                    encoding="utf-8"
                )
            )["items"]
        )
        for base in _DEV
    }
    assert planned == {
        _DEV[0]: 10,
        _DEV[1]: 7,
        _DEV[2]: 8,
        _DEV[3]: 11,
    }
    assert not ctx.prompts.blocked
    for row in ctx.plan.rows:
        assert ctx.prompts.notes[row.run_id] == "would build"
        assert len(ctx.prompts.sizes[row.run_id]) == planned[row.base_run]
        assert not ctx.prepare_dir(row.run_id).exists()


@pytest.mark.skipif(not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS)
def test_the_note_gives_the_owner_command_for_each_split_in_both_shells() -> (
    None
):
    note = (_ROOT / ra.NOTE).read_text(encoding="utf-8")
    assert "## Commands to come" not in note
    for text in (
        "uv run --frozen python scripts/repair_arms.py --split dev --dry-run",
        "uv run --frozen python scripts/repair_arms.py --split test --dry-run",
        "Read-Host -AsSecureString",
        '$env:PYTHONIOENCODING = "utf-8"',
        "exit code: $LASTEXITCODE",
        "Remove-Item Env:DFILTERFORGE_MODEL_API_KEY",
        "unset DFILTERFORGE_MODEL_API_KEY",
        ra.EVIDENCE_DIR,
        "scripts/model_run.py publish",
        "lab score --run-dir",
        "lab repair --run-dir",
        "--check",
    ):
        assert text in note, text
    for code in (0, 1, 2, 3, 130):
        assert re.search(rf"^\| {code} \|", note, re.MULTILINE)
    blocks = re.findall(r"^```(bash|powershell)\n(.*?)^```", note, re.M | re.S)
    owner = [
        (shell, block)
        for shell, block in blocks
        if "scripts/repair_arms.py" in block
    ]
    assert sorted(shell for shell, _ in owner) == [
        "bash",
        "bash",
        "powershell",
        "powershell",
    ]
    for _, block in owner:
        assert block.splitlines()[1:3] == [
            "git switch main",
            "git pull --ff-only",
        ]


# The owner's ruling of 2026-10-04 (OD5) that moves the frontier slot's
# arm runs from DeepInfra to NextBit, and the run ids the move takes.
_MOVE_RULING = "docs/decisions/evidence/repair-arms/ruling-2026-10-04.json"
_CONFIG_DIR = "docs/decisions/evidence/bakeoff/configs"
# Every tag a run id already carries: arms, re-run, fallback and pass B.
_TAKEN_TAGS = frozenset({"res", "bare", "cx", "fb", "r2", "passb"})
_SMOKE_TAG = re.compile(r"rs[0-9]*")
_NOTE_MOVE_ROW = re.compile(
    r"^\| (resample|bare|counterexample) \| `(dev-[^`]+)` \| `([^`]+)` \|$",
    re.MULTILINE,
)


def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


@pytest.mark.skipif(not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS)
def test_the_frontier_move_ruling_matches_its_evidence() -> None:
    """The move to NextBit holds to its config, its evidence and its ids.

    Its figures are recounted from the committed evidence of the six
    DeepInfra runs it replaces, so a ruling that misstates them fails.
    Each moved id is the registered one with the move's tag after the arm
    tag. A replaced run never reaches docs/results, which guards the
    resample arm that no second-turn check covers.
    """
    ruling = json.loads(_read(_MOVE_RULING))
    old_bytes = (_ROOT / ruling["from_config"]).read_bytes()
    new_bytes = (_ROOT / ruling["to_config"]).read_bytes()
    old, new = json.loads(old_bytes), json.loads(new_bytes)
    frontier = _DEV[3]
    assert ruling["schema"] == "repair-arms-ruling/1.0"
    assert ruling["note"] == ra.NOTE
    assert ruling["registered_in"] == "docs/protocol.md"
    assert ruling["from_config"] == (
        f"{_CONFIG_DIR}/{_DEV_CONFIGS[frontier]}.json"
    )
    assert ruling["to_config"] == (
        f"{_CONFIG_DIR}/{_FALLBACK_CONFIGS['frontier']}.json"
    )
    assert ruling["to_config_sha256"] == _sha256(new_bytes)
    assert ruling["model_id"] == new["settings"]["model_id"]
    assert old["settings"]["openrouter"]["provider_order"] == ["deepinfra"]
    assert new["settings"]["openrouter"]["provider_order"] == ["nextbit"]
    assert old["prices"] != new["prices"]
    for config in (old, new):
        del config["settings"]["openrouter"]["provider_order"]
        del config["prices"]
    assert old == new
    caps = ra.load_caps(_read(ra.NOTE))
    assert ruling["caps_usd"] == {
        "dev": caps["frontier"].dev,
        "test": caps["frontier fallback"].test,
    }
    assert ruling["caps_usd"] == {"dev": _DEV_CAPS[3], "test": _TEST_CAPS[3]}

    decided = {item["id"]: item["by"] for item in ruling["decisions"]}
    assert list(decided) == ["OD5", "OD6", "OD7", "OD8"]
    assert decided["OD5"] == "owner"
    assert {decided[od] for od in ("OD6", "OD7", "OD8")} <= {
        "owner",
        "default_taken",
    }
    assert all(item["text"] for item in ruling["decisions"])
    dev_move, test_move = ruling["moves"]
    for move in ruling["moves"]:
        assert move["decided_by"] and set(move["decided_by"]) <= set(decided)

    # The evidence, recounted from the committed DeepInfra arm runs.
    registered = [
        run for first in _arms(frontier) for run in (first, _r2(first))
    ]
    kept = [
        run for run in registered if (_ROOT / ra.EVIDENCE_DIR / run).is_dir()
    ]
    attempts: list[Any] = []
    bound = 0.0
    revisions: set[str] = set()
    for run_id in kept:
        run = _ROOT / ra.EVIDENCE_DIR / run_id
        manifest = json.loads(
            (run / "run_manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["run_id"] == run_id
        assert manifest["charged_usd_upper_bound"] == 0.0
        assert manifest["settings"]["openrouter"]["provider_order"] == [
            "deepinfra"
        ]
        bound += manifest["charged_usd_upper_bound"]
        revisions |= {
            item["source_revision"] for item in manifest["invocations"]
        }
        for condition in manifest["conditions"]:
            lines = (run / condition["attempts_path"]).read_text(
                encoding="utf-8"
            )
            attempts += [json.loads(line) for line in lines.splitlines()]
    completions = [attempt["completion"] for attempt in attempts]
    sent = sorted(attempt["sent_at"] for attempt in attempts)
    (revision,) = revisions
    assert (len(kept), len(attempts)) == (6, 198)
    assert {completion["http_status"] for completion in completions} == {429}
    assert {completion["status"] for completion in completions} == {"failed"}
    assert sum(attempt["charged_micro_usd"] for attempt in attempts) == 0
    evidence = ruling["evidence"]
    assert evidence == {
        "runs": kept,
        "attempts": len(attempts),
        "http_429": sum(c["http_status"] == 429 for c in completions),
        "answers": sum(c["status"] == "completed" for c in completions),
        "charged_usd_upper_bound": bound,
        "first_attempt_at": sent[0],
        "last_attempt_at": sent[-1],
        "source_revision": revision,
        "diagnostics": (
            f"{ra.EVIDENCE_DIR}/frontier-provider-diagnostics-2026-10-04.md"
        ),
        "runner_summary": f"{ra.EVIDENCE_DIR}/summary-dev-2026-10-04.json",
        "test_baseline_http_429": 754,
    }
    assert (_ROOT / evidence["diagnostics"]).is_file()
    assert (_ROOT / evidence["runner_summary"]).is_file()
    assert kept == dev_move["replaced_runs"]
    assert test_move["replaced_runs"] == []

    # The moved ids: the registered ones, the tag after the arm tag.
    assert (dev_move["base_run"], dev_move["tag"]) == (frontier, "nb")
    assert (test_move["base_run"], test_move["tag"]) == (_TEST_PASSES[3], None)
    tag = dev_move["tag"]
    assert tag not in _TAKEN_TAGS and _SMOKE_TAG.fullmatch(tag) is None
    result_dir: re.Pattern[str] = getattr(model_run, "_RESULT_DIR")
    moved: list[str] = []
    for move in ruling["moves"]:
        assert sorted(move["arm_runs"]) == sorted(ra.ARMS)
        for arm, first in zip(ra.ARMS, _arms(move["base_run"])):
            arm_tag = f"-{ra.ARM_TAGS[arm]}-"
            runs = [first, _r2(first)]
            assert all(run.count(arm_tag) == 1 for run in runs)
            if move["tag"] is not None:
                runs = [
                    run.replace(arm_tag, f"{arm_tag}{move['tag']}-")
                    for run in runs
                ]
            assert move["arm_runs"][arm] == runs
            moved += runs
    assert len(moved) == len(set(moved)) == 12
    assert all(result_dir.fullmatch(run) is not None for run in moved)
    registry = json.loads(_read(tp.REGISTRY))
    named = [row["run_id"] for row in registry["runs"]] + list(ra.DEV_PASSES)
    assert not [name for name in named if f"-{tag}-" in name]
    assert not [
        run
        for run in dev_move["replaced_runs"]
        if (_ROOT / ra.RESULTS / run).exists()
    ]
    assert _NOTE_MOVE_ROW.findall(_read(ra.NOTE)) == [
        (arm, *dev_move["arm_runs"][arm]) for arm in ra.ARMS
    ]

    # The amended texts that register the move.
    protocol = " ".join(_read("docs/protocol.md").split())
    assert "Amended 2026-10-04" in protocol
    assert (
        "before any test repair prompt is prepared (owner ruling OD5"
        in protocol
    )
    bakeoff = _read("docs/decisions/model-bakeoff.md")
    _, section = bakeoff.split("## Repair arms' provider: 2026-10-04", 1)
    assert f"`{_FALLBACK_CONFIGS['frontier']}`" in section
    assert registry["repair_arms"]["amended"][0]["ruling"] == _MOVE_RULING
    locked = " ".join(_read(f"{ra.RESULTS}/locked-test-v1.md").split())
    assert "754 HTTP 429" in locked
