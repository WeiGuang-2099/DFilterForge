"""Tests for canonical serialization and hashing."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel
import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256


def test_canonical_json_sorts_keys_and_preserves_unicode() -> None:
    value = {"z": [2, 1], "a": "流量"}

    assert canonical_json(value) == '{"a":"流量","z":[2,1]}'
    assert content_sha256(value) == content_sha256({"a": "流量", "z": [2, 1]})


def test_canonical_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        canonical_json({"value": float("nan")})


def test_canonical_json_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_json({1: "not canonical"})


def test_canonical_json_supports_models_enums_and_paths() -> None:
    class Choice(StrEnum):
        VALUE = "value"

    class Payload(BaseModel):
        choice: Choice

    payload = Payload(choice=Choice.VALUE)

    assert canonical_json(payload) == '{"choice":"value"}'
    assert canonical_json(Path("fixtures/input.pcap")) == (
        '"fixtures/input.pcap"'
    )


def test_canonical_json_rejects_binary_values() -> None:
    with pytest.raises(TypeError, match="Unsupported"):
        canonical_json(b"binary")
