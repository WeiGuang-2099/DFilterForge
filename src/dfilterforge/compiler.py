"""Deterministic compiler from typed intent IR to display filters."""

from __future__ import annotations

import math

from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_catalog import validate_expression
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue


class CompileError(ValueError):
    """Raised when an IR value cannot be safely compiled."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_OPERATOR_TEXT = {
    Operator.EQ: "==",
    Operator.NE: "!=",
    Operator.LT: "<",
    Operator.LE: "<=",
    Operator.GT: ">",
    Operator.GE: ">=",
}


def _compile_string(value: str) -> str:
    if any(ord(character) < 0x20 for character in value):
        raise CompileError(
            "invalid_value", "String literals cannot contain control characters"
        )
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _compile_value(value: ScalarValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CompileError("invalid_value", "Numbers must be finite")
        return repr(value)
    return _compile_string(value)


def _compile_predicate(
    predicate: Predicate, field: FieldDefinition | None = None
) -> str:
    if predicate.operator == Operator.EXISTS:
        return predicate.field
    assert predicate.value is not None
    if predicate.operator == Operator.CONTAINS:
        assert isinstance(predicate.value, str)
        return f"{predicate.field} contains {_compile_string(predicate.value)}"
    if predicate.operator == Operator.IN_SUBNET:
        assert isinstance(predicate.value, str)
        return f"{predicate.field} in {predicate.value}"
    if predicate.operator == Operator.IN:
        assert isinstance(predicate.value, tuple)
        members = ", ".join(
            _compile_field_value(value, field) for value in predicate.value
        )
        return f"{predicate.field} in {{{members}}}"
    operator = _OPERATOR_TEXT[predicate.operator]
    assert not isinstance(predicate.value, tuple)
    value = _compile_field_value(predicate.value, field)
    return f"{predicate.field} {operator} {value}"


def _compile_field_value(
    value: ScalarValue, field: FieldDefinition | None
) -> str:
    if (
        field is not None
        and field.field_type in {FieldType.IPV4, FieldType.IPV6}
        and isinstance(value, str)
    ):
        return value
    return _compile_value(value)


def _compile_expression(
    expression: Expression, catalog: FieldCatalogV1 | None
) -> str:
    if isinstance(expression, Predicate):
        field = catalog.get(expression.field) if catalog is not None else None
        return _compile_predicate(expression, field)
    if isinstance(expression, All):
        body = " && ".join(
            _compile_expression(child, catalog) for child in expression.children
        )
        return f"({body})"
    if isinstance(expression, AnyOf):
        body = " || ".join(
            _compile_expression(child, catalog) for child in expression.children
        )
        return f"({body})"
    return f"!({_compile_expression(expression.child, catalog)})"


def compile_intent(
    intent: IntentIrV1, catalog: FieldCatalogV1 | None = None
) -> str:
    """Compiles a validated intent into a deterministic display filter.

    Args:
        intent: Typed version-one intent.
        catalog: Optional version-pinned catalog. When supplied, all fields,
            operators, and values are validated before compilation.

    Returns:
        A Wireshark display-filter expression.
    """
    if catalog is not None:
        validate_expression(intent.expression, catalog)
    return _compile_expression(intent.expression, catalog)
