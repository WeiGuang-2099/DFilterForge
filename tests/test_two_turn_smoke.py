"""The two-turn smoke builds, runs and judges by the bake-off note's rule.

Source runs, configurations and smoke runs are written from the real
contracts (``RunManifestV1``, ``AttemptV1``, ``CompletionV1``) and the
call step is replaced by a scripted fake, so nothing is sent anywhere.
The prompts are built by the real ``scripts/model_run.py follow-up``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import hashlib
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import threading
from types import ModuleType
from typing import Any

import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import OpenRouterOptionsV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import TokenPricesV1
from dfilterforge.generation import FOLLOW_UP_TEXT
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.model_client import API_KEY_ENV

_ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "two_turn_smoke", _ROOT / "scripts" / "two_turn_smoke.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("two_turn_smoke cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load()
db = smoke.db
Fields = dict[str, Any]
Answers = list[tuple[str, Fields]]
_ITEMS = ("mei-0001", "mei-0002", "mei-0003", "mei-0004", "mei-0501")
_DATE = "2026-09-26"
_READY = json.dumps(
    {
        "schema_version": "1.0",
        "status": "ready",
        "assumptions": [],
        "clarifying_question": None,
        "intent_ir": {
            "ir_schema_version": "1.0",
            "scope": "packet",
            "expression": {
                "kind": "predicate",
                "field": "tcp.dstport",
                "operator": "eq",
                "value": 443,
            },
        },
    }
)
_ABSTAINED = json.dumps(
    {
        "schema_version": "1.0",
        "status": "not_expressible",
        "assumptions": [],
        "clarifying_question": None,
        "intent_ir": None,
    }
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def ok(**extra: Any) -> Fields:
    """A completed reply that stops, parses and reports no reasoning."""
    return {
        "status": "completed",
        "response_text": _READY,
        "latency_ms": 1.0,
        "http_status": 200,
        "provider": "DeepInfra",
        "finish_reason": "stop",
        "reasoning_tokens": 0,
        "reasoning_present": False,
        "prompt_tokens": 1500,
        "completion_tokens": 60,
    } | extra


def http(status: int) -> Fields:
    """A non-2xx reply as the client records it."""
    return {
        "status": "failed",
        "error_code": "http_error",
        "latency_ms": 1.0,
        "http_status": status,
    }


REASONED = ok(reasoning_tokens=40, reasoning_present=True)
PROVIDER_ERROR: Fields = {
    "status": "failed",
    "error_code": "provider_error",
    "latency_ms": 1.0,
    "http_status": 200,
}


def _settings(model: str, reasoning: str | None) -> RequestSettingsV1:
    return RequestSettingsV1(
        model_id=model,
        openrouter=OpenRouterOptionsV1(
            reasoning=reasoning,  # type: ignore[arg-type]
            provider_order=("deepinfra",),
        ),
    )


_PRICES = TokenPricesV1(
    usd_per_million_input=0.08,
    usd_per_million_output=0.28,
    source="fixture prices",
)
# name: (model, reasoning switch, first-pass answers by item)
_SOURCES: dict[str, tuple[str, str | None, dict[str, str | None]]] = {
    "qwen3-32b": ("qwen/qwen3-32b", "enabled_false", {}),
    "alpha": ("vendor/alpha", None, {"mei-0001": "length"}),
    "beta": (
        "vendor/beta",
        "enabled_false",
        {
            "mei-0001": "length",
            "mei-0002": "abstained",
            "mei-0003": "unparseable",
            "mei-0004": "length",
        },
    ),
    "gamma": ("vendor/gamma", "enabled_false", {}),
}


def _answer(kind: str | None) -> Fields:
    if kind == "length":
        return ok(finish_reason="length")
    if kind == "abstained":
        return ok(response_text=_ABSTAINED)
    if kind == "unparseable":
        return ok(response_text='{"schema_version":"1.0"')
    return ok()


def _config(name: str) -> dict[str, Any]:
    model, reasoning, _ = _SOURCES[name]
    return {
        "endpoint_url": "https://openrouter.ai/api/v1/chat/completions",
        "settings": _settings(model, reasoning).model_dump(mode="json"),
        "prices": _PRICES.model_dump(mode="json"),
    }


def _write_source(runs: Path, name: str, host: str = "openrouter.ai") -> Path:
    """Writes one complete C4-only dev pass exactly as the call step does."""
    run_id = f"dev-{name}-{_DATE}"
    run_dir = runs / run_id
    model, reasoning, kinds = _SOURCES[name]
    settings = _settings(model, reasoning)
    batch = prepare_batch(
        [
            GenerationInputV1(
                item_id=item,
                intent=f"Show the packets of {item}",
                retrieved_fields=(),
                split="dev",
            )
            for item in _ITEMS
        ],
        output_contract=OutputContractV1.TYPED_IR,
        retrieval=RetrievalV1.LEXICAL,
    )
    prepared = _bytes(batch)
    prepare = PrepareManifestV1(
        prepare_id=f"dev-synthetic-{_DATE}",
        created_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
        source_revision="test",
        source_files={},
        split="dev",
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
        conditions=(
            PreparedConditionV1(
                label="C4",
                output_contract=batch.output_contract,
                retrieval=batch.retrieval,
                path="prepared/C4.json",
                sha256=_sha256(prepared),
                system_prompt_sha256="0" * 64,
                prompt_count=len(_ITEMS),
            ),
        ),
    )
    completions = tuple(
        CompletionV1(item_id=item, **_answer(kinds.get(item)))
        for item in _ITEMS
    )
    started = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    log = b"".join(
        _bytes(
            smoke.model_run.AttemptV1(
                attempt=1, sent_at=started, charged_micro_usd=10, completion=c
            )
        )
        for c in completions
    )
    answers = _bytes(
        CompletionBatchV1(
            output_contract=batch.output_contract,
            retrieval=batch.retrieval,
            settings=settings,
            completions=completions,
        )
    )
    files = {
        "prepare.json": _bytes(prepare),
        "prepared/C4.json": prepared,
        "attempts/C4.jsonl": log,
        "completions/C4.json": answers,
    }
    manifest = RunManifestV1(
        run_id=run_id,
        created_at=started,
        prepare=prepare,
        prepare_sha256=_sha256(files["prepare.json"]),
        endpoint_host=host,
        settings=settings,
        prices=_PRICES,
        max_attempts=3,
        min_interval_seconds=1.0,
        invocations=(
            InvocationV1(
                source_revision="test",
                source_files={},
                started_at=started,
                finished_at=started,
                max_usd=0.1,
                requests_sent=len(_ITEMS),
            ),
        ),
        status="complete",
        charged_usd_upper_bound=0.00005,
        conditions=(
            ConditionRunV1(
                label="C4",
                attempts_path="attempts/C4.jsonl",
                attempts_sha256=_sha256(log),
                completions_path="completions/C4.json",
                completions_sha256=_sha256(answers),
                attempts={item: 1 for item in _ITEMS},
                completed=len(_ITEMS),
                failed=0,
                pending=0,
            ),
        ),
    )
    files["run_manifest.json"] = _bytes(manifest)
    for name_, data in files.items():
        path = run_dir / name_
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return run_dir


def _record(slot: str, rank: str, name: str, passes: bool) -> dict[str, Any]:
    return {
        "slot": slot,
        "rank": rank,
        "candidate": name,
        "passes": passes,
        "qualifying_pass": (
            {"run_id": f"dev-{name}-{_DATE}", "config": f"{name}_cfg"}
            if passes
            else None
        ),
    }


@pytest.fixture(name="source", scope="module")
def fixture_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository root holding a runner summary, its runs and configs."""
    root = tmp_path_factory.mktemp("source")
    runs = root / "artifacts" / "model-eval" / "dev-synthetic" / "runs"
    configs = root / "configs"
    configs.mkdir()
    for name in _SOURCES:
        _write_source(runs, name)
        (configs / f"{name}_cfg.json").write_text(
            json.dumps(_config(name)), encoding="utf-8"
        )
    summary = {
        "prepare_dir": "artifacts/model-eval/dev-synthetic",
        "candidates": [
            _record("anchor", "A", "qwen3-32b", True),
            _record("small", "1", "alpha", True),
            _record("small", "2", "beta", True),
            _record("small", "3", "gamma", False),
        ],
    }
    path = root / "artifacts" / "bakeoff" / f"summary-{_DATE}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(summary), encoding="utf-8")
    return root


def _summary(source: Path) -> Path:
    return source / "artifacts" / "bakeoff" / f"summary-{_DATE}.json"


@pytest.fixture(name="prepared", scope="module")
def fixture_prepared(
    source: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """One prepared smoke directory, built by the real follow-up step."""
    out = tmp_path_factory.mktemp("prepared") / "two-turn-smoke"
    smoke.prepare(_summary(source), out, "test-rev", source / "configs")
    return out


@pytest.fixture(name="out")
def fixture_out(prepared: Path, tmp_path: Path) -> Path:
    """A private copy of the prepared smokes, no run started yet."""
    target = tmp_path / "two-turn-smoke"
    shutil.copytree(prepared, target)
    return target


def _plan(out: Path) -> Any:
    return smoke.load_plan(out)


def _smoke(out: Path, candidate: str) -> Any:
    (found,) = [s for s in _plan(out).smokes if s.candidate == candidate]
    return found


# Preparing.


def test_prepare_builds_one_smoke_per_run_gate_survivor(prepared: Path) -> None:
    plan = _plan(prepared)
    rows = {
        s.candidate: (s.smoke_id, s.status, s.items, s.informational)
        for s in plan.smokes
    }
    date = plan.prepare_date

    assert rows == {
        "qwen3-32b": (
            f"dev-qwen3-32b-rs-{date}",
            "prepared",
            ("mei-0001", "mei-0002"),
            True,
        ),
        "alpha": (
            f"dev-alpha-rs-{date}",
            "prepared",
            ("mei-0002", "mei-0003"),
            False,
        ),
        "beta": (f"dev-beta-rs-{date}", "ready_answers_missing", (), False),
    }
    assert plan.follow_up_text_sha256 == _sha256(FOLLOW_UP_TEXT.encode())
    for entry in plan.smokes:
        config = Path(entry.config_path)
        assert entry.config_sha256 == _sha256(config.read_bytes())
        prepare_dir = prepared / entry.smoke_id
        if entry.status != "prepared":
            assert not prepare_dir.exists()
            continue
        assert entry.prepare_sha256 == _sha256(
            (prepare_dir / "prepare.json").read_bytes()
        )
        batch = PreparedBatchV1.model_validate_json(
            (prepare_dir / "prepared" / "C4.json").read_bytes()
        )
        assert [p.item_id for p in batch.prompts] == list(entry.items)
        for prompt in batch.prompts:
            assert [m.role for m in prompt.messages] == [
                "system",
                "user",
                "assistant",
                "user",
            ]
            assert prompt.messages[2].content == _READY
            assert prompt.messages[3].content == FOLLOW_UP_TEXT
        assert entry.prompt_bytes == {
            p.item_id: sum(len(m.content.encode()) for m in p.messages)
            for p in batch.prompts
        }


def _refused_prepare(source: Path, out: Path) -> str:
    with pytest.raises(smoke.PlanError) as caught:
        smoke.prepare(_summary(source), out, "test-rev", source / "configs")
    return str(caught.value)


def test_prepare_refuses_a_config_the_counted_pass_did_not_send(
    source: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "source"
    shutil.copytree(source, copy)
    config = copy / "configs" / "alpha_cfg.json"
    document = json.loads(config.read_text(encoding="utf-8"))
    document["settings"]["openrouter"]["provider_order"] = ["parasail"]
    config.write_text(json.dumps(document), encoding="utf-8")
    out = tmp_path / "out"

    assert "not the config dev-alpha" in _refused_prepare(copy, out)
    assert not out.exists() or not any(out.iterdir())


def test_prepare_refuses_a_tampered_source_and_leaves_nothing(
    source: Path, tmp_path: Path
) -> None:
    copy = tmp_path / "source"
    shutil.copytree(source, copy)
    answers = (
        copy
        / "artifacts/model-eval/dev-synthetic/runs"
        / f"dev-alpha-{_DATE}/completions/C4.json"
    )
    answers.write_bytes(answers.read_bytes().replace(b"443", b"444"))
    out = tmp_path / "out"

    assert "hash_mismatch" in _refused_prepare(copy, out)
    assert list(out.iterdir()) == []


def test_prepare_runs_once(source: Path, out: Path) -> None:
    assert "exists; the smokes are prepared" in _refused_prepare(source, out)


def test_smoke_run_ids_fit_the_result_names() -> None:
    nemotron = "dev-nemotron-3-super-120b-a12b-2026-09-26"
    reserve = "dev-qwen3-next-80b-a3b-instruct-2026-09-26"
    longest = smoke.smoke_run_id(nemotron, "2026-09-27")
    fallback = smoke.smoke_run_id(
        nemotron.replace("-2026", "-fb-2026"), "2026-09-27"
    )

    assert longest == "dev-nemotron-3-super-120b-a12b-rs-2026-09-27"
    assert fallback == "dev-nemotron-3-super-120b-a12b-fb-rs-2026-09-27"
    assert list(smoke.run_ids(longest))[:3] == [
        longest,
        "dev-nemotron-3-super-120b-a12b-rs2-2026-09-27",
        "dev-nemotron-3-super-120b-a12b-rs3-2026-09-27",
    ]
    for run in (
        *smoke.run_ids(longest),
        *smoke.run_ids(smoke.smoke_run_id(reserve, "2026-09-27")),
    ):
        assert db.RESULT_DIR.fullmatch(run), run
    assert not db.RESULT_DIR.fullmatch(list(smoke.run_ids(fallback))[1])
    for refused in ("dev-a-b", "test-qwen3-32b-2026-09-26"):
        with pytest.raises(smoke.PlanError):
            smoke.smoke_run_id(refused, "2026-09-27")


# Smoke runs, written as the call step writes them.


class SmokeRun:
    """Writes one smoke run directory exactly as the call step shapes it."""

    def __init__(self, out: Path, entry: Any, run_id: str) -> None:
        self.entry = entry
        self.run_id = run_id
        self.run_dir = out / entry.smoke_id / "runs" / run_id
        self.prepare_bytes = (
            out / entry.smoke_id / "prepare.json"
        ).read_bytes()
        self.prepare = PrepareManifestV1.model_validate_json(self.prepare_bytes)
        self.settings: RequestSettingsV1 = entry.settings
        self.attempts: dict[str, list[Any]] = {i: [] for i in entry.items}
        self.invocations: list[InvocationV1] = []
        self.clock = datetime(2026, 9, 27, tzinfo=timezone.utc)
        if (self.run_dir / "run_manifest.json").exists():
            self._reload()

    def _reload(self) -> None:
        manifest = RunManifestV1.model_validate_json(
            (self.run_dir / "run_manifest.json").read_bytes()
        )
        self.invocations = list(manifest.invocations)
        self.settings = manifest.settings
        log = self.run_dir / "attempts" / "C4.jsonl"
        for line in log.read_bytes().split(b"\n"):
            if line:
                attempt = smoke.model_run.AttemptV1.model_validate_json(line)
                self.attempts[attempt.completion.item_id].append(attempt)
        self.clock = max(i.finished_at for i in self.invocations)

    def _tick(self) -> datetime:
        self.clock += timedelta(seconds=1)
        return self.clock

    def owed(self) -> list[str]:
        """Lists the items a further pass would still send, in order."""
        return [
            item
            for item, entries in self.attempts.items()
            if not smoke.model_run._is_settled(entries, 3)
        ]

    def invoke(
        self,
        answers: Answers,
        stop: str | None = None,
        max_usd: float = 0.2,
    ) -> dict[str, Any]:
        """Records one invocation and returns the report it would print."""
        started = self._tick()
        for item, fields in answers:
            entries = self.attempts[item]
            entries.append(
                smoke.model_run.AttemptV1(
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
                stop_reason=stop,  # type: ignore[arg-type]
            )
        )
        manifest = self.write()
        return {
            "run_id": self.run_id,
            "status": manifest.status,
            "requests_sent": len(answers),
            "charged_usd_upper_bound": manifest.charged_usd_upper_bound,
            "stop_reason": stop,
        }

    def write(self) -> RunManifestV1:
        """Writes the log and the manifest, census included."""
        log = self.run_dir / "attempts" / "C4.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_bytes(
            b"".join(
                _bytes(attempt)
                for entries in self.attempts.values()
                for attempt in entries
            )
        )
        states = [
            smoke.model_run._prompt_state(entries, 3)
            for entries in self.attempts.values()
        ]
        complete = "pending" not in states
        digest = None
        if complete:
            path = self.run_dir / "completions" / "C4.json"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"{}\n")
            digest = _sha256(path.read_bytes())
        manifest = RunManifestV1(
            run_id=self.run_id,
            created_at=self.invocations[0].started_at,
            prepare=self.prepare,
            prepare_sha256=_sha256(self.prepare_bytes),
            endpoint_host="openrouter.ai",
            settings=self.settings,
            prices=_PRICES,
            max_attempts=3,
            min_interval_seconds=1.0,
            invocations=tuple(self.invocations),
            status="complete" if complete else "incomplete",
            charged_usd_upper_bound=0.0001,
            conditions=(
                ConditionRunV1(
                    label="C4",
                    attempts_path="attempts/C4.jsonl",
                    attempts_sha256=_sha256(log.read_bytes()),
                    completions_path=(
                        "completions/C4.json" if complete else None
                    ),
                    completions_sha256=digest,
                    attempts={i: len(e) for i, e in self.attempts.items()},
                    completed=states.count("completed"),
                    failed=states.count("failed"),
                    pending=states.count("pending"),
                ),
            ),
        )
        (self.run_dir / "run_manifest.json").write_bytes(_bytes(manifest))
        return manifest


def _run(out: Path, candidate: str, number: int = 1) -> SmokeRun:
    entry = _smoke(out, candidate)
    run_id = list(smoke.run_ids(entry.smoke_id))[number - 1]
    return SmokeRun(out, entry, run_id)


def _both(
    first: Fields, second: Fields | None = None
) -> Callable[..., Answers]:
    def answers(run: SmokeRun) -> Answers:
        items = list(run.entry.items)
        return [(items[0], first), (items[1], second or first)]

    return answers


def _assess(out: Path, run: SmokeRun) -> Any:
    return smoke.assess(run.entry, run.run_dir)


def test_two_good_replies_pass(out: Path) -> None:
    run = _run(out, "qwen3-32b")
    run.invoke(_both(ok())(run))

    outcome = _assess(out, run)

    assert (outcome.kind, outcome.reasons) == ("pass", ())
    assert outcome.record["thinking"] == "honoured"


def test_a_model_without_a_switch_may_leave_thinking_uncontrolled(
    out: Path,
) -> None:
    run = _run(out, "alpha")
    bare = ok(reasoning_tokens=None, reasoning_present=None)
    run.invoke(_both(bare)(run))

    assert _assess(out, run).kind == "pass"


@pytest.mark.parametrize(
    ("candidate", "first", "second", "reason"),
    [
        (
            "qwen3-32b",
            ok(finish_reason="length"),
            ok(),
            ":finish_reason_length",
        ),
        ("qwen3-32b", ok(response_text="tcp.port == 1"), ok(), ":no_parse"),
        ("qwen3-32b", ok(reasoning_tokens=12), ok(), "reasoning_shown"),
        (
            "qwen3-32b",
            ok(reasoning_tokens=None, reasoning_present=True),
            ok(),
            "reasoning_shown",
        ),
        ("alpha", ok(reasoning_tokens=5), ok(), "reasoning_shown"),
        ("qwen3-32b", http(400), ok(), ":final_http_error_400"),
        ("qwen3-32b", PROVIDER_ERROR, ok(), ":final_provider_error_200"),
        (
            "qwen3-32b",
            ok(reasoning_tokens=None, reasoning_present=None),
            ok(reasoning_tokens=None, reasoning_present=None),
            "thinking_uncontrolled",
        ),
    ],
)
def test_each_model_failure_fails_the_smoke(
    out: Path, candidate: str, first: Fields, second: Fields, reason: str
) -> None:
    run = _run(out, candidate)
    run.invoke(_both(first, second)(run))

    outcome = _assess(out, run)

    assert outcome.kind == "fail"
    assert any(r.endswith(reason) for r in outcome.reasons), outcome.reasons


def test_a_gate_stop_on_a_reasoning_reply_fails(out: Path) -> None:
    run = _run(out, "qwen3-32b")
    run.invoke([(run.entry.items[0], REASONED)], "thinking_not_honoured")

    outcome = _assess(out, run)

    assert outcome.kind == "fail"
    assert outcome.reasons[0] == "reasoning_shown"


def test_a_model_failure_is_final_beside_a_harness_failure(out: Path) -> None:
    run = _run(out, "qwen3-32b")
    first, second = run.entry.items
    run.invoke([(first, REASONED), (second, http(503))])
    run.invoke([(second, http(503))])
    run.invoke([(second, http(503))])

    assert _assess(out, run).kind == "fail"


def _transient_three_times(run: SmokeRun) -> None:
    first, second = run.entry.items
    run.invoke([(first, ok()), (second, http(503))])
    run.invoke(
        [
            (
                second,
                {
                    "status": "failed",
                    "error_code": "timeout",
                    "latency_ms": 1.0,
                },
            )
        ]
    )
    run.invoke([(second, http(429))])


def _refused(run: SmokeRun) -> dict[str, Any]:
    return run.invoke([(run.entry.items[0], http(402))], "fatal_http")


def _budget_stop(run: SmokeRun) -> dict[str, Any]:
    return run.invoke([], "budget")


def _over_cap(run: SmokeRun) -> dict[str, Any]:
    return run.invoke(_both(ok())(run), None, 0.5)


def _settings_changed(run: SmokeRun) -> None:
    run.settings = _settings("vendor/other", "enabled_false")
    run.invoke(_both(ok())(run))


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (_refused, "account_refused_402"),
        (_budget_stop, "budget_stop"),
        (_transient_three_times, ":only_transient_failures"),
        (_settings_changed, "settings_not_the_counted_pass"),
        (_over_cap, "cap_not_registered"),
    ],
)
def test_harness_and_operator_failures_owe_a_re_run(
    out: Path, write: Callable[[SmokeRun], Any], reason: str
) -> None:
    run = _run(out, "qwen3-32b")
    write(run)

    outcome = _assess(out, run)

    assert outcome.kind == "rerun"
    assert any(r.endswith(reason) for r in outcome.reasons), outcome.reasons


def test_a_transient_failure_with_attempts_left_owes_a_resume(
    out: Path,
) -> None:
    run = _run(out, "qwen3-32b")
    first, second = run.entry.items
    run.invoke([(first, ok()), (second, http(502))])

    outcome = _assess(out, run)

    assert (outcome.kind, outcome.reasons) == (
        "resume",
        (f"{second}:transient_pending",),
    )


def test_a_log_edited_after_its_manifest_cannot_be_judged(out: Path) -> None:
    run = _run(out, "qwen3-32b")
    run.invoke(_both(ok())(run))
    log = run.run_dir / "attempts" / "C4.jsonl"
    log.write_bytes(
        log.read_bytes().replace(
            b'"reasoning_tokens":0', b'"reasoning_tokens":1'
        )
    )

    assert _assess(out, run).reasons == ("attempt_log_digest",)


# One smoke across its runs, and the verdict files.


def test_a_re_run_decides_after_a_harness_failure(out: Path) -> None:
    refused = _run(out, "qwen3-32b")
    refused.invoke([(refused.entry.items[0], http(402))], "fatal_http")
    again = _run(out, "qwen3-32b", 2)
    again.invoke(_both(ok())(again))

    state = smoke.smoke_state(out, again.entry)

    assert state.verdict == "pass"
    assert [r.run_id for r in state.runs] == [refused.run_id, again.run_id]
    assert [r.kind for r in state.runs] == ["rerun", "pass"]


def test_a_run_after_a_verdict_cannot_be_judged(out: Path) -> None:
    first = _run(out, "qwen3-32b")
    first.invoke(_both(ok(finish_reason="length"))(first))
    second = _run(out, "qwen3-32b", 2)
    second.invoke(_both(ok())(second))

    state = smoke.smoke_state(out, first.entry)

    assert state.verdict == "unjudgeable"


def test_judge_writes_one_verdict_per_smoke_and_a_summary(out: Path) -> None:
    anchor = _run(out, "qwen3-32b")
    anchor.invoke(_both(ok())(anchor))
    alpha = _run(out, "alpha")
    alpha.invoke(_both(ok(finish_reason="length"), ok())(alpha))
    plan = _plan(out)

    states, text = smoke.judge(out, plan)
    first = {
        path.name: path.read_bytes()
        for path in sorted((out / "verdicts").iterdir())
    }
    smoke.judge(out, plan)

    assert {s.smoke.candidate: s.verdict for s in states} == {
        "qwen3-32b": "pass",
        "alpha": "fail",
        "beta": "fail",
    }
    assert smoke.judge_exit(states) == smoke.EXIT_OK
    assert first == {
        path.name: path.read_bytes()
        for path in sorted((out / "verdicts").iterdir())
    }
    verdict = json.loads(first[f"{anchor.entry.smoke_id}.json"])
    assert verdict["informational"] is True
    assert verdict["items"] == ["mei-0001", "mei-0002"]
    assert verdict["evidence"] == [
        f"{anchor.run_id}/run_manifest.json",
        f"{anchor.run_id}/attempts/C4.jsonl",
    ]
    beta = json.loads(first[f"{_smoke(out, 'beta').smoke_id}.json"])
    assert (beta["verdict"], beta["reasons"]) == (
        "fail",
        ["ready_answers_missing"],
    )
    lines = text.read_text(encoding="utf-8")
    assert "(informational)" in lines
    assert "small: every run-gate survivor failed its smoke" in lines
    assert "--only reserve-small --after-smoke-failures" in lines


def test_judge_cannot_judge_a_smoke_whose_source_changed(
    out: Path, tmp_path: Path
) -> None:
    plan = _plan(out)
    anchor = next(s for s in plan.smokes if s.candidate == "qwen3-32b")
    moved = tmp_path / "moved"
    shutil.copytree(Path(anchor.source_run_dir), moved)
    manifest = moved / "run_manifest.json"
    manifest.write_bytes(
        manifest.read_bytes().replace(b'"max_usd":0.1', b'"max_usd":0.2')
    )
    edited = anchor.model_copy(update={"source_run_dir": moved.as_posix()})
    changed = plan.model_copy(update={"smokes": (edited, *plan.smokes[1:])})

    states, _ = smoke.judge(out, changed)

    assert states[0].verdict == "unjudgeable"
    assert states[0].reasons == ("prompts_not_rebuilt",)
    assert smoke.judge_exit(states) == smoke.EXIT_REFUSED


def _judged_from(out: Path, candidate: str, source_run_dir: Path) -> Any:
    """Judges the plan with one smoke's source run read from elsewhere."""
    plan = _plan(out)
    moved = tuple(
        (
            s.model_copy(update={"source_run_dir": source_run_dir.as_posix()})
            if s.candidate == candidate
            else s
        )
        for s in plan.smokes
    )
    states, _ = smoke.judge(out, plan.model_copy(update={"smokes": moved}))
    return states


def _passing_anchor(out: Path) -> Path:
    """Gives the anchor a passing run and returns its source run."""
    anchor = _run(out, "qwen3-32b")
    anchor.invoke(_both(ok())(anchor))
    return Path(anchor.entry.source_run_dir)


def test_judge_cannot_judge_a_smoke_whose_source_is_gone(
    out: Path, tmp_path: Path
) -> None:
    _passing_anchor(out)

    states = _judged_from(out, "qwen3-32b", tmp_path / "gone")

    assert (states[0].verdict, states[0].reasons) == (
        "unjudgeable",
        ("source_refused_run_layout_invalid",),
    )
    assert smoke.judge_exit(states) == smoke.EXIT_REFUSED


def test_judge_cannot_judge_a_smoke_whose_source_answers_changed(
    out: Path, tmp_path: Path
) -> None:
    edited = tmp_path / "edited"
    shutil.copytree(_passing_anchor(out), edited)
    answers = edited / "completions" / "C4.json"
    answers.write_bytes(answers.read_bytes().replace(b"443", b"444"))

    states = _judged_from(out, "qwen3-32b", edited)

    assert (states[0].verdict, states[0].reasons) == (
        "unjudgeable",
        ("source_refused_hash_mismatch",),
    )
    assert smoke.judge_exit(states) == smoke.EXIT_REFUSED


def test_judge_cannot_judge_a_smoke_whose_source_now_has_ready_answers(
    out: Path,
) -> None:
    alpha = Path(_smoke(out, "alpha").source_run_dir)

    states = _judged_from(out, "beta", alpha)

    beta = next(s for s in states if s.smoke.candidate == "beta")
    assert (beta.verdict, beta.reasons) == (
        "unjudgeable",
        ("source_now_has_ready_answers",),
    )
    assert smoke.judge_exit(states) == smoke.EXIT_REFUSED


# The paid batch, with the call step replaced.


class FakeCalls:
    """Plays scripted call steps and records every argv it was given."""

    def __init__(
        self, out: Path, script: list[Callable[[SmokeRun], dict[str, Any]]]
    ) -> None:
        self.out = out
        self.script = list(script)
        self.calls: list[tuple[list[str], bool]] = []

    def __call__(self, argv: Sequence[str], with_key: bool) -> Any:
        argv = list(argv)
        self.calls.append((argv, with_key))
        if not with_key:
            return db.Invocation(2, None, "api_key_missing")
        step = self.script.pop(0)
        run_id = argv[argv.index("--run-id") + 1]
        prepare_dir = Path(argv[argv.index("--prepare-dir") + 1])
        entry = next(
            s for s in _plan(self.out).smokes if s.smoke_id == prepare_dir.name
        )
        report = step(SmokeRun(self.out, entry, run_id))
        if not report:
            return db.Invocation(2, None, "prepare_code_mismatch")
        complete = report["status"] == "complete"
        return db.Invocation(0 if complete else 1, report, None)

    def paid(self) -> list[list[str]]:
        """Returns the argv of every call made with the key."""
        return [argv for argv, with_key in self.calls if with_key]


def _good(run: SmokeRun) -> dict[str, Any]:
    return run.invoke([(item, ok()) for item in run.owed()])


def _committed() -> list[str]:
    return []


def _ctx(
    out: Path, calls: FakeCalls, changes: Callable[[], list[str]] = _committed
) -> Any:
    printed: list[str] = []
    context = smoke.Context(
        out, _plan(out), "test-rev", calls, changes=changes, out=printed.append
    )
    context.printed = printed
    return context


@pytest.fixture(name="slept")
def fixture_slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(smoke, "pause", slept.append)
    monkeypatch.setenv(API_KEY_ENV, "fixture-key")
    return slept


def test_the_batch_calls_each_prepared_smoke_with_the_registered_options(
    out: Path, slept: list[float]
) -> None:
    calls = FakeCalls(out, [_good, _good])
    ctx = _ctx(out, calls)

    assert smoke.locked_run(ctx) == smoke.EXIT_OK

    preflights = [argv for argv, key in calls.calls if not key]
    assert len(preflights) == 2
    assert calls.paid() == preflights
    anchor, alpha = (_smoke(out, name) for name in ("qwen3-32b", "alpha"))
    for argv, entry in zip(calls.paid(), (anchor, alpha)):
        assert argv[:3] == [sys.executable, "scripts/model_run.py", "call"]
        flags = dict(zip(argv[3:-1:2], argv[4:-1:2]))
        assert flags == {
            "--prepare-dir": (out / entry.smoke_id).resolve().as_posix(),
            "--run-id": entry.smoke_id,
            "--config": entry.config_path,
            "--max-usd": "0.20",
            "--source-revision": "test-rev",
            "--min-interval-seconds": "1.0",
            "--max-attempts": "3",
        }
        assert argv[-1] == "--gate-first"
    assert slept == []
    assert (out / "verdicts" / f"{anchor.smoke_id}.json").is_file()
    assert not (out / smoke.LOCK_NAME).exists()
    assert not any(
        _smoke(out, "beta").smoke_id in " ".join(argv)
        for argv, _ in calls.calls
    )


def test_a_missing_key_aborts_after_the_preflight_with_nothing_sent(
    out: Path, slept: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(API_KEY_ENV)
    calls = FakeCalls(out, [])
    ctx = _ctx(out, calls)

    assert smoke.locked_run(ctx) == smoke.EXIT_ABORTED

    assert calls.paid() == []
    assert len(calls.calls) == 2
    assert any("nothing was sent" in line for line in ctx.printed)
    assert not (out / smoke.LOCK_NAME).exists()
    del slept


def test_a_preflight_that_stops_elsewhere_refuses(
    out: Path, slept: list[float]
) -> None:
    def refuse(argv: Sequence[str], with_key: bool) -> Any:
        del argv, with_key
        return db.Invocation(2, None, "prepare_code_mismatch")

    ctx = _ctx(out, FakeCalls(out, []))
    ctx.invoke = refuse

    assert smoke.locked_run(ctx) == smoke.EXIT_REFUSED
    del slept


def test_pending_items_resume_after_a_wait(
    out: Path, slept: list[float]
) -> None:
    def flaky(run: SmokeRun) -> dict[str, Any]:
        first, second = run.entry.items
        return run.invoke([(first, ok()), (second, http(503))])

    calls = FakeCalls(out, [flaky, _good, _good])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_OK

    paid = calls.paid()
    assert ["--resume" in argv for argv in paid] == [False, True, False]
    assert slept == [smoke.RESUME_WAIT_SECONDS]


def test_an_account_refusal_aborts_and_the_next_command_re_runs(
    out: Path, slept: list[float]
) -> None:
    def refused(run: SmokeRun) -> dict[str, Any]:
        return run.invoke([(run.entry.items[0], http(402))], "fatal_http")

    first = FakeCalls(out, [refused])
    assert smoke.locked_run(_ctx(out, first)) == smoke.EXIT_ABORTED
    second = FakeCalls(out, [_good, _good])

    assert smoke.locked_run(_ctx(out, second)) == smoke.EXIT_OK

    anchor = _smoke(out, "qwen3-32b")
    rerun = list(smoke.run_ids(anchor.smoke_id))[1]
    assert [argv[argv.index("--run-id") + 1] for argv in second.paid()][0] == (
        rerun
    )
    assert "--resume" not in second.paid()[0]
    assert smoke.smoke_state(out, anchor).verdict == "pass"
    del slept


def test_a_budget_stop_owes_a_re_run_and_the_batch_goes_on(
    out: Path, slept: list[float]
) -> None:
    calls = FakeCalls(out, [_budget_stop, _good])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_STOPPED

    assert len(calls.paid()) == 2
    anchor = _smoke(out, "qwen3-32b")
    assert smoke.smoke_state(out, anchor).verdict == "rerun_owed"
    assert smoke.smoke_state(out, _smoke(out, "alpha")).verdict == "pass"
    del slept


def test_a_call_step_error_stops_the_batch(
    out: Path, slept: list[float]
) -> None:
    calls = FakeCalls(out, [lambda run: {}])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_STOPPED
    del slept


def test_uncommitted_tooling_is_refused_before_a_paid_call(
    out: Path, slept: list[float]
) -> None:
    calls = FakeCalls(out, [])
    ctx = _ctx(out, calls, changes=lambda: [" M scripts/two_turn_smoke.py"])

    assert smoke.locked_run(ctx) == smoke.EXIT_REFUSED
    assert calls.paid() == []
    del slept


def test_a_held_lock_refuses(out: Path, slept: list[float]) -> None:
    (out / smoke.LOCK_NAME).write_text("pid 1\n", encoding="utf-8")
    calls = FakeCalls(out, [])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_REFUSED
    assert calls.calls == []
    del slept


def _steps(out: Path) -> list[dict[str, Any]]:
    lines = (out / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _printed(ctx: Any, label: str) -> str:
    """Returns the one printed line that starts with the label."""
    (found,) = [line for line in ctx.printed if line.startswith(label)]
    return found


def _interrupted(ctx: Any) -> str:
    return _printed(ctx, "INTERRUPTED")


def test_an_interrupt_releases_the_lock(out: Path, slept: list[float]) -> None:
    def interrupted(run: SmokeRun) -> dict[str, Any]:
        raise KeyboardInterrupt

    calls = FakeCalls(out, [interrupted])
    ctx = _ctx(out, calls)

    assert smoke.locked_run(ctx) == smoke.EXIT_INTERRUPTED
    assert not (out / smoke.LOCK_NAME).exists()
    assert "may be billed but not recorded" in _interrupted(ctx)
    assert "run the same command again" in _interrupted(ctx)
    assert _steps(out)[-1]["phase"] == "interrupted"
    del slept


def test_a_call_step_still_running_keeps_the_smoke_lock(
    out: Path, slept: list[float]
) -> None:
    def still_running(run: SmokeRun) -> dict[str, Any]:
        raise db.ChildStillRunning(
            "call step pid 7 is still running; let it exit, then delete"
            " artifacts/bakeoff/.lock and run the same command"
        )

    ctx = _ctx(out, FakeCalls(out, [still_running]))

    assert smoke.locked_run(ctx) == smoke.EXIT_INTERRUPTED
    lock = out / smoke.LOCK_NAME
    assert lock.exists()
    assert lock.resolve().as_posix() in _interrupted(ctx)
    assert "artifacts/bakeoff" not in _interrupted(ctx)
    assert "may be billed but not recorded" in _interrupted(ctx)
    assert _steps(out)[-1] == {
        "at": _steps(out)[-1]["at"],
        "phase": "interrupted",
        "reason": "call_step_still_running",
    }
    del slept


def test_a_changed_config_is_refused_before_anything(out: Path) -> None:
    plan = _plan(out)
    entry = plan.smokes[0]
    edited = entry.model_copy(update={"config_sha256": "0" * 64})
    ctx = _ctx(out, FakeCalls(out, []))
    ctx.plan = plan.model_copy(update={"smokes": (edited, *plan.smokes[1:])})

    with pytest.raises(smoke.PlanError, match="config file changed"):
        smoke.check_inputs(ctx)


def test_dry_run_prints_the_calls_and_sends_nothing(out: Path) -> None:
    calls = FakeCalls(out, [])
    ctx = _ctx(out, calls)

    smoke.dry_run(ctx)

    assert calls.calls == []
    printed = "\n".join(ctx.printed)
    assert "--max-usd 0.20" in printed
    assert "ready_answers_missing" not in printed
    assert f"{_smoke(out, 'beta').smoke_id}: fail" in printed
    assert not (out / smoke.LOCK_NAME).exists()


def test_main_refuses_without_a_plan(tmp_path: Path) -> None:
    code = smoke.main(["--out-dir", str(tmp_path), "judge"])

    assert code == smoke.EXIT_REFUSED


def test_main_judges_offline(
    out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = smoke.main(["--out-dir", str(out), "judge"])

    assert code == smoke.EXIT_STOPPED
    assert "not_run" in capsys.readouterr().out


def _no_manifest(run: SmokeRun) -> None:
    run.invoke(_both(ok())(run))
    (run.run_dir / "run_manifest.json").unlink()


def _torn_log(run: SmokeRun) -> None:
    run.invoke(_both(ok())(run))
    with (run.run_dir / "attempts" / "C4.jsonl").open("ab") as log:
        log.write(b'{"attempt":')


def _bad_manifest(run: SmokeRun) -> None:
    run.invoke(_both(ok())(run))
    (run.run_dir / "run_manifest.json").write_text("{}\n", encoding="utf-8")


def _bad_log_line(run: SmokeRun) -> None:
    run.invoke(_both(ok())(run))
    with (run.run_dir / "attempts" / "C4.jsonl").open("ab") as log:
        log.write(b"{}\n")


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (_no_manifest, "manifest_missing"),
        (_bad_manifest, "manifest_invalid"),
        (_torn_log, "attempt_log_torn"),
        (_bad_log_line, "attempt_log_invalid"),
    ],
)
def test_an_unreadable_run_stops_the_batch_for_the_owner(
    out: Path,
    slept: list[float],
    write: Callable[[SmokeRun], None],
    reason: str,
) -> None:
    run = _run(out, "qwen3-32b")
    write(run)
    calls = FakeCalls(out, [])
    ctx = _ctx(out, calls)

    assert _assess(out, run).reasons == (reason,)
    assert smoke.locked_run(ctx) == smoke.EXIT_STOPPED
    assert calls.calls == []
    assert any(reason in line for line in ctx.printed)
    del slept


def test_a_log_ahead_of_its_manifest_is_resumed(
    out: Path, slept: list[float]
) -> None:
    run = _run(out, "qwen3-32b")
    first, second = run.entry.items
    run.invoke([(first, ok()), (second, http(503))])
    ahead = smoke.model_run.AttemptV1(
        attempt=2,
        sent_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
        charged_micro_usd=10,
        completion=CompletionV1(item_id=second, **http(503)),
    )
    with (run.run_dir / "attempts" / "C4.jsonl").open("ab") as log:
        log.write(_bytes(ahead))

    assert _assess(out, run).reasons == ("log_ahead",)
    del slept


def test_main_prepare_refuses_uncommitted_tooling(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def edited(paths: Sequence[str]) -> list[str]:
        del paths
        return [" M src/x.py"]

    monkeypatch.setattr(smoke, "uncommitted", edited)
    out = tmp_path / "out"

    code = smoke.main(
        ["--out-dir", str(out), "prepare", "--summary", str(_summary(source))]
    )

    assert code == smoke.EXIT_REFUSED
    assert not out.exists()


class _Replies(BaseHTTPRequestHandler):
    """Answers every request with one ready reply that reports no reasoning."""

    received: list[bytes] = []

    def do_POST(self) -> None:  # pylint: disable=invalid-name
        length = int(self.headers.get("Content-Length") or 0)
        self.received.append(self.rfile.read(length))
        body = json.dumps(
            {
                "id": "gen-local",
                "model": "qwen/qwen3-32b",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": _READY},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1400,
                    "completion_tokens": 50,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


def test_the_real_call_step_answers_a_smoke_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare, the batch's own child call step and the judge, on loopback.

    The source pass is recorded against 127.0.0.1, so the config the batch
    sends is that pass's own; nothing leaves the machine.
    """
    _Replies.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Replies)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = tmp_path / "source"
        runs = root / "artifacts" / "model-eval" / "dev-synthetic" / "runs"
        source = _write_source(runs, "qwen3-32b", "127.0.0.1")
        config = _config("qwen3-32b")
        config["endpoint_url"] = (
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
        )
        configs = root / "configs"
        configs.mkdir()
        (configs / "qwen3-32b_cfg.json").write_text(
            json.dumps(config), encoding="utf-8"
        )
        summary = root / "artifacts" / "bakeoff" / f"summary-{_DATE}.json"
        summary.parent.mkdir(parents=True)
        summary.write_text(
            json.dumps(
                {
                    "prepare_dir": "artifacts/model-eval/dev-synthetic",
                    "candidates": [_record("anchor", "A", "qwen3-32b", True)],
                }
            ),
            encoding="utf-8",
        )
        out = tmp_path / "out"
        plan = smoke.prepare(summary, out, "test-rev", configs)
        monkeypatch.setenv(API_KEY_ENV, "local-fixture-key")
        printed: list[str] = []
        ctx = smoke.Context(
            out,
            plan,
            "test-rev",
            smoke.subprocess_invoke(printed.append),
            changes=_committed,
            out=printed.append,
        )

        assert smoke.locked_run(ctx) == smoke.EXIT_OK
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    (entry,) = plan.smokes
    bodies = [json.loads(body) for body in _Replies.received]
    answered = CompletionBatchV1.model_validate_json(
        (source / "completions" / "C4.json").read_bytes()
    )
    first = {a.item_id: a.response_text for a in answered.completions}
    assert len(bodies) == 2
    for body, item in zip(bodies, entry.items):
        roles = [m["role"] for m in body["messages"]]
        assert roles == ["system", "user", "assistant", "user"]
        assert body["messages"][2]["content"] == first[item]
        assert body["messages"][3]["content"] == FOLLOW_UP_TEXT
        assert body["reasoning"] == {"enabled": False}
    state = smoke.smoke_state(out, entry)
    assert (state.verdict, state.reasons) == ("pass", ())
    assert not any("local-fixture-key" in line for line in printed)
