"""Versioned Wireshark field catalog and intent validation."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
import ipaddress
from typing import Literal

from pydantic import field_validator
from pydantic import model_validator
from pydantic import PrivateAttr

from dfilterforge.canonical import content_sha256
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate


class CatalogError(ValueError):
    """Raised when an intent is incompatible with a field catalog."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FieldType(StrEnum):
    """Portable field types used by the compiler's supported subset."""

    PROTOCOL = "protocol"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"
    BYTES = "bytes"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    ENUM = "enum"


class EnumValue(FrozenModel):
    """One legal numeric or textual enum value."""

    value: int | str
    label: str


class FieldDefinition(FrozenModel):
    """The subset of a tshark field definition required for validation."""

    abbreviation: str
    field_type: FieldType
    protocol: str
    display_name: str
    enum_values: tuple[EnumValue, ...] = ()

    @field_validator("abbreviation", "protocol")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Rejects empty names and surrounding whitespace."""
        if not value or value != value.strip():
            raise ValueError("field names must be non-empty and trimmed")
        return value


class FieldCatalogV1(FrozenModel):
    """An immutable, version-pinned field catalog."""

    schema_version: Literal["1.0"] = "1.0"
    tshark_version: str
    profile_hash: str
    fields: tuple[FieldDefinition, ...]
    catalog_hash: str | None = None
    _by_name: dict[str, FieldDefinition] = PrivateAttr(default_factory=dict)

    @model_validator(mode="after")
    def validate_catalog(self) -> "FieldCatalogV1":
        """Checks uniqueness and an optional supplied content hash."""
        by_name = {field.abbreviation: field for field in self.fields}
        if len(by_name) != len(self.fields):
            raise ValueError("catalog contains duplicate field abbreviations")
        object.__setattr__(self, "_by_name", by_name)
        expected = self.compute_hash()
        if self.catalog_hash is not None and self.catalog_hash != expected:
            raise ValueError("catalog_hash does not match catalog contents")
        return self

    def compute_hash(self) -> str:
        """Computes the catalog hash, excluding its self-referential field."""
        return content_sha256(
            {
                "schema_version": self.schema_version,
                "tshark_version": self.tshark_version,
                "profile_hash": self.profile_hash,
                "fields": self.fields,
            }
        )

    def get(self, abbreviation: str) -> FieldDefinition:
        """Returns a field definition or raises a stable catalog error."""
        try:
            return self._by_name[abbreviation]
        except KeyError as error:
            raise CatalogError(
                "unknown_field", f"Unknown field: {abbreviation}"
            ) from error


_ORDERED_TYPES = {FieldType.INTEGER, FieldType.FLOAT}
_IP_TYPES = {FieldType.IPV4, FieldType.IPV6}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _value_matches(  # pylint: disable=too-many-return-statements
    field: FieldDefinition, value: object
) -> bool:
    if field.field_type == FieldType.BOOLEAN:
        return isinstance(value, bool)
    if field.field_type == FieldType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if field.field_type == FieldType.FLOAT:
        return _is_number(value)
    if field.field_type in {FieldType.STRING, FieldType.BYTES}:
        return isinstance(value, str)
    if field.field_type in _IP_TYPES:
        if not isinstance(value, str):
            return False
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return False
        return (
            field.field_type == FieldType.IPV4 and address.version == 4
        ) or (field.field_type == FieldType.IPV6 and address.version == 6)
    if field.field_type == FieldType.ENUM:
        return value in {member.value for member in field.enum_values}
    return False


def validate_predicate(predicate: Predicate, catalog: FieldCatalogV1) -> None:
    """Validates a predicate against field type and operator rules.

    Raises:
        CatalogError: If the field, operator, or value is invalid.
    """
    field = catalog.get(predicate.field)
    operator = predicate.operator
    if operator == Operator.EXISTS:
        return
    if field.field_type == FieldType.PROTOCOL:
        raise CatalogError(
            "unsupported_operator",
            f"Protocol {field.abbreviation} only supports exists",
        )
    values: Iterable[object]
    if operator == Operator.IN:
        assert isinstance(predicate.value, tuple)
        values = predicate.value
    else:
        values = (predicate.value,)
    if operator in {Operator.LT, Operator.LE, Operator.GT, Operator.GE}:
        if field.field_type not in _ORDERED_TYPES:
            raise CatalogError(
                "unsupported_operator",
                f"{operator.value} is not supported by "
                f"{field.field_type.value}",
            )
    if operator == Operator.CONTAINS and field.field_type not in {
        FieldType.STRING,
        FieldType.BYTES,
    }:
        raise CatalogError(
            "unsupported_operator",
            f"contains is not supported by {field.field_type.value}",
        )
    if operator == Operator.IN_SUBNET:
        if field.field_type not in _IP_TYPES:
            raise CatalogError(
                "unsupported_operator",
                f"in_subnet is not supported by {field.field_type.value}",
            )
        assert isinstance(predicate.value, str)
        network = ipaddress.ip_network(predicate.value, strict=False)
        expected_version = 4 if field.field_type == FieldType.IPV4 else 6
        if network.version != expected_version:
            raise CatalogError(
                "type_mismatch", "CIDR version does not match field type"
            )
        return
    if not all(_value_matches(field, value) for value in values):
        raise CatalogError(
            "type_mismatch",
            f"Value does not match {field.abbreviation} "
            f"({field.field_type.value})",
        )


def validate_expression(
    expression: Expression, catalog: FieldCatalogV1
) -> None:
    """Recursively validates an expression against a field catalog."""
    if isinstance(expression, Predicate):
        validate_predicate(expression, catalog)
    elif isinstance(expression, (All, AnyOf)):
        for child in expression.children:
            validate_expression(child, catalog)
    else:
        validate_expression(expression.child, catalog)


_TSHARK_TYPE_MAP: dict[str, FieldType] = {
    "FT_PROTOCOL": FieldType.PROTOCOL,
    "FT_BOOLEAN": FieldType.BOOLEAN,
    "FT_CHAR": FieldType.INTEGER,
    "FT_UINT8": FieldType.INTEGER,
    "FT_UINT16": FieldType.INTEGER,
    "FT_UINT24": FieldType.INTEGER,
    "FT_UINT32": FieldType.INTEGER,
    "FT_UINT40": FieldType.INTEGER,
    "FT_UINT48": FieldType.INTEGER,
    "FT_UINT56": FieldType.INTEGER,
    "FT_UINT64": FieldType.INTEGER,
    "FT_INT8": FieldType.INTEGER,
    "FT_INT16": FieldType.INTEGER,
    "FT_INT24": FieldType.INTEGER,
    "FT_INT32": FieldType.INTEGER,
    "FT_INT40": FieldType.INTEGER,
    "FT_INT48": FieldType.INTEGER,
    "FT_INT56": FieldType.INTEGER,
    "FT_INT64": FieldType.INTEGER,
    "FT_FLOAT": FieldType.FLOAT,
    "FT_DOUBLE": FieldType.FLOAT,
    "FT_STRING": FieldType.STRING,
    "FT_STRINGZ": FieldType.STRING,
    "FT_UINT_STRING": FieldType.STRING,
    "FT_BYTES": FieldType.BYTES,
    "FT_ETHER": FieldType.BYTES,
    "FT_IPv4": FieldType.IPV4,
    "FT_IPv6": FieldType.IPV6,
}


def parse_tshark_fields(lines: Iterable[str]) -> tuple[FieldDefinition, ...]:
    """Parses the stable prefix of ``tshark -G fields`` tabular output.

    Unsupported field types are skipped because the version-one IR cannot
    represent them safely.
    """
    definitions: list[FieldDefinition] = []
    for line in lines:
        columns = line.rstrip("\r\n").split("\t")
        if not columns or columns[0] not in {"F", "P"}:
            continue
        if columns[0] == "P" and len(columns) >= 3:
            definitions.append(
                FieldDefinition(
                    abbreviation=columns[2],
                    field_type=FieldType.PROTOCOL,
                    protocol=columns[2],
                    display_name=columns[1],
                )
            )
            continue
        if len(columns) < 5:
            continue
        field_type = _TSHARK_TYPE_MAP.get(columns[3])
        if field_type is None:
            continue
        definitions.append(
            FieldDefinition(
                abbreviation=columns[2],
                field_type=field_type,
                protocol=columns[4],
                display_name=columns[1],
            )
        )
    return tuple(definitions)


def parse_tshark_values(
    lines: Iterable[str],
) -> dict[str, tuple[EnumValue, ...]]:
    """Parses value-string entries from ``tshark -G values`` output.

    Range and true/false entries are intentionally ignored in version one;
    only exact ``V`` entries can be represented without losing semantics.
    """
    values: dict[str, list[EnumValue]] = {}
    for line in lines:
        columns = line.rstrip("\r\n").split("\t")
        if len(columns) < 4 or columns[0] != "V":
            continue
        raw_value: int | str
        try:
            raw_value = int(columns[2], 0)
        except ValueError:
            raw_value = columns[2]
        values.setdefault(columns[1], []).append(
            EnumValue(value=raw_value, label=columns[3])
        )
    return {name: tuple(members) for name, members in values.items()}


def apply_enum_values(
    fields: Iterable[FieldDefinition],
    values: dict[str, tuple[EnumValue, ...]],
) -> tuple[FieldDefinition, ...]:
    """Returns catalog fields enriched with exact enum definitions."""
    enriched: list[FieldDefinition] = []
    for field in fields:
        members = values.get(field.abbreviation, ())
        if members and field.field_type == FieldType.INTEGER:
            enriched.append(
                field.model_copy(
                    update={
                        "field_type": FieldType.ENUM,
                        "enum_values": members,
                    }
                )
            )
        else:
            enriched.append(field)
    return tuple(enriched)
