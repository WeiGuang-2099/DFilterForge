"""Replay documented provider reply shapes through the model client.

Every reply below is copied from the OpenRouter or OpenAI documentation,
except the last two bounds probes, which are built from the documented
response schema rather than from published replies. Each reply is served from
a loopback server on 127.0.0.1, so no external endpoint is contacted, and a
fixed placeholder bearer token keeps the credential header exercised without
ever putting an operator key on the wire. Only what the client recorded is
written out.
"""

from __future__ import annotations

import argparse
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import threading
from typing import Any

import dfilterforge
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import RetrievalV1
from dfilterforge.model_client import OpenAiCompatibleBackend

PROVIDER_TEXT = "PROVIDER-PROSE"
_CONTENT = '{"schema_version":"direct-filter/1.0","display_filter":"tcp"}'
_PLACEHOLDER_KEY = "replay-no-credential"
_OPENAI_ERRORS = "https://platform.openai.com/docs/guides/error-codes"
_OPENAI_OBJECT = "https://platform.openai.com/docs/api-reference/chat/object"
_OPENROUTER_ERRORS = "https://openrouter.ai/docs/api-reference/errors"
_OPENROUTER_LIMITS = "https://openrouter.ai/docs/api-reference/limits"
_OPENROUTER_REASONING = "https://openrouter.ai/docs/use-cases/reasoning-tokens"
_OPENROUTER_SCHEMA = "https://openrouter.ai/docs/api-reference/overview"
_PROVENANCE = (
    "response_id",
    "response_model",
    "provider",
    "system_fingerprint",
    "native_finish_reason",
    "reasoning_tokens",
    "reasoning_present",
    "cost_usd",
)


@dataclass(frozen=True)
class ProviderReply:
    """One documented reply shape and the record it has to produce."""

    name: str
    source: str
    status: int
    body: object
    expected: tuple[str, int | None, str | None]
    headers: tuple[tuple[str, str], ...] = ()


def _choice(
    message: dict[str, object], finish: str | None
) -> dict[str, object]:
    """Builds the documented OpenRouter chat.completion envelope."""
    return {
        "id": "gen-1726000000-abc",
        "object": "chat.completion",
        "created": 1726000000,
        "model": "qwen/qwen3-8b",
        "provider": "Alibaba",
        "system_fingerprint": None,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish,
                "native_finish_reason": finish,
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": 240,
            "completion_tokens": 21,
            "total_tokens": 261,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "cost": 0.0000376,
        },
    }


def _error(code: object) -> dict[str, object]:
    """Builds a documented error body around one provider code."""
    return {"error": {"code": code, "message": PROVIDER_TEXT}}


REPLIES: tuple[ProviderReply, ...] = (
    ProviderReply(
        name="openrouter_completed",
        source=_OPENROUTER_SCHEMA,
        status=200,
        body=_choice(
            {"role": "assistant", "content": _CONTENT, "refusal": None},
            "stop",
        ),
        expected=("completed", 200, None),
    ),
    ProviderReply(
        name="reasoning_not_disabled",
        source=_OPENROUTER_REASONING,
        status=200,
        body=_choice(
            {
                "role": "assistant",
                "content": _CONTENT,
                "reasoning": PROVIDER_TEXT,
            },
            "stop",
        ),
        expected=("completed", 200, None),
    ),
    ProviderReply(
        name="credits_exhausted",
        source=_OPENROUTER_ERRORS,
        status=402,
        body=_error(402),
        expected=("http_error", 402, "402"),
    ),
    ProviderReply(
        name="rate_limited",
        source=_OPENROUTER_LIMITS,
        status=429,
        body=_error(429),
        expected=("http_error", 429, "429"),
        headers=(("Retry-After", "60"),),
    ),
    ProviderReply(
        name="no_provider",
        source=_OPENROUTER_ERRORS,
        status=503,
        body=_error(503),
        expected=("http_error", 503, "503"),
    ),
    ProviderReply(
        name="no_allowed_provider",
        source=_OPENROUTER_ERRORS,
        status=404,
        body=_error(404),
        expected=("http_error", 404, "404"),
    ),
    ProviderReply(
        name="invalid_api_key_openai",
        source=_OPENAI_ERRORS,
        status=401,
        body={
            "error": {
                "message": PROVIDER_TEXT,
                "type": "invalid_request_error",
                "param": None,
                "code": "invalid_api_key",
            }
        },
        expected=("http_error", 401, "invalid_api_key"),
    ),
    ProviderReply(
        name="unknown_argument_openai",
        source=_OPENAI_ERRORS,
        status=400,
        body={
            "error": {
                "message": PROVIDER_TEXT,
                "type": "invalid_request_error",
                "param": None,
                "code": None,
            }
        },
        expected=("http_error", 400, None),
    ),
    ProviderReply(
        name="error_inside_http_200",
        source=_OPENROUTER_ERRORS,
        status=200,
        body={"id": "gen-1726000000-err"} | _error(502),
        expected=("provider_error", 200, "502"),
    ),
    ProviderReply(
        name="choice_finished_with_error",
        source=_OPENROUTER_ERRORS,
        status=200,
        body=_choice({"role": "assistant", "content": PROVIDER_TEXT}, "error"),
        expected=("provider_error", 200, None),
    ),
    ProviderReply(
        name="reasoning_used_the_output_budget",
        source=_OPENROUTER_REASONING,
        status=200,
        body=_choice(
            {
                "role": "assistant",
                "content": None,
                "reasoning": PROVIDER_TEXT,
            },
            "length",
        ),
        expected=("empty_content", 200, None),
    ),
    ProviderReply(
        name="refusal",
        source=_OPENAI_OBJECT,
        status=200,
        body=_choice(
            {
                "role": "assistant",
                "content": None,
                "refusal": PROVIDER_TEXT,
            },
            "content_filter",
        ),
        expected=("empty_content", 200, None),
    ),
    # Two bounds probes built from the documented envelope, not copied
    # replies. Prose aimed at a recorded metadata field fails the 256-byte
    # bound, so the whole reply is rejected rather than truncated.
    ProviderReply(
        name="metadata_prose_is_bounded",
        source=_OPENROUTER_SCHEMA,
        status=200,
        body=_choice(
            {"role": "assistant", "content": _CONTENT},
            PROVIDER_TEXT * 40,
        ),
        expected=("response_invalid", 200, None),
    ),
    # Prose aimed at the top-level provider name, which is recorded as
    # provenance and so carries the same bound as the finish reason.
    ProviderReply(
        name="provider_prose_is_bounded",
        source=_OPENROUTER_SCHEMA,
        status=200,
        body=_choice({"role": "assistant", "content": _CONTENT}, "stop")
        | {"provider": PROVIDER_TEXT * 40},
        expected=("response_invalid", 200, None),
    ),
)


@contextmanager
def serve(
    reply: ProviderReply,
) -> Generator[tuple[str, list[bytes]], None, None]:
    """Serves one reply from 127.0.0.1 and yields its URL and sent bodies."""
    received: list[bytes] = []

    class Handler(BaseHTTPRequestHandler):
        """Answers one chat-completions POST with the documented reply."""

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            """Keeps the request body and writes the fixed reply."""
            received.append(
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
            )
            payload = json.dumps(reply.body).encode("utf-8")
            self.send_response(reply.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in reply.headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()

        # pylint: disable-next=redefined-builtin
        def log_message(self, format: str, *args: Any) -> None:
            """Keeps the replay output free of request logging."""
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
        yield url, received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request_body_bytes(sent: list[bytes]) -> int | None:
    """Returns the canonical size of one request body without its messages."""
    if not sent:
        return None
    body = json.loads(sent[0].decode("utf-8"))
    del body["messages"]
    return len(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _package_src() -> str:
    """Returns the source root the client was imported from, repo-relative."""
    root = Path(dfilterforge.__file__).resolve().parent.parent
    try:
        return root.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return root.as_posix()


def _row(
    reply: ProviderReply, result: Any, sent: list[bytes]
) -> dict[str, Any]:
    """Records the client-visible outcome of one replayed reply."""
    record: Any = result.completions[0]
    return {
        "reply": reply.name,
        "source": reply.source,
        "recorded_as": record.error_code or str(record.status),
        "http_status": getattr(record, "http_status", None),
        "provider_error_code": getattr(record, "provider_error_code", None),
        "reasoning_present": getattr(record, "reasoning_present", None),
        "provenance_fields": sum(
            getattr(record, name, None) is not None for name in _PROVENANCE
        ),
        "provider_text_recorded": PROVIDER_TEXT in result.model_dump_json(),
        "request_body_bytes": _request_body_bytes(sent),
    }


def replay(settings_module: str) -> list[dict[str, Any]]:
    """Runs every documented reply through the client and keeps the records."""
    settings_type = importlib.import_module(settings_module).RequestSettingsV1
    options: dict[str, Any] = {"model_id": "qwen/qwen3-8b"}
    if "openrouter" in settings_type.model_fields:
        options["openrouter"] = {"provider_order": ("alibaba",)}
    settings = settings_type(**options)
    batch = prepare_batch(
        (GenerationInputV1(item_id="item-1", intent="Show TCP packets"),),
        output_contract=OutputContractV1.DISPLAY_FILTER,
        retrieval=RetrievalV1.NONE,
    )
    rows: list[dict[str, Any]] = []
    for reply in REPLIES:
        with serve(reply) as (url, sent):
            backend = OpenAiCompatibleBackend(
                url, settings, api_key=_PLACEHOLDER_KEY
            )
            result = backend.complete(batch)
        rows.append(_row(reply, result, sent))
    return rows


def main() -> None:
    """Writes one row per documented reply to the named output file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--settings-module", default="dfilterforge.completions")
    arguments = parser.parse_args()
    document = {
        "revision": arguments.revision,
        "package_src": _package_src(),
        "rows": replay(arguments.settings_module),
    }
    output: Path = arguments.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
