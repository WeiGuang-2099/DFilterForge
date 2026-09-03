"""Tests for catalog parsing and typed field validation."""

import pytest

from dfilterforge.field_catalog import apply_enum_values
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_catalog import parse_tshark_fields
from dfilterforge.field_catalog import parse_tshark_values
from dfilterforge.field_catalog import validate_predicate
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import ScalarValue


@pytest.fixture(name="catalog")
def catalog_fixture() -> FieldCatalogV1:
    return FieldCatalogV1(
        tshark_version="4.6.8",
        profile_hash="profile",
        fields=(
            FieldDefinition(
                abbreviation="tcp",
                field_type=FieldType.PROTOCOL,
                protocol="tcp",
                display_name="Transmission Control Protocol",
            ),
            FieldDefinition(
                abbreviation="tcp.dstport",
                field_type=FieldType.INTEGER,
                protocol="tcp",
                display_name="Destination Port",
            ),
            FieldDefinition(
                abbreviation="ip.src",
                field_type=FieldType.IPV4,
                protocol="ip",
                display_name="Source Address",
            ),
            FieldDefinition(
                abbreviation="http.host",
                field_type=FieldType.STRING,
                protocol="http",
                display_name="Host",
            ),
        ),
    )


def test_catalog_hash_can_be_pinned(catalog: FieldCatalogV1) -> None:
    payload = catalog.model_dump(mode="json")
    payload["catalog_hash"] = catalog.compute_hash()

    restored = FieldCatalogV1.model_validate(payload)

    assert restored.catalog_hash == catalog.compute_hash()


def test_catalog_rejects_wrong_hash(catalog: FieldCatalogV1) -> None:
    payload = catalog.model_dump(mode="json")
    payload["catalog_hash"] = "wrong"

    with pytest.raises(ValueError, match="does not match"):
        FieldCatalogV1.model_validate(payload)


def test_validate_predicate_reports_stable_error_codes(
    catalog: FieldCatalogV1,
) -> None:
    with pytest.raises(CatalogError) as unknown:
        validate_predicate(
            Predicate(field="tcp.magic", operator=Operator.EQ, value=1), catalog
        )
    assert unknown.value.code == "unknown_field"

    with pytest.raises(CatalogError) as mismatch:
        validate_predicate(
            Predicate(field="tcp.dstport", operator=Operator.EQ, value="443"),
            catalog,
        )
    assert mismatch.value.code == "type_mismatch"

    with pytest.raises(CatalogError) as unsupported:
        validate_predicate(
            Predicate(field="http.host", operator=Operator.GT, value="a"),
            catalog,
        )
    assert unsupported.value.code == "unsupported_operator"


def test_validate_ip_version(catalog: FieldCatalogV1) -> None:
    with pytest.raises(CatalogError) as mismatch:
        validate_predicate(
            Predicate(
                field="ip.src",
                operator=Operator.IN_SUBNET,
                value="2001:db8::/32",
            ),
            catalog,
        )

    assert mismatch.value.code == "type_mismatch"


def test_supported_predicates_pass_catalog_validation(
    catalog: FieldCatalogV1,
) -> None:
    validate_predicate(
        Predicate(field="tcp", operator=Operator.EXISTS), catalog
    )
    validate_predicate(
        Predicate(field="tcp.dstport", operator=Operator.GE, value=1024),
        catalog,
    )
    validate_predicate(
        Predicate(field="http.host", operator=Operator.CONTAINS, value="api"),
        catalog,
    )
    validate_predicate(
        Predicate(
            field="ip.src", operator=Operator.IN_SUBNET, value="10.0.0.0/8"
        ),
        catalog,
    )


def test_protocol_comparison_is_rejected(catalog: FieldCatalogV1) -> None:
    with pytest.raises(CatalogError) as error:
        validate_predicate(
            Predicate(field="tcp", operator=Operator.EQ, value=True), catalog
        )

    assert error.value.code == "unsupported_operator"


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        (FieldType.BOOLEAN, 1),
        (FieldType.INTEGER, True),
        (FieldType.FLOAT, "1.5"),
        (FieldType.STRING, 80),
        (FieldType.BYTES, 80),
        (FieldType.IPV4, "2001:db8::1"),
        (FieldType.IPV6, "192.0.2.1"),
    ],
)
def test_field_types_reject_mismatched_equality(
    field_type: FieldType, value: ScalarValue
) -> None:
    catalog = FieldCatalogV1(
        tshark_version="4.6.8",
        profile_hash="profile",
        fields=(
            FieldDefinition(
                abbreviation="test.field",
                field_type=field_type,
                protocol="test",
                display_name="Test Field",
            ),
        ),
    )

    with pytest.raises(CatalogError) as error:
        validate_predicate(
            Predicate(field="test.field", operator=Operator.EQ, value=value),
            catalog,
        )

    assert error.value.code == "type_mismatch"


def test_enum_accepts_only_catalog_members() -> None:
    fields = apply_enum_values(
        (
            FieldDefinition(
                abbreviation="dns.qry.type",
                field_type=FieldType.INTEGER,
                protocol="dns",
                display_name="Query Type",
            ),
        ),
        parse_tshark_values(["V\tdns.qry.type\t1\tA"]),
    )
    catalog = FieldCatalogV1(
        tshark_version="4.6.8", profile_hash="profile", fields=fields
    )
    validate_predicate(
        Predicate(field="dns.qry.type", operator=Operator.EQ, value=1), catalog
    )

    with pytest.raises(CatalogError) as error:
        validate_predicate(
            Predicate(field="dns.qry.type", operator=Operator.EQ, value=28),
            catalog,
        )

    assert error.value.code == "type_mismatch"


def test_parse_tshark_fields_and_values() -> None:
    fields = parse_tshark_fields(
        [
            "P\tDomain Name System\tdns",
            "F\tQuery Type\tdns.qry.type\tFT_UINT16\tdns\tBASE_DEC",
            "F\tIgnored\tdns.time\tFT_RELATIVE_TIME\tdns\tBASE_NONE",
        ]
    )
    values = parse_tshark_values(
        [
            "V\tdns.qry.type\t1\tA (Host Address)",
            "V\tdns.qry.type\t0x1c\tAAAA",
            "R\tdns.qry.type\t2\t10\tReserved",
        ]
    )

    enriched = apply_enum_values(fields, values)

    assert [field.abbreviation for field in enriched] == ["dns", "dns.qry.type"]
    assert enriched[1].field_type == FieldType.ENUM
    assert [member.value for member in enriched[1].enum_values] == [1, 28]


def test_catalog_rejects_duplicate_field_abbreviations() -> None:
    field = FieldDefinition(
        abbreviation="tcp.port",
        field_type=FieldType.INTEGER,
        protocol="tcp",
        display_name="Port",
    )

    with pytest.raises(ValueError, match="duplicate"):
        FieldCatalogV1(
            tshark_version="4.6.8",
            profile_hash="profile",
            fields=(field, field),
        )


def test_field_names_must_be_trimmed() -> None:
    with pytest.raises(ValueError, match="trimmed"):
        FieldDefinition(
            abbreviation=" tcp.port ",
            field_type=FieldType.INTEGER,
            protocol="tcp",
            display_name="Port",
        )


def test_in_operator_validates_every_member(catalog: FieldCatalogV1) -> None:
    validate_predicate(
        Predicate(field="tcp.dstport", operator=Operator.IN, value=(80, 443)),
        catalog,
    )

    with pytest.raises(CatalogError) as error:
        validate_predicate(
            Predicate(
                field="tcp.dstport", operator=Operator.IN, value=(80, "443")
            ),
            catalog,
        )

    assert error.value.code == "type_mismatch"


def test_invalid_ip_address_is_a_type_mismatch(
    catalog: FieldCatalogV1,
) -> None:
    with pytest.raises(CatalogError) as error:
        validate_predicate(
            Predicate(field="ip.src", operator=Operator.EQ, value="invalid"),
            catalog,
        )

    assert error.value.code == "type_mismatch"


def test_string_enum_value_is_preserved() -> None:
    values = parse_tshark_values(["V\ttest.mode\tauto\tAutomatic"])

    assert values["test.mode"][0].value == "auto"
