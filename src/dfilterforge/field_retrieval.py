"""Bounded lexical retrieval over the frozen tshark field inventory."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
import heapq
from pathlib import Path
import re
import sqlite3
from typing import Self

from pydantic import Field
from pydantic import field_validator
from pydantic import ValidationError

from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_catalog import parse_tshark_fields
from dfilterforge.generation import RetrievedFieldV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.text_limits import utf8_size

_FIELD_STREAM_SQL = (
    "SELECT name, record FROM fields_records ORDER BY name COLLATE BINARY"
)
_TOKEN_PATTERN = re.compile(r"[^\W_]+")
_LEXEME_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_MAX_FIELD_RECORD_BYTES = 16 * 1024
_MAX_REGISTRATIONS_PER_FIELD = 64


class FieldRetrievalError(DFilterForgeError):
    """Raised when a retrieval request or frozen inventory is unsafe."""


class RetrievalLimits(FrozenModel):
    """Hard upper bounds for one field-retrieval batch."""

    max_items: int = Field(default=128, ge=1, le=128)
    max_item_id_bytes: int = Field(default=256, ge=1, le=256)
    max_query_bytes: int = Field(default=4096, ge=1, le=4096)
    max_query_tokens: int = Field(default=64, ge=1, le=64)
    max_top_k: int = Field(default=32, ge=1, le=32)
    max_context_bytes: int = Field(default=32 * 1024, ge=2, le=32 * 1024)
    max_enum_values: int = Field(default=8, ge=1, le=8)


class FieldRetrievalItemV1(FrozenModel):
    """One opaque correlation identifier and its natural-language intent."""

    item_id: str
    intent: str

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        """Require an identifier without interpreting its contents."""
        if not value or not value.strip():
            raise ValueError("item_id must be non-empty")
        return value


class FieldRetrievalResultV1(FrozenModel):
    """Ranked field context correlated with one retrieval item."""

    item_id: str
    fields: tuple[RetrievedFieldV1, ...]


@dataclass(frozen=True)
class _PreparedQuery:
    """Bounded lexical state used while streaming catalog fields."""

    tokens: frozenset[str]
    token_sequence: tuple[str, ...]
    lexemes: frozenset[str]


@dataclass(frozen=True)
class _RankedCandidate:
    """A heap entry whose comparison keeps the worst candidate at the root."""

    score: int
    field: FieldDefinition

    @property
    def order_key(self) -> tuple[int, str, str, str, str]:
        """Return the final, deterministic best-first ordering key."""
        return (
            -self.score,
            self.field.abbreviation,
            self.field.protocol,
            self.field.display_name,
            self.field.field_type.value,
        )

    def __lt__(self, other: Self) -> bool:
        """Reverse final order so a min-heap exposes its worst member."""
        return self.order_key > other.order_key


@dataclass
class _QueryState:
    """Mutable top-k state for one input item."""

    query: _PreparedQuery
    candidates: list[_RankedCandidate]


def _tokens(value: str) -> tuple[str, ...]:
    """Split text into deterministic ASCII lexical tokens."""
    return tuple(_TOKEN_PATTERN.findall(value.casefold()))


def _prepare_query(
    item: FieldRetrievalItemV1, limits: RetrievalLimits
) -> _PreparedQuery:
    """Validate and tokenize an untrusted natural-language query."""
    try:
        item_id_bytes = utf8_size(item.item_id, "item_id")
        query_bytes = utf8_size(item.intent, "intent")
    except ValueError:
        raise FieldRetrievalError(
            "query_invalid", "Retrieval text must be valid UTF-8"
        ) from None
    if item_id_bytes > limits.max_item_id_bytes:
        raise FieldRetrievalError(
            "item_id_too_long", "Retrieval item identifier exceeds its limit"
        )
    if query_bytes > limits.max_query_bytes:
        raise FieldRetrievalError(
            "query_too_long", "Retrieval query exceeds its UTF-8 byte limit"
        )
    token_sequence = _tokens(item.intent)
    if len(token_sequence) > limits.max_query_tokens:
        raise FieldRetrievalError(
            "query_too_many_tokens", "Retrieval query has too many tokens"
        )
    if not token_sequence:
        raise FieldRetrievalError(
            "query_empty", "Retrieval query has no searchable tokens"
        )
    folded = item.intent.casefold()
    return _PreparedQuery(
        tokens=frozenset(token_sequence),
        token_sequence=token_sequence,
        lexemes=frozenset(_LEXEME_PATTERN.findall(folded)),
    )


def _contains_sequence(
    haystack: tuple[str, ...], needle: tuple[str, ...]
) -> bool:
    """Return whether one short token sequence occurs contiguously."""
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(
        haystack[index : index + width] == needle
        for index in range(len(haystack) - width + 1)
    )


def _score(field: FieldDefinition, query: _PreparedQuery) -> int:
    """Compute a deterministic integer lexical relevance score."""
    abbreviation = field.abbreviation.casefold()
    abbreviation_tokens = frozenset(_tokens(field.abbreviation))
    display_tokens = _tokens(field.display_name)
    protocol_tokens = frozenset(_tokens(field.protocol))
    score = 0
    if abbreviation in query.lexemes:
        score += 1000 if "." in abbreviation else 80
    if _contains_sequence(query.token_sequence, display_tokens):
        score += 300
    score += 100 * len(query.tokens & abbreviation_tokens)
    score += 40 * len(query.tokens & frozenset(display_tokens))
    score += 20 * len(query.tokens & protocol_tokens)
    return score


def _parse_record(name: str, record: object) -> FieldDefinition | None:
    """Return one field parsed from a raw frozen record, or None if unsafe."""
    if not isinstance(record, str):
        return None
    try:
        if utf8_size(record, "record") > _MAX_FIELD_RECORD_BYTES:
            return None
        parsed = parse_tshark_fields((record,))
    except (TypeError, ValueError, UnicodeError):
        return None
    if len(parsed) != 1 or parsed[0].abbreviation != name:
        return None
    return parsed[0]


def _resolve_group(
    name: object, records: list[object], group_overflowed: bool
) -> FieldDefinition | None:
    """Return one safe projection, filtering malformed or ambiguous groups."""
    if group_overflowed or not isinstance(name, str) or not records:
        return None
    fields: list[FieldDefinition] = []
    for record in records:
        field = _parse_record(name, record)
        if field is None:
            return None
        fields.append(field)
    field_types = {field.field_type for field in fields}
    raw_types = {
        field.tshark_type for field in fields if field.tshark_type is not None
    }
    if (
        len(field_types) != 1
        or len(raw_types) > 1
        or FieldType.UNSUPPORTED in field_types
    ):
        return None
    return min(
        fields,
        key=lambda field: (
            field.abbreviation,
            field.protocol,
            field.display_name,
            field.field_type.value,
            field.tshark_type or "",
        ),
    )


def _stream_fields(database: sqlite3.Connection) -> Iterator[FieldDefinition]:
    """Yield supported, unambiguous fields from one ordered cursor pass."""
    current_name: object | None = None
    records: list[object] = []
    group_overflowed = False
    seen_row = False
    for name, record in database.execute(_FIELD_STREAM_SQL):
        if seen_row and name != current_name:
            field = _resolve_group(current_name, records, group_overflowed)
            if field is not None:
                yield field
            records = []
            group_overflowed = False
        current_name = name
        seen_row = True
        if len(records) < _MAX_REGISTRATIONS_PER_FIELD:
            records.append(record)
        else:
            group_overflowed = True
    if seen_row:
        field = _resolve_group(current_name, records, group_overflowed)
        if field is not None:
            yield field


def _consider(state: _QueryState, field: FieldDefinition, top_k: int) -> None:
    """Retain a matching field when it belongs in one bounded top-k heap."""
    score = _score(field, state.query)
    if score <= 0:
        return
    candidate = _RankedCandidate(score=score, field=field)
    admitted = (
        len(state.candidates) < top_k
        or candidate.order_key < state.candidates[0].order_key
    )
    if not admitted or not _projectable(field):
        return
    if len(state.candidates) < top_k:
        heapq.heappush(state.candidates, candidate)
    else:
        heapq.heapreplace(state.candidates, candidate)


def _retrieved_field(field: FieldDefinition, rank: int) -> RetrievedFieldV1:
    """Project catalog metadata into the bounded generation contract."""
    return RetrievedFieldV1(
        rank=rank,
        abbreviation=field.abbreviation,
        field_type=field.field_type,
        protocol=field.protocol,
        display_name=field.display_name,
        enum_values=(),
        enum_values_truncated=False,
    )


def _projectable(field: FieldDefinition) -> bool:
    """Returns whether one catalog row can enter a prompt contract."""
    try:
        _retrieved_field(field, 1)
    except ValidationError:
        return False
    return True


def _bounded_context(
    candidates: list[_RankedCandidate], limits: RetrievalLimits
) -> tuple[RetrievedFieldV1, ...]:
    """Keep the best-first prefix that fits the serialized context budget."""
    output: list[RetrievedFieldV1] = []
    serialized_bytes = 2  # JSON list delimiters.
    for candidate in sorted(candidates, key=lambda item: item.order_key):
        field = _retrieved_field(candidate.field, len(output) + 1)
        field_bytes = len(field.model_dump_json().encode("utf-8"))
        separator_bytes = 1 if output else 0
        if (
            serialized_bytes + separator_bytes + field_bytes
            > limits.max_context_bytes
        ):
            break
        output.append(field)
        serialized_bytes += separator_bytes + field_bytes
    return tuple(output)


def retrieve_fields(
    path: Path,
    items: Sequence[FieldRetrievalItemV1],
    *,
    top_k: int = 16,
    limits: RetrievalLimits = RetrievalLimits(),
) -> tuple[FieldRetrievalResultV1, ...]:
    """Retrieve field context for a batch with one frozen-inventory scan.

    Results preserve input order and opaque item identifiers. Ranking uses
    integer lexical scores followed by catalog metadata as deterministic tie
    breakers. The inventory is opened read-only and no request value enters an
    SQL statement.

    Args:
        path: Frozen SQLite catalog path.
        items: Correlated natural-language retrieval items.
        top_k: Maximum candidate fields per item, capped at 32.
        limits: Immutable request and output safety limits.

    Returns:
        One bounded result for every input item, in input order.

    Raises:
        FieldRetrievalError: If request limits or the catalog boundary fail.
    """
    if top_k < 1:
        raise FieldRetrievalError(
            "top_k_invalid", "top_k must be a positive integer"
        )
    if top_k > limits.max_top_k:
        raise FieldRetrievalError(
            "top_k_too_large", "top_k exceeds the retrieval limit"
        )
    if len(items) > limits.max_items:
        raise FieldRetrievalError(
            "batch_too_large", "Retrieval batch exceeds its item limit"
        )
    identifiers = [item.item_id for item in items]
    if len(set(identifiers)) != len(identifiers):
        raise FieldRetrievalError(
            "duplicate_item_id", "Retrieval item identifiers must be unique"
        )
    if not items:
        return ()
    states = [
        _QueryState(query=_prepare_query(item, limits), candidates=[])
        for item in items
    ]
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        with closing(sqlite3.connect(uri, uri=True)) as database:
            database.execute("PRAGMA trusted_schema = OFF")
            for field in _stream_fields(database):
                for state in states:
                    _consider(state, field, top_k)
    except (OSError, sqlite3.Error):
        raise FieldRetrievalError(
            "catalog_unavailable", "Frozen field inventory is unavailable"
        ) from None
    return tuple(
        FieldRetrievalResultV1(
            item_id=item.item_id,
            fields=_bounded_context(state.candidates, limits),
        )
        for item, state in zip(items, states, strict=True)
    )
