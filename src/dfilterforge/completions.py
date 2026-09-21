"""Recorded completion batches, their request settings and run manifests.

Offline scoring loads these records inside the no-network container, so this
module holds data contracts only and never imports the HTTP client. Every
provider-supplied value is bounded, provider metadata to 256 UTF-8 bytes
each, and no reasoning, refusal or error prose is stored.

This module is also the single definition of :class:`PrepareManifestV1` and
:class:`RunManifestV1`. The prompt preparation step, the call step, the
offline scorer and the publish step all construct and read exactly these
fields; none of them restates the shape. The one rule that reads a reply's
reasoning evidence lives here for the same reason: the call step applies it
to its first answer and the scorer applies it to every answer, and a rule
stated twice would let the two disagree.
"""

# The recorded catalog identity repeats the five fields the runtime reports
# when it opens the frozen inventory, on purpose: the manifest exists to
# carry exactly those values.
# pylint: disable=duplicate-code

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
from enum import StrEnum
import re
from typing import Annotated, Literal

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator

from dfilterforge.generation import ConditionLabel
from dfilterforge.generation import MAX_RESPONSE_BYTES
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.score_summary import ThinkingState
from dfilterforge.text_limits import validate_text
from dfilterforge.text_limits import validate_utf8

ENDPOINT_KIND = "openai-compatible-chat-completions"
MAX_METADATA_BYTES = 256
CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_OUTPUT_TOKENS = 65_536
MAX_SEED = 2**31 - 1
# No money figure any record may carry, so a provider number can never
# make an already-paid run unwritable.
MAX_RECORDED_USD = 1000.0
_MAX_ITEM_ID_BYTES = 256
_MAX_TIMEOUT_SECONDS = 300.0
_MAX_PROVIDER_ROUTES = 4
# The published protocol allows three attempts per item in total, so a run
# that exceeded it cannot be written or published at all.
_MAX_ATTEMPTS_PER_ITEM = 3
_MAX_ITEMS_PER_CONDITION = 128
_MAX_INVOCATIONS = 32

_PROVIDER_SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,64}(/[a-z0-9-]{1,64})?$")
_MODEL_ITEM_ID_PATTERN = re.compile(r"^mei-[0-9]{4}$")

# The run directory's own layout, so a manifest cannot name a file that
# the publish and scoring steps would never look for.
_Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_AttemptsPath = Annotated[str, Field(pattern=r"^attempts/C[1-4]\.jsonl$")]
_CompletionsPath = Annotated[str, Field(pattern=r"^completions/C[1-4]\.json$")]


def _utc(value: datetime) -> datetime:
    """Normalizes an aware timestamp to UTC and rejects a naive one."""
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(timezone.utc)


class CompletionStatusV1(StrEnum):
    """Whether a provider returned a usable raw response envelope."""

    COMPLETED = "completed"
    FAILED = "failed"


class CompletionV1(FrozenModel):
    """One bounded raw completion or one sanitized failure.

    Provenance fields are filled whenever the provider answered, on failures
    as well as successes. ``http_status`` is None only when the client never
    recorded a status line: a transport or client failure, or a timeout that
    struck before the provider answered. A timeout while reading an answered
    body keeps the status it already had.
    """

    item_id: str
    status: CompletionStatusV1
    response_text: str | None = None
    error_code: str | None = None
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    http_status: int | None = Field(default=None, ge=100, le=999, strict=True)
    provider_error_code: str | None = None
    response_id: str | None = None
    response_model: str | None = None
    provider: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    native_finish_reason: str | None = None
    prompt_tokens: int | None = Field(default=None, ge=0, strict=True)
    completion_tokens: int | None = Field(default=None, ge=0, strict=True)
    reasoning_tokens: int | None = Field(default=None, ge=0, strict=True)
    reasoning_present: bool | None = None
    cost_usd: float | None = Field(
        default=None, ge=0, le=MAX_RECORDED_USD, allow_inf_nan=False
    )

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

    @field_validator("error_code", "provider_error_code")
    @classmethod
    def validate_code(cls, value: str | None) -> str | None:
        """Keeps recorded codes short identifiers that cannot carry prose."""
        if value is not None and not CODE_PATTERN.fullmatch(value):
            raise ValueError("codes must be short identifiers")
        return value

    @field_validator(
        "response_id",
        "response_model",
        "provider",
        "system_fingerprint",
        "finish_reason",
        "native_finish_reason",
    )
    @classmethod
    def validate_metadata(cls, value: str | None) -> str | None:
        """Bounds provider metadata independently of response content."""
        if value is not None:
            validate_utf8(value, MAX_METADATA_BYTES, "provider metadata")
        return value

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CompletionV1":
        """Makes successful content and sanitized errors mutually exclusive."""
        if self.status == CompletionStatusV1.COMPLETED:
            if self.response_text is None:
                raise ValueError("completed requires response_text")
            if self.error_code is not None or self.provider_error_code:
                raise ValueError("completed cannot include an error")
        else:
            if self.response_text is not None:
                raise ValueError("failed cannot include response_text")
            if self.error_code is None:
                raise ValueError("failed requires error_code")
        return self


def thinking_state(
    answered: Sequence[CompletionV1],
) -> tuple[ThinkingState, int]:
    """Classifies the thinking switch by the rule the client documents.

    A control counts as honoured only where a reply reports a reasoning
    token count, so records that carry nothing but the flag leave the
    switch uncontrolled rather than honoured. Evidence is wider than
    that rule on purpose: a record carrying either reading counts, so
    the published counter can never read zero beneath a verdict that was
    drawn from a reading.

    Args:
        answered: Every record the provider answered, successful or not.

    Returns:
        The verdict and how many records carried any reasoning reading.
    """
    evidence = sum(
        1
        for record in answered
        if record.reasoning_tokens is not None
        or record.reasoning_present is not None
    )
    if any(
        (record.reasoning_tokens or 0) > 0 or record.reasoning_present
        for record in answered
    ):
        return "not_honoured", evidence
    if any(record.reasoning_tokens is not None for record in answered):
        return "honoured", evidence
    return "uncontrolled", evidence


class OpenRouterOptionsV1(FrozenModel):
    """Body keys only OpenRouter understands; other endpoints never get them.

    ``reasoning`` selects the documented off switch: ``enabled_false`` sends
    ``{"enabled": false}`` and ``effort_none`` sends ``{"effort": "none"}``.
    Hiding reasoning (``exclude``) is deliberately not offered because the
    model still reasons and is billed for it. A model whose reasoning is
    mandatory needs ``reasoning=None``, or the endpoint answers 400. A local
    vLLM or llama.cpp server wants a top-level ``reasoning_effort`` instead
    and must therefore run with ``openrouter=None``.
    """

    reasoning: Literal["enabled_false", "effort_none"] | None = "enabled_false"
    provider_order: tuple[str, ...] = Field(
        default=(), max_length=_MAX_PROVIDER_ROUTES
    )
    allow_fallbacks: bool = False
    require_parameters: bool = True
    data_collection: Literal["allow", "deny"] | None = None

    @field_validator("provider_order")
    @classmethod
    def validate_provider_order(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Accepts only unique lowercase provider slugs such as ``alibaba``."""
        if len(set(values)) != len(values):
            raise ValueError("provider_order must be unique")
        for value in values:
            if not _PROVIDER_SLUG_PATTERN.fullmatch(value):
                raise ValueError("provider_order entries must be slugs")
        return values


class RequestSettingsV1(FrozenModel):
    """Reproducibility-safe request configuration recorded with every batch.

    Credentials and endpoint addresses never belong here: this model is
    serialized into completion batches and may appear in reports.
    """

    model_id: str
    temperature: float = Field(default=0.0, ge=0, le=2, allow_inf_nan=False)
    seed: int | None = Field(default=17, ge=0, le=MAX_SEED, strict=True)
    max_output_tokens: int = Field(
        default=2048, ge=1, le=MAX_OUTPUT_TOKENS, strict=True
    )
    timeout_seconds: float = Field(
        default=120.0, gt=0, le=_MAX_TIMEOUT_SECONDS, allow_inf_nan=False
    )
    json_mode: bool = True
    openrouter: OpenRouterOptionsV1 | None = None

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        """Bounds the recorded provider model identifier."""
        return validate_text(value, MAX_METADATA_BYTES, "model_id")


class CompletionBatchV1(FrozenModel):
    """Raw model results plus the reproducibility-safe request configuration."""

    schema_version: Literal["completion-batch/1.0"] = "completion-batch/1.0"
    output_contract: OutputContractV1
    retrieval: RetrievalV1
    endpoint_kind: Literal["openai-compatible-chat-completions"] = ENDPOINT_KIND
    settings: RequestSettingsV1
    completions: tuple[CompletionV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_completion_ids(self) -> "CompletionBatchV1":
        """Rejects ambiguous duplicate completion keys."""
        item_ids = tuple(item.item_id for item in self.completions)
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("completion item IDs must be unique")
        return self


class CatalogIdentityV1(FrozenModel):
    """The frozen field catalog the prepared prompts were built against."""

    file_name: str
    file_sha256: str
    sqlite_sha256: str
    catalog_hash: str
    tshark_version: str


class PreparedConditionV1(FrozenModel):
    """One published prompt file and the two digests that pin its content.

    ``sha256`` is the SHA-256 of the published file's bytes exactly as
    written: UTF-8, LF endings, canonical JSON plus one trailing newline.
    ``system_prompt_sha256`` is the content hash of the system message
    string itself, so writer and reader cannot drift on either digest.
    """

    label: ConditionLabel
    output_contract: OutputContractV1
    retrieval: RetrievalV1
    path: str
    sha256: str
    system_prompt_sha256: str
    prompt_count: int = Field(ge=1, le=64)


class PrepareManifestV1(FrozenModel):
    """Everything the preparation step fixed before any request was sent.

    ``split`` is deliberately ``Literal["dev"]``. The protocol's strongest
    prohibition is that no held-out item reaches a model before the freeze
    commit, and this type makes a held-out manifest unconstructible rather
    than one script constant away. Widening it is a one-token, reviewed
    edit in the slice that performs the freeze.
    """

    schema_version: Literal["model-prepare/1.0"] = "model-prepare/1.0"
    prepare_id: str
    created_at: datetime
    source_revision: str
    source_files: dict[str, str]
    split: Literal["dev"]
    item_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    model_inputs_sha256: str
    catalog: CatalogIdentityV1
    top_k: int = Field(ge=1, le=32)
    empty_context_item_ids: tuple[str, ...] = ()
    conditions: tuple[PreparedConditionV1, ...] = Field(
        min_length=1, max_length=4
    )

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """Requires an aware timestamp and stores it as UTC."""
        return _utc(value)


class TokenPricesV1(FrozenModel):
    """Recorded token prices, the only basis for a derived cost figure."""

    usd_per_million_input: float = Field(ge=0, le=1000, allow_inf_nan=False)
    usd_per_million_output: float = Field(ge=0, le=1000, allow_inf_nan=False)
    source: str

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        """Bounds the recorded price provenance note."""
        validate_utf8(value, MAX_METADATA_BYTES, "price source")
        return value


class InvocationV1(FrozenModel):
    """One bounded pass of the call step over the prepared batches."""

    source_revision: str
    source_files: dict[str, str]
    started_at: datetime
    finished_at: datetime
    max_usd: float = Field(gt=0, le=12, allow_inf_nan=False)
    requests_sent: int = Field(ge=0, le=4096, strict=True)
    stop_reason: (
        Literal["budget", "fatal_http", "thinking_not_honoured"] | None
    ) = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamps(cls, value: datetime) -> datetime:
        """Requires aware timestamps and stores them as UTC."""
        return _utc(value)


class ConditionRunV1(FrozenModel):
    """What one condition's call produced, file by file.

    The two file names are the condition's own, the completions pair is
    written or absent together, and the three counts census exactly the
    items the attempt log describes: a condition that cannot describe
    itself is not evidence, and is refused before it can be published.
    """

    label: ConditionLabel
    attempts_path: _AttemptsPath
    attempts_sha256: _Sha256
    completions_path: _CompletionsPath | None = None
    completions_sha256: _Sha256 | None = None
    attempts: dict[str, int] = Field(
        min_length=1, max_length=_MAX_ITEMS_PER_CONDITION
    )
    completed: int = Field(ge=0, le=_MAX_ITEMS_PER_CONDITION)
    failed: int = Field(ge=0, le=_MAX_ITEMS_PER_CONDITION)
    pending: int = Field(ge=0, le=_MAX_ITEMS_PER_CONDITION)

    @field_validator("attempts")
    @classmethod
    def validate_attempts(cls, value: dict[str, int]) -> dict[str, int]:
        """Keeps the per-item attempt census keyed and bounded."""
        for item_id, count in value.items():
            if not _MODEL_ITEM_ID_PATTERN.fullmatch(item_id):
                raise ValueError("attempt keys must be model item IDs")
            if not 0 <= count <= _MAX_ATTEMPTS_PER_ITEM:
                raise ValueError("attempt counts must be 0 to 3")
        return value

    @model_validator(mode="after")
    def validate_files_and_census(self) -> "ConditionRunV1":
        """Ties both file names and the three counts to this condition."""
        if (self.completions_path is None) != (self.completions_sha256 is None):
            raise ValueError("completions path and digest are written as one")
        if self.attempts_path != f"attempts/{self.label}.jsonl":
            raise ValueError("attempts_path must name its own condition")
        if self.completions_path is not None and (
            self.completions_path != f"completions/{self.label}.json"
        ):
            raise ValueError("completions_path must name its own condition")
        if self.completed + self.failed + self.pending != len(self.attempts):
            raise ValueError("the census must count every recorded item")
        return self


class RunManifestV1(FrozenModel):
    """The one run shape the call, scoring and publish steps all share.

    There is no top-level ``split`` and no top-level ``prepare_id``: both
    are read through ``prepare``. The endpoint URL and the API key never
    appear in this model; only ``endpoint_host`` does.

    A ``complete`` run is one that has nothing left to send and has
    published every condition's answers, and that claim is an invariant
    of this type rather than a note in a report: a directory whose
    manifest says complete while six items were never answered cannot
    be written.
    """

    schema_version: Literal["model-run/1.0"] = "model-run/1.0"
    run_id: str
    created_at: datetime
    prepare: PrepareManifestV1
    prepare_sha256: _Sha256
    endpoint_kind: Literal["openai-compatible-chat-completions"] = ENDPOINT_KIND
    endpoint_host: str
    settings: RequestSettingsV1
    prices: TokenPricesV1 | None = None
    max_attempts: int = Field(ge=1, le=_MAX_ATTEMPTS_PER_ITEM)
    min_interval_seconds: float = Field(ge=0, le=60, allow_inf_nan=False)
    token_bound_rule: Literal["utf8-bytes-plus-64"] = "utf8-bytes-plus-64"
    invocations: tuple[InvocationV1, ...] = Field(
        min_length=1, max_length=_MAX_INVOCATIONS
    )
    status: Literal["complete", "incomplete"]
    charged_usd_upper_bound: float = Field(
        ge=0, le=MAX_RECORDED_USD, allow_inf_nan=False
    )
    provider_reported_usd: float | None = Field(
        default=None, ge=0, le=MAX_RECORDED_USD, allow_inf_nan=False
    )
    conditions: tuple[ConditionRunV1, ...] = Field(min_length=1, max_length=4)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        """Requires an aware timestamp and stores it as UTC."""
        return _utc(value)

    @model_validator(mode="after")
    def validate_run_identity(self) -> "RunManifestV1":
        """Makes the split prefix of the run identifier an invariant."""
        if not self.run_id.startswith(f"{self.prepare.split}-"):
            raise ValueError("run_id must start with the prepared split")
        return self

    @model_validator(mode="after")
    def validate_completeness(self) -> "RunManifestV1":
        """Makes a complete run one that published every condition."""
        labels = [condition.label for condition in self.conditions]
        if len(set(labels)) != len(labels):
            raise ValueError("condition labels must be unique")
        if self.status == "complete" and any(
            condition.completions_path is None or condition.pending
            for condition in self.conditions
        ):
            raise ValueError("a complete run has published every condition")
        return self
