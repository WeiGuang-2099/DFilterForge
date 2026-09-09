"""Tests for complete frozen inventories and fail-closed runtime binding."""

from pathlib import Path
import sqlite3

import pytest

from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import freeze_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldType
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.runner import RunnerError
from dfilterforge.runner import TsharkRunner


class _MetadataRunner(TsharkRunner):

    def __init__(
        self,
        profile: bytes = b"default",
        version: str = "4.6.8",
        reverse_reports: bool = False,
    ) -> None:
        super().__init__()
        self.profile = profile
        self.recorded_version = version
        self.reverse_reports = reverse_reports

    def version(self) -> str:
        return self.recorded_version

    def report(self, name: str) -> bytes:
        if name == "fields":
            records = (
                b"P\tTCP\ttcp\n",
                b"P\tTCP duplicate\ttcp\n",
                b"F\tPort\ttcp.port\tFT_UINT16\ttcp\tBASE_DEC\n",
                b"F\tBytes\ttcp.payload\tFT_BYTES\ttcp\t\n",
                b"F\tTime\ttcp.time\tFT_RELATIVE_TIME\ttcp\t\n",
            )
        elif name == "values":
            records = (
                b"V\ttcp.port\t443\tHTTPS\n",
                b"R\ttcp.port\t0\t10\tReserved\n",
                b"T\ttcp.flag\tSet\tNot set\n",
                b"V64\ttcp.large\t4294967296\tLong label\ncontinued label\n",
            )
        else:
            return self.profile
        ordered = reversed(records) if self.reverse_reports else records
        return b"".join(ordered)


def _intent(
    field: str = "tcp.port", value: object = 443, operator: str = "eq"
) -> IntentIrV1:
    expression: dict[str, object] = {
        "kind": "predicate",
        "field": field,
        "operator": operator,
    }
    if operator != "exists":
        expression["value"] = value
    return IntentIrV1.model_validate({"expression": expression})


def test_freeze_is_byte_stable_and_retains_all_records(tmp_path: Path) -> None:
    first, second = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    metadata = freeze_catalog(first, _MetadataRunner())
    freeze_catalog(second, _MetadataRunner(reverse_reports=True))
    assert first.read_bytes() == second.read_bytes()
    assert metadata["counts"] == {"fields": 5, "values": 4}
    with sqlite3.connect(first) as database:
        value_records = database.execute(
            "SELECT record FROM values_records ORDER BY rowid"
        ).fetchall()
    assert len(value_records) == 4
    assert any(
        record.endswith("Long label\ncontinued label")
        for (record,) in value_records
    )
    catalog = bind_catalog(_MetadataRunner(), (_intent(),), path=first)
    assert len(catalog.fields) == 1
    assert catalog.get("tcp.port").enum_values[0].label == "HTTPS"
    assert compile_intent(_intent(value=65535), catalog) == "tcp.port == 65535"
    with pytest.raises(FileExistsError):
        freeze_catalog(first, _MetadataRunner())


@pytest.mark.parametrize(
    ("field", "value", "operator", "code"),
    [
        ("tcp.missing", 1, "eq", "unknown_field"),
        ("tcp.port", "443", "eq", "type_mismatch"),
        ("tcp.port", True, "eq", "type_mismatch"),
        ("tcp.port", -1, "eq", "type_mismatch"),
        ("tcp.port", 65536, "eq", "type_mismatch"),
        ("tcp.time", None, "exists", "unsupported_type"),
        ("tcp.payload", "not hex", "eq", "type_mismatch"),
        ("tcp.port", "44", "contains", "unsupported_operator"),
    ],
)
def test_invalid_intents_rejected_before_execution(
    tmp_path: Path, field: str, value: object, operator: str, code: str
) -> None:
    path = tmp_path / "catalog.sqlite3"
    freeze_catalog(path, _MetadataRunner())
    intent = _intent(field, value, operator)
    with pytest.raises(CatalogError) as caught:
        catalog = bind_catalog(_MetadataRunner(), (intent,), path=path)
        compile_intent(intent, catalog)
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("version", "profile", "code"),
    [
        ("4.6.7", b"default", "catalog_version_mismatch"),
        ("4.6.8", b"changed", "catalog_profile_mismatch"),
    ],
)
def test_runtime_drift_fails_closed(
    tmp_path: Path, version: str, profile: bytes, code: str
) -> None:
    path = tmp_path / "catalog.sqlite3"
    freeze_catalog(path, _MetadataRunner())
    with pytest.raises(CatalogError) as caught:
        bind_catalog(_MetadataRunner(profile, version), (_intent(),), path=path)
    assert caught.value.code == code


def test_supplied_projection_cannot_forge_type_or_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite3"
    freeze_catalog(path, _MetadataRunner())
    runner = _MetadataRunner()
    intent = _intent()
    catalog = bind_catalog(runner, (intent,), path=path)
    assert bind_catalog(runner, (intent,), catalog, path) == catalog
    wrong_field = catalog.fields[0].model_copy(
        update={"field_type": FieldType.STRING}
    )
    for changes, code in [
        ({"fields": (wrong_field,)}, "catalog_field_mismatch"),
        ({"profile_hash": "changed"}, "catalog_profile_mismatch"),
        ({"source_catalog_hash": "changed"}, "catalog_identity_mismatch"),
    ]:
        with pytest.raises(CatalogError) as caught:
            bind_catalog(
                runner, (intent,), catalog.model_copy(update=changes), path
            )
        assert caught.value.code == code


def test_duplicate_protocols_and_bytes_compile_safely(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite3"
    freeze_catalog(path, _MetadataRunner())
    intents = (
        _intent("tcp", operator="exists"),
        _intent("tcp.payload", "aa:bb", "contains"),
    )
    catalog = bind_catalog(_MetadataRunner(), intents, path=path)
    assert compile_intent(intents[0], catalog) == "tcp"
    assert compile_intent(intents[1], catalog) == "tcp.payload contains aa:bb"


@pytest.mark.parametrize(
    "state",
    [
        "missing",
        "invalid",
        "metadata",
        "json",
        "schema",
        "identity",
        "count",
        "truncated",
        "conflict",
    ],
)
def test_corrupted_inventory_is_sanitized(tmp_path: Path, state: str) -> None:
    path = tmp_path / "catalog.sqlite3"
    if state == "invalid":
        path.write_bytes(b"not sqlite")
    elif state != "missing":
        freeze_catalog(path, _MetadataRunner())
        with sqlite3.connect(path) as database:
            if state == "metadata":
                database.execute("DELETE FROM metadata WHERE name = 'profile'")
            elif state == "json":
                database.execute(
                    "UPDATE metadata SET value = 'bad private text' "
                    "WHERE name = 'profile'"
                )
            elif state == "schema":
                database.execute(
                    "UPDATE metadata SET value = '\"2.0\"' "
                    "WHERE name = 'schema_version'"
                )
            elif state == "identity":
                database.execute(
                    "UPDATE metadata SET value = '\"not-a-digest\"' "
                    "WHERE name = 'catalog_hash'"
                )
            elif state == "count":
                database.execute(
                    "UPDATE metadata SET value = "
                    '\'{"fields":5,"values":3}\' '
                    "WHERE name = 'counts'"
                )
            elif state == "truncated":
                database.execute(
                    "DELETE FROM values_records WHERE name = 'tcp.port'"
                )
            elif state == "conflict":
                database.execute(
                    "INSERT INTO fields_records VALUES "
                    "('tcp.port', "
                    "'F\tConflict\ttcp.port\tFT_STRING\ttcp')"
                )
    with pytest.raises(CatalogError) as caught:
        bind_catalog(_MetadataRunner(), (_intent(),), path=path)
    assert caught.value.code in {
        "catalog_invalid",
        "catalog_unavailable",
        "ambiguous_field",
    }
    assert "private" not in str(caught.value)


def test_metadata_report_allowlist() -> None:
    with pytest.raises(RunnerError) as caught:
        TsharkRunner().report("fields; echo unsafe")
    assert caught.value.code == "report_invalid"
