"""Measure the guarded frozen-catalog opener against a direct alternative."""

from __future__ import annotations

import argparse
import gzip
import inspect
import json
from pathlib import Path
import re
import resource
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from dfilterforge import canonical
from dfilterforge import catalog_runtime
from dfilterforge.catalog_runtime import _catalog_metadata
from dfilterforge.catalog_runtime import open_frozen_catalog
from dfilterforge.field_catalog import CatalogError

_CASES = (
    "intact",
    "truncated",
    "no_metadata",
    "missing_archive",
    "missing_plain",
)
_VARIANTS = ("full", "simplified")
_FULL_SYMBOLS = (
    "FrozenCatalogFile",
    "_unavailable",
    "_decompress_catalog",
    "_frozen_metadata",
    "open_frozen_catalog",
)
_ABSOLUTE_PATH = re.compile(r"(?:^|[\s'\"(=])/[A-Za-z0-9._/-]+")
_CHUNK_BYTES = 1024 * 1024


def _simplified_open(path: Path) -> tuple[str, str]:
    """The obvious alternative: decompress in memory and connect directly."""
    target = Path(tempfile.mkdtemp()) / "catalog.sqlite3"
    target.write_bytes(gzip.decompress(path.read_bytes()))
    profile, identity = _catalog_metadata(sqlite3.connect(str(target)))
    return identity, profile["tshark_version"]


def _case_path(work_dir: Path, case: str) -> Path:
    """Map a case name to the input the child opens."""
    names = {
        "intact": "catalog.sqlite3.gz",
        "truncated": "truncated.sqlite3.gz",
        "no_metadata": "no-metadata.sqlite3.gz",
        "missing_archive": "missing.sqlite3.gz",
        "missing_plain": "missing.sqlite3",
    }
    return work_dir / names[case]


def _write_archive(source: Path, target: Path) -> None:
    """Write the deterministic archive form scripts/export_catalog.py writes."""
    with source.open("rb") as stream:
        with target.open("xb") as raw:
            with gzip.GzipFile(
                filename="", fileobj=raw, mode="wb", mtime=0
            ) as archive:
                shutil.copyfileobj(stream, archive, _CHUNK_BYTES)


def _prepare(catalog: Path, work_dir: Path) -> dict[str, object]:
    """Build every input once and record what identifies them."""
    work_dir.mkdir(parents=True, exist_ok=True)
    archive = _case_path(work_dir, "intact")
    if not archive.exists():
        _write_archive(catalog, archive)
    truncated = _case_path(work_dir, "truncated")
    if not truncated.exists():
        with archive.open("rb") as stream:
            truncated.write_bytes(stream.read(512))
    stripped = _case_path(work_dir, "no_metadata")
    if not stripped.exists():
        copy = work_dir / "no-metadata.sqlite3"
        shutil.copyfile(catalog, copy)
        with sqlite3.connect(copy) as database:
            database.execute("DROP TABLE metadata")
        _write_archive(copy, stripped)
        copy.unlink()
    return {
        "path_name": catalog.name,
        "bytes": catalog.stat().st_size,
        "sha256": canonical.file_sha256(catalog),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": canonical.file_sha256(archive),
    }


def _leftovers(temp_dir: Path) -> tuple[int, int]:
    """Count entries and bytes a variant left in its private temporary area."""
    entries = list(temp_dir.iterdir())
    total = sum(
        item.stat().st_size
        for entry in entries
        for item in ([entry] if entry.is_file() else entry.rglob("*"))
        if item.is_file()
    )
    return len(entries), total


def _run_case(variant: str, path: Path, temp_dir: Path) -> dict[str, object]:
    """Open one input with one variant and record what it did."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temp_dir)
    identity: str | None = None
    version: str | None = None
    outcome = "opened"
    sanitized = True
    message = ""
    start = time.perf_counter()
    try:
        if variant == "full":
            with open_frozen_catalog(path) as frozen:
                identity = frozen.catalog_hash
                version = frozen.tshark_version
        else:
            identity, version = _simplified_open(path)
    except CatalogError as error:
        outcome, message = error.code, str(error)
    except Exception as error:  # pylint: disable=broad-except
        outcome = type(error).__name__
        sanitized = False
        message = str(error)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    entries, leftover_bytes = _leftovers(temp_dir)
    return {
        "variant": variant,
        "outcome": outcome,
        "sanitized_code": sanitized,
        "catalog_hash": identity,
        "tshark_version": version,
        "message_has_absolute_path": bool(_ABSOLUTE_PATH.search(message)),
        "leftover_entries": entries,
        "leftover_bytes": leftover_bytes,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "wall_ms": round(elapsed_ms, 3),
    }


def _child(variant: str, case: str, work_dir: Path) -> dict[str, object]:
    """Run one variant and case in a fresh process and read its one record."""
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--variant",
            variant,
            "--case",
            case,
            "--work-dir",
            str(work_dir),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"child {variant}/{case} failed: {completed.stderr[-2000:]}"
        )
    record = json.loads(completed.stdout)
    if not isinstance(record, dict):
        raise SystemExit(f"child {variant}/{case} returned no record")
    return {"case": case, **record}


def _nonblank_source_lines(source: str) -> int:
    """Count source lines that are neither blank nor a whole-line comment."""
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in source.splitlines()
    )


def _compared_lines() -> dict[str, int]:
    """Measure the compared abstraction on both sides."""
    full = "".join(
        inspect.getsource(getattr(catalog_runtime, name))
        for name in _FULL_SYMBOLS
    ) + inspect.getsource(canonical.file_sha256)
    return {
        "full": _nonblank_source_lines(full),
        "simplified": _nonblank_source_lines(
            inspect.getsource(_simplified_open)
        ),
    }


def main() -> None:
    """Prepare the inputs, measure both variants, and write the receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=catalog_runtime.DEFAULT_CATALOG_PATH
    )
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--code-revision", default="unknown")
    parser.add_argument("--variant", choices=_VARIANTS)
    parser.add_argument("--case", choices=_CASES)
    arguments = parser.parse_args()
    work_dir: Path = arguments.work_dir
    if arguments.variant is not None and arguments.case is not None:
        record = _run_case(
            arguments.variant,
            _case_path(work_dir, arguments.case),
            work_dir / "temp" / f"{arguments.variant}-{arguments.case}",
        )
        print(json.dumps(record))
        return
    if arguments.output is None:
        parser.error("--output is required for the parent run")
    catalog: Path = arguments.catalog
    receipt = {
        "code_revision": arguments.code_revision,
        "catalog": _prepare(catalog, work_dir),
        "compared_nonblank_source_lines": _compared_lines(),
        "rows": [
            _child(variant, case, work_dir)
            for case in _CASES
            for variant in _VARIANTS
        ],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Receipt: {arguments.output}")


if __name__ == "__main__":
    main()
