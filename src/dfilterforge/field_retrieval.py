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
_PROTOCOL_ROWS_SQL = (
    "SELECT record FROM fields_records "
    "WHERE substr(record, 1, 2) = 'P' || char(9)"
)
_TOKEN_PATTERN = re.compile(r"[^\W_]+")
_LEXEME_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_MAX_FIELD_RECORD_BYTES = 16 * 1024
_MAX_REGISTRATIONS_PER_FIELD = 64
_EXACT_WEIGHT = 4
_ABBREVIATION_WEIGHT = 2
_PROTOCOL_WEIGHT = 4
_COVERAGE_SLACK = 2
_MIN_ABBREVIATION_CHARS = 3
_MAX_ABBREVIATED_WORD_CHARS = 32
_VERBATIM_BONUS = 10**9


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

    words: frozenset[str]
    protocol_words: frozenset[str]
    lexemes: frozenset[str]


@dataclass(frozen=True)
class _FieldTokens:
    """Lexical view of one catalog field, computed once per streamed row."""

    abbreviation: frozenset[str]
    display: frozenset[str]
    protocol: str
    protocol_tokens: frozenset[str]
    folded: str


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
    protocols: frozenset[str] = frozenset()


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
    words = frozenset(
        word[:-3] + "y" if len(word) > 4 and word.endswith("ies") else word
        for word in token_sequence
    )
    any_upper = any(character.isupper() for character in item.intent)
    protocol_words = frozenset(
        token.casefold()
        for token in _TOKEN_PATTERN.findall(item.intent)
        if not any_upper or sum(c.isupper() for c in token) >= 2
    )
    return _PreparedQuery(
        words=words,
        protocol_words=protocol_words,
        lexemes=frozenset(_LEXEME_PATTERN.findall(folded)),
    )


def _initials(text: str) -> str:
    """Return the acronym of a display name, keeping numeric words whole."""
    return "".join(
        word if word.isdigit() else word[0] for word in _tokens(text)
    )


def _is_abbreviation(token: str, word: str) -> bool:
    """Return whether token abbreviates word by dropping letters in order."""
    if not _MIN_ABBREVIATION_CHARS <= len(token) < len(word):
        return False
    if token[0] != word[0]:
        return False
    remaining = iter(word)
    return all(character in remaining for character in token)


def _field_tokens(field: FieldDefinition) -> _FieldTokens:
    """Tokenize one field once for every query in the batch."""
    return _FieldTokens(
        abbreviation=frozenset(_tokens(field.abbreviation)),
        display=frozenset(_tokens(field.display_name)),
        protocol=field.protocol.casefold(),
        protocol_tokens=frozenset(_tokens(field.protocol)),
        folded=field.abbreviation.casefold(),
    )


def _score(
    state: _QueryState,
    tokens: _FieldTokens,
    weights: dict[str, int],
    covered: dict[str, set[str]],
) -> int:
    """Compute a deterministic integer lexical relevance score."""
    words = state.query.words & weights.keys()
    raw = sum(weights[word] for word in words)
    matched: set[str] = set()
    for word in words:
        matched |= covered.get(word, set())
    if tokens.protocol in state.protocols:
        raw += _PROTOCOL_WEIGHT
        matched |= tokens.protocol_tokens
    if raw == 0:
        return 0
    unmatched = len(tokens.abbreviation - matched)
    score = raw * 1000 // (_COVERAGE_SLACK + unmatched)
    if "." in tokens.folded and tokens.folded in state.query.lexemes:
        score += _VERBATIM_BONUS
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


def _consider(
    state: _QueryState, field: FieldDefinition, score: int, top_k: int
) -> None:
    """Retain a matching field when it belongs in one bounded top-k heap."""
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


def _select_protocols(
    database: sqlite3.Connection, states: list[_QueryState]
) -> None:
    """Resolve protocols named by abbreviation or display-name acronym."""
    wanted = frozenset[str]().union(
        *(state.query.protocol_words for state in states)
    )
    acronyms: dict[str, set[str]] = {}
    for (record,) in database.execute(_PROTOCOL_ROWS_SQL):
        columns = str(record).split("\t")
        if len(columns) < 3:
            continue
        acronym = _initials(columns[1])
        if len(acronym) >= _MIN_ABBREVIATION_CHARS and acronym in wanted:
            acronyms.setdefault(acronym, set()).add(columns[2].casefold())
    for state in states:
        words = state.query.protocol_words
        state.protocols = words.union(
            *(acronyms.get(word, ()) for word in words)
        )


class _BatchIndex:
    """Word, protocol and abbreviation lookups shared by one batch."""

    def __init__(self, states: list[_QueryState]) -> None:
        self.by_word: dict[str, list[_QueryState]] = {}
        self.by_protocol: dict[str, list[_QueryState]] = {}
        self._by_initial: dict[str, list[str]] = {}
        self._expansions: dict[str, tuple[str, ...]] = {}
        for state in states:
            for word in sorted(state.query.words):
                if word not in self.by_word and (
                    _MIN_ABBREVIATION_CHARS
                    < len(word)
                    <= _MAX_ABBREVIATED_WORD_CHARS
                ):
                    self._by_initial.setdefault(word[0], []).append(word)
                self.by_word.setdefault(word, []).append(state)
            for protocol in state.protocols:
                self.by_protocol.setdefault(protocol, []).append(state)

    def expansions(self, token: str) -> tuple[str, ...]:
        """Return batch words that the catalog token abbreviates."""
        words = self._by_initial.get(token[0])
        if not words:
            return ()
        cached = self._expansions.get(token)
        if cached is None:
            cached = tuple(
                word for word in words if _is_abbreviation(token, word)
            )
            self._expansions[token] = cached
        return cached


def _scan(
    database: sqlite3.Connection, states: list[_QueryState], top_k: int
) -> None:
    """Stream the inventory once, scoring a field only where it can match."""
    index = _BatchIndex(states)
    for field in _stream_fields(database):
        tokens = _field_tokens(field)
        weights: dict[str, int] = {}
        covered: dict[str, set[str]] = {}
        for token in tokens.abbreviation:
            if token in index.by_word:
                weights[token] = _EXACT_WEIGHT
                covered.setdefault(token, set()).add(token)
            for word in index.expansions(token):
                weights[word] = max(weights.get(word, 0), _ABBREVIATION_WEIGHT)
                covered.setdefault(word, set()).add(token)
        for token in tokens.display:
            if token in index.by_word:
                weights[token] = _EXACT_WEIGHT
        touched = {
            id(state): state
            for word in weights
            for state in index.by_word[word]
        }
        for state in index.by_protocol.get(tokens.protocol, ()):
            touched[id(state)] = state
        for state in touched.values():
            score = _score(state, tokens, weights, covered)
            _consider(state, field, score, top_k)


def retrieve_fields(
    path: Path,
    items: Sequence[FieldRetrievalItemV1],
    *,
    top_k: int = 16,
    limits: RetrievalLimits = RetrievalLimits(),
) -> tuple[FieldRetrievalResultV1, ...]:
    """Retrieve field context for a batch from the frozen inventory.

    The batch is served with one ordered scan plus one constant protocol-row
    pass. Results preserve input order and opaque item identifiers. Ranking
    prefers fields whose protocol the request names, scores exact and
    abbreviated name matches, divides by the parts of the field name the
    request did not mention, and falls back to catalog metadata as a
    deterministic tie breaker. The inventory is opened read-only and no
    request value enters an SQL statement.

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
            _select_protocols(database, states)
            _scan(database, states, top_k)
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
