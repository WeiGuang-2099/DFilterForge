"""The judge study runner, against a fake provider on 127.0.0.1.

Each split's answer set is two small scored passes written from the real
contracts into a private tree, with the module's pins, judge pass and
counts patched to it, and the two registered configs hold the judge note's
settings and prices; a call config sends one of them to the local fake.
The runner's waits are recorded instead of slept, so nothing here takes
long and nothing leaves the machine.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
from types import ModuleType
from typing import Any, NoReturn

import pytest

from dfilterforge import judge
from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import RetrievalV1
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import OutcomeV1

_ROOT = Path(__file__).resolve().parents[1]
_KEY = "fake-judge-key-for-a-local-server"
_NOWHERE = "http://127.0.0.1:9/v1/chat/completions"


def _settings(route: str) -> dict[str, Any]:
    """The note's settings for one route."""
    return {
        "model_id": "deepseek/deepseek-v4-pro-0813",
        "temperature": 0.0,
        "seed": 17,
        "max_output_tokens": 256,
        "timeout_seconds": 120.0,
        "json_mode": True,
        "openrouter": {
            "reasoning": "enabled_false",
            "provider_order": [route],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": "deny",
        },
    }


# Each route's prices per million input and output tokens, as the note's.
_PRICES = {"deepinfra": (1.3, 2.6), "gmicloud": (1.056, 3.168)}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "judge_study", _ROOT / "scripts" / "judge_study.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("judge_study cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


js = _load()


def _write_pass(results: Path, run: str, rows: list[tuple[Any, ...]]) -> str:
    """Writes one scored pass with its prompts; returns its outcome digest."""
    scored = results / run / "scored"
    scored.mkdir(parents=True)
    lines: list[str] = []
    for label, item, outcome, ran, reference in rows:
        row = ItemOutcomeV1(
            condition=label,
            item_id=item,
            case_id=f"case-{item}",
            outcome=OutcomeV1(outcome),
            candidate_filter=ran,
            gold_field_count=1,
            latency_ms=1.0,
        )
        lines.append(canonical_json(row) + "\n")
        receipt = scored / "receipts" / label / f"{item}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "run_id": run,
            "candidate_filter": ran,
            "reference_filter": reference,
        }
        receipt.write_text(json.dumps(document), encoding="utf-8")
    (scored / "outcomes.jsonl").write_text("".join(lines), encoding="utf-8")
    shown = [
        GenerationInputV1(item_id=item, intent=f"Show {item}.", split="x")
        for item in sorted({row[1] for row in rows})
    ]
    for label, contract in (
        ("C1", OutputContractV1.DISPLAY_FILTER),
        ("C2", OutputContractV1.DISPLAY_FILTER),
        ("C3", OutputContractV1.TYPED_IR),
        ("C4", OutputContractV1.TYPED_IR),
    ):
        batch = prepare_batch(
            shown, output_contract=contract, retrieval=RetrievalV1.NONE
        )
        path = results / run / "prepared" / f"{label}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(batch) + "\n", encoding="utf-8")
    return file_sha256(scored / "outcomes.jsonl")


@pytest.fixture(name="bench")
def fixture_bench(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[float]:
    """Each split's two passes and the registered config, under a new root.

    Returns the runner's waits, recorded instead of slept. Both passes
    wrote "tcp" for the first item, so a split has two pairs and four
    requests: each pair's primary request, then each secondary one.
    """
    results = tmp_path / "docs" / "results"
    for split, first in (("dev", 1), ("test", 1001)):
        items = [f"mei-{first:04d}", f"mei-{first + 1:04d}"]
        other, own = f"{split}-alpha-2026-09-26", f"{split}-judge-2026-09-26"
        pins = {
            other: _write_pass(
                results,
                other,
                [
                    ("C1", items[0], "strong_exact", "tcp", "tcp"),
                    ("C2", items[1], "silent_wrong", "udp", "udp && dns"),
                ],
            ),
            own: _write_pass(
                results, own, [("C1", items[0], "strong_exact", "tcp", "tcp")]
            ),
        }
        monkeypatch.setitem(judge.ANSWER_SETS, split, pins)
        monkeypatch.setitem(judge.SELF_RUNS, split, own)
        monkeypatch.setitem(judge.REGISTERED_COUNTS, split, (3, 2))
    configs = tmp_path / js.CONFIGS
    configs.mkdir(parents=True)
    for route in _PRICES:
        _write_config(
            configs / f"deepseek-v4-pro-0813_{route}_judge.json",
            "https://openrouter.ai/api/v1/chat/completions",
            route,
        )
    waits: list[float] = []
    monkeypatch.setattr(js, "ROOT", tmp_path)
    monkeypatch.setattr(js, "_sleep", waits.append)
    return waits


def _prices(route: str) -> dict[str, Any]:
    usd_in, usd_out = _PRICES[route]
    return {
        "usd_per_million_input": usd_in,
        "usd_per_million_output": usd_out,
        "source": "fixture prices",
    }


def _write_config(path: Path, url: str, route: str = "deepinfra") -> None:
    document = {
        "endpoint_url": url,
        "settings": _settings(route),
        "prices": _prices(route),
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _write_run(path: Path, split: str, route: str, failed: int) -> None:
    """Writes the manifest of a complete four-request run with failures."""
    run = js.JudgeRunV1.model_validate(
        {
            "prompt_version": judge.PROMPT_VERSION,
            "split": split,
            "route": route,
            "endpoint_host": "openrouter.ai",
            "settings": _settings(route),
            "prices": _prices(route),
            "max_attempts": js.MAX_ATTEMPTS,
            "min_interval_seconds": js.PACE_SECONDS,
            "sweep_wait_seconds": js.SWEEP_WAIT_SECONDS,
            "token_bound_rule": js.TOKEN_BOUND_RULE,
            "system_prompt_sha256": {},
            "request_set_sha256": "0" * 64,
            "requests": 4,
            "answer_set": {},
            "created_at": "2026-10-20T00:00:00Z",
            "invocations": [],
            "status": "complete",
            "completed": 4 - failed,
            "failed": failed,
            "pending": 0,
            "attempts_sha256": "0" * 64,
            "charged_usd_upper_bound": 0.0,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(run) + "\n", encoding="utf-8")


def _body(content: str) -> bytes:
    """A completed OpenRouter reply that reports no thinking."""
    return json.dumps(
        {
            "id": "gen-1",
            "model": "deepseek/deepseek-v4-pro-0813",
            "provider": "DeepInfra",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 300,
                "completion_tokens": 30,
                "completion_tokens_details": {"reasoning_tokens": 0},
                "cost": 0.0005,
            },
        }
    ).encode("utf-8")


def _says(verdict: str) -> tuple[int, bytes]:
    reply = {"verdict": verdict, "reason": "It selects those packets."}
    return 200, _body(json.dumps(reply))


_LIMITED = (429, b'{"error":{"code":429}}')
_REFUSED = (401, b'{"error":{"code":401}}')
# The connection closes before any reply: a transport error.
_DROPPED = (0, b"")


@contextmanager
def _provider(
    script: list[tuple[int, bytes]],
) -> Generator[tuple[str, list[dict[str, Any]]], None, None]:
    """Serves the scripted replies in order, then correct verdicts."""
    received: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            length = int(self.headers.get("Content-Length") or 0)
            received.append(json.loads(self.rfile.read(length)))
            status, body = script.pop(0) if script else _says("correct")
            if not status:
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}/v1/chat/completions", received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _no_socket(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise AssertionError("a socket was opened")


def _attempts(run_dir: Path) -> dict[str, list[int]]:
    """Each request's attempts, as the HTTP status of each reply, 0 for none."""
    sent: dict[str, list[int]] = {}
    for line in (run_dir / js.ATTEMPTS).read_text("utf-8").splitlines():
        completion = json.loads(line)["completion"]
        sent.setdefault(completion["item_id"], []).append(
            completion["http_status"] or 0
        )
    return sent


def test_the_runner_sends_resumes_publishes_and_tabulates(
    bench: list[float],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One run through every step, against scripted replies.

    The keyless call refuses before any socket. The first call meets 429,
    a reply that parses to no verdict and 401, which stops it. A fresh
    call is refused. The first resume meets three dropped connections in a
    row and ends with their requests pending; the second sends only the
    owed requests, the least tried first and one of them again after a
    sweep wait, and completes. The dev check is published, the test study
    follows on its route, and the table is written and checked.
    """
    config = tmp_path / "call.json"
    run_dir = tmp_path / "artifacts" / "judge-v2" / "dev-deepinfra"
    script = [_LIMITED, (200, _body("no verdict here")), _REFUSED]
    with _provider(script) as (url, received):
        _write_config(config, url)
        dev = ["--split", "dev", "--config", str(config), "--max-usd", "0.40"]
        monkeypatch.delenv(API_KEY_ENV, raising=False)
        with monkeypatch.context() as patch:
            patch.setattr(socket, "create_connection", _no_socket)
            assert js.main(["call", *dev]) == 2
        assert '"api_key_missing"' in capsys.readouterr().err
        assert not received and not run_dir.exists()
        monkeypatch.setenv(API_KEY_ENV, _KEY)

        assert js.main(["call", *dev]) == 3
        assert (
            json.loads(capsys.readouterr().out)["stop_reason"] == "fatal_http"
        )
        assert js.main(["call", *dev]) == 2
        assert '"run_exists"' in capsys.readouterr().err
        script += [_DROPPED] * js.FAULT_LIMIT
        assert js.main(["call", *dev, "--resume"]) == 1
        ended = json.loads(capsys.readouterr().out)
        assert (ended["stop_reason"], ended["pending"]) == ("unreachable", 3)
        # The secondary request of the second pair, tried once, goes first.
        script += [_LIMITED, _says("correct"), _says("correct")]
        script += [_says("incorrect")]
        assert js.main(["call", *dev, "--resume"]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "complete"
        assert len(received) == 10 and bench.count(js.SWEEP_WAIT_SECONDS) == 1
        first = received[0]
        assert (
            first["messages"][0]["content"] == judge.SYSTEM_PROMPTS["primary"]
        )
        assert (first["max_tokens"], first["provider"]["data_collection"]) == (
            256,
            "deny",
        )
        assert (
            js.main(["publish", "--split", "dev", "--route", "deepinfra"]) == 0
        )
        assert json.loads(capsys.readouterr().out)["ratings"] == {
            "primary": {"correct": 1, "none": 1},
            "secondary": {"correct": 1, "incorrect": 1},
        }
        test = ["--split", "test", "--config", str(config), "--max-usd", "1.50"]
        assert js.main(["call", *test]) == 0
        assert (
            js.main(["publish", "--split", "test", "--route", "deepinfra"]) == 0
        )

    assert sorted(_attempts(run_dir).values()) == [
        [0, 429, 200],
        [200],
        [401, 0, 200],
        [429, 0, 200],
    ]
    manifest = json.loads((run_dir / js.MANIFEST).read_text("utf-8"))
    assert [i["stop_reason"] for i in manifest["invocations"]] == [
        "fatal_http",
        "unreachable",
        None,
    ]
    assert (manifest["status"], manifest["completed"]) == ("complete", 4)
    assert manifest["endpoint_host"] == "127.0.0.1"
    published = tmp_path / "docs" / "results" / "judge-v2"
    for name in (js.ATTEMPTS, js.MANIFEST):
        data = (published / "dev" / name).read_bytes()
        assert data == (run_dir / name).read_bytes()
        assert _KEY.encode() not in data and b"/chat/completions" not in data
    assert js.main(["table"]) == 0
    table = json.loads((published / "table.json").read_text("utf-8"))
    assert table["modes"]["primary"]["headline"] == {
        "silent_wrong": 1,
        "silent_wrong_rated_correct": 1,
        "self_silent_wrong": 0,
        "self_silent_wrong_rated_correct": 0,
    }
    assert js.main(["table", "--check"]) == 0
    (published / "table.json").write_text("{}\n", encoding="utf-8")
    assert js.main(["table", "--check"]) == 1


@pytest.mark.usefixtures("bench")
def test_the_dry_run_prints_the_plan_and_writes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No key, no socket, no file; a cap above the note's is refused."""
    config = tmp_path / "call.json"
    _write_config(config, _NOWHERE)
    before = sorted(path for path in tmp_path.rglob("*"))
    dry = ["dry-run", "--split", "dev", "--config", str(config)]
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setattr(socket, "create_connection", _no_socket)

    assert js.main([*dry, "--max-usd", "0.40"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["answers"], report["requests"]) == (3, 4)
    assert report["outcomes"] == {"strong_exact": 2, "silent_wrong": 1}
    assert report["of_them_silent_wrong"] == 1
    assert report["route"] == "deepinfra" and not report["run_dir_exists"]
    assert 0 < report["expected_usd"] < report["worst_sweep_usd"]
    assert js.main([*dry, "--max-usd", "0.41"]) == 2
    assert '"cap_invalid"' in capsys.readouterr().err
    assert sorted(path for path in tmp_path.rglob("*")) == before


# Each case: the call's route; the runs already in the tree, by where each
# sits, with the route it ran on and its failed requests of four (a run
# under artifacts/ is only its directory); and the refusal a keyless test
# call meets. api_key_missing is the last check, so meeting it means J2
# leaves that route standing.
_TREES = {
    "dev": ("docs", "results", "judge-v2", "dev"),
    "moved": ("docs", "decisions", "evidence", "judge", "dev-deepinfra"),
    "test": ("docs", "results", "judge-v2", "test"),
    "run": ("artifacts", "judge-v2", "test-deepinfra"),
}


@pytest.mark.usefixtures("bench")
@pytest.mark.parametrize(
    ("route", "runs", "code"),
    [
        pytest.param("deepinfra", {}, "route_not_standing", id="no-dev-check"),
        pytest.param(
            "deepinfra",
            {"dev": ("deepinfra", 1)},
            "route_not_standing",
            id="j2-moves-the-study-off-deepinfra",
        ),
        pytest.param(
            "deepinfra",
            {"dev": ("deepinfra", 0)},
            "api_key_missing",
            id="deepinfra-stands",
        ),
        pytest.param(
            "gmicloud",
            {"dev": ("gmicloud", 0)},
            "route_not_standing",
            id="gmicloud-before-a-failed-deepinfra-check",
        ),
        pytest.param(
            "gmicloud",
            {"dev": ("gmicloud", 4), "moved": ("deepinfra", 1)},
            "route_not_standing",
            id="j3-no-reply-on-gmicloud",
        ),
        pytest.param(
            "gmicloud",
            {"dev": ("gmicloud", 1), "moved": ("deepinfra", 1)},
            "api_key_missing",
            id="gmicloud-stands",
        ),
        pytest.param(
            "gmicloud",
            {
                "dev": ("gmicloud", 0),
                "moved": ("deepinfra", 1),
                "run": ("deepinfra", 0),
            },
            "route_fixed",
            id="a-test-run-on-deepinfra",
        ),
        pytest.param(
            "gmicloud",
            {
                "dev": ("gmicloud", 0),
                "moved": ("deepinfra", 1),
                "test": ("deepinfra", 0),
            },
            "route_fixed",
            id="a-published-test-run-on-deepinfra",
        ),
    ],
)
def test_a_test_call_goes_only_to_the_route_j2_leaves_standing(
    route: str,
    runs: dict[str, tuple[str, int]],
    code: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """DeepInfra stands while its dev check left no request unanswered.

    GMICloud stands once that check, moved to the evidence, left one, and
    its own dev check answered some request; a test run fixes its route.
    """
    for where, (ran_on, failed) in runs.items():
        place = tmp_path.joinpath(*_TREES[where])
        if where == "run":
            place.mkdir(parents=True)
        else:
            split = "test" if where == "test" else "dev"
            _write_run(place / js.MANIFEST, split, ran_on, failed)
    config = tmp_path / "call.json"
    _write_config(config, _NOWHERE, route)
    test = ["--split", "test", "--config", str(config), "--max-usd", "1.50"]
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.setattr(socket, "create_connection", _no_socket)

    assert js.main(["call", *test]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == code


def _thinks() -> tuple[int, bytes]:
    """A completed reply whose usage reports thinking tokens."""
    body = json.loads(_says("correct")[1])
    body["usage"]["completion_tokens_details"]["reasoning_tokens"] = 12
    return 200, json.dumps(body).encode("utf-8")


@pytest.mark.usefixtures("bench")
def test_a_gate_stop_on_the_last_owed_reply_leaves_the_run_unpublished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A thinking reply ends the run even when it settles the last request."""
    config = tmp_path / "call.json"
    script = [_says("correct")] * 3 + [_REFUSED, _thinks()]
    with _provider(script) as (url, _):
        _write_config(config, url)
        dev = ["--split", "dev", "--config", str(config), "--max-usd", "0.40"]
        monkeypatch.setenv(API_KEY_ENV, _KEY)
        assert js.main(["call", *dev]) == 3
        assert js.main(["call", *dev, "--resume"]) == 3
    ended = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert (ended["stop_reason"], ended["pending"], ended["status"]) == (
        "thinking_not_honoured",
        0,
        "incomplete",
    )
    assert js.main(["publish", "--split", "dev", "--route", "deepinfra"]) == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == (
        "run_incomplete"
    )


@pytest.mark.usefixtures("bench")
def test_a_failed_write_keeps_the_run_for_a_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An attempt log that cannot be written leaves the run pending."""
    config = tmp_path / "call.json"
    appended: list[int] = []
    append = js._append_attempt  # pylint: disable=protected-access

    def fails_second(handle: Any, attempt: Any) -> None:
        appended.append(1)
        if len(appended) == 2:
            raise OSError("the disk is full")
        append(handle, attempt)

    with _provider([]) as (url, _):
        _write_config(config, url)
        dev = ["--split", "dev", "--config", str(config), "--max-usd", "0.40"]
        monkeypatch.setenv(API_KEY_ENV, _KEY)
        with monkeypatch.context() as patch:
            patch.setattr(js, "_append_attempt", fails_second)
            assert js.main(["call", *dev]) == 1
        ended = json.loads(capsys.readouterr().out)
        assert (ended["stop_reason"], ended["pending"]) == ("io_error", 3)
        assert js.main(["call", *dev, "--resume"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "complete"
