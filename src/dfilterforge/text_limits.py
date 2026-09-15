"""Shared UTF-8 byte-limit checks for bounded text contracts.

Every model-facing contract bounds text by encoded UTF-8 size rather than by
code points, so one oversized or unencodable value fails the same way in
prompts, responses, retrieval queries, and recorded configuration.
"""

from __future__ import annotations


def utf8_size(value: str, description: str) -> int:
    """Returns the encoded UTF-8 size of ``value``.

    Args:
        value: Text that may contain lone surrogates from untrusted decoding.
        description: Short name used in the error message.

    Returns:
        The number of bytes ``value`` occupies once UTF-8 encoded.

    Raises:
        ValueError: If ``value`` cannot be encoded as UTF-8.
    """
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise ValueError(f"{description} must be valid UTF-8") from None


def validate_utf8(value: str, maximum: int, description: str) -> None:
    """Raises ``ValueError`` unless ``value`` fits in ``maximum`` bytes."""
    if utf8_size(value, description) > maximum:
        raise ValueError(f"{description} exceeds the byte limit")


def validate_text(value: str, maximum: int, description: str) -> str:
    """Requires non-blank text within ``maximum`` UTF-8 bytes and returns it."""
    if not value.strip():
        raise ValueError(f"{description} must be non-empty")
    validate_utf8(value, maximum, description)
    return value


def validate_trimmed_text(value: str, maximum: int, description: str) -> str:
    """Requires non-empty text without surrounding whitespace and returns it."""
    if not value or value != value.strip():
        raise ValueError(f"{description} must be non-empty and trimmed")
    validate_utf8(value, maximum, description)
    return value
