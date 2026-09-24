"""Frozen SQLite inventory and the local tshark catalog binding boundary."""

from __future__ import annotations

from collections.abc import Generator, Iterable, Iterator
from contextlib import closing
from contextlib import contextmanager
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from typing import cast
import zlib

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.canonical import file_sha256
from dfilterforge.field_catalog import apply_enum_values
from dfilterforge.field_catalog import CatalogError
from dfilterforge.field_catalog import FieldCatalogV1
from dfilterforge.field_catalog import FieldDefinition
from dfilterforge.field_catalog import parse_tshark_fields
from dfilterforge.field_catalog import parse_tshark_values
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Predicate
from dfilterforge.runner import TsharkRunner

DEFAULT_CATALOG_PATH = Path("/opt/dfilterforge/catalog.sqlite3")
# The cap sits above the measured 299,327,488-byte frozen inventory and is
# read from this global inside the decompressor so a test can lower it.
_MAX_CATALOG_BYTES = 1 << 30
_CATALOG_CHUNK_BYTES = 1 << 20
_CATALOG_REPORTS = ("fields", "values")
_PROFILE_REPORTS = ("currentprefs", "decodes", "heuristic-decodes")
_PROFILE_KEYS = frozenset(
    {
        "tshark_version",
        "build_and_libraries",
        "execution_policy",
        *_PROFILE_REPORTS,
    }
)
_RECORD_KINDS = frozenset({"F", "P", "V", "V64", "R", "T", "E", "U"})
_SCHEMA_VERSION = "frozen-catalog/1.0"


@lru_cache(maxsize=16)
def runtime_profile(runner: TsharkRunner) -> dict[str, str]:
    """Measure configuration once using the runner's isolated environment."""
    return {
        "tshark_version": runner.version(),
        "build_and_libraries": "\n".join(
            line
            for line in runner.report("version").decode("utf-8").splitlines()
            if not line.strip().startswith(
                ("OS:", "CPU:", "Memory:", "Locale:")
            )
        ),
        "execution_policy": "isolated-default-profile;name-resolution-disabled",
        **{
            name: runner.report(name).decode("utf-8")
            for name in _PROFILE_REPORTS
        },
    }


def _lines(output: bytes) -> Iterator[str]:
    """Yield logical report records, including multiline value labels."""
    pending = ""
    with io.BytesIO(output) as stream:
        for line in stream:
            decoded = line.decode("utf-8").rstrip("\r\n")
            if decoded.partition("\t")[0] in _RECORD_KINDS:
                if pending:
                    yield pending
                pending = decoded
            else:
                pending += "\n" + decoded
    if pending:
        yield pending


def _record_name(report: str, record: str) -> str:
    """Return the indexed abbreviation for one raw tshark record."""
    columns = record.split("\t", 3)
    if report == "fields" and len(columns) >= 3:
        return columns[2]
    return columns[1] if len(columns) >= 2 else ""


def _freeze_report(
    database: sqlite3.Connection, report: str, raw: bytes
) -> tuple[int, str]:
    """Store one report in canonical order and return its count and identity."""
    database.execute(
        "CREATE TABLE staging (name TEXT NOT NULL, record TEXT NOT NULL)"
    )
    count = 0
    for record in _lines(raw):
        database.execute(
            "INSERT INTO staging VALUES (?, ?)",
            (_record_name(report, record), record),
        )
        count += 1
    database.execute("CREATE INDEX staging_name ON staging(name)")
    database.execute(
        f"CREATE TABLE {report}_records "
        "(name TEXT NOT NULL, record TEXT NOT NULL)"
    )
    digest = hashlib.sha256()
    # tshark registers some value tables in process-dependent hash-map order.
    # Sort each indexed group to bound sort memory and preserve duplicates.
    names = database.execute(
        "SELECT DISTINCT name FROM staging ORDER BY name COLLATE BINARY"
    )
    for (name,) in names:
        records = database.execute(
            "SELECT record FROM staging WHERE name = ? "
            "ORDER BY record COLLATE BINARY",
            (name,),
        )
        for (record,) in records:
            database.execute(
                f"INSERT INTO {report}_records VALUES (?, ?)", (name, record)
            )
            encoded = record.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    database.execute("DROP TABLE staging")
    database.execute(f"CREATE INDEX {report}_name ON {report}_records(name)")
    return count, digest.hexdigest()


def freeze_catalog(
    output: Path, runner: TsharkRunner | None = None
) -> dict[str, object]:
    """Freeze every registered field and raw enum report record in SQLite.

    Raw records preserve unsupported types, ranges, boolean labels and extended
    tables. Numeric labels are descriptive metadata, never a closed value set.
    The indexed inventory projects only requested fields into the domain core.
    """
    active = runner if runner is not None else TsharkRunner()
    profile = runtime_profile(active)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite an existing freeze, including one currently in use.
    with output.open("xb"):
        pass
    counts: dict[str, int] = {}
    identities: dict[str, str] = {}
    with sqlite3.connect(output) as database:
        database.execute(
            "CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        for report in _CATALOG_REPORTS:
            counts[report], identities[report] = _freeze_report(
                database, report, active.report(report)
            )
        metadata: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "profile": profile,
            "catalog_hash": content_sha256(identities),
            "counts": counts,
        }
        database.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [(name, canonical_json(value)) for name, value in metadata.items()],
        )
        database.commit()
        # Remove staging pages; file bytes depend only on canonical rows.
        database.execute("VACUUM")
    return metadata


def _field_names(expression: Expression) -> Iterator[str]:
    if isinstance(expression, Predicate):
        yield expression.field
    elif isinstance(expression, (All, AnyOf)):
        for child in expression.children:
            yield from _field_names(child)
    else:
        yield from _field_names(expression.child)


def _definition(database: sqlite3.Connection, name: str) -> FieldDefinition:
    rows = database.execute(
        "SELECT record FROM fields_records WHERE name = ? ORDER BY rowid",
        (name,),
    )
    fields = parse_tshark_fields(str(row[0]) for row in rows)
    if not fields:
        raise CatalogError("unknown_field", f"Unknown field: {name}")
    types = {field.field_type for field in fields}
    raw_types = {
        field.tshark_type for field in fields if field.tshark_type is not None
    }
    if len(types) != 1 or len(raw_types) > 1:
        raise CatalogError(
            "ambiguous_field", f"Conflicting field registrations: {name}"
        )
    rows = database.execute(
        "SELECT record FROM values_records WHERE name = ? ORDER BY rowid",
        (name,),
    )
    values = parse_tshark_values(str(row[0]) for row in rows)
    return apply_enum_values((fields[0],), values)[0]


def tshark_types(
    names: Iterable[str], path: Path = DEFAULT_CATALOG_PATH
) -> dict[str, str]:
    """Returns the raw tshark type of each name the frozen inventory registers.

    A name the inventory does not register, or registers with conflicting
    types, is left out, so no caller can mistake it for a known type.

    Args:
        names: Field names as a candidate wrote them.
        path: The frozen inventory.

    Returns:
        The tshark type, such as ``FT_FRAMENUM``, of each registered name.

    Raises:
        CatalogError: With code ``catalog_unavailable`` or
            ``catalog_invalid`` when the inventory cannot be read.
    """
    try:
        with closing(
            sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
            )
        ) as database:
            database.execute("PRAGMA trusted_schema = OFF")
            found: dict[str, str] = {}
            for name in sorted(set(names)):
                rows = database.execute(
                    "SELECT record FROM fields_records WHERE name = ? "
                    "ORDER BY rowid",
                    (name,),
                )
                raw = {
                    field.tshark_type
                    for field in parse_tshark_fields(
                        str(row[0]) for row in rows
                    )
                    if field.tshark_type is not None
                }
                if len(raw) == 1:
                    found[name] = raw.pop()
            return found
    except (sqlite3.Error, OSError):
        raise _unavailable() from None
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise _invalid_metadata() from None


def _invalid_metadata() -> CatalogError:
    """Build the one sanitized error raised for malformed frozen metadata."""
    return CatalogError(
        "catalog_invalid", "Frozen inventory metadata is invalid"
    )


def _unavailable() -> CatalogError:
    """Build the one sanitized error raised for an unreadable inventory."""
    return CatalogError(
        "catalog_unavailable",
        "Frozen catalog cannot be opened; build the pinned Docker image",
    )


def _profile_metadata(value: object) -> dict[str, str]:
    """Validate and narrow a decoded runtime profile."""
    if not isinstance(value, dict):
        raise _invalid_metadata()
    mapping = cast(dict[object, object], value)
    if set(mapping) != set(_PROFILE_KEYS) or not all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in mapping.items()
    ):
        raise _invalid_metadata()
    return cast(dict[str, str], mapping)


def _count_metadata(value: object) -> dict[str, int]:
    """Validate and narrow decoded inventory record counts."""
    if not isinstance(value, dict):
        raise _invalid_metadata()
    mapping = cast(dict[object, object], value)
    if set(mapping) != set(_CATALOG_REPORTS) or not all(
        isinstance(key, str)
        and isinstance(item, int)
        and not isinstance(item, bool)
        and item >= 0
        for key, item in mapping.items()
    ):
        raise _invalid_metadata()
    return cast(dict[str, int], mapping)


def _catalog_identity(value: object) -> str:
    """Validate and narrow a frozen inventory digest."""
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _invalid_metadata()
    return value


def _catalog_metadata(
    database: sqlite3.Connection,
) -> tuple[dict[str, str], str]:
    """Read and validate the frozen inventory's self-describing metadata."""
    rows = database.execute("SELECT name, value FROM metadata").fetchall()
    metadata: dict[str, object] = {}
    for name, value in rows:
        if not isinstance(name, str) or not isinstance(value, str):
            raise _invalid_metadata()
        metadata[name] = cast(object, json.loads(value))
    required = {"schema_version", "profile", "catalog_hash", "counts"}
    if (
        set(metadata) != required
        or metadata["schema_version"] != _SCHEMA_VERSION
    ):
        raise CatalogError(
            "catalog_invalid", "Frozen inventory metadata is missing"
        )

    profile = _profile_metadata(metadata["profile"])
    identity = _catalog_identity(metadata["catalog_hash"])
    counts = _count_metadata(metadata["counts"])
    actual_counts = {
        report: int(
            database.execute(
                f"SELECT count(*) FROM {report}_records"
            ).fetchone()[0]
        )
        for report in _CATALOG_REPORTS
    }
    if counts != actual_counts:
        raise CatalogError(
            "catalog_invalid", "Frozen inventory record counts differ"
        )
    return profile, identity


@dataclass(frozen=True)
class FrozenCatalogFile:
    """One opened frozen inventory and the identity that names it.

    ``sqlite_path`` is a live handle for this context only and must not be
    recorded, because an absolute path would leak the host layout. The
    remaining fields are what a committed run manifest carries.
    """

    sqlite_path: Path
    file_name: str
    file_sha256: str
    sqlite_sha256: str
    catalog_hash: str
    tshark_version: str


def _decompress_catalog(archive: Path, target: Path) -> str:
    """Streams a gzip archive to ``target`` and returns its SHA-256 digest."""
    digest = hashlib.sha256()
    total = 0
    try:
        with gzip.open(archive, "rb") as source, target.open("wb") as output:
            while chunk := source.read(_CATALOG_CHUNK_BYTES):
                total += len(chunk)
                if total > _MAX_CATALOG_BYTES:
                    raise CatalogError(
                        "catalog_too_large",
                        "Frozen catalog archive exceeds its size limit",
                    )
                digest.update(chunk)
                output.write(chunk)
    except (EOFError, OSError, zlib.error):
        raise _unavailable() from None
    return digest.hexdigest()


def _frozen_metadata(path: Path) -> tuple[dict[str, str], str]:
    """Reads profile and identity from a plain frozen SQLite inventory."""
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
        )
    except (OSError, sqlite3.Error):
        raise _unavailable() from None
    try:
        with closing(connection) as database:
            database.execute("PRAGMA trusted_schema = OFF")
            return _catalog_metadata(database)
    except CatalogError:
        raise
    except (sqlite3.Error, ValueError, TypeError, KeyError, UnicodeError):
        raise _invalid_metadata() from None


@contextmanager
def open_frozen_catalog(path: Path) -> Generator[FrozenCatalogFile]:
    """Opens a plain or gzipped frozen inventory and records its identity.

    Args:
        path: A ``.sqlite3`` inventory or a ``.gz`` archive of one. An archive
            is decompressed into a private temporary directory that is removed
            when the context exits.

    Yields:
        The readable inventory path and the identity that names it.

    Raises:
        CatalogError: If the file cannot be read, the decompressed inventory
            exceeds the size cap, or its frozen metadata is invalid.
    """
    with ExitStack() as stack:
        try:
            archive_digest = file_sha256(path)
        except OSError:
            raise _unavailable() from None
        if path.suffix == ".gz":
            directory = stack.enter_context(
                TemporaryDirectory(prefix="dfilterforge-catalog-")
            )
            sqlite_path = Path(directory) / "catalog.sqlite3"
            sqlite_digest = _decompress_catalog(path, sqlite_path)
        else:
            sqlite_path = path
            sqlite_digest = archive_digest
        profile, identity = _frozen_metadata(sqlite_path)
        yield FrozenCatalogFile(
            sqlite_path=sqlite_path,
            file_name=path.name,
            file_sha256=archive_digest,
            sqlite_sha256=sqlite_digest,
            catalog_hash=identity,
            tshark_version=profile["tshark_version"],
        )


def _runtime_binding(
    runner: TsharkRunner,
    profile: dict[str, str],
    supplied: FieldCatalogV1 | None,
) -> tuple[str, str]:
    """Validate the executable and supplied projection against the profile."""
    version = runner.version()
    if profile["tshark_version"] != version or (
        supplied is not None and supplied.tshark_version != version
    ):
        raise CatalogError(
            "catalog_version_mismatch",
            "Catalog and executable versions differ",
        )
    if profile != runtime_profile(runner):
        raise CatalogError(
            "catalog_profile_mismatch",
            "Catalog and runtime configurations differ",
        )
    profile_hash = content_sha256(profile)
    if supplied is not None and supplied.profile_hash != profile_hash:
        raise CatalogError(
            "catalog_profile_mismatch", "Supplied catalog profile differs"
        )
    return version, profile_hash


def _validate_projection(
    supplied: FieldCatalogV1 | None,
    fields: tuple[FieldDefinition, ...],
    identity: str,
) -> None:
    """Reject caller fields or source identities not present in the freeze."""
    if supplied is None:
        return
    supplied_fields = {field.abbreviation: field for field in supplied.fields}
    for field in fields:
        if field.abbreviation not in supplied_fields:
            raise CatalogError(
                "unknown_field", f"Unknown field: {field.abbreviation}"
            )
        if supplied_fields[field.abbreviation] != field:
            raise CatalogError(
                "catalog_field_mismatch",
                "Supplied field differs from frozen inventory",
            )
    if supplied.source_catalog_hash not in (None, identity):
        raise CatalogError(
            "catalog_identity_mismatch",
            "Supplied inventory identity differs",
        )


def bind_catalog(
    runner: TsharkRunner,
    intents: tuple[IntentIrV1, ...],
    supplied: FieldCatalogV1 | None = None,
    path: Path = DEFAULT_CATALOG_PATH,
) -> FieldCatalogV1:
    """Bind requested fields to the frozen inventory and actual runtime.

    A caller-supplied projection cannot introduce or change definitions. The
    immutable Docker inventory is the trust anchor; no full rehash is needed.
    """
    try:
        # closing(), not the connection's own context manager: the queries are
        # read-only, and an open handle blocks removal of a decompressed copy.
        with closing(
            sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True
            )
        ) as database:
            database.execute("PRAGMA trusted_schema = OFF")
            profile, identity = _catalog_metadata(database)
            version, profile_hash = _runtime_binding(runner, profile, supplied)
            names = sorted(
                {
                    name
                    for intent in intents
                    for name in _field_names(intent.expression)
                }
            )
            fields = tuple(_definition(database, name) for name in names)
            _validate_projection(supplied, fields, identity)
            return FieldCatalogV1(
                tshark_version=version,
                profile_hash=profile_hash,
                fields=fields,
                source_catalog_hash=identity,
            )
    except CatalogError:
        raise
    except (sqlite3.Error, OSError):
        raise _unavailable() from None
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise _invalid_metadata() from None
