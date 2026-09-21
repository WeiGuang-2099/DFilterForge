"""Tests for the bounded OpenAI-compatible backend against a local fake."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import importlib.util
import json
import logging
from pathlib import Path
import sys
import threading
import time
from typing import Any, cast, Protocol

import pytest

from dfilterforge import model_client
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import OpenRouterOptionsV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.model_client import ModelClientError
from dfilterforge.model_client import OpenAiCompatibleBackend

_API_KEY = "sk-test-SECRET-9f2c"
_PROVIDER_TEXT = "PROVIDER-PROSE"
_CONTENT = (
    '{"schema_version":"direct-filter/1.0","status":"ready",'
    '"display_filter":"tcp"}'
)
_OK_BODY = json.dumps(
    {
        "id": "chatcmpl-1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _CONTENT},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
).encode("utf-8")
_HUGE_BODY = json.dumps(
    {"choices": [{"message": {"content": "x" * MAX_RESPONSE_BYTES}}]}
).encode("utf-8")
_PADDED_ERROR = b'{"error":{"code":503},"pad":"' + b"x" * 16_000 + b'"}'

Responder = Callable[[BaseHTTPRequestHandler], None]


class _DocumentedReply(Protocol):
    """The replay corpus entry this test compares records against."""

    name: str
    expected: tuple[str, int | None, str | None]


class _ReplyReplay(Protocol):
    """The part of the replay script this test drives."""

    REPLIES: tuple[_DocumentedReply, ...]

    def replay(self, settings_module: str) -> list[dict[str, Any]]:
        """Runs every documented reply and returns the recorded rows."""
        ...


@dataclass(frozen=True)
class _Received:
    path: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class _Provider:
    url: str
    received: list[_Received]


@contextmanager
def _provider(respond: Responder) -> Generator[_Provider, None, None]:
    received: list[_Received] = []

    class Handler(BaseHTTPRequestHandler):

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            length = int(self.headers.get("Content-Length") or 0)
            received.append(
                _Received(
                    self.path,
                    dict(self.headers.items()),
                    self.rfile.read(length),
                )
            )
            respond(self)

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield _Provider(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            received,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _reply(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    chunked: bool = False,
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    if chunked:
        handler.send_header("Transfer-Encoding", "chunked")
        handler.end_headers()
        handler.wfile.write(f"{len(body):x}\r\n".encode("ascii"))
        handler.wfile.write(body + b"\r\n0\r\n\r\n")
    else:
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    handler.wfile.flush()


def _ok(handler: BaseHTTPRequestHandler) -> None:
    _reply(handler, 200, _OK_BODY)


def _status(
    status: int,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    chunked: bool = False,
) -> Responder:
    """Returns a responder that always answers with one fixed reply."""

    def respond(handler: BaseHTTPRequestHandler) -> None:
        _reply(handler, status, body, headers=headers, chunked=chunked)

    return respond


def _json(status: int, value: object, **kwargs: Any) -> Responder:
    """Returns a responder that serves one JSON document."""
    return _status(status, json.dumps(value).encode("utf-8"), **kwargs)


def _envelope(
    message: dict[str, object],
    *,
    finish_reason: str | None = "stop",
    native_finish_reason: str | None = "stop_native",
    usage: dict[str, object] | None = None,
    **top_level: object,
) -> dict[str, object]:
    """Returns the documented OpenRouter chat.completion reply body.

    The native finish reason defaults to a value the normalized one never
    takes, so a record that read the wrong key would be visible.
    """
    return {
        "id": "gen-1726000000-abc",
        "model": "qwen/qwen3-8b-04-28",
        "provider": "Alibaba",
        "system_fingerprint": None,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", **message},
                "finish_reason": finish_reason,
                "native_finish_reason": native_finish_reason,
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 240,
            "completion_tokens": 21,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "cost": 0.0000376,
            "is_byok": False,
        },
        **top_level,
    }


def _error(code: object, **extra: object) -> dict[str, object]:
    """Returns a provider error body carrying prose beside its code."""
    return {"error": {"code": code, "message": _PROVIDER_TEXT, **extra}}


def _error_in_choice() -> dict[str, object]:
    """Returns a 200 body whose only choice reports a provider failure."""
    body = _envelope({"content": _PROVIDER_TEXT}, finish_reason="error")
    choices = cast(list[dict[str, object]], body["choices"])
    choices[0] |= _error(502)
    return body


def _slow(handler: BaseHTTPRequestHandler) -> None:
    time.sleep(1.5)
    try:
        _reply(handler, 200, _OK_BODY)
    except OSError:
        pass


def _redirect(handler: BaseHTTPRequestHandler) -> None:
    host = handler.headers.get("Host") or "127.0.0.1"
    _reply(
        handler,
        302,
        b"",
        headers={"Location": f"http://{host}/elsewhere/chat/completions"},
    )


def _hang_up(handler: BaseHTTPRequestHandler) -> None:
    handler.close_connection = True


def _stall_after_headers(handler: BaseHTTPRequestHandler) -> None:
    """Sends a status line and headers, then stops short of the body."""
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(_OK_BODY)))
    handler.end_headers()
    try:
        handler.wfile.write(_OK_BODY[:1])
        handler.wfile.flush()
        time.sleep(1.5)
    except OSError:
        pass


def _load_reply_replay() -> _ReplyReplay:
    """Imports the replay script by path, as the evidence run does."""
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "provider_reply_replay.py"
    )
    spec = importlib.util.spec_from_file_location(
        "provider_reply_replay", script
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return cast(_ReplyReplay, module)


def _backend(
    url: str,
    *,
    api_key: str | None = _API_KEY,
    settings: RequestSettingsV1 | None = None,
) -> OpenAiCompatibleBackend:
    settings = settings or RequestSettingsV1(model_id="test-model")
    return OpenAiCompatibleBackend(url, settings, api_key=api_key)


def _prepared() -> PreparedBatchV1:
    return prepare_batch(
        (GenerationInputV1(item_id="item-1", intent="Show TCP packets"),),
        output_contract=OutputContractV1.DISPLAY_FILTER,
        retrieval=RetrievalV1.NONE,
    )


def test_successful_completion_is_bounded_and_carries_the_bearer_key() -> None:
    batch = _prepared()

    with _provider(_ok) as provider:
        result = _backend(provider.url).complete(batch)

    assert result.output_contract is batch.output_contract
    assert result.retrieval is batch.retrieval
    assert result.settings == RequestSettingsV1(model_id="test-model")
    (completion,) = result.completions
    assert completion.item_id == "item-1"
    assert completion.status is CompletionStatusV1.COMPLETED
    assert completion.response_text == _CONTENT
    assert completion.error_code is None
    assert completion.http_status == 200
    assert completion.finish_reason == "stop"
    assert completion.native_finish_reason is None
    assert completion.response_id == "chatcmpl-1"
    assert completion.prompt_tokens == 12
    assert completion.completion_tokens == 3
    assert completion.reasoning_tokens is None
    assert completion.reasoning_present is False
    assert completion.cost_usd is None
    assert completion.latency_ms >= 0
    assert parse_response(
        result.output_contract, _CONTENT
    ) == DirectFilterResultV1(
        status=GenerationStatus.READY, display_filter="tcp"
    )
    assert CompletionBatchV1.model_validate_json(result.model_dump_json()) == (
        result
    )

    (request,) = provider.received
    assert request.path == "/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {_API_KEY}"
    assert request.headers["Content-Type"].startswith("application/json")
    assert request.headers["User-Agent"] == "dfilterforge-model-client"
    prompt = batch.prompts[0]
    assert json.loads(request.body) == {
        "model": "test-model",
        "messages": [
            {"role": message.role, "content": message.content}
            for message in prompt.messages
        ],
        "temperature": 0.0,
        "max_tokens": 2048,
        "seed": 17,
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize(
    ("settings", "extra_keys"),
    [
        (RequestSettingsV1(model_id="m", seed=None, json_mode=False), {}),
        (
            RequestSettingsV1(
                model_id="qwen/qwen3-8b",
                openrouter=OpenRouterOptionsV1(provider_order=("alibaba",)),
            ),
            {
                "seed": 17,
                "response_format": {"type": "json_object"},
                "reasoning": {"enabled": False},
                "provider": {
                    "order": ["alibaba"],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                },
            },
        ),
        (
            RequestSettingsV1(
                model_id="m",
                seed=None,
                json_mode=False,
                openrouter=OpenRouterOptionsV1(
                    reasoning="effort_none",
                    allow_fallbacks=True,
                    data_collection="deny",
                ),
            ),
            {
                "reasoning": {"effort": "none"},
                "provider": {
                    "allow_fallbacks": True,
                    "require_parameters": True,
                    "data_collection": "deny",
                },
            },
        ),
        (
            RequestSettingsV1(
                model_id="m",
                seed=None,
                json_mode=False,
                openrouter=OpenRouterOptionsV1(reasoning=None),
            ),
            {
                "provider": {
                    "allow_fallbacks": False,
                    "require_parameters": True,
                },
            },
        ),
    ],
)
def test_request_controls_are_opt_in_and_recorded(
    settings: RequestSettingsV1, extra_keys: dict[str, object]
) -> None:
    with _provider(_ok) as provider:
        result = _backend(provider.url, settings=settings).complete(_prepared())

    (request,) = provider.received
    body = json.loads(request.body)
    del body["messages"]
    assert body == {
        "model": settings.model_id,
        "temperature": 0.0,
        "max_tokens": 2048,
        **extra_keys,
    }
    assert result.settings == settings


def test_environment_credential_is_used_only_when_no_key_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with _provider(_ok) as provider:
        _backend(provider.url, api_key=None).complete(_prepared())
        assert "Authorization" not in provider.received[0].headers

    monkeypatch.setenv(API_KEY_ENV, "sk-from-env")
    with _provider(_ok) as provider:
        _backend(provider.url, api_key=None).complete(_prepared())
        assert provider.received[0].headers["Authorization"] == (
            "Bearer sk-from-env"
        )


def test_documented_provider_replies_are_recorded_as_expected() -> None:
    replay = _load_reply_replay()

    rows = replay.replay("dfilterforge.completions")

    assert len(replay.REPLIES) == 14
    for reply, row in zip(replay.REPLIES, rows, strict=True):
        assert row["reply"] == reply.name
        assert (
            row["recorded_as"],
            row["http_status"],
            row["provider_error_code"],
        ) == reply.expected
        assert row["provider_text_recorded"] is False


@pytest.mark.parametrize(
    ("respond", "code", "http_status", "provider_code"),
    [
        (_json(500, _error("two words")), "http_error", 500, None),
        (_json(401, _error(_API_KEY)), "http_error", 401, None),
        (
            _status(500, _PROVIDER_TEXT.encode("utf-8")),
            "http_error",
            500,
            None,
        ),
        (_status(503, _PADDED_ERROR), "http_error", 503, None),
        (_json(200, _error_in_choice()), "provider_error", 200, "502"),
        (_json(200, _envelope({"content": ""})), "empty_content", 200, None),
        (
            _json(
                200,
                _envelope(
                    {"content": None},
                    finish_reason=_API_KEY,
                    native_finish_reason=_API_KEY,
                ),
            ),
            "empty_content",
            200,
            None,
        ),
        (_status(200, b"{not json"), "response_invalid", 200, None),
        (_status(200, b"\xff\xfe"), "response_invalid", 200, None),
        (_status(200, b'{"choices":[]}'), "response_invalid", 200, None),
        (_status(200, b'{"choices":[{}]}'), "response_invalid", 200, None),
        (
            _status(200, b'{"choices":[{"message":{"content":42}}]}'),
            "response_invalid",
            200,
            None,
        ),
        (
            _json(
                200,
                _envelope({"content": _CONTENT}, usage={"prompt_tokens": "12"}),
            ),
            "response_invalid",
            200,
            None,
        ),
        (
            _json(
                200,
                _envelope(
                    {"content": _CONTENT}, finish_reason=_PROVIDER_TEXT * 40
                ),
            ),
            "response_invalid",
            200,
            None,
        ),
        (
            _json(200, _envelope({"content": _CONTENT}, model="m" * 257)),
            "response_invalid",
            200,
            None,
        ),
        (
            _json(
                200,
                _envelope({"content": _CONTENT}, provider=_PROVIDER_TEXT * 40),
            ),
            "response_invalid",
            200,
            None,
        ),
        (
            _json(200, _envelope({"content": _CONTENT}, usage={"cost": -1})),
            "response_invalid",
            200,
            None,
        ),
        (
            _json(
                200,
                _envelope(
                    {"content": None},
                    finish_reason="length",
                    id=_API_KEY,
                    model=_API_KEY,
                    provider=_API_KEY,
                    system_fingerprint=_API_KEY,
                ),
            ),
            "empty_content",
            200,
            None,
        ),
        (_status(200, _HUGE_BODY), "response_too_large", 200, None),
        (
            _status(200, _HUGE_BODY, chunked=True),
            "response_too_large",
            200,
            None,
        ),
        (
            _status(200, _OK_BODY, headers={"Content-Length": "many"}),
            "response_invalid",
            200,
            None,
        ),
        (_redirect, "redirect_rejected", 302, None),
        (_hang_up, "transport_error", None, None),
    ],
)
def test_failures_are_recorded_as_stable_codes_without_retries(
    respond: Responder,
    code: str,
    http_status: int | None,
    provider_code: str | None,
) -> None:
    with _provider(respond) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.FAILED
    assert completion.error_code == code
    assert completion.http_status == http_status
    assert completion.provider_error_code == provider_code
    assert completion.response_text is None
    assert [request.path for request in provider.received] == [
        "/v1/chat/completions"
    ]
    dumped = result.model_dump_json()
    assert _API_KEY not in dumped
    assert _PROVIDER_TEXT not in dumped


def test_openrouter_provenance_is_recorded_without_reasoning_text() -> None:
    respond = _json(
        200,
        _envelope(
            {"content": _CONTENT, "reasoning": f"{_PROVIDER_TEXT} I think"},
            system_fingerprint="fp_44709586",
            usage={
                "prompt_tokens": 240,
                "completion_tokens": 171,
                "completion_tokens_details": {"reasoning_tokens": 150},
                "cost": 0.000106,
            },
        ),
    )

    with _provider(respond) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.COMPLETED
    assert completion.response_text == _CONTENT
    assert completion.response_id == "gen-1726000000-abc"
    assert completion.response_model == "qwen/qwen3-8b-04-28"
    assert completion.provider == "Alibaba"
    assert completion.system_fingerprint == "fp_44709586"
    assert completion.finish_reason == "stop"
    assert completion.native_finish_reason == "stop_native"
    assert completion.reasoning_tokens == 150
    assert completion.reasoning_present is True
    assert completion.cost_usd == 0.000106
    assert _PROVIDER_TEXT not in result.model_dump_json()


def test_exhausted_output_budget_keeps_its_evidence() -> None:
    respond = _json(
        200,
        _envelope(
            {"content": None, "reasoning": _PROVIDER_TEXT * 50},
            finish_reason="length",
            native_finish_reason="length_native",
            usage={
                "prompt_tokens": 240,
                "completion_tokens": 2048,
                "completion_tokens_details": {"reasoning_tokens": 2048},
                "cost": 0.00096,
            },
        ),
    )

    with _provider(respond) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.FAILED
    assert completion.error_code == "empty_content"
    assert completion.http_status == 200
    assert completion.finish_reason == "length"
    assert completion.native_finish_reason == "length_native"
    assert completion.completion_tokens == 2048
    assert completion.reasoning_tokens == 2048
    assert completion.reasoning_present is True
    assert completion.cost_usd == 0.00096
    assert _PROVIDER_TEXT not in result.model_dump_json()


def test_an_envelope_level_error_keeps_the_provenance_it_arrived_with() -> None:
    respond = _json(
        200,
        _envelope(
            {"content": _CONTENT},
            system_fingerprint="fp_44709586",
            error={"code": 502, "message": _PROVIDER_TEXT},
        ),
    )

    with _provider(respond) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.FAILED
    assert completion.error_code == "provider_error"
    assert completion.provider_error_code == "502"
    assert completion.http_status == 200
    assert completion.response_id == "gen-1726000000-abc"
    assert completion.response_model == "qwen/qwen3-8b-04-28"
    assert completion.provider == "Alibaba"
    assert completion.system_fingerprint == "fp_44709586"
    assert completion.prompt_tokens == 240
    assert completion.completion_tokens == 21
    assert completion.reasoning_tokens == 0
    assert completion.cost_usd == 0.0000376
    assert completion.finish_reason is None
    assert completion.native_finish_reason is None
    assert completion.reasoning_present is None
    assert _PROVIDER_TEXT not in result.model_dump_json()


@pytest.mark.parametrize(
    "body",
    [
        _envelope(
            {"content": _CONTENT},
            usage={
                "prompt_tokens": 240,
                "completion_tokens": 21,
                "completion_tokens_details": None,
            },
        ),
        _envelope({"content": _CONTENT}) | {"usage": None},
    ],
)
def test_a_null_usage_breakdown_keeps_the_answer_it_paid_for(
    body: dict[str, object],
) -> None:
    with _provider(_json(200, body)) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.COMPLETED
    assert completion.response_text == _CONTENT
    assert completion.reasoning_tokens is None
    assert completion.cost_usd is None
    assert [request.path for request in provider.received] == [
        "/v1/chat/completions"
    ]


def test_a_reply_that_fails_a_record_bound_cannot_leak_through_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def looser(
        body: bytes, status: dict[str, object], secret: str | None
    ) -> dict[str, object]:
        del body, secret
        return status | {
            "finish_reason": _PROVIDER_TEXT * 40,
            "response_text": _CONTENT,
        }

    monkeypatch.setattr(model_client, "_parse_reply", looser)
    with _provider(_ok) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.FAILED
    assert completion.error_code == "client_error"
    assert completion.http_status is None
    assert completion.response_text is None
    assert _PROVIDER_TEXT not in result.model_dump_json()
    assert [request.path for request in provider.received] == [
        "/v1/chat/completions"
    ]


def test_timeout_after_the_status_line_keeps_the_recorded_status() -> None:
    with _provider(_stall_after_headers) as provider:
        result = _backend(
            provider.url,
            settings=RequestSettingsV1(model_id="m", timeout_seconds=0.3),
        ).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.FAILED
    assert completion.error_code == "timeout"
    assert completion.http_status == 200
    assert completion.response_text is None
    assert [request.path for request in provider.received] == [
        "/v1/chat/completions"
    ]


def test_timeout_is_bounded_and_reported_as_a_code() -> None:
    started = time.monotonic()

    with _provider(_slow) as provider:
        result = _backend(
            provider.url,
            settings=RequestSettingsV1(model_id="m", timeout_seconds=0.3),
        ).complete(_prepared())

    assert result.completions[0].error_code == "timeout"
    assert result.completions[0].http_status is None
    assert time.monotonic() - started < 3


def test_credential_never_appears_in_errors_repr_or_logs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.DEBUG)
    good_url = "https://example.com/v1/chat/completions"

    with pytest.raises(ModelClientError) as explicit:
        _backend(good_url, api_key="sk-explicit\nSECRET-A")
    monkeypatch.setenv(API_KEY_ENV, "sk-env\tSECRET-B")
    with pytest.raises(ModelClientError) as from_env:
        _backend(good_url, api_key=None)
    with pytest.raises(ModelClientError) as bad_url:
        _backend("https://user:hunter2@example.com/v1/chat/completions")
    with _provider(_status(500, b"nope")) as provider:
        backend = _backend(provider.url)
        result = backend.complete(_prepared())

    for caught in (explicit, from_env, bad_url):
        assert caught.value.code == "configuration_invalid"
        assert isinstance(caught.value, DFilterForgeError)
        assert "SECRET" not in str(caught.value)
    assert "hunter2" not in str(bad_url.value)
    assert "example.com" not in str(bad_url.value)
    assert _API_KEY not in repr(backend)
    assert provider.url not in repr(backend)
    assert _API_KEY not in repr(result)
    assert _API_KEY not in caplog.text


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1/chat/completions",
        "http://localhost:8080/v1/chat/completions",
        "http://127.0.0.1/v1/chat/completions",
        "http://model-runner.docker.internal/engines/v1/chat/completions",
    ],
)
def test_accepted_endpoints_need_no_network_to_construct(url: str) -> None:
    assert isinstance(_backend(url), OpenAiCompatibleBackend)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1/chat/completions",
        "https://user@example.com/v1/chat/completions",
        "https://example.com/v1/chat/completions?stream=true",
        "https://example.com/v1/chat/completions#fragment",
        "https://example.com/v1/models",
        "https://example.com:0/v1/chat/completions",
        "https://example.com:99999/v1/chat/completions",
        "ftp://localhost/v1/chat/completions",
        "/v1/chat/completions",
        "",
    ],
)
def test_unsafe_endpoints_are_rejected_with_a_sanitized_error(
    url: str,
) -> None:
    with pytest.raises(ModelClientError) as caught:
        _backend(url)

    assert caught.value.code == "configuration_invalid"
    assert "example.com" not in str(caught.value)
