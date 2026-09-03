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

_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")


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
        if not _FIELD_PATTERN.fullmatch(self.field):
            raise ValueError("field must be a Wireshark-style abbreviation")
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


class GenerationResultV1(FrozenModel):
    """Structured output from an intent generation backend."""

    schema_version: Literal["1.0"] = "1.0"
    status: GenerationStatus
    assumptions: tuple[str, ...] = ()
    clarifying_question: str | None = None
    intent_ir: IntentIrV1 | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "GenerationResultV1":
        """Ensures each status carries only the payload it can use."""
        if self.status == GenerationStatus.READY:
            if self.intent_ir is None:
                raise ValueError("ready requires intent_ir")
            if self.clarifying_question is not None:
                raise ValueError("ready cannot include a clarifying question")
        elif self.status == GenerationStatus.NEEDS_CLARIFICATION:
            if not self.clarifying_question:
                raise ValueError(
                    "needs_clarification requires clarifying_question"
                )
            if self.intent_ir is not None:
                raise ValueError("needs_clarification cannot include intent_ir")
        elif self.intent_ir is not None or self.clarifying_question is not None:
            raise ValueError(
                "not_expressible cannot include intent_ir or a question"
            )
        return self


All.model_rebuild()
AnyOf.model_rebuild()
Not.model_rebuild()
IntentIrV1.model_rebuild()
