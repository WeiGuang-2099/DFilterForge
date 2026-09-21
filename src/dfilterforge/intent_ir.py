"""Versioned typed intent intermediate representation."""

from __future__ import annotations

from enum import StrEnum
import ipaddress
import re
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

# Only ever applied with fullmatch.
FIELD_NAME_PATTERN = re.compile(r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*")
MAX_FIELD_NAME_BYTES = 256


def validate_field_name(value: str) -> str:
    """Returns one Wireshark-style field name, unchanged and bounded.

    The length check rejects oversized input before the regular
    expression sees it. The grammar admits only ASCII, so every name
    that is returned occupies exactly one byte per character.

    Args:
        value: Untrusted name from a model reply or a catalog row.

    Returns:
        The name exactly as given, including its case.

    Raises:
        ValueError: If the name is too long or is not a field name.
    """
    if len(value) > MAX_FIELD_NAME_BYTES:
        raise ValueError("field name exceeds 256 bytes")
    if not FIELD_NAME_PATTERN.fullmatch(value):
        raise ValueError("field must be a Wireshark-style field name")
    return value


class FrozenModel(BaseModel):
    """Base configuration shared by public immutable contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Operator(StrEnum):
    """Operators supported by the version-one compiler."""

    EXISTS = "exists"
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    CONTAINS = "contains"
    IN = "in"
    IN_SUBNET = "in_subnet"


ScalarValue: TypeAlias = bool | int | float | str


class Predicate(FrozenModel):
    """A single typed field operation."""

    kind: Literal["predicate"] = "predicate"
    field: str
    operator: Operator
    value: ScalarValue | tuple[ScalarValue, ...] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "Predicate":
        """Validates operator-specific value shape."""
        validate_field_name(self.field)
        if self.operator == Operator.EXISTS:
            if self.value is not None:
                raise ValueError("exists does not accept a value")
            return self
        if self.value is None:
            raise ValueError(f"{self.operator.value} requires a value")
        if self.operator == Operator.IN:
            if not isinstance(self.value, tuple) or not self.value:
                raise ValueError("in requires a non-empty value list")
            return self
        if isinstance(self.value, tuple):
            raise ValueError(f"{self.operator.value} requires a scalar value")
        if self.operator == Operator.CONTAINS and not isinstance(
            self.value, str
        ):
            raise ValueError("contains requires a string value")
        if self.operator == Operator.IN_SUBNET:
            if not isinstance(self.value, str):
                raise ValueError("in_subnet requires a CIDR string")
            try:
                ipaddress.ip_network(self.value, strict=False)
            except ValueError as error:
                raise ValueError(
                    "in_subnet requires valid CIDR notation"
                ) from error
        return self


class All(FrozenModel):
    """A conjunction of two or more expressions."""

    kind: Literal["all"] = "all"
    children: tuple["Expression", ...] = Field(min_length=2)


class AnyOf(FrozenModel):
    """A disjunction of two or more expressions."""

    kind: Literal["any"] = "any"
    children: tuple["Expression", ...] = Field(min_length=2)


class Not(FrozenModel):
    """Logical negation of one expression."""

    kind: Literal["not"] = "not"
    child: "Expression"


Expression: TypeAlias = Annotated[
    Predicate | All | AnyOf | Not,
    Field(discriminator="kind"),
]


def walk_predicates(
    expression: Expression,
) -> tuple[tuple[tuple[int, ...], Predicate], ...]:
    """Returns leaf predicates in stable preorder with their AST paths.

    ``All`` and ``AnyOf`` children use their zero-based child index. A ``Not``
    child uses index zero. A predicate at the expression root has an empty
    path.

    Args:
        expression: Typed expression tree to traverse.

    Returns:
        Predicate paths and values in stable preorder.
    """
    predicates: list[tuple[tuple[int, ...], Predicate]] = []
    pending: list[tuple[tuple[int, ...], Expression]] = [((), expression)]
    while pending:
        path, node = pending.pop()
        if isinstance(node, Predicate):
            predicates.append((path, node))
        elif isinstance(node, (All, AnyOf)):
            for index in range(len(node.children) - 1, -1, -1):
                pending.append((path + (index,), node.children[index]))
        else:
            pending.append((path + (0,), node.child))
    return tuple(predicates)


class IntentIrV1(FrozenModel):
    """Root contract for a packet-scoped version-one intent."""

    ir_schema_version: Literal["1.0"] = "1.0"
    scope: Literal["packet"] = "packet"
    expression: Expression


class GenerationStatus(StrEnum):
    """Expressibility outcome for natural-language generation."""

    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    NOT_EXPRESSIBLE = "not_expressible"


class MissingSlot(StrEnum):
    """The closed set of request slots a model may report as open."""

    ADDRESS = "address"
    DIRECTION = "direction"
    FIELD = "field"
    PORT = "port"
    PROTOCOL = "protocol"
    VALUE = "value"


def check_status_payload(
    status: GenerationStatus,
    *,
    payload_name: str,
    has_payload: bool,
    clarifying_question: str | None,
    missing_slots: tuple[MissingSlot, ...],
) -> None:
    """Applies one abstention rule set to every generation envelope.

    Args:
        status: Expressibility outcome the model returned.
        payload_name: Name of the status-bearing payload field.
        has_payload: Whether that payload is present.
        clarifying_question: The single question, when one was asked.
        missing_slots: Slots the request leaves open.

    Raises:
        ValueError: If the status and its payload cannot occur together.
    """
    if len(set(missing_slots)) != len(missing_slots):
        raise ValueError("missing_slots must be unique")
    if status != GenerationStatus.NEEDS_CLARIFICATION and missing_slots:
        raise ValueError(
            "missing_slots are allowed only for needs_clarification"
        )
    if status == GenerationStatus.READY:
        if not has_payload:
            raise ValueError(f"ready requires {payload_name}")
        if clarifying_question is not None:
            raise ValueError("ready cannot include a clarifying question")
    elif status == GenerationStatus.NEEDS_CLARIFICATION:
        if not clarifying_question:
            raise ValueError("needs_clarification requires clarifying_question")
        if has_payload:
            raise ValueError(
                f"needs_clarification cannot include {payload_name}"
            )
    elif has_payload or clarifying_question is not None:
        raise ValueError(
            f"not_expressible cannot include {payload_name} or a question"
        )


class GenerationResultV1(FrozenModel):
    """Structured output from an intent generation backend."""

    schema_version: Literal["1.0"] = "1.0"
    status: GenerationStatus
    assumptions: tuple[str, ...] = ()
    clarifying_question: str | None = None
    missing_slots: tuple[MissingSlot, ...] = Field(
        default=(), max_length=len(MissingSlot)
    )
    intent_ir: IntentIrV1 | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "GenerationResultV1":
        """Ensures each status carries only the payload it can use."""
        check_status_payload(
            self.status,
            payload_name="intent_ir",
            has_payload=self.intent_ir is not None,
            clarifying_question=self.clarifying_question,
            missing_slots=self.missing_slots,
        )
        return self


All.model_rebuild()
AnyOf.model_rebuild()
Not.model_rebuild()
IntentIrV1.model_rebuild()
