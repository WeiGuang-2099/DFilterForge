"""Tests for complete frozen inventories and fail-closed runtime binding."""

import gzip
from pathlib import Path
import sqlite3
import tempfile

import pytest

from dfilterforge import catalog_runtime
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import freeze_catalog
from dfilterforge.catalog_runtime import open_frozen_catalog
from dfilterforge.compiler import compile_intent
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldType
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import retrieve_fields
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


def _gzip_copy(source: Path, target: Path) -> Path:
    """Write the deterministic archive form scripts/export_catalog.py writes."""
    with target.open("xb") as stream:
        with gzip.GzipFile(
            filename="", fileobj=stream, mode="wb", mtime=0
        ) as archive:
            archive.write(source.read_bytes())
    return target


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


def test_open_frozen_catalog_identifies_plain_and_gzip_inventories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "catalog.sqlite3"
    metadata = freeze_catalog(plain, _MetadataRunner())
    archive = _gzip_copy(plain, tmp_path / "catalog.sqlite3.gz")
    plain_digest = file_sha256(plain)
    with open_frozen_catalog(plain) as frozen:
        assert frozen.catalog_hash == metadata["catalog_hash"]
        assert frozen.tshark_version == "4.6.8"
        assert frozen.file_name == "catalog.sqlite3"
        assert frozen.file_sha256 == plain_digest
        assert frozen.sqlite_sha256 == plain_digest
        assert frozen.sqlite_path == plain
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def _record(database: str, *, uri: bool = False) -> sqlite3.Connection:
        connection = real_connect(database, uri=uri)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", _record)
    with open_frozen_catalog(archive) as frozen:
        assert frozen.catalog_hash == metadata["catalog_hash"]
        assert frozen.tshark_version == "4.6.8"
        assert frozen.file_name == "catalog.sqlite3.gz"
        assert frozen.sqlite_sha256 == plain_digest
        assert frozen.file_sha256 != plain_digest
        catalog = bind_catalog(
            _MetadataRunner(), (_intent(),), path=frozen.sqlite_path
        )
        assert catalog.get("tcp.port").enum_values[0].label == "HTTPS"
        results = retrieve_fields(
            frozen.sqlite_path,
            (FieldRetrievalItemV1(item_id="port", intent="TCP port"),),
            top_k=1,
        )
        assert results[0].fields[0].abbreviation == "tcp.port"
        decompressed = frozen.sqlite_path
    assert not decompressed.exists()
    assert plain.exists()
    # Both call sites inside the context must close their handle. On Windows
    # an open handle makes TemporaryDirectory.cleanup raise, so the removal
    # assertion above guards it only off CI; this one holds everywhere.
    assert len(opened) == 3
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("truncated", "catalog_unavailable"),
        ("corrupt_body", "catalog_unavailable"),
        ("oversize", "catalog_too_large"),
        ("missing_plain", "catalog_unavailable"),
        ("missing_archive", "catalog_unavailable"),
        ("no_metadata", "catalog_invalid"),
    ],
)
def test_open_frozen_catalog_fails_closed_on_bad_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, code: str
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    target = tmp_path / "missing.sqlite3"
    if case == "missing_archive":
        target = tmp_path / "missing.gz"
    elif case != "missing_plain":
        plain = tmp_path / "catalog.sqlite3"
        freeze_catalog(plain, _MetadataRunner())
        if case == "no_metadata":
            with sqlite3.connect(plain) as database:
                database.execute("DROP TABLE metadata")
            target = plain
        else:
            target = _gzip_copy(plain, tmp_path / "catalog.sqlite3.gz")
            if case == "truncated":
                target.write_bytes(target.read_bytes()[:512])
            elif case == "corrupt_body":
                # The first deflate byte, past the ten-byte gzip header: a
                # corrupted compressed stream raises zlib.error, which is not
                # an OSError and would otherwise escape unsanitized.
                raw = bytearray(target.read_bytes())
                raw[10] ^= 0x5A
                target.write_bytes(bytes(raw))
            else:
                monkeypatch.setattr(catalog_runtime, "_MAX_CATALOG_BYTES", 1024)
    with pytest.raises(CatalogError) as caught:
        with open_frozen_catalog(target):
            pass
    assert caught.value.code == code
    assert "private" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)
    assert not [
        entry
        for entry in tmp_path.iterdir()
        if entry.name.startswith("dfilterforge-catalog-")
    ]


def test_metadata_report_allowlist() -> None:
    with pytest.raises(RunnerError) as caught:
        TsharkRunner().report("fields; echo unsafe")
    assert caught.value.code == "report_invalid"
