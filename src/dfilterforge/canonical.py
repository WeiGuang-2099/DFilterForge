"""Deterministic serialization and content hashing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import cast

from pydantic import BaseModel

_HASH_CHUNK_BYTES = 1 << 20


def _json_value(value: object) -> object:
    """Converts supported objects to deterministic JSON values.

    Args:
        value: A Pydantic model or JSON-compatible value.

    Returns:
        A JSON-compatible value with mappings normalized recursively.

    Raises:
        TypeError: If ``value`` is not JSON-compatible.
    """
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Path):
        return value.as_posix()
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        normalized: dict[str, object] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise TypeError("Canonical JSON mapping keys must be strings.")
            normalized[key] = _json_value(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        sequence = cast(Sequence[object], value)
        return [_json_value(item) for item in sequence]
    raise TypeError(f"Unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Serializes a value using the project's canonical JSON encoding.

    Object keys are sorted, whitespace is omitted, Unicode is preserved, and
    non-finite floating point numbers are rejected.

    Args:
        value: A Pydantic model or JSON-compatible value.

    Returns:
        Canonically encoded JSON text.
    """
    return json.dumps(
        _json_value(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def content_sha256(value: object) -> str:
    """Returns the SHA-256 digest of a value's canonical JSON encoding."""
    encoded = canonical_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    """Returns the SHA-256 digest of a file's bytes without loading it.

    Args:
        path: File to hash.

    Returns:
        The lowercase hexadecimal digest of the file's contents.

    Raises:
        OSError: If the file cannot be opened or read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()
