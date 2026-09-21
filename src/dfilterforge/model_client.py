"""Bounded OpenAI-compatible chat-completions boundary.

The backend sends each prepared prompt exactly once, never follows redirects,
caps response bytes, and records failures only as stable codes plus bounded
provider metadata. The API credential is deliberately kept outside every
pydantic model so it can never be serialized, compared, or echoed inside a
validation error.
"""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import os
import ssl
import time
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CODE_PATTERN
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ENDPOINT_KIND
from dfilterforge.completions import MAX_METADATA_BYTES
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.text_limits import validate_utf8

API_KEY_ENV = "DFILTERFORGE_MODEL_API_KEY"
_MAX_API_KEY_BYTES = 8 * 1024
_MAX_ERROR_BODY_BYTES = 8 * 1024
_PLAIN_HTTP_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "model-runner.docker.internal"}
)
_OPENROUTER_REASONING: dict[str, dict[str, object]] = {
    "enabled_false": {"enabled": False},
    "effort_none": {"effort": "none"},
}


def _bounded_metadata(value: str) -> str:
    validate_utf8(value, MAX_METADATA_BYTES, "provider metadata")
    return value


_Metadata = Annotated[str, AfterValidator(_bounded_metadata)]
_Count = Annotated[int, Field(ge=0)]


class ModelClientError(DFilterForgeError):
    """A configuration failure containing only a stable code and safe text."""


class _RequestFailure(RuntimeError):
    """A provider failure carrying a safe code and bounded metadata."""

    def __init__(self, code: str, recorded: dict[str, object]) -> None:
        super().__init__(code)
        self.code = code
        self.recorded = recorded


@dataclass(frozen=True, slots=True)
class _Endpoint:
    """A validated chat-completions address without credentials or query."""

    host: str
    port: int | None
    path: str
    tls: bool


class _ReplyPart(BaseModel):
    """Provider JSON: undeclared keys are ignored, declared keys are strict."""

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class _ErrorBody(_ReplyPart):
    """A provider error object, kept only for its short identifier."""

    code: int | str | None = None

    def recorded_code(self, secret: str | None) -> str | None:
        """Keeps ``error.code`` only when it is a safe short identifier.

        A bearer credential has the shape of a short identifier, so an
        endpoint that echoes the Authorization it was sent back as the
        error code would otherwise have it stored in a record.
        """
        code = None if self.code is None else str(self.code)
        if not code or code == secret or not CODE_PATTERN.fullmatch(code):
            return None
        return code


class _ErrorReply(_ReplyPart):
    """A non-success body read for nothing but its error code."""

    error: _ErrorBody = _ErrorBody()


class _Message(_ReplyPart):
    """One assistant message, read for its content and reasoning presence.

    The three reasoning keys are typed as bare ``object`` because the three
    documented dialects put a string, a list of blocks or null there, and
    because their value is never read: only their truthiness is recorded.
    """

    content: str | None = None
    reasoning: object = None
    reasoning_content: object = None
    reasoning_details: object = None


class _Choice(_ReplyPart):
    """One generated choice plus the provenance a record may keep."""

    message: _Message
    finish_reason: _Metadata | None = None
    native_finish_reason: _Metadata | None = None
    error: _ErrorBody | None = None


class _TokenDetails(_ReplyPart):
    """The provider-reported breakdown of the generated token count."""

    reasoning_tokens: _Count | None = None


class _Usage(_ReplyPart):
    """Provider-reported token counts and the charge they incurred.

    Providers that report no breakdown send the key as JSON null rather
    than omitting it, so the sub-object is optional: an absent breakdown
    must record a missing reasoning count, not discard a paid answer.
    """

    prompt_tokens: _Count | None = None
    completion_tokens: _Count | None = None
    completion_tokens_details: _TokenDetails | None = None
    cost: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None


class _Envelope(_ReplyPart):
    """One chat-completions reply body, successful or in-band failed."""

    id: _Metadata | None = None
    model: _Metadata | None = None
    provider: _Metadata | None = None
    system_fingerprint: _Metadata | None = None
    choices: list[_Choice] | None = None
    usage: _Usage | None = None
    error: _ErrorBody | None = None


class OpenAiCompatibleBackend:
    """Synchronous, non-redirecting OpenAI chat-completions backend."""

    __slots__ = ("_api_key", "_endpoint", "_settings")

    def __init__(
        self,
        endpoint_url: str,
        settings: RequestSettingsV1,
        *,
        api_key: str | None = None,
    ) -> None:
        """Validates the endpoint and credential without contacting anyone.

        Args:
            endpoint_url: A ``/chat/completions`` URL. Plain http is accepted
                only for local hosts; credentials, queries, and fragments are
                rejected.
            settings: Request configuration recorded with every batch.
            api_key: Bearer credential. When omitted, ``API_KEY_ENV`` is read.
                Neither source is logged, represented, or echoed in errors.

        Raises:
            ModelClientError: If the endpoint or credential is unsafe.
        """
        self._endpoint = _parse_endpoint(endpoint_url)
        self._settings = settings
        self._api_key = _resolve_api_key(api_key)

    def __repr__(self) -> str:
        """Returns a representation that omits endpoint and credentials."""
        return f"OpenAiCompatibleBackend(endpoint_kind={ENDPOINT_KIND!r})"

    def complete(self, batch: PreparedBatchV1) -> CompletionBatchV1:
        """Executes each prompt once and records only bounded safe failures."""
        return CompletionBatchV1(
            output_contract=batch.output_contract,
            retrieval=batch.retrieval,
            settings=self._settings,
            completions=tuple(
                self._complete_prompt(prompt) for prompt in batch.prompts
            ),
        )

    def _complete_prompt(self, prompt: PreparedPromptV1) -> CompletionV1:
        started = time.monotonic()
        recorded: dict[str, object]
        try:
            recorded = self._request(prompt)
        except _RequestFailure as failure:
            recorded = failure.recorded | {"error_code": failure.code}
        except TimeoutError:
            recorded = {"error_code": "timeout"}
        except (OSError, http.client.HTTPException):
            recorded = {"error_code": "transport_error"}
        except Exception:  # pylint: disable=broad-exception-caught
            # The provider boundary must never leak internals into a batch.
            recorded = {"error_code": "client_error"}
        return _record(prompt.item_id, recorded, _elapsed_ms(started))

    def _request(self, prompt: PreparedPromptV1) -> dict[str, object]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "dfilterforge-model-client",
        }
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        connection = self._connection()
        try:
            connection.request(
                "POST",
                self._endpoint.path,
                body=canonical_json(
                    _request_body(self._settings, prompt)
                ).encode("utf-8"),
                headers=headers,
            )
            response = connection.getresponse()
            status: dict[str, object] = {"http_status": response.status}
            if 300 <= response.status < 400:
                raise _RequestFailure("redirect_rejected", status)
            if not 200 <= response.status < 300:
                code = _error_body_code(response, self._api_key)
                raise _RequestFailure(
                    "http_error", status | {"provider_error_code": code}
                )
            if _declared_length(response) > MAX_RESPONSE_BYTES:
                raise _RequestFailure("response_too_large", status)
            try:
                response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
            except TimeoutError:
                raise _RequestFailure("timeout", status) from None
        finally:
            connection.close()
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise _RequestFailure("response_too_large", status)
        return _parse_reply(response_bytes, status, self._api_key)

    def _connection(self) -> http.client.HTTPConnection:
        endpoint = self._endpoint
        timeout = self._settings.timeout_seconds
        if endpoint.tls:
            return http.client.HTTPSConnection(
                endpoint.host,
                endpoint.port,
                timeout=timeout,
                context=ssl.create_default_context(),
            )
        return http.client.HTTPConnection(
            endpoint.host, endpoint.port, timeout=timeout
        )


def _request_body(
    settings: RequestSettingsV1, prompt: PreparedPromptV1
) -> dict[str, object]:
    """Builds the body; OpenRouter-only keys appear only when opted in."""
    body: dict[str, object] = {
        "model": settings.model_id,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in prompt.messages
        ],
        "temperature": settings.temperature,
        "max_tokens": settings.max_output_tokens,
    }
    if settings.seed is not None:
        body["seed"] = settings.seed
    if settings.json_mode:
        body["response_format"] = {"type": "json_object"}
    options = settings.openrouter
    if options is None:
        return body
    if options.reasoning is not None:
        body["reasoning"] = _OPENROUTER_REASONING[options.reasoning]
    provider: dict[str, object] = {
        "allow_fallbacks": options.allow_fallbacks,
        "require_parameters": options.require_parameters,
    }
    if options.provider_order:
        provider["order"] = options.provider_order
    if options.data_collection is not None:
        provider["data_collection"] = options.data_collection
    body["provider"] = provider
    return body


def _parse_endpoint(endpoint_url: str) -> _Endpoint:
    """Accepts credential-free chat-completions URLs; http must be local."""
    invalid = ModelClientError(
        "configuration_invalid", "Model endpoint is invalid"
    )
    try:
        parts = urlsplit(endpoint_url)
        port = parts.port
    except ValueError:
        raise invalid from None
    host = parts.hostname
    if host is None or port == 0 or parts.username or parts.password:
        raise invalid
    if parts.query or parts.fragment:
        raise invalid
    if not parts.path.endswith("/chat/completions"):
        raise invalid
    if parts.scheme == "https":
        return _Endpoint(host, port, parts.path, tls=True)
    if parts.scheme == "http" and host in _PLAIN_HTTP_HOSTS:
        return _Endpoint(host, port, parts.path, tls=False)
    raise invalid


def _resolve_api_key(api_key: str | None) -> str | None:
    """Returns the explicit or environment credential after safe validation."""
    if api_key is None:
        api_key = os.environ.get(API_KEY_ENV)
    if api_key is None:
        return None
    try:
        validate_utf8(api_key, _MAX_API_KEY_BYTES, "api_key")
    except ValueError:
        raise ModelClientError(
            "configuration_invalid", "API credential is invalid"
        ) from None
    if not api_key or any(ord(character) < 0x20 for character in api_key):
        raise ModelClientError(
            "configuration_invalid", "API credential is invalid"
        )
    return api_key


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.monotonic() - started) * 1000)


def _record(
    item_id: str, recorded: dict[str, object], latency_ms: float
) -> CompletionV1:
    """Builds one record, falling back when a value fails a record bound.

    Each wire model is bounded exactly like the record field it feeds, but
    a future mismatch must not raise a validation error carrying provider
    bytes out of this boundary, so an unexpected rejection is recorded as
    a client failure instead.
    """
    status = (
        CompletionStatusV1.FAILED
        if "error_code" in recorded
        else CompletionStatusV1.COMPLETED
    )
    try:
        return CompletionV1.model_validate(
            recorded
            | {"item_id": item_id, "status": status, "latency_ms": latency_ms}
        )
    except ValidationError:
        return CompletionV1(
            item_id=item_id,
            status=CompletionStatusV1.FAILED,
            error_code="client_error",
            latency_ms=latency_ms,
        )


def _declared_length(response: http.client.HTTPResponse) -> int:
    declared = response.getheader("Content-Length")
    if declared is None:
        return 0
    try:
        return int(declared)
    except ValueError:
        raise _RequestFailure(
            "response_invalid", {"http_status": response.status}
        ) from None


def _error_body_code(
    response: http.client.HTTPResponse, secret: str | None
) -> str | None:
    """Reads a bounded error body and keeps only its ``error.code``."""
    try:
        prefix = response.read(_MAX_ERROR_BODY_BYTES)
        error = _ErrorReply.model_validate_json(prefix).error
        return error.recorded_code(secret)
    except (OSError, http.client.HTTPException, ValidationError):
        return None


def _recorded_metadata(value: str | None, secret: str | None) -> str | None:
    """Drops provider metadata that merely echoes the sent credential.

    Every metadata field is provider-chosen and roomy enough to hold a
    bearer token, so an endpoint that reflected the Authorization it was
    sent would otherwise have it stored in a record.
    """
    return None if value == secret else value


def _parse_reply(
    body: bytes, status: dict[str, object], secret: str | None
) -> dict[str, object]:
    """Keeps content plus bounded provenance; in-band errors become failures.

    The credential is passed in so that no provider-chosen metadata string
    equal to it is recorded, however short and identifier-shaped it looks.
    Response content is kept verbatim and is not filtered that way.
    """
    try:
        envelope = _Envelope.model_validate_json(body)
    except ValidationError:
        raise _RequestFailure("response_invalid", status) from None
    usage = envelope.usage or _Usage()
    details = usage.completion_tokens_details or _TokenDetails()
    recorded: dict[str, object] = status | {
        "response_id": _recorded_metadata(envelope.id, secret),
        "response_model": _recorded_metadata(envelope.model, secret),
        "provider": _recorded_metadata(envelope.provider, secret),
        "system_fingerprint": _recorded_metadata(
            envelope.system_fingerprint, secret
        ),
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "reasoning_tokens": details.reasoning_tokens,
        "cost_usd": usage.cost,
    }
    if envelope.error is not None:
        code = envelope.error.recorded_code(secret)
        raise _RequestFailure(
            "provider_error", recorded | {"provider_error_code": code}
        )
    if envelope.choices is None or len(envelope.choices) != 1:
        raise _RequestFailure("response_invalid", recorded)
    choice = envelope.choices[0]
    message = choice.message
    recorded |= {
        "finish_reason": _recorded_metadata(choice.finish_reason, secret),
        "native_finish_reason": _recorded_metadata(
            choice.native_finish_reason, secret
        ),
        "reasoning_present": any(
            bool(value)
            for value in (
                message.reasoning,
                message.reasoning_content,
                message.reasoning_details,
            )
        ),
    }
    if choice.error is not None or choice.finish_reason == "error":
        code = (
            None if choice.error is None else choice.error.recorded_code(secret)
        )
        raise _RequestFailure(
            "provider_error", recorded | {"provider_error_code": code}
        )
    if not message.content:
        raise _RequestFailure("empty_content", recorded)
    return recorded | {"response_text": message.content}
