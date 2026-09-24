"""Host-side model run: prepare prompts, call the endpoint, publish a run.

Preparation and publication open no socket and read no evaluator gold: the
split is regenerated inside a temporary directory, only its model-visible
dev items are kept, and the gold contract is deleted with that directory
before the first prompt file is written.

The call step is the only one that opens a connection. It reads the
credential from the environment, sends each prepared prompt at most once
per pass, and writes neither the credential nor the endpoint URL into any
file it produces.
"""

# The three subcommands still share one file, which is over the size this
# project prefers. Splitting them is not a change to this file alone: the
# new modules have to join the type-checked and linted sets, the path
# loader the tests use has to reach them, and the prompt-building half
# must stay the file ``_MODEL_SIDE_FILES`` records, or every prepared
# directory is invalidated by the move alone.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from tempfile import TemporaryDirectory
import time
from typing import cast, Literal, NamedTuple, TextIO
from urllib.parse import urlsplit

from pydantic import Field
from pydantic import field_validator
from pydantic import model_validator
from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import open_frozen_catalog
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import ENDPOINT_KIND
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import MAX_RECORDED_USD
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import thinking_state
from dfilterforge.completions import TokenPricesV1
from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import FieldRetrievalResultV1
from dfilterforge.field_retrieval import retrieve_fields
from dfilterforge.generation import condition_label
from dfilterforge.generation import ConditionLabel
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.model_client import API_KEY_ENV
from dfilterforge.model_client import ModelClientError
from dfilterforge.model_client import OpenAiCompatibleBackend
from dfilterforge.model_split import generate_model_split
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.text_limits import validate_text

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_RESULT_DIR = re.compile(
    r"(dev|test)-[a-z0-9][a-z0-9.-]{0,31}-[0-9]{4}-[0-9]{2}-[0-9]{2}"
)
_ALLOWED_SPLIT = "dev"
_DEFAULT_TOP_K = 16
_MAX_TOP_K = 32
_FAILURE = 2
_MAX_PREPARE_BYTES = 1 << 20
_MAX_BATCH_BYTES = 8 << 20
_MAX_CONFIG_BYTES = 64 << 10
_MAX_ATTEMPT_LINE_BYTES = 512 << 10
_MAX_ENDPOINT_BYTES = 4096
_MAX_ATTEMPTS = 3
_MAX_USD = 12.0
_MAX_INTERVAL_SECONDS = 60.0
_MICRO_USD = 1_000_000
_TOKEN_BOUND_RULE = "utf8-bytes-plus-64"
_TOKEN_BOUND_SLACK = 64
_LABELS: tuple[ConditionLabel, ...] = ("C1", "C2", "C3", "C4")
# A credential problem or a refused account cannot be retried; a backlog
# or a server fault can. Everything else is a real answer to record.
_STOP_STATUSES = frozenset({401, 402, 403})
_RETRY_STATUSES = frozenset({408, 429})
_RETRY_CODES = frozenset({"timeout", "transport_error"})
_SCHEMA_MESSAGE = "Input does not match the required schema"
_IO_MESSAGE = "File operation failed"
# Every file that decides what a prompt contains. A change to any of them
# invalidates a prepare directory, which is why the digests are recorded.
_MODEL_SIDE_FILES: tuple[str, ...] = (
    "scripts/model_run.py",
    "src/dfilterforge/field_retrieval.py",
    "src/dfilterforge/generation.py",
    "src/dfilterforge/intent_ir.py",
    "src/dfilterforge/model_cases.py",
    "src/dfilterforge/model_dev_cases.py",
    "src/dfilterforge/model_split.py",
    "src/dfilterforge/model_test_cases.py",
)
# C1, C2, C3 and C4 in condition_label order.
_CONDITIONS: tuple[tuple[OutputContractV1, RetrievalV1], ...] = (
    (OutputContractV1.DISPLAY_FILTER, RetrievalV1.NONE),
    (OutputContractV1.DISPLAY_FILTER, RetrievalV1.LEXICAL),
    (OutputContractV1.TYPED_IR, RetrievalV1.NONE),
    (OutputContractV1.TYPED_IR, RetrievalV1.LEXICAL),
)
# Every file a published run directory carries, in written order. The
# prepare manifest travels with the run although the run manifest embeds
# the same fields: the offline scorer reads it as a standalone receipt,
# it is the only provenance a pass that answers the committed prompts
# from gold can have, and the run manifest records its digest, so the two
# are cross-checked here rather than trusted. The prompt files are read
# from the run directory because the call step copied them there.
_PUBLISHED_FILES: tuple[str, ...] = (
    "run_manifest.json",
    "prepare.json",
    *(f"prepared/{label}.json" for label in _LABELS),
    *(f"completions/{label}.json" for label in _LABELS),
    *(f"attempts/{label}.jsonl" for label in _LABELS),
)
# The published files a results directory may already hold, because the
# prompt set and its receipt are frozen and control-scored before any
# model is called. Each one is compared with the run that answers it, so
# a re-prepared prompt set or a receipt from another preparation cannot
# be published over a frozen one.
_FROZEN_FILES: tuple[str, ...] = (
    "prepare.json",
    *(f"prepared/{label}.json" for label in _LABELS),
)
# The receipt is a file at the run root, never inside ``prepared/``: the
# offline scorer reads ``prepared/`` as four condition files and refuses
# any other name there.
_PREEXISTING_DIRS = frozenset(
    {"prepared", "control-reference", "control-mutation"}
)
_PREEXISTING_ENTRIES = _PREEXISTING_DIRS | {"prepare.json"}
_MAX_PUBLISHED_BYTES = 8 << 20
_MIN_SECRET_BYTES = 8
# The shapes a credential takes inside a log or a reply. They are refused
# whether or not a key is exported, because publishing from a shell that
# never held one is the common case and would otherwise mean no scan.
_SECRET_PATTERNS: tuple[re.Pattern[bytes], ...] = (
    re.compile(rb"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"Bearer [A-Za-z0-9._-]{16,}"),
)


class RunError(DFilterForgeError, RuntimeError):
    """A model-run failure carrying only a stable code and safe text."""


def _print_error(code: str, message: str) -> None:
    """Writes the machine-readable error envelope to stderr."""
    envelope = {"error": {"code": code, "message": message}}
    print(canonical_json(envelope), file=sys.stderr)


def _source_revision(value: str) -> str:
    """Validates the human-readable revision supplied by the caller."""
    if _SOURCE_REVISION.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "source revision must be 1-128 safe, non-whitespace characters"
        )
    return value


def _top_k(value: str) -> int:
    """Validates the retrieval depth against the shared retrieval cap."""
    depth = int(value)
    if not 1 <= depth <= _MAX_TOP_K:
        raise argparse.ArgumentTypeError("top-k must be between 1 and 32")
    return depth


def _hash_text(text: str) -> str:
    """Returns the SHA-256 digest of one string's UTF-8 encoding."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: object) -> str:
    """Writes canonical JSON with LF endings and returns its digest."""
    text = canonical_json(value) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return _hash_text(text)


def _source_manifest() -> dict[str, str]:
    """Digests every source file that decides what a prompt contains.

    Returns:
        A mapping from repository-relative POSIX path to SHA-256 digest.

    Raises:
        RunError: If a recorded path is missing or is not a regular file.
    """
    digests: dict[str, str] = {}
    for name in _MODEL_SIDE_FILES:
        path = _PROJECT_ROOT / name
        if not path.is_file():
            raise RunError(
                "source_file_missing",
                "A recorded model-side source file is missing",
            )
        digests[name] = file_sha256(path)
    return digests


def _dev_items() -> tuple[tuple[ModelInputItemV1, ...], str]:
    """Regenerates the split and keeps only its model-visible dev items.

    The evaluator gold contract and the six captures are written into a
    temporary directory that is removed before this function returns, and
    neither is read. The recorded digest covers the parsed items of both
    splits rather than the file that held them, because the split writer
    uses platform line endings and a file digest would therefore name the
    same split differently on different hosts.

    Returns:
        The dev items in file order and the digest of the parsed split.

    Raises:
        RunError: If the regenerated split has no dev item.
    """
    with TemporaryDirectory(prefix="dfilterforge-model-split-") as staging:
        artifacts = generate_model_split(Path(staging))
        lines = artifacts.inputs_path.read_text(encoding="utf-8").splitlines()
        parsed = tuple(
            ModelInputItemV1.model_validate_json(line)
            for line in lines
            if line.strip()
        )
    items = tuple(item for item in parsed if item.split == _ALLOWED_SPLIT)
    if not items:
        raise RunError("split_empty", "The regenerated split has no dev items")
    return items, content_sha256(parsed)


def _retrieved(
    catalog: Path, items: Sequence[ModelInputItemV1], top_k: int
) -> tuple[CatalogIdentityV1, tuple[FieldRetrievalResultV1, ...]]:
    """Runs one retrieval pass and records the catalog that answered it.

    Args:
        catalog: A frozen ``.sqlite3`` inventory or a ``.gz`` archive of one.
        items: The dev items whose intents are the retrieval queries.
        top_k: Maximum candidate fields per item.

    Returns:
        The catalog identity and one result per item, in item order.

    Raises:
        RunError: If a result does not correlate with its item.
    """
    with open_frozen_catalog(catalog) as frozen:
        queries = tuple(
            FieldRetrievalItemV1(item_id=item.item_id, intent=item.intent)
            for item in items
        )
        results = retrieve_fields(frozen.sqlite_path, queries, top_k=top_k)
        identity = CatalogIdentityV1(
            file_name=frozen.file_name,
            file_sha256=frozen.file_sha256,
            sqlite_sha256=frozen.sqlite_sha256,
            catalog_hash=frozen.catalog_hash,
            tshark_version=frozen.tshark_version,
        )
    for item, result in zip(items, results, strict=True):
        if result.item_id != item.item_id:
            raise RunError(
                "retrieval_misaligned",
                "Retrieval results are not aligned with the split",
            )
    return identity, results


def _generation_inputs(
    items: Sequence[ModelInputItemV1],
    results: Sequence[FieldRetrievalResultV1],
) -> tuple[tuple[GenerationInputV1, ...], tuple[GenerationInputV1, ...]]:
    """Builds the no-retrieval and lexical item lists for one split.

    A lexical item carries the retrieved tuple even when it is empty, which
    is the difference between context that matched nothing and no retrieval
    at all; a no-retrieval item carries none.

    Args:
        items: The dev items in file order.
        results: One retrieval result per item, in the same order.

    Returns:
        The no-retrieval items and the lexical items, both in item order.
    """
    none_inputs: list[GenerationInputV1] = []
    lexical_inputs: list[GenerationInputV1] = []
    for item, result in zip(items, results, strict=True):
        none_inputs.append(
            GenerationInputV1(
                item_id=item.item_id,
                intent=item.intent,
                user_assumptions=item.user_assumptions,
                split=item.split,
            )
        )
        lexical_inputs.append(
            GenerationInputV1(
                item_id=item.item_id,
                intent=item.intent,
                user_assumptions=item.user_assumptions,
                retrieved_fields=result.fields,
                split=item.split,
            )
        )
    return tuple(none_inputs), tuple(lexical_inputs)


def _write_conditions(
    prepared_dir: Path,
    none_inputs: Sequence[GenerationInputV1],
    lexical_inputs: Sequence[GenerationInputV1],
) -> tuple[PreparedConditionV1, ...]:
    """Writes one hashed prompt file per condition, in protocol order.

    Args:
        prepared_dir: Existing directory that receives ``C1.json`` to
            ``C4.json``.
        none_inputs: Items prepared for the no-retrieval conditions.
        lexical_inputs: Items prepared for the lexical conditions.

    Returns:
        One record per written file, in protocol order.

    Raises:
        RunError: If a prompt is not a dev prompt, or if one condition
            produced more than one system prompt.
    """
    conditions: list[PreparedConditionV1] = []
    for contract, retrieval in _CONDITIONS:
        label: ConditionLabel = condition_label(contract, retrieval)
        lexical = retrieval is RetrievalV1.LEXICAL
        batch = prepare_batch(
            lexical_inputs if lexical else none_inputs,
            output_contract=contract,
            retrieval=retrieval,
        )
        if any(prompt.split != _ALLOWED_SPLIT for prompt in batch.prompts):
            raise RunError(
                "split_refused", "A prepared prompt is not from the dev split"
            )
        systems = {prompt.messages[0].content for prompt in batch.prompts}
        if len(systems) != 1:
            raise RunError(
                "system_prompt_unstable",
                "One condition produced more than one system prompt",
            )
        digest = _write_json(prepared_dir / f"{label}.json", batch)
        conditions.append(
            PreparedConditionV1(
                label=label,
                output_contract=contract,
                retrieval=retrieval,
                path=f"prepared/{label}.json",
                sha256=digest,
                system_prompt_sha256=_hash_text(systems.pop()),
                prompt_count=len(batch.prompts),
            )
        )
    return tuple(conditions)


def _build_prepare(
    staging: Path,
    arguments: argparse.Namespace,
    items: Sequence[ModelInputItemV1],
    source_files: dict[str, str],
    model_inputs_sha256: str,
) -> PrepareManifestV1:
    """Fills one staged prepare directory and returns its manifest.

    Args:
        staging: Directory holding an empty ``prepared`` subdirectory.
        arguments: The parsed ``prepare`` arguments.
        items: The dev items in file order.
        source_files: Digests of the files that decide prompt content.
        model_inputs_sha256: Digest of the parsed split.

    Returns:
        The manifest that was written to ``prepare.json``.
    """
    catalog = cast(Path, arguments.catalog)
    top_k = cast(int, arguments.top_k)
    identity, results = _retrieved(catalog, items, top_k)
    none_inputs, lexical_inputs = _generation_inputs(items, results)
    conditions = _write_conditions(
        staging / "prepared", none_inputs, lexical_inputs
    )
    manifest = PrepareManifestV1(
        prepare_id=cast(Path, arguments.output_dir).name,
        created_at=datetime.now(timezone.utc),
        source_revision=cast(str, arguments.source_revision),
        source_files=source_files,
        split=_ALLOWED_SPLIT,
        item_ids=tuple(item.item_id for item in items),
        model_inputs_sha256=model_inputs_sha256,
        catalog=identity,
        top_k=top_k,
        empty_context_item_ids=tuple(
            result.item_id for result in results if not result.fields
        ),
        conditions=conditions,
    )
    _write_json(staging / "prepare.json", manifest)
    return manifest


def _prepare(arguments: argparse.Namespace) -> int:
    """Writes four hashed prompt files and their manifest, without network.

    Args:
        arguments: The parsed ``prepare`` arguments.

    Returns:
        The process exit code.

    Raises:
        RunError: If the output name is unusable, the directory already
            exists, or preparation cannot be completed.
    """
    output_dir = cast(Path, arguments.output_dir)
    prepare_id = output_dir.name
    if _IDENTIFIER.fullmatch(prepare_id) is None:
        raise RunError(
            "prepare_id_invalid",
            "The output directory name is not a valid prepare id",
        )
    if output_dir.exists():
        raise RunError("output_exists", "The prepare directory already exists")
    source_files = _source_manifest()
    items, model_inputs_sha256 = _dev_items()
    staging = output_dir.parent / f".{prepare_id}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    (staging / "prepared").mkdir(parents=True)
    try:
        manifest = _build_prepare(
            staging, arguments, items, source_files, model_inputs_sha256
        )
        try:
            staging.rename(output_dir)
        except OSError:
            raise RunError(
                "output_exists", "The prepare directory already exists"
            ) from None
    except BaseException:
        # A half-written prepare directory must never be publishable.
        shutil.rmtree(staging, ignore_errors=True)
        raise
    print(
        canonical_json(
            {
                "prepare_id": prepare_id,
                "output_dir": output_dir.as_posix(),
                "items": len(items),
                "top_k": manifest.top_k,
                "empty_contexts": len(manifest.empty_context_item_ids),
                "conditions": {
                    condition.label: condition.sha256
                    for condition in manifest.conditions
                },
            }
        )
    )
    return 0


class CallConfigV1(FrozenModel):
    """The endpoint, request settings and token prices of one call.

    This file is user-local. It is never copied into a run directory and
    is never published, because it is the only place the endpoint URL is
    written down; a run manifest keeps the bare host name instead.
    """

    endpoint_url: str
    settings: RequestSettingsV1
    prices: TokenPricesV1

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, value: str) -> str:
        """Bounds the address before the client is asked to parse it."""
        return validate_text(value, _MAX_ENDPOINT_BYTES, "endpoint_url")

    @model_validator(mode="after")
    def validate_prices(self) -> "CallConfigV1":
        """Refuses prices that would make the spend cap unenforceable.

        The pre-request bound is derived from these two rates alone, so a
        pair of zeros, or rates written per token instead of per million,
        lets every request pass a cap of any size. A free endpoint is
        therefore configured with a nominal price, not with none.
        """
        rates = (
            self.prices.usd_per_million_input,
            self.prices.usd_per_million_output,
        )
        if sum(rates) <= 0:
            raise ValueError("token prices must make a request cost something")
        return self


class AttemptV1(FrozenModel):
    """One request sent once, with what it was charged for sending.

    An attempt is appended and fsynced before the next request starts, so
    a crash can lose at most the answer that was in flight.
    """

    attempt: int = Field(ge=1, le=_MAX_ATTEMPTS)
    sent_at: datetime
    charged_micro_usd: int = Field(ge=0)
    completion: CompletionV1

    @field_validator("sent_at")
    @classmethod
    def validate_sent_at(cls, value: datetime) -> datetime:
        """Requires an aware timestamp and stores it as UTC."""
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)


# Every attempt of every prepared prompt, keyed by condition then item.
_AttemptLog = dict[ConditionLabel, dict[str, list[AttemptV1]]]
_PromptState = Literal["completed", "pending", "failed"]


class _CallOptions(NamedTuple):
    """The bounded command-line arguments of one call pass."""

    run_id: str
    source_revision: str
    max_usd: float
    max_attempts: int
    min_interval_seconds: float
    resume: bool
    gate_first: bool


class _CallPlan(NamedTuple):
    """Everything one call checked before it opened a socket."""

    options: _CallOptions
    run_dir: Path
    prepare: PrepareManifestV1
    prepare_bytes: bytes
    config: CallConfigV1
    batches: dict[ConditionLabel, PreparedBatchV1]
    raw: dict[ConditionLabel, bytes]

    @property
    def prepare_sha256(self) -> str:
        """Returns the digest of the prepare manifest as it was read."""
        return hashlib.sha256(self.prepare_bytes).hexdigest()


_StopReason = Literal["budget", "fatal_http", "thinking_not_honoured"]


@dataclass
class _PassState:
    """What one pass has spent and why it stopped, if it stopped.

    ``gated`` records that the first completed answer of this pass has
    already been through the reasoning gate, which runs once.
    """

    spent_micro_usd: int
    started_at: datetime
    requests_sent: int = 0
    stop_reason: _StopReason | None = None
    last_start: float | None = None
    gated: bool = False


def _monotonic() -> float:
    """Reads the pacing clock through a seam the tests can replace."""
    return time.monotonic()


def _sleep(seconds: float) -> None:
    """Waits through a seam the tests can replace."""
    time.sleep(seconds)


def _prompt_bytes(prompt: PreparedPromptV1) -> int:
    """Returns the UTF-8 size of both messages of one prepared prompt."""
    return sum(
        len(message.content.encode("utf-8")) for message in prompt.messages
    )


def _prompt_token_bound(prompt: PreparedPromptV1) -> int:
    """Bounds the prompt tokens a provider can charge for.

    One token never spans fewer than one UTF-8 byte, so the byte count is
    an upper bound on the tokenized prompt; the slack covers the chat
    template bytes the provider adds around the two messages.
    """
    return _prompt_bytes(prompt) + _TOKEN_BOUND_SLACK


def _worst_case_micro_usd(
    prompt: PreparedPromptV1,
    prices: TokenPricesV1,
    settings: RequestSettingsV1,
) -> int:
    """Returns the most one request for this prompt could cost.

    Cost is integer micro-USD throughout, because a price is stated per
    million tokens and ``tokens * usd_per_million`` is exactly micro-USD.
    """
    return math.ceil(
        _prompt_token_bound(prompt) * prices.usd_per_million_input
        + settings.max_output_tokens * prices.usd_per_million_output
    )


def _charge_micro_usd(
    completion: CompletionV1,
    prompt: PreparedPromptV1,
    config: CallConfigV1,
    worst_case: int,
) -> int:
    """Charges one attempt, never below what the provider may bill.

    The rule, in order: a provider-reported cost wins; otherwise reported
    token counts are priced, with the unreported side replaced by its own
    upper bound; otherwise an answered or timed-out request is charged its
    whole worst case, because the provider may have generated before the
    answer was lost; otherwise nothing was generated and nothing is
    charged. The prompt bound is ``utf8-bytes-plus-64``, and ``worst_case``
    is this prompt's pre-request bound.
    """
    prices = config.prices
    if completion.cost_usd is not None:
        return math.ceil(completion.cost_usd * _MICRO_USD)
    reported = (completion.prompt_tokens, completion.completion_tokens)
    if any(count is not None for count in reported):
        prompt_tokens = (
            _prompt_token_bound(prompt)
            if completion.prompt_tokens is None
            else completion.prompt_tokens
        )
        output_tokens = (
            config.settings.max_output_tokens
            if completion.completion_tokens is None
            else completion.completion_tokens
        )
        return math.ceil(
            prompt_tokens * prices.usd_per_million_input
            + output_tokens * prices.usd_per_million_output
        )
    if (
        completion.error_code in _RETRY_CODES
        or completion.status is CompletionStatusV1.COMPLETED
    ):
        return worst_case
    return 0


def _retry_class(
    completion: CompletionV1,
) -> Literal["final", "retry", "stop"]:
    """Decides whether one recorded attempt may be sent again.

    A ``stop`` attempt ends the invocation immediately and is re-sent by
    the next resume; a ``final`` attempt is never re-sent. ``provider_error``
    and ``empty_content`` are deliberately final: they are answers the
    model gave, not transport faults, and re-sending them would spend the
    budget on the same answer.
    """
    if completion.status is CompletionStatusV1.COMPLETED:
        return "final"
    status = completion.http_status
    if status in _STOP_STATUSES:
        return "stop"
    if completion.error_code in _RETRY_CODES:
        return "retry"
    if status is not None and (status in _RETRY_STATUSES or status >= 500):
        return "retry"
    return "final"


def _is_settled(entries: Sequence[AttemptV1], max_attempts: int) -> bool:
    """Reports whether one prompt must not be sent again in this pass."""
    if not entries:
        return False
    return (
        _retry_class(entries[-1].completion) == "final"
        or len(entries) >= max_attempts
    )


def _prompt_state(
    entries: Sequence[AttemptV1], max_attempts: int
) -> _PromptState:
    """Classifies one prompt so the three census counts always sum.

    A prompt is ``pending`` while a further attempt is owed and ``failed``
    on a final failure or an exhausted transient one.
    """
    if not entries:
        return "pending"
    last = entries[-1].completion
    if last.status is CompletionStatusV1.COMPLETED:
        return "completed"
    retryable = _retry_class(last) in ("retry", "stop")
    if retryable and len(entries) < max_attempts:
        return "pending"
    return "failed"


def _read_bounded(path: Path, limit: int, code: str, missing: str) -> bytes:
    """Reads one file, refusing an absent or oversized input by code.

    Every input of a call carries its own refusal, so an operator never
    has to read a generic ``io_error`` to learn which file was not there.

    Raises:
        RunError: With ``missing``, if the path is not a regular file;
            with ``code``, if the file is larger than ``limit``.
    """
    if not path.is_file():
        raise RunError(missing, "A required file is missing")
    if path.stat().st_size > limit:
        raise RunError(code, "A recorded file is larger than its bound")
    return path.read_bytes()


def _attempt_lines(path: Path) -> tuple[AttemptV1, ...]:
    """Reads one attempt log, oldest attempt first.

    The log need not exist yet.

    Raises:
        RunError: If the log is torn, oversized, or unreadable.
    """
    if not path.exists():
        return ()
    return _attempt_records(
        _read_bounded(
            path, _MAX_BATCH_BYTES, "attempt_log_invalid", "attempt_log_invalid"
        )
    )


def _attempt_records(data: bytes) -> tuple[AttemptV1, ...]:
    """Parses one attempt log's bytes, oldest attempt first.

    The rule that a log ends on a whole line is stated here alone, so the
    call step that resumes a run and the publish step that copies it can
    never disagree about what a torn log is.

    Raises:
        RunError: If the log is torn or holds a line that is not usable.
    """
    if not data:
        return ()
    if not data.endswith(b"\n"):
        raise RunError(
            "attempt_log_invalid", "An attempt log ends with a torn line"
        )
    attempts: list[AttemptV1] = []
    for line in data.split(b"\n")[:-1]:
        if len(line) > _MAX_ATTEMPT_LINE_BYTES:
            raise RunError(
                "attempt_log_invalid", "An attempt log line is too large"
            )
        try:
            attempts.append(AttemptV1.model_validate_json(line))
        except ValidationError:
            raise RunError(
                "attempt_log_invalid", "An attempt log line is not usable"
            ) from None
    return tuple(attempts)


def _append_attempt(handle: TextIO, attempt: AttemptV1) -> None:
    """Appends one attempt and makes it durable before the next request."""
    handle.write(canonical_json(attempt) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _ordered_labels(
    batches: dict[ConditionLabel, PreparedBatchV1],
) -> tuple[ConditionLabel, ...]:
    """Returns the prepared conditions in protocol order."""
    return tuple(label for label in _LABELS if label in batches)


def _spent_micro_usd(attempts: _AttemptLog) -> int:
    """Sums what every attempt already on disk was charged."""
    return sum(
        attempt.charged_micro_usd
        for history in attempts.values()
        for entries in history.values()
        for attempt in entries
    )


def _recorded_usd(value: float) -> float:
    """Rounds one money figure and saturates it at the recorded ceiling.

    A run that has already been paid for must always be writable, so no
    provider number can push a recorded total past the bound the manifest
    declares. The per-attempt charges in the logs are never clamped.
    """
    return min(round(value, 8), MAX_RECORDED_USD)


def _provider_reported_usd(attempts: _AttemptLog) -> float | None:
    """Sums the costs the provider reported, or None when it reported none."""
    costs = [
        attempt.completion.cost_usd
        for history in attempts.values()
        for entries in history.values()
        for attempt in entries
        if attempt.completion.cost_usd is not None
    ]
    return _recorded_usd(math.fsum(costs)) if costs else None


def _endpoint_host(config: CallConfigV1) -> str:
    """Returns the bare host of the endpoint, never its full address."""
    return urlsplit(config.endpoint_url).hostname or ""


def _call_options(arguments: argparse.Namespace) -> _CallOptions:
    """Bounds every call argument before anything is read or opened.

    Raises:
        RunError: If a budget, ceiling, interval or run id is unusable.
    """
    options = _CallOptions(
        run_id=cast(str, arguments.run_id),
        source_revision=cast(str, arguments.source_revision),
        max_usd=float(cast(float, arguments.max_usd)),
        max_attempts=int(cast(int, arguments.max_attempts)),
        min_interval_seconds=float(cast(float, arguments.min_interval_seconds)),
        resume=bool(arguments.resume),
        gate_first=bool(arguments.gate_first),
    )
    if not 0 < options.max_usd <= _MAX_USD:
        raise RunError(
            "budget_invalid", "The run budget is outside the project cap"
        )
    if not 1 <= options.max_attempts <= _MAX_ATTEMPTS:
        raise RunError(
            "max_attempts_invalid",
            "The attempt ceiling is outside the protocol bound",
        )
    if not 0 <= options.min_interval_seconds <= _MAX_INTERVAL_SECONDS:
        raise RunError(
            "interval_invalid", "The pacing interval is outside its bound"
        )
    if _RESULT_DIR.fullmatch(options.run_id) is None:
        raise RunError(
            "run_id_invalid", "The run id is not a usable result name"
        )
    return options


def _read_prepare(prepare_dir: Path) -> tuple[PrepareManifestV1, bytes]:
    """Reads the prepare manifest and the exact bytes it came from.

    A hand-edited manifest naming the held-out split is refused here,
    before an endpoint object exists, because the manifest type admits
    only the dev split.

    Raises:
        RunError: If the manifest is oversized or unusable.
    """
    data = _read_bounded(
        prepare_dir / "prepare.json",
        _MAX_PREPARE_BYTES,
        "prepare_too_large",
        "prepare_invalid",
    )
    try:
        manifest = PrepareManifestV1.model_validate_json(data)
    except ValidationError:
        raise RunError(
            "prepare_invalid", "The prepare manifest is not usable"
        ) from None
    return manifest, data


def _read_prepared(
    prepare_dir: Path, manifest: PrepareManifestV1
) -> tuple[dict[ConditionLabel, PreparedBatchV1], dict[ConditionLabel, bytes]]:
    """Reads every recorded prompt file and checks it against the manifest.

    The parsed batches and their exact bytes are both keyed by label.

    Raises:
        RunError: If a file is oversized, altered, prepared for another
            condition, or holds a prompt from another split.
    """
    batches: dict[ConditionLabel, PreparedBatchV1] = {}
    raw: dict[ConditionLabel, bytes] = {}
    for condition in manifest.conditions:
        data = _read_bounded(
            prepare_dir / condition.path,
            _MAX_BATCH_BYTES,
            "prepare_too_large",
            "prepare_hash_mismatch",
        )
        if hashlib.sha256(data).hexdigest() != condition.sha256:
            raise RunError(
                "prepare_hash_mismatch",
                "A prepared prompt file does not match its digest",
            )
        try:
            batch = PreparedBatchV1.model_validate_json(data)
        except ValidationError:
            raise RunError(
                "prepare_invalid", "A prepared prompt file is not usable"
            ) from None
        if condition_label(batch.output_contract, batch.retrieval) != (
            condition.label
        ):
            raise RunError(
                "condition_mismatch",
                "A prepared prompt file names another condition",
            )
        if any(prompt.split != manifest.split for prompt in batch.prompts):
            raise RunError(
                "split_refused", "A prepared prompt is not from that split"
            )
        batches[condition.label] = batch
        raw[condition.label] = data
    return batches, raw


def _read_config(path: Path) -> CallConfigV1:
    """Reads the user-local endpoint, settings and prices.

    Raises:
        RunError: If the file is oversized or unusable.
    """
    data = _read_bounded(
        path, _MAX_CONFIG_BYTES, "config_too_large", "config_invalid"
    )
    try:
        return CallConfigV1.model_validate_json(data)
    except ValidationError:
        raise RunError(
            "config_invalid", "The call configuration is not usable"
        ) from None


def _call_plan(arguments: argparse.Namespace) -> _CallPlan:
    """Performs every refusal that must precede the first request.

    Raises:
        RunError: If any recorded input, credential or directory is not
            what this pass requires.
    """
    options = _call_options(arguments)
    prepare_dir = cast(Path, arguments.prepare_dir)
    prepare, prepare_bytes = _read_prepare(prepare_dir)
    if options.run_id.split("-", 1)[0] != prepare.split:
        raise RunError(
            "split_mismatch", "The run id does not name the prepared split"
        )
    batches, raw = _read_prepared(prepare_dir, prepare)
    if _source_manifest() != prepare.source_files:
        raise RunError(
            "prepare_code_mismatch",
            "Model-side source files changed since preparation",
        )
    config = _read_config(cast(Path, arguments.config))
    if not os.environ.get(API_KEY_ENV):
        raise RunError("api_key_missing", "The model API credential is not set")
    return _CallPlan(
        options=options,
        run_dir=_run_directory(prepare_dir, options),
        prepare=prepare,
        prepare_bytes=prepare_bytes,
        config=config,
        batches=batches,
        raw=raw,
    )


def _run_directory(prepare_dir: Path, options: _CallOptions) -> Path:
    """Locates this run's directory without creating anything.

    Raises:
        RunError: If a fresh pass would overwrite a run, or a resumed
            pass has no run to continue.
    """
    run_dir = prepare_dir / "runs" / options.run_id
    if options.resume:
        if not run_dir.is_dir():
            raise RunError("run_missing", "The run directory does not exist")
    elif run_dir.exists():
        raise RunError("run_exists", "The run directory already exists")
    return run_dir


def _backend(config: CallConfigV1) -> OpenAiCompatibleBackend:
    """Builds the bounded client without contacting anyone.

    Raises:
        RunError: If the endpoint or the credential is unusable.
    """
    try:
        return OpenAiCompatibleBackend(config.endpoint_url, config.settings)
    except ModelClientError:
        raise RunError(
            "endpoint_invalid", "The configured model endpoint is unusable"
        ) from None


def _previous_run(plan: _CallPlan) -> RunManifestV1 | None:
    """Reads the manifest a resumed pass must agree with.

    Returns None when this pass is not a resume.

    Raises:
        RunError: If that manifest is unusable, or was written for a
            different prompt set, endpoint, settings, prices or bounds.
    """
    if not plan.options.resume:
        return None
    data = _read_bounded(
        plan.run_dir / "run_manifest.json",
        _MAX_BATCH_BYTES,
        "run_manifest_invalid",
        "run_manifest_invalid",
    )
    try:
        manifest = RunManifestV1.model_validate_json(data)
    except ValidationError:
        raise RunError(
            "run_manifest_invalid", "The run manifest is not usable"
        ) from None
    if (
        manifest.prepare_sha256,
        manifest.endpoint_host,
        manifest.settings,
        manifest.prices,
        manifest.max_attempts,
        manifest.min_interval_seconds,
    ) != (
        plan.prepare_sha256,
        _endpoint_host(plan.config),
        plan.config.settings,
        plan.config.prices,
        plan.options.max_attempts,
        plan.options.min_interval_seconds,
    ):
        raise RunError(
            "settings_changed", "The resumed run was configured differently"
        )
    return manifest


def _copy_prepared(plan: _CallPlan) -> None:
    """Copies the prompt set and its manifest into the run directory.

    A run directory that carries its own prompts and their provenance can
    be verified without the working area that produced them, which is what
    makes a published run replayable and scorable on its own.

    Raises:
        RunError: If a copy already present differs from what is prepared.
    """
    copies: dict[str, bytes] = {"prepare.json": plan.prepare_bytes}
    copies.update(
        {f"prepared/{label}.json": data for label, data in plan.raw.items()}
    )
    for name, data in copies.items():
        path = plan.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        elif path.read_bytes() != data:
            raise RunError(
                "prepare_hash_mismatch",
                "A copied prompt file does not match the prepared bytes",
            )


def _existing_attempts(plan: _CallPlan) -> _AttemptLog:
    """Loads every attempt this run already recorded.

    Returns one list per prepared prompt, oldest attempt first.

    Raises:
        RunError: If a log is unusable or names an unprepared item.
    """
    attempts: _AttemptLog = {}
    for label in _ordered_labels(plan.batches):
        history: dict[str, list[AttemptV1]] = {
            prompt.item_id: [] for prompt in plan.batches[label].prompts
        }
        log = plan.run_dir / "attempts" / f"{label}.jsonl"
        for attempt in _attempt_lines(log):
            item_id = attempt.completion.item_id
            if item_id not in history:
                raise RunError(
                    "attempt_log_invalid",
                    "An attempt log names an unprepared item",
                )
            history[item_id].append(attempt)
        attempts[label] = history
    return attempts


class _CallPass:
    """One greedy pass over the prepared prompts, bounded by a spend cap."""

    __slots__ = ("_attempts", "_backend", "_cap", "_plan", "_state")

    def __init__(
        self,
        backend: OpenAiCompatibleBackend,
        plan: _CallPlan,
        attempts: _AttemptLog,
        state: _PassState,
    ) -> None:
        """Binds one pass to the run it continues.

        ``attempts`` holds every attempt already recorded and is extended
        in place as this pass sends, and ``state`` carries what the run
        had already spent when this pass began.
        """
        self._backend = backend
        self._plan = plan
        self._attempts = attempts
        self._cap = round(plan.options.max_usd * _MICRO_USD)
        self._state = state

    def run(self) -> _PassState:
        """Sends what this pass can afford and reports what it spent.

        Every condition's log exists before the first request, so a
        condition the pass never reaches still has a log to hash.
        """
        directory = self._plan.run_dir / "attempts"
        labels = _ordered_labels(self._plan.batches)
        with ExitStack() as stack:
            handles = {
                label: stack.enter_context(
                    (directory / f"{label}.jsonl").open(
                        "a", encoding="utf-8", newline="\n"
                    )
                )
                for label in labels
            }
            for label in labels:
                if not self._condition(label, handles[label]):
                    break
        return self._state

    def _condition(self, label: ConditionLabel, handle: TextIO) -> bool:
        """Sends one condition's outstanding prompts, in file order.

        The handle is its append-mode log, fsynced after every attempt.

        Returns:
            True when the pass may continue, False when it must stop.
        """
        batch = self._plan.batches[label]
        history = self._attempts[label]
        config = self._plan.config
        for prompt in batch.prompts:
            entries = history[prompt.item_id]
            if _is_settled(entries, self._plan.options.max_attempts):
                continue
            worst = _worst_case_micro_usd(
                prompt, config.prices, config.settings
            )
            if self._state.spent_micro_usd + worst > self._cap:
                self._state.stop_reason = "budget"
                return False
            attempt = self._attempt(batch, prompt, len(entries) + 1, worst)
            _append_attempt(handle, attempt)
            entries.append(attempt)
            self._state.spent_micro_usd += attempt.charged_micro_usd
            self._state.requests_sent += 1
            if _retry_class(attempt.completion) == "stop":
                self._state.stop_reason = "fatal_http"
                return False
            if self._gate(attempt.completion):
                return False
        return True

    def _gate(self, completion: CompletionV1) -> bool:
        """Stops the pass when the first answer shows thinking was on.

        The gate reads the first completed answer of the pass and nothing
        else: the point of a first run is that its settings are known,
        and discovering after sixty-four requests that the reasoning
        control was ignored spends the budget on a comparison that cannot
        be made. Stopping here costs one request. A run the gate stopped
        is over: the provider or model is changed and a new run starts,
        rather than resuming this one with the gate off.

        Returns:
            True when this pass must stop before sending anything more.
        """
        if self._state.gated or not self._plan.options.gate_first:
            return False
        if completion.status is not CompletionStatusV1.COMPLETED:
            return False
        self._state.gated = True
        if thinking_state((completion,))[0] != "not_honoured":
            return False
        self._state.stop_reason = "thinking_not_honoured"
        return True

    def _attempt(
        self,
        batch: PreparedBatchV1,
        prompt: PreparedPromptV1,
        number: int,
        worst: int,
    ) -> AttemptV1:
        """Paces, sends one prompt exactly once, and prices the answer.

        ``number`` is the ordinal of this attempt for that prompt and
        ``worst`` is its pre-request cost bound.
        """
        last = self._state.last_start
        if last is not None:
            remaining = self._plan.options.min_interval_seconds - (
                _monotonic() - last
            )
            if remaining > 0:
                _sleep(remaining)
        self._state.last_start = _monotonic()
        sent_at = datetime.now(timezone.utc)
        single = PreparedBatchV1(
            output_contract=batch.output_contract,
            retrieval=batch.retrieval,
            prompts=(prompt,),
        )
        completion = self._backend.complete(single).completions[0]
        return AttemptV1(
            attempt=number,
            sent_at=sent_at,
            charged_micro_usd=_charge_micro_usd(
                completion, prompt, self._plan.config, worst
            ),
            completion=completion,
        )


def _write_completions(
    plan: _CallPlan,
    label: ConditionLabel,
    history: dict[str, list[AttemptV1]],
) -> tuple[str, str]:
    """Writes one condition's last answers as a scorable batch.

    Returns the recorded relative path and the digest of the bytes.
    """
    batch = plan.batches[label]
    record = CompletionBatchV1(
        output_contract=batch.output_contract,
        retrieval=batch.retrieval,
        settings=plan.config.settings,
        completions=tuple(
            history[prompt.item_id][-1].completion for prompt in batch.prompts
        ),
    )
    path = plan.run_dir / "completions" / f"{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        canonical_json(record) + "\n", encoding="utf-8", newline="\n"
    )
    return f"completions/{label}.json", file_sha256(path)


def _condition_run(
    plan: _CallPlan,
    label: ConditionLabel,
    history: dict[str, list[AttemptV1]],
    publish: bool,
) -> ConditionRunV1:
    """Censuses one condition and publishes its answers when it is done.

    With ``publish`` false nothing is written and no condition claims a
    completions file, which is the shape of the anchor a pass records
    before its first request.

    Returns what this condition contributes to the run manifest.
    """
    max_attempts = plan.options.max_attempts
    prompts = plan.batches[label].prompts
    states = tuple(
        _prompt_state(history[prompt.item_id], max_attempts)
        for prompt in prompts
    )
    pending = states.count("pending")
    written = (
        _write_completions(plan, label, history)
        if publish and pending == 0
        else None
    )
    log = plan.run_dir / "attempts" / f"{label}.jsonl"
    return ConditionRunV1(
        label=label,
        attempts_path=f"attempts/{label}.jsonl",
        attempts_sha256=file_sha256(log),
        completions_path=None if written is None else written[0],
        completions_sha256=None if written is None else written[1],
        attempts={
            prompt.item_id: len(history[prompt.item_id]) for prompt in prompts
        },
        completed=states.count("completed"),
        failed=states.count("failed"),
        pending=pending,
    )


def _open_logs(plan: _CallPlan) -> None:
    """Creates every condition's attempt log before the anchor is written."""
    directory = plan.run_dir / "attempts"
    directory.mkdir(parents=True, exist_ok=True)
    for label in _ordered_labels(plan.batches):
        (directory / f"{label}.jsonl").touch()


def _write_manifest(run_dir: Path, manifest: RunManifestV1) -> None:
    """Replaces the run manifest with one atomic rename."""
    staging = run_dir / ".run_manifest.json.partial"
    staging.write_text(
        canonical_json(manifest) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(staging, run_dir / "run_manifest.json")


def _record_run(
    plan: _CallPlan,
    previous: RunManifestV1 | None,
    attempts: _AttemptLog,
    state: _PassState,
    publish: bool,
) -> RunManifestV1:
    """Records this pass and replaces the run manifest atomically.

    ``previous`` is the manifest this pass resumed, if it resumed one.
    With ``publish`` false this writes the anchor every pass leaves
    before its first request: an incomplete run whose invocation has not
    ended yet and which claims no answers. The manifest is the only file
    a resume can start from, so it exists from before the first request
    rather than from after the last one, and a pass that dies with paid
    answers in its logs leaves a directory its own ``--resume`` reads.
    The anchor's invocation is what the pass knew when it began; the
    attempt logs, not that record, are the account of what it sent.
    """
    conditions = tuple(
        _condition_run(plan, label, attempts[label], publish)
        for label in _ordered_labels(plan.batches)
    )
    complete = publish and all(
        condition.pending == 0 for condition in conditions
    )
    finished_at = datetime.now(timezone.utc) if publish else state.started_at
    manifest = RunManifestV1(
        run_id=plan.options.run_id,
        created_at=(
            state.started_at if previous is None else previous.created_at
        ),
        prepare=plan.prepare,
        prepare_sha256=plan.prepare_sha256,
        endpoint_kind=ENDPOINT_KIND,
        endpoint_host=_endpoint_host(plan.config),
        settings=plan.config.settings,
        prices=plan.config.prices,
        max_attempts=plan.options.max_attempts,
        min_interval_seconds=plan.options.min_interval_seconds,
        token_bound_rule=_TOKEN_BOUND_RULE,
        invocations=(
            *(() if previous is None else previous.invocations),
            InvocationV1(
                source_revision=plan.options.source_revision,
                source_files=_source_manifest(),
                started_at=state.started_at,
                finished_at=finished_at,
                max_usd=plan.options.max_usd,
                requests_sent=state.requests_sent,
                stop_reason=state.stop_reason,
            ),
        ),
        status="complete" if complete else "incomplete",
        charged_usd_upper_bound=_recorded_usd(
            state.spent_micro_usd / _MICRO_USD
        ),
        provider_reported_usd=_provider_reported_usd(attempts),
        conditions=conditions,
    )
    _write_manifest(plan.run_dir, manifest)
    return manifest


def _report(manifest: RunManifestV1, state: _PassState) -> int:
    """Prints what this pass did and returns the process exit code."""
    print(
        canonical_json(
            {
                "run_id": manifest.run_id,
                "status": manifest.status,
                "requests_sent": state.requests_sent,
                "charged_usd_upper_bound": manifest.charged_usd_upper_bound,
                "stop_reason": state.stop_reason,
                "pending": {
                    condition.label: condition.pending
                    for condition in manifest.conditions
                },
            }
        )
    )
    return 0 if manifest.status == "complete" else 1


def _call(arguments: argparse.Namespace) -> int:
    """Sends every prepared prompt at most once, inside a spend cap.

    Raises:
        RunError: If any pre-request check refuses this pass.
    """
    plan = _call_plan(arguments)
    backend = _backend(plan.config)
    previous = _previous_run(plan)
    _copy_prepared(plan)
    attempts = _existing_attempts(plan)
    _open_logs(plan)
    state = _PassState(
        spent_micro_usd=_spent_micro_usd(attempts),
        started_at=datetime.now(timezone.utc),
    )
    _record_run(plan, previous, attempts, state, False)
    _CallPass(backend, plan, attempts, state).run()
    return _report(_record_run(plan, previous, attempts, state, True), state)


def _regular_file(path: Path, maximum: int) -> bytes:
    """Reads one file of a run, refusing anything but a bounded plain file.

    A published tree is copied byte for byte, so a symbolic link or a
    directory standing in for a run file would publish something other
    than the bytes the manifest describes.

    Raises:
        RunError: With ``run_layout_invalid`` if the path is absent or is
            not a regular file, and with ``file_too_large`` above
            ``maximum`` bytes.
    """
    if not os.path.lexists(path):
        raise RunError("run_layout_invalid", "A run file is missing")
    status = path.lstat()
    if not stat.S_ISREG(status.st_mode):
        raise RunError("run_layout_invalid", "A run file is not a regular file")
    if status.st_size > maximum:
        raise RunError("file_too_large", "A run file exceeds its byte limit")
    return path.read_bytes()


def _publish_manifest(run_dir: Path) -> tuple[RunManifestV1, bytes]:
    """Reads the manifest of a run that is allowed to be published.

    ``RunManifestV1`` bounds the attempt ceiling to the published
    protocol's, so a run that retried an item more often than the
    protocol allows cannot be validated here at all.

    Returns:
        The validated manifest and the exact bytes it was validated from,
        which are the bytes that get published: the manifest is the one
        file no digest covers, so reading it a second time would publish
        something that was never checked.

    Raises:
        RunError: If the manifest is unusable, does not describe a
            finished run, or records no token prices.
    """
    data = _regular_file(run_dir / "run_manifest.json", _MAX_PREPARE_BYTES)
    try:
        manifest = RunManifestV1.model_validate_json(data)
    except ValidationError:
        raise RunError(
            "run_manifest_invalid", "The run manifest is not usable"
        ) from None
    if manifest.status != "complete":
        raise RunError("run_incomplete", "Only a complete run can be published")
    if manifest.prices is None:
        raise RunError(
            "prices_missing", "A published run must record its token prices"
        )
    return manifest, data


def _check_output_name(manifest: RunManifestV1, output: Path) -> None:
    """Requires the target directory to be named after this very run.

    Raises:
        RunError: If the run id is not a result name, if the target is
            named after something else, or if the run id and the prepared
            split disagree.
    """
    if _RESULT_DIR.fullmatch(manifest.run_id) is None:
        raise RunError(
            "run_id_invalid", "The run id is not a usable result name"
        )
    if output.name != manifest.run_id:
        raise RunError(
            "output_name_mismatch", "The target is not named after the run"
        )
    if manifest.run_id.split("-", 1)[0] != manifest.prepare.split:
        raise RunError(
            "split_mismatch", "The run id does not name the prepared split"
        )


def _recorded_digests(manifest: RunManifestV1) -> dict[str, str]:
    """Maps every published file to the digest the manifest recorded.

    Every lookup is by condition label rather than by position, so a
    manifest that lists its conditions in another order cannot pair one
    condition's file with another condition's digest.
    """
    digests = {"prepare.json": manifest.prepare_sha256}
    for prepared in manifest.prepare.conditions:
        digests[f"prepared/{prepared.label}.json"] = prepared.sha256
    for condition in manifest.conditions:
        digests[f"attempts/{condition.label}.jsonl"] = condition.attempts_sha256
        if condition.completions_sha256 is not None:
            digests[f"completions/{condition.label}.json"] = (
                condition.completions_sha256
            )
    return digests


def _published_sources(
    run_dir: Path, manifest: RunManifestV1, manifest_bytes: bytes
) -> dict[str, bytes]:
    """Reads every file of the run and re-checks it against the manifest.

    The manifest is not read again: the bytes it was validated from are
    the bytes that get published, so one read decides both what was
    checked and what is copied.

    Raises:
        RunError: If a file is missing, is not a bounded regular file, or
            no longer matches the digest recorded when it was written.
    """
    digests = _recorded_digests(manifest)
    sources: dict[str, bytes] = {"run_manifest.json": manifest_bytes}
    for name in _PUBLISHED_FILES:
        if name in sources:
            continue
        data = _regular_file(run_dir / name, _MAX_PUBLISHED_BYTES)
        recorded = digests.get(name)
        if recorded is None or hashlib.sha256(data).hexdigest() != recorded:
            raise RunError(
                "hash_mismatch", "A run file does not match its recorded digest"
            )
        sources[name] = data
    return sources


def _check_published_contracts(
    manifest: RunManifestV1, sources: Mapping[str, bytes]
) -> None:
    """Re-parses every prompt file, answer batch and attempt log.

    A digest proves that a file did not change; parsing it again proves
    that what was recorded is still the contract the scorer will read.

    Raises:
        RunError: If a published file is not usable, names another
            condition, carries a prompt from another split, or answers
            another item set.
    """
    for label in _LABELS:
        try:
            batch = PreparedBatchV1.model_validate_json(
                sources[f"prepared/{label}.json"]
            )
            answers = CompletionBatchV1.model_validate_json(
                sources[f"completions/{label}.json"]
            )
        except ValidationError:
            raise RunError(
                "published_file_invalid", "A published run file is not usable"
            ) from None
        if condition_label(batch.output_contract, batch.retrieval) != label:
            raise RunError(
                "condition_mismatch",
                "A published prompt file names another condition",
            )
        if any(
            prompt.split != manifest.prepare.split for prompt in batch.prompts
        ):
            raise RunError(
                "split_refused", "A published prompt is not from that split"
            )
        if {item.item_id for item in answers.completions} != {
            prompt.item_id for prompt in batch.prompts
        }:
            raise RunError(
                "items_mismatch",
                "A published batch does not answer its own prompts",
            )
        _attempt_records(sources[f"attempts/{label}.jsonl"])


def _scan_for_secrets(sources: Mapping[str, bytes]) -> None:
    """Refuses to publish any file that reads as if it held a credential.

    Raises:
        RunError: Naming the relative path of the first file that holds
            credential-shaped text or the exported credential itself.
    """
    key = os.environ.get(API_KEY_ENV, "").encode("utf-8")
    secret = key if len(key) >= _MIN_SECRET_BYTES else b""
    for name, data in sources.items():
        if any(pattern.search(data) for pattern in _SECRET_PATTERNS):
            raise RunError(
                "secret_found", f"{name} holds credential-shaped text"
            )
        if secret and secret in data:
            raise RunError("secret_found", f"{name} holds the API credential")


def _check_target(output: Path, sources: Mapping[str, bytes]) -> None:
    """Requires a target holding only a frozen prompt set and its controls.

    A results directory is committed before any model is called: the
    prompts, their receipt and the two control scores are frozen first and
    the run that answers them is published into the same directory
    afterwards. Anything else there is a stale publication or a stale
    score, which has to be removed deliberately rather than replaced in
    place. An allowlisted entry must also be the plain file or directory
    its name claims, because publishing writes through it.

    Raises:
        RunError: With ``output_exists`` if the target is not a directory
            or holds an entry this run cannot replace, and with
            ``prepared_drift`` if a frozen file is not the one this run
            was prepared from.
    """
    if not os.path.lexists(output):
        return
    if output.is_symlink() or not output.is_dir():
        raise RunError(
            "output_exists", "The published run path is not a directory"
        )
    for entry in sorted(output.iterdir()):
        if entry.name not in _PREEXISTING_ENTRIES:
            raise RunError(
                "output_exists",
                "The published run directory holds entries this run "
                "cannot replace",
            )
        if entry.is_symlink() or entry.is_dir() != (
            entry.name in _PREEXISTING_DIRS
        ):
            raise RunError(
                "output_exists",
                "A published run directory entry is not the plain file "
                "or directory it names",
            )
    for name in _FROZEN_FILES:
        frozen = output / name
        if not os.path.lexists(frozen):
            continue
        if _regular_file(frozen, _MAX_PUBLISHED_BYTES) != sources[name]:
            raise RunError(
                "prepared_drift",
                "A committed file differs from the run that answered it",
            )


def _write_published(
    output: Path, sources: Mapping[str, bytes], run_id: str
) -> None:
    """Stages the whole tree beside the target, then moves it into place.

    Nothing is created at the target path until every published byte has
    been written, so an interrupted publish leaves a committed directory
    exactly as it was.
    """
    staging = output.parent / f".{run_id}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        for name, data in sources.items():
            staged = staging / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(data)
        if not os.path.lexists(output):
            staging.rename(output)
            return
        for name in sources:
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / name, target)
        shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _publish(arguments: argparse.Namespace) -> int:
    """Copies one verified complete run into the committed results tree.

    Raises:
        RunError: If the run, the target or any published byte is not
            what a committed result must be.
    """
    run_dir = cast(Path, arguments.run_dir)
    output = cast(Path, arguments.output)
    manifest, manifest_bytes = _publish_manifest(run_dir)
    _check_output_name(manifest, output)
    sources = _published_sources(run_dir, manifest, manifest_bytes)
    _check_published_contracts(manifest, sources)
    _scan_for_secrets(sources)
    _check_target(output, sources)
    _write_published(output, sources, manifest.run_id)
    print(
        canonical_json(
            {
                "run_id": manifest.run_id,
                "output": output.as_posix(),
                "files": list(_PUBLISHED_FILES),
            }
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds the model-run command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare",
        help="Write the four prepared prompt files and their manifest",
    )
    prepare.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument(
        "--source-revision", type=_source_revision, required=True
    )
    prepare.add_argument("--top-k", type=_top_k, default=_DEFAULT_TOP_K)
    prepare.set_defaults(handler=_prepare)
    call = commands.add_parser(
        "call",
        help="Send every prepared prompt at most once per pass",
    )
    call.add_argument("--prepare-dir", type=Path, required=True)
    call.add_argument("--run-id", required=True)
    call.add_argument("--config", type=Path, required=True)
    call.add_argument("--max-usd", type=float, required=True)
    call.add_argument("--source-revision", type=_source_revision, required=True)
    call.add_argument("--min-interval-seconds", type=float, default=1.0)
    call.add_argument("--max-attempts", type=int, default=_MAX_ATTEMPTS)
    call.add_argument("--resume", action="store_true")
    call.add_argument(
        "--gate-first", action=argparse.BooleanOptionalAction, default=True
    )
    call.set_defaults(handler=_call)
    publish = commands.add_parser(
        "publish",
        help="Copy one verified complete run into the results directory",
    )
    publish.add_argument("--run-dir", type=Path, required=True)
    publish.add_argument("--output", type=Path, required=True)
    publish.set_defaults(handler=_publish)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Runs one model-run subcommand and returns a process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except DFilterForgeError as error:
        _print_error(error.code, str(error))
        return _FAILURE
    except ValidationError:
        _print_error("schema_invalid", _SCHEMA_MESSAGE)
        return _FAILURE
    except OSError:
        _print_error("io_error", _IO_MESSAGE)
        return _FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
