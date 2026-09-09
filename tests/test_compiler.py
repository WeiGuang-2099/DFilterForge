"""Golden and safety tests for deterministic compilation."""

import pytest

from dfilterforge.compiler import compile_intent
from dfilterforge.compiler import CompileError
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import FieldType
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate


def test_compile_nested_expression_has_stable_parentheses() -> None:
    intent = IntentIrV1(
        expression=All(
            children=(
                Predicate(field="udp", operator=Operator.EXISTS),
                Not(
                    child=Predicate(
                        field="dns.flags.response",
                        operator=Operator.EQ,
                        value=True,
                    )
                ),
                AnyOf(
                    children=(
                        Predicate(
                            field="dns.qry.type", operator=Operator.EQ, value=1
                        ),
                        Predicate(
                            field="dns.qry.type", operator=Operator.EQ, value=28
                        ),
                    )
                ),
            )
        )
    )

    assert compile_intent(intent) == (
        "(udp && !(dns.flags.response == true) && "
        "(dns.qry.type == 1 || dns.qry.type == 28))"
    )


def test_compile_supported_literals_and_operators() -> None:
    intent = IntentIrV1(
        expression=All(
            children=(
                Predicate(
                    field="ip.src",
                    operator=Operator.IN_SUBNET,
                    value="10.0.0.0/8",
                ),
                Predicate(
                    field="tcp.dstport", operator=Operator.IN, value=(80, 443)
                ),
                Predicate(
                    field="http.host",
                    operator=Operator.CONTAINS,
                    value='a"b\\c',
                ),
            )
        )
    )

    assert compile_intent(intent) == (
        "(ip.src == 10.0.0.0/8 && tcp.dstport in {80, 443} && "
        'http.host contains "a\\"b\\\\c")'
    )


def test_compile_rejects_control_characters() -> None:
    intent = IntentIrV1(
        expression=Predicate(
            field="http.host", operator=Operator.EQ, value="bad\nvalue"
        )
    )

    with pytest.raises(CompileError) as error:
        compile_intent(intent)

    assert error.value.code == "invalid_value"


def test_compile_rejects_non_finite_number() -> None:
    intent = IntentIrV1(
        expression=Predicate(
            field="tcp.time_delta", operator=Operator.GT, value=float("inf")
        )
    )

    with pytest.raises(CompileError) as error:
        compile_intent(intent)

    assert error.value.code == "invalid_value"


def test_compile_validates_against_catalog() -> None:
    catalog = FieldCatalogV1(
        tshark_version="4.6.8",
        profile_hash="profile",
        fields=(
            FieldDefinition(
                abbreviation="tcp.dstport",
                field_type=FieldType.INTEGER,
                protocol="tcp",
                display_name="Destination Port",
            ),
        ),
    )
    intent = IntentIrV1(
        expression=Predicate(
            field="tcp.dstport", operator=Operator.EQ, value="443"
        )
    )

    with pytest.raises(CatalogError) as error:
        compile_intent(intent, catalog)

    assert error.value.code == "type_mismatch"


def test_compile_ip_address_without_string_quotes_when_catalog_is_known() -> (
    None
):
    catalog = FieldCatalogV1(
        tshark_version="4.6.8",
        profile_hash="profile",
        fields=(
            FieldDefinition(
                abbreviation="ip.src",
                field_type=FieldType.IPV4,
                protocol="ip",
                display_name="Source Address",
            ),
        ),
    )
    intent = IntentIrV1(
        expression=Predicate(
            field="ip.src", operator=Operator.EQ, value="192.0.2.1"
        )
    )

    assert compile_intent(intent, catalog) == "ip.src == 192.0.2.1"
