"""Tests for the bounded OpenAI-compatible backend against a local fake."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import json
import logging
import threading
import time
from typing import Any

import pytest

from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import DirectFilterResultV1
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.model_client import CompletionBatchV1
from dfilterforge.model_client import CompletionStatusV1
from dfilterforge.model_client import ModelClientError
from dfilterforge.model_client import OpenAiCompatibleBackend
from dfilterforge.model_client import RequestSettingsV1

_API_KEY = "sk-test-SECRET-9f2c"
_CONTENT = '{"schema_version":"direct-filter/1.0","display_filter":"tcp"}'
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

Responder = Callable[[BaseHTTPRequestHandler], None]


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


def _status(status: int, body: bytes, *, chunked: bool = False) -> Responder:
    """Returns a responder that always answers with one fixed reply."""

    def respond(handler: BaseHTTPRequestHandler) -> None:
        _reply(handler, status, body, chunked=chunked)

    return respond


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


def _backend(
    url: str,
    *,
    api_key: str | None = _API_KEY,
    timeout_seconds: float = 30.0,
) -> OpenAiCompatibleBackend:
    settings = RequestSettingsV1(
        model_id="test-model", timeout_seconds=timeout_seconds
    )
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
    assert completion.finish_reason == "stop"
    assert completion.prompt_tokens == 12
    assert completion.completion_tokens == 3
    assert completion.latency_ms >= 0
    assert parse_response(
        result.output_contract, _CONTENT
    ) == DirectFilterResultV1(display_filter="tcp")
    assert CompletionBatchV1.model_validate_json(result.model_dump_json()) == (
        result
    )

    (request,) = provider.received
    assert request.path == "/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {_API_KEY}"
    assert request.headers["Content-Type"].startswith("application/json")
    body = json.loads(request.body)
    prompt = batch.prompts[0]
    assert body["model"] == "test-model"
    assert body["messages"] == [
        {"role": message.role, "content": message.content}
        for message in prompt.messages
    ]
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 2048
    assert body["n"] == 1
    assert body["seed"] == 17
    assert body["response_format"] == {"type": "json_object"}


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


@pytest.mark.parametrize(
    ("respond", "code"),
    [
        (_status(500, b'{"error":"boom"}'), "http_error"),
        (_status(404, b"missing"), "http_error"),
        (_status(200, b"{not json"), "response_invalid"),
        (_status(200, b"\xff\xfe"), "response_invalid"),
        (_status(200, b'{"choices":[]}'), "response_invalid"),
        (
            _status(200, b'{"choices":[{"message":{"content":42}}]}'),
            "response_invalid",
        ),
        (_status(200, _HUGE_BODY), "response_too_large"),
        (_status(200, _HUGE_BODY, chunked=True), "response_too_large"),
        (_redirect, "redirect_rejected"),
    ],
)
def test_failures_are_recorded_as_stable_codes_without_retries(
    respond: Responder, code: str
) -> None:
    with _provider(respond) as provider:
        result = _backend(provider.url).complete(_prepared())

    (completion,) = result.completions
    assert completion.status is CompletionStatusV1.FAILED
    assert completion.error_code == code
    assert completion.response_text is None
    assert [request.path for request in provider.received] == [
        "/v1/chat/completions"
    ]
    assert _API_KEY not in result.model_dump_json()


def test_timeout_is_bounded_and_reported_as_a_code() -> None:
    started = time.monotonic()

    with _provider(_slow) as provider:
        result = _backend(provider.url, timeout_seconds=0.3).complete(
            _prepared()
        )

    assert result.completions[0].error_code == "timeout"
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


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": 301},
        {"timeout_seconds": float("nan")},
        {"temperature": 2.5},
        {"temperature": float("inf")},
        {"max_output_tokens": 0},
        {"max_output_tokens": 65_537},
        {"seed": True},
        {"model_id": "   "},
        {"api_key": "sk-must-not-live-here"},
    ],
)
def test_request_settings_are_bounded(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RequestSettingsV1.model_validate({"model_id": "m", **overrides})
