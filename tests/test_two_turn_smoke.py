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
import functools
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


def failed(error_code: str, status: int | None = None) -> Fields:
    """A failure the client records under its own error code."""
    return {
        "status": "failed",
        "error_code": error_code,
        "latency_ms": 1.0,
        "http_status": status,
    }


REASONED = ok(reasoning_tokens=40, reasoning_present=True)
PROVIDER_ERROR: Fields = failed("provider_error", 200)


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


def _other_route(document: dict[str, Any]) -> None:
    document["settings"]["openrouter"]["provider_order"] = ["parasail"]


def _other_prices(document: dict[str, Any]) -> None:
    document["prices"]["usd_per_million_output"] = 0.3


def _other_host(document: dict[str, Any]) -> None:
    document["endpoint_url"] = "https://api.example.com/v1/chat/completions"


@pytest.mark.parametrize("edit", [_other_route, _other_prices, _other_host])
def test_prepare_refuses_a_config_the_counted_pass_did_not_send(
    source: Path, tmp_path: Path, edit: Callable[[dict[str, Any]], None]
) -> None:
    """Settings, prices and host are each compared with the pass's manifest."""
    copy = tmp_path / "source"
    shutil.copytree(source, copy)
    config = copy / "configs" / "alpha_cfg.json"
    document = json.loads(config.read_text(encoding="utf-8"))
    edit(document)
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


def test_prepare_reads_only_the_runner_s_own_summary(
    source: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The committed copy has no raw runs beside it, so it is refused."""
    evidence = source / "docs" / "decisions" / "evidence" / "bakeoff"
    copy = tmp_path / evidence.relative_to(source) / f"summary-{_DATE}.json"
    copy.parent.mkdir(parents=True)
    shutil.copyfile(_summary(source), copy)
    monkeypatch.setattr(smoke, "uncommitted", _nothing_uncommitted)
    monkeypatch.setattr(smoke.db, "head_revision", lambda: "test-rev")
    out = tmp_path / "out"

    code = smoke.main(
        ["--out-dir", str(out), "prepare", "--summary", str(copy)]
    )

    assert code == smoke.EXIT_REFUSED
    error = capsys.readouterr().err
    assert "the bake-off runner's own summary" in error
    assert "<checkout>/artifacts/bakeoff/summary-<date>.json" in error
    assert "docs/decisions/artifacts" not in error
    assert not out.exists()


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("{", "not a runner summary"),
        ("[]", "not a runner summary (top level"),
        ('{"candidates": []}', "(prepare_dir: missing)"),
        (
            '{"prepare_dir": "artifacts/model-eval/x", "candidates": {}}',
            "(candidates:",
        ),
        (
            json.dumps(
                {
                    "prepare_dir": "artifacts/model-eval/dev-synthetic",
                    "candidates": [_record("small", "1", "alpha", True)]
                    + [_record("small", "2", "beta", True) | {"passes": "yes"}],
                }
            ),
            "(candidates.1.passes: bool_type)",
        ),
        (
            json.dumps(
                {
                    "prepare_dir": "artifacts/model-eval/dev-synthetic",
                    "candidates": [
                        _record("small", "1", "alpha", True)
                        | {"qualifying_pass": {"run_id": "dev-alpha"}}
                    ],
                }
            ),
            "(candidates.0.qualifying_pass.config: missing)",
        ),
        (
            json.dumps({"prepare_dir": "../../outside", "candidates": []}),
            "prepare_dir is not a directory under artifacts/model-eval/",
        ),
        (
            json.dumps(
                {"prepare_dir": "D:/artifacts/model-eval/x", "candidates": []}
            ),
            "prepare_dir is not a directory under artifacts/model-eval/",
        ),
    ],
)
def test_prepare_refuses_a_summary_of_another_shape(
    tmp_path: Path, content: str, problem: str
) -> None:
    summary = tmp_path / "artifacts" / "bakeoff" / f"summary-{_DATE}.json"
    summary.parent.mkdir(parents=True)
    summary.write_text(content, encoding="utf-8")
    out = tmp_path / "out"

    with pytest.raises(smoke.PlanError) as caught:
        smoke.prepare(summary, out, "test-rev", tmp_path / "configs")

    assert problem in str(caught.value)
    assert not out.exists()


def test_prepare_runs_once(source: Path, out: Path) -> None:
    assert "exists; the smokes are prepared" in _refused_prepare(source, out)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_prepare_never_removes_a_smoke_directory_it_did_not_make(
    source: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-day prepare after plan.json went must leave the runs alone."""
    plan = _plan(out)
    monkeypatch.setattr(smoke, "_now", lambda: f"{plan.prepare_date}T01:00:00Z")
    anchor = _smoke(out, "qwen3-32b")
    run = out / anchor.smoke_id / "runs" / anchor.smoke_id
    run.mkdir(parents=True)
    (run / "run_manifest.json").write_text("{}\n", encoding="utf-8")
    (out / "plan.json").unlink()
    before = _snapshot(out)

    message = _refused_prepare(source, out)

    assert anchor.smoke_id in message
    assert "holds no runs/" in message
    assert _snapshot(out) == before


def test_prepare_refuses_a_killed_prepare_s_staging_directory(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(smoke, "_now", lambda: "2026-09-27T01:00:00Z")
    out = tmp_path / "out"
    staging = out / ".dev-alpha-rs-2026-09-27.partial"
    staging.mkdir(parents=True)

    message = _refused_prepare(source, out)

    assert ".dev-alpha-rs-2026-09-27.partial" in message
    assert [p.name for p in out.iterdir()] == [staging.name]


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
    # Re-runs go up to -rs9 without a further ruling (owner, 2026-09-27).
    assert len(list(smoke.run_ids(longest))) == 9
    assert list(smoke.run_ids(longest))[-1] == (
        "dev-nemotron-3-super-120b-a12b-rs9-2026-09-27"
    )
    for run in (
        *smoke.run_ids(longest),
        *smoke.run_ids(smoke.smoke_run_id(reserve, "2026-09-27")),
    ):
        assert db.RESULT_DIR.fullmatch(run), run
    assert not db.RESULT_DIR.fullmatch(list(smoke.run_ids(fallback))[1])
    for refused, problem in (
        ("dev-a-b", "not a dev run id"),
        ("test-qwen3-32b-2026-09-26", "not a dev run id"),
        # A 30-character middle is a dev run id, but its smoke id is not.
        (f"dev-{'a' * 30}-2026-09-26", "not a usable result name"),
    ):
        with pytest.raises(smoke.PlanError, match=problem):
            smoke.smoke_run_id(refused, "2026-09-27")


def test_run_ids_need_a_middle_of_29_or_28_characters() -> None:
    """A smoke id needs at most 29 characters of middle, a re-run 28.

    Checked on every listed pass and outage re-run of the bake-off.
    """
    no_smoke: set[str] = set()
    no_re_run: set[str] = set()
    for candidate in db.all_candidates():
        for target in db.registered_targets(candidate):
            middle = target.run_id.removeprefix("dev-")[: -len("-2026-09-26")]
            try:
                first = smoke.smoke_run_id(target.run_id, "2026-09-27")
            except smoke.PlanError:
                assert len(middle) > 29, target.run_id
                no_smoke.add(target.run_id)
                continue
            fits = all(db.RESULT_DIR.fullmatch(r) for r in smoke.run_ids(first))
            assert fits == (len(middle) <= 28), target.run_id
            if not fits:
                no_re_run.add(target.run_id)

    assert no_smoke == {
        "dev-nemotron-3-super-120b-a12b-fb-r2-2026-09-26",
        "dev-qwen3-next-80b-a3b-instruct-r2-2026-09-26",
    }
    assert no_re_run == {
        "dev-nemotron-3-super-120b-a12b-fb-2026-09-26",
        "dev-nemotron-3-super-120b-a12b-r2-2026-09-26",
    }


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
        self.prices: TokenPricesV1 | None = _PRICES
        self.endpoint_host = "openrouter.ai"
        self.max_attempts = 3
        self.min_interval_seconds = 1.0
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
        self.prices = manifest.prices
        self.endpoint_host = manifest.endpoint_host
        self.max_attempts = manifest.max_attempts
        self.min_interval_seconds = manifest.min_interval_seconds
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
            endpoint_host=self.endpoint_host,
            settings=self.settings,
            prices=self.prices,
            max_attempts=self.max_attempts,
            min_interval_seconds=self.min_interval_seconds,
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
        # Final errors by the owner's 2026-09-27 reading, not harness ones.
        ("qwen3-32b", failed("client_error"), ok(), ":final_client_error_None"),
        (
            "qwen3-32b",
            failed("redirect_rejected", 302),
            ok(),
            ":final_redirect_rejected_302",
        ),
        (
            "qwen3-32b",
            failed("response_too_large", 200),
            ok(),
            ":final_response_too_large_200",
        ),
        (
            "qwen3-32b",
            failed("empty_content", 200),
            ok(),
            ":final_empty_content_200",
        ),
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


def test_a_model_failure_is_final_beside_an_account_refusal(out: Path) -> None:
    run = _run(out, "qwen3-32b")
    first, second = run.entry.items
    run.invoke(
        [(first, ok(finish_reason="length")), (second, http(402))],
        "fatal_http",
    )

    outcome = _assess(out, run)

    assert (outcome.kind, outcome.reasons) == (
        "fail",
        (f"{first}:finish_reason_length",),
    )


def test_reasoning_on_an_attempt_that_is_not_counted_fails(out: Path) -> None:
    """Reasoning is read over every recorded attempt, not the last only."""
    run = _run(out, "qwen3-32b")
    first, second = run.entry.items
    run.invoke([(first, ok()), (second, http(503) | {"reasoning_tokens": 40})])
    run.invoke([(second, ok())])

    outcome = _assess(out, run)

    assert (outcome.kind, outcome.reasons) == ("fail", ("reasoning_shown",))


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


Replies = Callable[..., Answers]


def _replies(run: SmokeRun, replies: Replies | None) -> Answers:
    """Returns what a void run answers: two good replies unless given."""
    return (replies or _both(ok()))(run)


def _over_cap(run: SmokeRun, replies: Replies | None = None) -> dict[str, Any]:
    return run.invoke(_replies(run, replies), None, 0.5)


def _settings_changed(run: SmokeRun, replies: Replies | None = None) -> None:
    run.settings = _settings("vendor/other", "enabled_false")
    run.invoke(_replies(run, replies))


def _prices_changed(run: SmokeRun, replies: Replies | None = None) -> None:
    run.prices = _PRICES.model_copy(update={"usd_per_million_output": 0.3})
    run.invoke(_replies(run, replies))


def _host_changed(run: SmokeRun, replies: Replies | None = None) -> None:
    run.endpoint_host = "api.example.com"
    run.invoke(_replies(run, replies))


def _prompts_changed(run: SmokeRun, replies: Replies | None = None) -> None:
    (condition,) = run.prepare.conditions
    other = condition.model_copy(update={"sha256": "0" * 64})
    run.prepare = run.prepare.model_copy(update={"conditions": (other,)})
    run.invoke(_replies(run, replies))


def _attempts_changed(run: SmokeRun, replies: Replies | None = None) -> None:
    run.max_attempts = 2
    run.invoke(_replies(run, replies))


def _interval_changed(run: SmokeRun, replies: Replies | None = None) -> None:
    run.min_interval_seconds = 2.0
    run.invoke(_replies(run, replies))


# The owner confirmed on 2026-09-27 that a run whose settings, prices,
# host, prompts or cap differ from the counted pass is void and owes a
# re-run, whatever its replies (docs/decisions/second-turn.md). So is a
# run whose call options are not the note's --max-attempts 3 and
# --min-interval-seconds 1.0.
_VOID_RUNS = [
    (_settings_changed, "settings_not_the_counted_pass"),
    (_prices_changed, "settings_not_the_counted_pass"),
    (_host_changed, "settings_not_the_counted_pass"),
    (_prompts_changed, "prompts_not_the_prepared_ones"),
    (_attempts_changed, "call_options_not_registered"),
    (_interval_changed, "call_options_not_registered"),
    (_over_cap, "cap_not_registered"),
]


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (_refused, "account_refused_402"),
        (_budget_stop, "budget_stop"),
        (_transient_three_times, ":only_transient_failures"),
        *_VOID_RUNS,
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


@pytest.mark.parametrize(
    "first",
    [ok(reasoning_tokens=12), ok(finish_reason="length")],
    ids=["reasoning_shown", "finish_reason_length"],
)
@pytest.mark.parametrize(("write", "reason"), _VOID_RUNS)
def test_a_void_run_owes_a_re_run_whatever_its_replies_show(
    out: Path,
    write: Callable[[SmokeRun, Replies], Any],
    reason: str,
    first: Fields,
) -> None:
    """The owner's reading 1 comes before reading 2.

    A void run's replies are never read, so a model failure in one owes
    a re-run under a new run id and never fails the smoke.
    """
    run = _run(out, "qwen3-32b")
    write(run, _both(first, ok()))

    outcome = _assess(out, run)

    assert (outcome.kind, outcome.reasons) == ("rerun", (reason,))


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


@pytest.mark.parametrize(
    "raw",
    [
        "length]; items mei-0001\nsmall: smoke passed by alpha\x1b[2K",
        "length\n",
    ],
)
def test_a_provider_finish_reason_cannot_write_summary_lines(
    out: Path, raw: str
) -> None:
    anchor = _run(out, "qwen3-32b")
    anchor.invoke(_both(ok())(anchor))
    alpha = _run(out, "alpha")
    alpha.invoke(_both(ok(finish_reason=raw), ok())(alpha))
    first = alpha.entry.items[0]

    states, text = smoke.judge(out, _plan(out))

    state = next(s for s in states if s.smoke.candidate == "alpha")
    assert (state.verdict, state.reasons) == (
        "fail",
        (f"{first}:finish_reason_other",),
    )
    lines = text.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(states) + 1 + len(smoke.slot_lines(states))
    assert not any("\x1b" in line or "passed by" in line for line in lines)
    verdict = json.loads(
        (out / "verdicts" / f"{alpha.entry.smoke_id}.json").read_bytes()
    )
    assert verdict["runs"][0]["items"][first]["finish_reason"] == raw


# A reserve's smoke (rule 6).

_LATER = "2026-09-29"


def _reserve_summary(
    source: Path, tmp_path: Path, *records: dict[str, Any]
) -> Path:
    """Writes the runner's later summary, with small's reserve passing."""
    root = tmp_path / "source"
    shutil.copytree(source, root)
    summary = {
        "prepare_dir": "artifacts/model-eval/dev-synthetic",
        "candidates": list(records)
        or [
            _record("anchor", "A", "qwen3-32b", True),
            _record("small", "1", "alpha", True),
            _record("small", "2", "beta", True),
            _record("reserve-small", "R", "gamma", True),
        ],
    }
    path = root / "artifacts" / "bakeoff" / f"summary-{_LATER}.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    return path


def _add_reserve(summary: Path, out: Path) -> Any:
    return smoke.prepare_reserve(
        summary, out, "reserve-rev", "small", summary.parents[2] / "configs"
    )


def _small_failed(out: Path) -> None:
    alpha = _run(out, "alpha")
    alpha.invoke(_both(ok(finish_reason="length"), ok())(alpha))


def _small_passed(out: Path) -> None:
    alpha = _run(out, "alpha")
    alpha.invoke(_both(ok())(alpha))


def test_a_reserve_smoke_is_appended_and_nothing_else_moves(
    source: Path,
    out: Path,
    tmp_path: Path,
    slept: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke, "_now", lambda: f"{_LATER}T01:00:00Z")
    anchor = _run(out, "qwen3-32b")
    anchor.invoke(_both(ok())(anchor))
    _small_failed(out)
    before = _plan(out)
    files = _snapshot(out)
    summary = _reserve_summary(source, tmp_path)

    plan = _add_reserve(summary, out)

    (reserve,) = plan.reserves
    added = plan.smokes[-1]
    assert plan.smokes[:-1] == before.smokes
    assert (
        plan.model_copy(update={"smokes": before.smokes, "reserves": ()})
        == before
    )
    assert (added.slot, added.candidate, added.status) == (
        "reserve-small",
        "gamma",
        "prepared",
    )
    assert added.smoke_id == f"dev-gamma-rs-{_LATER}"
    assert reserve.model_dump() == {
        "smoke_id": added.smoke_id,
        "prepare_date": _LATER,
        "source_revision": "reserve-rev",
        "summary_path": summary.resolve().as_posix(),
        "summary_sha256": _sha256(summary.read_bytes()),
    }
    assert smoke.load_plan(out) == plan
    after = _snapshot(out)
    assert {
        name: data
        for name, data in after.items()
        if name != "plan.json" and not name.startswith(added.smoke_id)
    } == {name: data for name, data in files.items() if name != "plan.json"}
    calls = FakeCalls(out, [_good])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_OK

    assert [argv[argv.index("--run-id") + 1] for argv in calls.paid()] == [
        added.smoke_id
    ]
    summary_text = (out / f"summary-{_LATER}.txt").read_text(encoding="utf-8")
    assert "small: smoke passed by gamma" in summary_text
    del slept


def _smoke_open(out: Path) -> None:
    del out


def _reserve_already_added(out: Path) -> None:
    _small_failed(out)
    plan = _plan(out)
    gamma = _smoke(out, "alpha").model_copy(
        update={"slot": "reserve-small", "candidate": "gamma"}
    )
    (out / "plan.json").write_bytes(
        _bytes(plan.model_copy(update={"smokes": (*plan.smokes, gamma)}))
    )


def _failed_but_source_gone(out: Path) -> None:
    _small_failed(out)
    plan = _plan(out)
    gone = (out / "gone").as_posix()
    smokes = tuple(
        (
            s.model_copy(update={"source_run_dir": gone})
            if s.candidate == "alpha"
            else s
        )
        for s in plan.smokes
    )
    (out / "plan.json").write_bytes(
        _bytes(plan.model_copy(update={"smokes": smokes}))
    )


@pytest.mark.parametrize(
    ("setup", "records", "message"),
    [
        (_smoke_open, (), "alpha not_run"),
        (_small_passed, (), "alpha pass"),
        (_failed_but_source_gone, (), "alpha unjudgeable"),
        (_reserve_already_added, (), "already holds the reserve-small smoke"),
        (
            _small_failed,
            (_record("reserve-small", "R", "gamma", False),),
            "no reserve-small candidate passing",
        ),
        (
            _small_failed,
            (
                _record("small", "1", "alpha", True)
                | {
                    "qualifying_pass": {
                        "run_id": f"dev-alpha-fb-{_DATE}",
                        "config": "alpha_cfg",
                    }
                },
                _record("reserve-small", "R", "gamma", True),
            ),
            "alpha passes the run gates in the summary but the plan",
        ),
        (
            _small_failed,
            (
                _record("anchor", "A", "qwen3-32b", True),
                _record("small", "1", "alpha", True),
                _record("small", "2", "beta", True),
                _record("reserve-small", "R", "delta", False),
                _record("reserve-mid", "R", "gamma", True),
            ),
            "no reserve-small candidate passing",
        ),
    ],
)
def test_a_reserve_smoke_is_refused_unless_rule_6_allows_it(
    source: Path,
    out: Path,
    tmp_path: Path,
    setup: Callable[[Path], None],
    records: tuple[dict[str, Any], ...],
    message: str,
) -> None:
    setup(out)
    plan_bytes = (out / "plan.json").read_bytes()
    summary = _reserve_summary(source, tmp_path, *records)

    with pytest.raises(smoke.PlanError, match=message):
        _add_reserve(summary, out)

    assert (out / "plan.json").read_bytes() == plan_bytes
    assert not list(out.glob("dev-gamma-*"))


def test_a_failed_reserve_prepare_removes_only_its_own_smoke(
    source: Path,
    out: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def over_cap(entry: Any) -> None:
        raise smoke.PlanError(f"{entry.smoke_id}: over the cap")

    _small_failed(out)
    files = _snapshot(out)
    summary = _reserve_summary(source, tmp_path)
    monkeypatch.setattr(smoke, "check_cap", over_cap)

    with pytest.raises(smoke.PlanError, match="over the cap"):
        _add_reserve(summary, out)

    assert _snapshot(out) == files


@pytest.mark.parametrize(
    "seed",
    [
        f"dev-gamma-rs-{_LATER}/runs/dev-gamma-rs-{_LATER}/run_manifest.json",
        f".dev-gamma-rs-{_LATER}.partial/marker",
    ],
)
def test_a_reserve_prepare_never_touches_a_smoke_directory_it_did_not_make(
    source: Path,
    out: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seed: str,
) -> None:
    """The reserve's own directory on disk, with runs or half prepared, stays.

    Without the up-front refusal, the cleanup after a failed follow-up
    deletes runs it did not make, and a killed prepare's staging
    directory is silently written over.
    """
    monkeypatch.setattr(smoke, "_now", lambda: f"{_LATER}T01:00:00Z")
    _small_failed(out)
    path = out / seed
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")
    before = _snapshot(out)
    summary = _reserve_summary(source, tmp_path)

    with pytest.raises(smoke.PlanError, match="already exist") as refused:
        _add_reserve(summary, out)

    assert "holds no runs/" in str(refused.value)
    assert _snapshot(out) == before


def _nothing_uncommitted(paths: Sequence[str]) -> list[str]:
    del paths
    return []


def test_main_prepares_a_reserve_smoke(
    source: Path,
    out: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _small_failed(out)
    summary = _reserve_summary(source, tmp_path)
    monkeypatch.setattr(smoke, "uncommitted", _nothing_uncommitted)
    monkeypatch.setattr(smoke.db, "head_revision", lambda: "reserve-rev")
    monkeypatch.setattr(
        smoke,
        "prepare_reserve",
        functools.partial(
            smoke.prepare_reserve, config_dir=summary.parents[2] / "configs"
        ),
    )
    argv = ["--out-dir", str(out), "prepare", "--summary", str(summary)]

    code = smoke.main([*argv, "--reserve", "small"])

    assert code == smoke.EXIT_OK
    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("dev-gamma-rs-") and "from dev-gamma-" in line
    assert _plan(out).smokes[-1].candidate == "gamma"


def _line(text: Path, smoke_id: str) -> str:
    (found,) = [
        line
        for line in text.read_text(encoding="utf-8").splitlines()
        if smoke_id in line
    ]
    return found


def test_the_pinned_provider_is_shown_and_nothing_is_flagged(
    out: Path,
) -> None:
    anchor = _run(out, "qwen3-32b")
    anchor.invoke(_both(ok())(anchor))

    _, text = smoke.judge(out, _plan(out))

    line = _line(text, anchor.entry.smoke_id)
    assert line.endswith("; served DeepInfra")
    verdict = json.loads(
        (out / "verdicts" / f"{anchor.entry.smoke_id}.json").read_bytes()
    )
    assert (verdict["providers"], verdict["provider_changed"]) == (
        ["DeepInfra"],
        False,
    )
    assert (verdict["served_models"], verdict["model_changed"]) == ([], False)


@pytest.mark.parametrize(
    ("reply", "verdict", "shown"),
    [
        (ok(provider="Novita"), "pass", "Novita"),
        (
            ok(provider="Novita", reasoning_tokens=40, reasoning_present=True),
            "fail",
            "Novita",
        ),
        (ok(provider="x\nsmall: smoke passed by alpha"), "pass", "other"),
    ],
)
def test_another_provider_is_flagged_and_the_verdict_stands(
    out: Path, reply: Fields, verdict: str, shown: str
) -> None:
    """The owner's 2026-09-27 ruling: a flag, never another verdict."""
    alpha = _run(out, "alpha")
    alpha.invoke(_both(reply)(alpha))

    states, text = smoke.judge(out, _plan(out))

    state = next(s for s in states if s.smoke.candidate == "alpha")
    assert state.verdict == verdict
    assert _line(text, alpha.entry.smoke_id).endswith(
        f"; served {shown} PROVIDER CHANGED"
    )
    document = json.loads(
        (out / "verdicts" / f"{alpha.entry.smoke_id}.json").read_bytes()
    )
    assert document["providers"] == [reply["provider"]]
    assert document["provider_changed"] is True
    assert document["model_changed"] is False
    assert document["runs"][0]["provider_changed"] is True


def test_a_substituted_model_is_flagged_and_the_verdict_stands(
    out: Path,
) -> None:
    anchor = _run(out, "qwen3-32b")
    other = "qwen/qwen3-235b-a22b"
    anchor.invoke(_both(ok(response_model=other))(anchor))

    states, text = smoke.judge(out, _plan(out))

    assert (states[0].verdict, states[0].reasons) == ("pass", ())
    assert _line(text, anchor.entry.smoke_id).endswith(
        "; served DeepInfra MODEL CHANGED"
    )
    document = json.loads(
        (out / "verdicts" / f"{anchor.entry.smoke_id}.json").read_bytes()
    )
    assert (document["served_models"], document["model_changed"]) == (
        [other],
        True,
    )
    first = anchor.entry.items[0]
    assert document["runs"][0]["items"][first]["response_model"] == other


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


def _one_transient(run: SmokeRun) -> dict[str, Any]:
    first, second = run.entry.items
    return run.invoke([(first, ok()), (second, http(503))])


def _call_step_error(run: SmokeRun) -> dict[str, Any]:
    del run
    return {}


def _interrupted_after_one(run: SmokeRun) -> dict[str, Any]:
    run.invoke([(run.entry.items[0], ok())])
    raise KeyboardInterrupt


@pytest.mark.parametrize(
    ("first_command", "code", "reason"),
    [
        (
            (_one_transient, _call_step_error),
            smoke.EXIT_STOPPED,
            "transient_pending",
        ),
        ((_interrupted_after_one,), smoke.EXIT_INTERRUPTED, "not_sent"),
    ],
)
def test_the_next_command_resumes_a_run_left_pending(
    out: Path,
    slept: list[float],
    first_command: tuple[Callable[[SmokeRun], dict[str, Any]], ...],
    code: int,
    reason: str,
) -> None:
    """A later execution resumes the same run, preflight and paid alike.

    An item the interrupted command never sent owes a resume too, never
    a re-run under a new run id.
    """
    anchor = _smoke(out, "qwen3-32b")
    assert smoke.locked_run(_ctx(out, FakeCalls(out, list(first_command)))) == (
        code
    )
    left = smoke.smoke_state(out, anchor)
    assert (left.verdict, left.reasons) == (
        "resume_owed",
        (f"{anchor.items[1]}:{reason}",),
    )
    calls = FakeCalls(out, [_good, _good])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_OK

    assert [argv for argv, key in calls.calls if not key] == calls.paid()
    resumed, started = calls.paid()
    assert resumed[resumed.index("--run-id") + 1] == anchor.smoke_id
    assert "--resume" in resumed
    assert "--resume" not in started
    assert smoke.existing_runs(out, anchor) == [anchor.smoke_id]
    assert smoke.smoke_state(out, anchor).verdict == "pass"
    del slept


def test_an_account_refusal_aborts_and_the_next_command_re_runs(
    out: Path, slept: list[float]
) -> None:
    def refused(run: SmokeRun) -> dict[str, Any]:
        return run.invoke([(run.entry.items[0], http(402))], "fatal_http")

    first = _ctx(out, FakeCalls(out, [refused]))
    assert smoke.locked_run(first) == smoke.EXIT_ABORTED
    assert _printed(first, "ABORTED").endswith("this smoke is owed a re-run")
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


def test_an_account_refusal_after_a_model_failure_promises_no_re_run(
    out: Path, slept: list[float]
) -> None:
    """Reading 2: the model failure is final, so the abort owes nothing."""

    def length_then_refused(run: SmokeRun) -> dict[str, Any]:
        first, second = run.entry.items
        return run.invoke(
            [(first, ok(finish_reason="length")), (second, http(402))],
            "fatal_http",
        )

    anchor = _smoke(out, "qwen3-32b")
    ctx = _ctx(out, FakeCalls(out, [length_then_refused]))

    assert smoke.locked_run(ctx) == smoke.EXIT_ABORTED

    aborted = _printed(ctx, "ABORTED")
    assert "the account refused a request" in aborted
    assert f"already failed on {anchor.items[0]}:finish_reason_length" in (
        aborted
    )
    assert not any("owed a re-run" in line for line in ctx.printed)
    calls = FakeCalls(out, [_good])

    assert smoke.locked_run(_ctx(out, calls)) == smoke.EXIT_OK

    assert [argv[argv.index("--run-id") + 1] for argv in calls.paid()] == [
        _smoke(out, "alpha").smoke_id
    ]
    assert smoke.existing_runs(out, anchor) == [anchor.smoke_id]
    assert smoke.smoke_state(out, anchor).verdict == "fail"
    del slept


def test_an_account_refusal_on_an_unreadable_run_points_at_the_summary(
    out: Path, slept: list[float]
) -> None:
    def refused_then_torn(run: SmokeRun) -> dict[str, Any]:
        report = run.invoke([(run.entry.items[0], http(402))], "fatal_http")
        with (run.run_dir / "attempts" / "C4.jsonl").open("ab") as log:
            log.write(b'{"attempt":')
        return report

    ctx = _ctx(out, FakeCalls(out, [refused_then_torn]))

    assert smoke.locked_run(ctx) == smoke.EXIT_ABORTED

    aborted = _printed(ctx, "ABORTED")
    assert aborted.endswith("the summary below gives this smoke's state")
    assert not any("owed a re-run" in line for line in ctx.printed)
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


def _renamed_smoke(out: Path, candidate: str, smoke_id: str) -> Any:
    """Moves one prepared smoke, prompt set and plan entry, to another id."""
    entry = _smoke(out, candidate)
    (out / entry.smoke_id).rename(out / smoke_id)
    moved = entry.model_copy(update={"smoke_id": smoke_id})
    plan = _plan(out)
    smokes = tuple(moved if s == entry else s for s in plan.smokes)
    (out / "plan.json").write_bytes(
        _bytes(plan.model_copy(update={"smokes": smokes}))
    )
    return moved


@pytest.mark.parametrize(
    ("smoke_id", "refused_runs"),
    [
        # nemotron's -fb pass gets a smoke id, but its -rs2 has a
        # 33-character middle, one more than a result name allows.
        ("dev-nemotron-3-super-120b-a12b-fb-rs-2026-09-27", 1),
        ("dev-alpha-fb-rs-2026-09-27", smoke.MAX_RUNS_PER_SMOKE),
    ],
)
def test_a_re_run_with_no_usable_run_id_stops_the_batch(
    out: Path, slept: list[float], smoke_id: str, refused_runs: int
) -> None:
    """A re-run owed past the last usable id stops before any call."""
    entry = _renamed_smoke(out, "alpha", smoke_id)
    for run_id in list(smoke.run_ids(smoke_id))[:refused_runs]:
        _refused(SmokeRun(out, entry, run_id))
    assert smoke.smoke_state(out, entry).verdict == "rerun_owed"
    calls = FakeCalls(out, [])
    ctx = _ctx(out, calls)

    assert smoke.locked_run(ctx) == smoke.EXIT_STOPPED

    assert not calls.calls
    assert _printed(ctx, "STOPPED") == (
        f"STOPPED: {smoke_id}: no usable re-run id is left"
    )
    del slept


def test_an_unusable_key_is_blamed_on_the_key_not_the_endpoint(
    out: Path, slept: list[float]
) -> None:
    def unusable_key(argv: Sequence[str], with_key: bool) -> Any:
        del argv
        return db.Invocation(
            2, None, "endpoint_invalid" if with_key else "api_key_missing"
        )

    ctx = _ctx(out, FakeCalls(out, []))
    ctx.invoke = unusable_key

    assert smoke.locked_run(ctx) == smoke.EXIT_STOPPED
    stopped = _printed(ctx, "STOPPED")
    assert API_KEY_ENV in stopped
    assert "control character" in stopped
    assert "nothing was sent" in stopped
    assert not any("fixture-key" in line for line in ctx.printed)
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


def test_an_unexpected_error_after_a_paid_call_stops_and_still_judges(
    out: Path, slept: list[float]
) -> None:
    def full_disk(run: SmokeRun) -> dict[str, Any]:
        _good(run)
        raise OSError(28, "No space left on device")

    calls = FakeCalls(out, [full_disk])
    ctx = _ctx(out, calls)

    assert smoke.locked_run(ctx) == smoke.EXIT_STOPPED
    stopped = _printed(ctx, "STOPPED")
    assert "OSError" in stopped
    assert "requests may have been sent" in stopped
    assert not any("refused" in line.lower() for line in ctx.printed)
    anchor = _smoke(out, "qwen3-32b")
    assert (out / "verdicts" / f"{anchor.smoke_id}.json").is_file()
    assert not (out / smoke.LOCK_NAME).exists()
    assert len(calls.paid()) == 1
    del slept


def test_an_interrupted_judging_after_the_batch_exits_130(
    out: Path, slept: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(out_dir: Path, plan: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(smoke, "judge", interrupted)
    ctx = _ctx(out, FakeCalls(out, [_good, _good]))

    assert smoke.locked_run(ctx) == smoke.EXIT_INTERRUPTED
    assert "run the judge subcommand" in _interrupted(ctx)
    assert ctx.printed[-1] == f"exit {smoke.EXIT_INTERRUPTED}"
    assert not (out / smoke.LOCK_NAME).exists()
    del slept


def test_a_changed_config_is_refused_before_anything(out: Path) -> None:
    plan = _plan(out)
    entry = plan.smokes[0]
    edited = entry.model_copy(update={"config_sha256": "0" * 64})
    ctx = _ctx(out, FakeCalls(out, []))
    ctx.plan = plan.model_copy(update={"smokes": (edited, *plan.smokes[1:])})

    with pytest.raises(smoke.PlanError, match="config file changed"):
        smoke.check_inputs(ctx)


def test_a_re_prepared_prompt_set_is_refused_before_anything(
    out: Path,
) -> None:
    """A prompt set prepared again under an unchanged plan is not the plan's.

    It records the same code, so only the plan's digest of prepare.json
    can object.
    """
    entry = _smoke(out, "alpha")
    path = out / entry.smoke_id / "prepare.json"
    prepare = PrepareManifestV1.model_validate_json(path.read_bytes())
    later = prepare.created_at + timedelta(days=1)
    path.write_bytes(_bytes(prepare.model_copy(update={"created_at": later})))

    with pytest.raises(smoke.PlanError, match="prepare.json is not the plan's"):
        smoke.check_inputs(_ctx(out, FakeCalls(out, [])))


def _stale_code(out: Path, candidate: str) -> Any:
    """Makes one smoke's prompt set record other model-side code.

    Its prepare.json records another generation.py digest, as if that file
    had been committed since, and plan.json pins the edited file, so only
    the code check can object.
    """
    entry = _smoke(out, candidate)
    path = out / entry.smoke_id / "prepare.json"
    prepare = json.loads(path.read_bytes())
    prepare["source_files"]["src/dfilterforge/generation.py"] = "0" * 64
    path.write_bytes(_bytes(prepare))
    edited = entry.model_copy(
        update={"prepare_sha256": _sha256(path.read_bytes())}
    )
    plan = _plan(out)
    smokes = tuple(
        edited if s.smoke_id == entry.smoke_id else s for s in plan.smokes
    )
    (out / "plan.json").write_bytes(
        _bytes(plan.model_copy(update={"smokes": smokes}))
    )
    return edited


def test_a_prompt_set_the_code_no_longer_matches_is_refused(out: Path) -> None:
    entry = _stale_code(out, "alpha")
    ctx = _ctx(out, FakeCalls(out, []))

    with pytest.raises(smoke.PlanError) as caught:
        smoke.check_inputs(ctx)

    message = str(caught.value)
    assert message.startswith(
        f"{entry.smoke_id}: src/dfilterforge/generation.py"
    )
    assert "prepare_code_mismatch" in message
    assert "no smoke request was sent" in message
    assert f"prepare --summary {ctx.plan.summary_path}" in message
    assert "git checkout" not in message


def test_a_stale_prompt_set_beside_runs_says_to_delete_nothing(
    out: Path,
) -> None:
    anchor = _run(out, "qwen3-32b")
    anchor.invoke([(anchor.entry.items[0], http(402))], "fatal_http")
    _stale_code(out, "alpha")

    with pytest.raises(smoke.PlanError) as caught:
        smoke.check_inputs(_ctx(out, FakeCalls(out, [])))

    message = str(caught.value)
    assert "delete nothing" in message
    assert "git checkout test-rev -- src/dfilterforge/generation.py" in message
    assert "remove" not in message
    assert anchor.run_dir.is_dir()


def test_a_smoke_with_a_verdict_no_longer_needs_its_code(out: Path) -> None:
    anchor = _run(out, "qwen3-32b")
    anchor.invoke(_both(ok())(anchor))
    _stale_code(out, "qwen3-32b")

    smoke.check_inputs(_ctx(out, FakeCalls(out, [])))


def test_dry_run_refuses_a_prompt_set_the_code_no_longer_matches(
    out: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke.db, "head_revision", lambda: "test-rev")
    _stale_code(out, "alpha")

    code = smoke.main(["--out-dir", str(out), "run", "--dry-run"])

    printed = capsys.readouterr()
    assert code == smoke.EXIT_REFUSED
    assert "prepare_code_mismatch" in printed.err
    assert "scripts/model_run.py call" not in printed.out


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


def _rewrite_manifest(run: SmokeRun, **changes: Any) -> None:
    """Rewrites a valid run manifest with some fields changed."""
    path = run.run_dir / "run_manifest.json"
    manifest = RunManifestV1.model_validate_json(path.read_bytes())
    path.write_bytes(_bytes(manifest.model_copy(update=changes)))


def _another_run_s_manifest(run: SmokeRun) -> None:
    """A manifest naming the smoke's re-run, as if copied in from there."""
    run.invoke(_both(ok())(run))
    _rewrite_manifest(run, run_id=list(smoke.run_ids(run.entry.smoke_id))[1])


def _a_c3_run(run: SmokeRun) -> None:
    """A valid run whose one condition is C3, its paths following the label."""
    run.invoke(_both(ok())(run))
    (condition,) = RunManifestV1.model_validate_json(
        (run.run_dir / "run_manifest.json").read_bytes()
    ).conditions
    c3 = condition.model_copy(
        update={
            "label": "C3",
            "attempts_path": "attempts/C3.jsonl",
            "completions_path": "completions/C3.json",
        }
    )
    _rewrite_manifest(run, conditions=(c3,))


@pytest.mark.parametrize(
    ("write", "reason"),
    [
        (_no_manifest, "manifest_missing"),
        (_bad_manifest, "manifest_invalid"),
        (_another_run_s_manifest, "manifest_run_id"),
        (_a_c3_run, "not_a_c4_run"),
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
    stopped = _printed(ctx, "STOPPED")
    assert reason in stopped
    assert run.run_dir.resolve().as_posix() in stopped
    assert "will not change that" in stopped
    assert "delete nothing" in stopped
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
