"""Tests for the versioned intent IR contracts."""

from pydantic import ValidationError
import pytest

from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate


def test_recursive_ir_parses_discriminated_nodes() -> None:
    intent = IntentIrV1.model_validate(
        {
            "expression": {
                "kind": "all",
                "children": [
                    {
                        "kind": "predicate",
                        "field": "udp",
                        "operator": "exists",
                    },
                    {
                        "kind": "not",
                        "child": {
                            "kind": "predicate",
                            "field": "dns.flags.response",
                            "operator": "eq",
                            "value": True,
                        },
                    },
                ],
            }
        }
    )

    assert isinstance(intent.expression, All)
    assert intent.ir_schema_version == "1.0"


@pytest.mark.parametrize(
    ("operator", "value", "message"),
    [
        ("exists", 1, "does not accept"),
        ("eq", None, "requires a value"),
        ("in", [], "non-empty"),
        ("contains", 80, "string value"),
        ("in_subnet", "10.0.0.999/8", "valid CIDR"),
    ],
)
def test_predicate_rejects_invalid_operator_shape(
    operator: str, value: object, message: str
) -> None:
    payload = {"field": "ip.src", "operator": operator, "value": value}

    with pytest.raises(ValidationError, match=message):
        Predicate.model_validate(payload)


def test_boolean_value_is_not_confused_with_missing_value() -> None:
    predicate = Predicate(
        field="dns.flags.response", operator=Operator.EQ, value=False
    )

    assert predicate.value is False


def test_generation_status_contracts_are_exclusive() -> None:
    intent = IntentIrV1(
        expression=Predicate(field="tcp", operator=Operator.EXISTS)
    )
    result = GenerationResultV1(status=GenerationStatus.READY, intent_ir=intent)

    assert result.intent_ir == intent
    with pytest.raises(ValidationError, match="requires clarifying_question"):
        GenerationResultV1(status=GenerationStatus.NEEDS_CLARIFICATION)
    with pytest.raises(ValidationError, match="cannot include intent_ir"):
        GenerationResultV1(
            status=GenerationStatus.NOT_EXPRESSIBLE, intent_ir=intent
        )


def test_ir_is_frozen_and_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        IntentIrV1.model_validate(
            {
                "scope": "packet",
                "expression": {
                    "kind": "predicate",
                    "field": "tcp",
                    "operator": "exists",
                    "unexpected": True,
                },
            }
        )


def test_ir_rejects_bad_field_and_single_child_boolean_group() -> None:
    with pytest.raises(ValidationError, match="Wireshark-style"):
        Predicate(field="Invalid Field", operator=Operator.EXISTS)
    with pytest.raises(ValidationError, match="at least 2"):
        IntentIrV1.model_validate(
            {
                "expression": {
                    "kind": "all",
                    "children": [
                        {
                            "kind": "predicate",
                            "field": "tcp",
                            "operator": "exists",
                        }
                    ],
                }
            }
        )


def test_not_expressible_rejects_question_payload() -> None:
    with pytest.raises(ValidationError, match="cannot include"):
        GenerationResultV1(
            status=GenerationStatus.NOT_EXPRESSIBLE,
            clarifying_question="Which host?",
        )


def test_generation_ready_payload_rules() -> None:
    intent = IntentIrV1(
        expression=Predicate(field="tcp", operator=Operator.EXISTS)
    )
    with pytest.raises(ValidationError, match="ready requires"):
        GenerationResultV1(status=GenerationStatus.READY)
    with pytest.raises(ValidationError, match="cannot include a clarifying"):
        GenerationResultV1(
            status=GenerationStatus.READY,
            intent_ir=intent,
            clarifying_question="Unused question",
        )
    with pytest.raises(ValidationError, match="cannot include intent_ir"):
        GenerationResultV1(
            status=GenerationStatus.NEEDS_CLARIFICATION,
            clarifying_question="Which direction?",
            intent_ir=intent,
        )


def test_scalar_operator_rejects_list_value() -> None:
    with pytest.raises(ValidationError, match="requires a scalar"):
        Predicate(field="tcp.port", operator=Operator.EQ, value=(80, 443))
