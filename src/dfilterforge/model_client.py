"""Bounded OpenAI-compatible chat-completions boundary.

The backend sends each prepared prompt exactly once, never follows redirects,
caps response bytes, and records failures only as stable codes. The API
credential is deliberately kept outside every pydantic model so it can never
be serialized, compared, or echoed inside a validation error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import http.client
import json
import os
import ssl
import time
from typing import cast, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from dfilterforge.canonical import canonical_json
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.text_limits import validate_text
from dfilterforge.text_limits import validate_utf8

_ENDPOINT_KIND = "openai-compatible-chat-completions"
API_KEY_ENV = "DFILTERFORGE_MODEL_API_KEY"
_MAX_ITEM_ID_BYTES = 256
_MAX_MODEL_ID_BYTES = 256
_MAX_ERROR_CODE_BYTES = 64
_MAX_FINISH_REASON_BYTES = 256
_MAX_API_KEY_BYTES = 8 * 1024
_MAX_OUTPUT_TOKENS = 65_536
_MAX_TIMEOUT_SECONDS = 300.0
_PLAIN_HTTP_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "model-runner.docker.internal"}
)


class ModelClientError(DFilterForgeError):
    """A configuration failure containing only a stable code and safe text."""


class CompletionStatusV1(StrEnum):
    """Whether a provider returned a usable raw response envelope."""

    COMPLETED = "completed"
    FAILED = "failed"


class CompletionV1(FrozenModel):
    """One bounded raw completion or one sanitized failure."""

    item_id: str
    status: CompletionStatusV1
    response_text: str | None = None
    error_code: str | None = None
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    finish_reason: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        """Rejects empty or excessively large opaque item keys."""
        return validate_text(value, _MAX_ITEM_ID_BYTES, "item_id")

    @field_validator("response_text")
    @classmethod
    def validate_response_text(cls, value: str | None) -> str | None:
        """Applies the model response byte ceiling to successful content."""
        if value is not None:
            validate_utf8(value, MAX_RESPONSE_BYTES, "response_text")
        return value

    @field_validator("error_code")
    @classmethod
    def validate_error_code(cls, value: str | None) -> str | None:
        """Keeps recorded errors stable, short, and data-free."""
        if value is None:
            return None
        if not value or not value.replace("_", "").isalnum():
            raise ValueError("error_code must be a stable identifier")
        validate_utf8(value, _MAX_ERROR_CODE_BYTES, "error_code")
        return value

    @field_validator("finish_reason")
    @classmethod
    def validate_finish_reason(cls, value: str | None) -> str | None:
        """Bounds provider metadata independently of response content."""
        if value is not None:
            validate_utf8(value, _MAX_FINISH_REASON_BYTES, "finish_reason")
        return value

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CompletionV1":
        """Makes successful content and sanitized errors mutually exclusive."""
        if self.status == CompletionStatusV1.COMPLETED:
            if self.response_text is None:
                raise ValueError("completed requires response_text")
            if self.error_code is not None:
                raise ValueError("completed cannot include error_code")
        else:
            if self.response_text is not None:
                raise ValueError("failed cannot include response_text")
            if self.error_code is None:
                raise ValueError("failed requires error_code")
        return self


class RequestSettingsV1(FrozenModel):
    """Reproducibility-safe request configuration recorded with every batch.

    Credentials and endpoint addresses never belong here: this model is
    serialized into completion batches and may appear in reports.
    """

    model_id: str
    temperature: float = Field(default=0.0, ge=0, le=2, allow_inf_nan=False)
    seed: int | None = Field(default=17, strict=True)
    max_output_tokens: int = Field(
        default=2048, ge=1, le=_MAX_OUTPUT_TOKENS, strict=True
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0, le=_MAX_TIMEOUT_SECONDS, allow_inf_nan=False
    )

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        """Bounds the recorded provider model identifier."""
        return validate_text(value, _MAX_MODEL_ID_BYTES, "model_id")


class CompletionBatchV1(FrozenModel):
    """Raw model results plus the reproducibility-safe request configuration."""

    schema_version: Literal["completion-batch/1.0"] = "completion-batch/1.0"
    output_contract: OutputContractV1
    retrieval: RetrievalV1
    endpoint_kind: Literal["openai-compatible-chat-completions"] = (
        _ENDPOINT_KIND
    )
    settings: RequestSettingsV1
    completions: tuple[CompletionV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_completion_ids(self) -> "CompletionBatchV1":
        """Rejects ambiguous duplicate completion keys."""
        item_ids = tuple(item.item_id for item in self.completions)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("completion item IDs must be unique")
        return self


class CompletionBackend(Protocol):
    """The single external model-completion boundary used by orchestration."""

    def complete(self, batch: PreparedBatchV1) -> CompletionBatchV1:
        """Completes every prepared prompt exactly once."""
        ...


class _RequestFailure(RuntimeError):
    """An internal provider failure represented only by a safe code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Endpoint:
    """A validated chat-completions address without credentials or query."""

    host: str
    port: int | None
    path: str
    tls: bool


@dataclass(frozen=True, slots=True)
class _Reply:
    """The bounded fields kept from one provider response."""

    content: str
    finish_reason: str | None
    prompt_tokens: int | None
    completion_tokens: int | None


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
        return f"OpenAiCompatibleBackend(endpoint_kind={_ENDPOINT_KIND!r})"

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
        try:
            reply = self._request(prompt)
        except _RequestFailure as error:
            return _failed_completion(prompt.item_id, error.code, started)
        except TimeoutError:
            return _failed_completion(prompt.item_id, "timeout", started)
        except (OSError, http.client.HTTPException):
            return _failed_completion(
                prompt.item_id, "transport_error", started
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # The provider boundary must never leak internals into a batch.
            return _failed_completion(prompt.item_id, "client_error", started)
        return CompletionV1(
            item_id=prompt.item_id,
            status=CompletionStatusV1.COMPLETED,
            response_text=reply.content,
            latency_ms=_elapsed_ms(started),
            finish_reason=reply.finish_reason,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
        )

    def _request(self, prompt: PreparedPromptV1) -> _Reply:
        settings = self._settings
        body: dict[str, object] = {
            "model": settings.model_id,
            "messages": tuple(
                {"role": message.role, "content": message.content}
                for message in prompt.messages
            ),
            "temperature": settings.temperature,
            "max_tokens": settings.max_output_tokens,
            "n": 1,
            "response_format": {"type": "json_object"},
        }
        if settings.seed is not None:
            body["seed"] = settings.seed
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"
        connection = self._connection()
        try:
            connection.request(
                "POST",
                self._endpoint.path,
                body=canonical_json(body).encode("utf-8"),
                headers=headers,
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise _RequestFailure("redirect_rejected")
            if not 200 <= response.status < 300:
                raise _RequestFailure("http_error")
            _check_declared_length(response.getheader("Content-Length"))
            response_bytes = response.read(MAX_RESPONSE_BYTES + 1)
        finally:
            connection.close()
        if len(response_bytes) > MAX_RESPONSE_BYTES:
            raise _RequestFailure("response_too_large")
        try:
            payload = json.loads(response_bytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _RequestFailure("response_invalid") from None
        return _parse_reply(payload)

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


def _failed_completion(item_id: str, code: str, started: float) -> CompletionV1:
    return CompletionV1(
        item_id=item_id,
        status=CompletionStatusV1.FAILED,
        error_code=code,
        latency_ms=_elapsed_ms(started),
    )


def _check_declared_length(declared: str | None) -> None:
    if declared is None:
        return
    try:
        length = int(declared)
    except ValueError:
        raise _RequestFailure("response_invalid") from None
    if length > MAX_RESPONSE_BYTES:
        raise _RequestFailure("response_too_large")


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _RequestFailure("response_invalid")
    return cast(dict[str, object], value)


def _check_bytes(value: str, maximum: int, code: str) -> None:
    try:
        validate_utf8(value, maximum, "response")
    except ValueError:
        raise _RequestFailure(code) from None


def _parse_reply(payload: object) -> _Reply:
    envelope = _mapping(payload)
    choices = envelope.get("choices")
    if not isinstance(choices, list):
        raise _RequestFailure("response_invalid")
    choice_list = cast(list[object], choices)
    if len(choice_list) != 1:
        raise _RequestFailure("response_invalid")
    choice = _mapping(choice_list[0])
    content = _mapping(choice.get("message")).get("content")
    if not isinstance(content, str):
        raise _RequestFailure("response_invalid")
    _check_bytes(content, MAX_RESPONSE_BYTES, "response_too_large")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None:
        if not isinstance(finish_reason, str):
            raise _RequestFailure("response_invalid")
        _check_bytes(
            finish_reason, _MAX_FINISH_REASON_BYTES, "response_invalid"
        )
    usage = envelope.get("usage")
    if usage is None:
        return _Reply(content, finish_reason, None, None)
    usage_map = _mapping(usage)
    return _Reply(
        content,
        finish_reason,
        _optional_token_count(usage_map, "prompt_tokens"),
        _optional_token_count(usage_map, "completion_tokens"),
    )


def _optional_token_count(usage: dict[str, object], name: str) -> int | None:
    value = usage.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _RequestFailure("response_invalid")
    return value
