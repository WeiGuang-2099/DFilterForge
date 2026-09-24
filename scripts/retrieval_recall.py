"""Measure how often every gold field reaches the retrieved prompt context.

The script is evaluator-side: it reads gold only to learn which fields each
item needs, it never writes a prompt, and it never emits per-item detail for
a split that is not frozen, so the test split is reported as counts alone.
"""

# The error envelope and the revision check repeat scripts/model_run.py on
# purpose: each script is a standalone file loaded by path, and neither may
# import the other.
# pylint: disable=duplicate-code

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
import tracemalloc
from typing import cast

from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.catalog_runtime import open_frozen_catalog
from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import FieldRetrievalResultV1
from dfilterforge.field_retrieval import retrieve_fields
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.model_split import generate_model_split

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+:-]{0,127}")
# Every file that decides which fields are gold or which reach a prompt.
_SOURCE_FILES: tuple[str, ...] = (
    "scripts/retrieval_recall.py",
    "src/dfilterforge/field_retrieval.py",
    "src/dfilterforge/generation.py",
    "src/dfilterforge/intent_ir.py",
    "src/dfilterforge/model_cases.py",
    "src/dfilterforge/model_dev_cases.py",
    "src/dfilterforge/model_split.py",
    "src/dfilterforge/model_test_cases.py",
)
_DEFAULT_TOP_KS: tuple[int, ...] = (8, 16, 32)
_DETAIL_SPLITS: tuple[str, ...] = ("dev",)
_SCHEMA_VERSION = "retrieval-recall/1.0"
_SPLITS: tuple[str, ...] = ("dev", "test")
_MAX_TOP_K = 32
_FAILURE = 2
_OUTPUT_EXISTS = "The receipt file already exists"
_TIMING_NOTE = (
    "seconds is measured without tracemalloc; the peak comes from a second "
    "identical call"
)


class RecallError(DFilterForgeError, RuntimeError):
    """A recall-measurement failure carrying only a stable code and text."""


@dataclass(frozen=True)
class _GoldItem:
    """One model item and the sorted field names its gold expression uses."""

    item_id: str
    split: str
    case_id: str
    intent: str
    gold: tuple[str, ...]


def _gold_items() -> tuple[_GoldItem, ...]:
    """Regenerates the split and pairs every item with its gold fields."""
    with TemporaryDirectory(prefix="dfilterforge-recall-split-") as staging:
        artifacts = generate_model_split(Path(staging))
    cases = {case.case_id: case for case in artifacts.gold.cases}
    # Non-ready gold names no field, so it has no recall to measure.
    non_ready = {case.case_id for case in artifacts.gold.non_ready}
    items: list[_GoldItem] = []
    for item in artifacts.inputs:
        case_id = artifacts.gold.item_to_case.get(item.item_id, "")
        if case_id in non_ready:
            continue
        case = cases.get(case_id)
        if case is None:
            raise RecallError(
                "gold_routing_invalid", "A model item has no gold case"
            )
        predicates = walk_predicates(case.spec.canonical_ir.expression)
        gold = tuple(sorted({predicate.field for _, predicate in predicates}))
        items.append(
            _GoldItem(item.item_id, item.split, case.case_id, item.intent, gold)
        )
    return tuple(items)


def _context_bytes(result: FieldRetrievalResultV1) -> int:
    """Returns the canonical UTF-8 size of one retrieved context."""
    return len(canonical_json(result.fields).encode("utf-8"))


def _per_k(
    items: Sequence[_GoldItem],
    results: Sequence[FieldRetrievalResultV1],
    k: int,
) -> dict[str, object]:
    """Summarizes the retrieval pass taken at depth ``k``, not a deeper one."""
    if len(results) != len(items) or any(
        result.item_id != item.item_id or len(result.fields) > k
        for item, result in zip(items, results)
    ):
        raise RecallError(
            "retrieval_invalid", "Retrieval results do not match the request"
        )
    all_in = found_total = dotted_found = dotted_total = empty = 0
    recalls: list[float] = []
    for item, result in zip(items, results, strict=True):
        names = {field.abbreviation for field in result.fields}
        found = [name for name in item.gold if name in names]
        all_in += len(found) == len(item.gold)
        found_total += len(found)
        # Dotless gold names (tcp, udp, dns, ip) are protocol pseudo-fields.
        dotted_found += sum("." in name for name in found)
        dotted_total += sum("." in name for name in item.gold)
        empty += not result.fields
        recalls.append(len(found) / len(item.gold))
    return {
        "items": len(items),
        "all_in": all_in,
        "macro_recall": round(sum(recalls) / max(len(recalls), 1), 3),
        "micro_found": found_total,
        "micro_total": sum(len(item.gold) for item in items),
        "nonprotocol_found": dotted_found,
        "nonprotocol_total": dotted_total,
        "max_context_bytes": max(map(_context_bytes, results), default=0),
        "empty_contexts": empty,
    }


def _per_item(
    items: Sequence[_GoldItem], results: Sequence[FieldRetrievalResultV1]
) -> dict[str, object]:
    """Maps every gold field to its rank in one pass, or None when absent."""
    detail: dict[str, object] = {}
    for item, result in zip(items, results, strict=True):
        ranks = {field.abbreviation: field.rank for field in result.fields}
        detail[item.item_id] = {
            "case_id": item.case_id,
            "context_bytes": _context_bytes(result),
            "gold": {name: ranks.get(name) for name in item.gold},
        }
    return detail


def _peak_bytes(
    path: Path, queries: Sequence[FieldRetrievalItemV1], k: int
) -> int:
    """Repeats one retrieval pass under tracemalloc and returns its peak."""
    tracemalloc.start()
    try:
        retrieve_fields(path, queries, top_k=k)
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def _measure_split(
    path: Path,
    items: Sequence[_GoldItem],
    depths: Sequence[int],
    detailed: bool,
) -> tuple[dict[str, object], dict[str, object]]:
    """Runs one timed pass and one traced pass per depth over one split.

    Returns:
        The split's receipt block and its timing block. Per-item ranks,
        present only when ``detailed``, come from the deepest pass.
    """
    queries = tuple(
        FieldRetrievalItemV1(item_id=item.item_id, intent=item.intent)
        for item in items
    )
    per_k: dict[str, object] = {}
    timing: dict[str, object] = {}
    results: tuple[FieldRetrievalResultV1, ...] = ()
    for k in depths:
        started = perf_counter()
        results = retrieve_fields(path, queries, top_k=k)
        seconds = round(perf_counter() - started, 3)
        per_k[str(k)] = _per_k(items, results, k)
        timing[str(k)] = {
            "seconds": seconds,
            "tracemalloc_peak_bytes": _peak_bytes(path, queries, k),
        }
    block: dict[str, object] = {"items": len(items), "per_k": per_k}
    if detailed:
        block["per_item"] = _per_item(items, results)
    return block, timing


def measure(
    catalog: Path,
    splits: Sequence[str],
    top_ks: Sequence[int] = _DEFAULT_TOP_KS,
    *,
    source_revision: str = "unrecorded",
    detail_splits: Sequence[str] = _DETAIL_SPLITS,
) -> dict[str, object]:
    """Measures gold-field recall of one retrieval pass per split and depth.

    Args:
        catalog: A frozen ``.sqlite3`` inventory or a ``.gz`` archive of one.
        splits: ``dev``, ``test`` or both, in that order.
        top_ks: Retrieval depths between 1 and 32; each gets its own pass.
        source_revision: Human-readable revision recorded in the receipt.
        detail_splits: Measured splits that also get per-item gold ranks.

    Returns:
        The complete receipt. A split outside ``detail_splits`` carries
        aggregate counts only: no item id, field name or rank.

    Raises:
        RecallError: If an argument is out of range or retrieval misbehaves.
        CatalogError: If the catalog cannot be opened.
    """
    if not splits or list(splits) != [s for s in _SPLITS if s in splits]:
        raise RecallError(
            "split_invalid", "Splits must be dev, test or both, in that order"
        )
    if not top_ks or any(not 1 <= k <= _MAX_TOP_K for k in top_ks):
        raise RecallError("top_k_invalid", "Every top-k must be from 1 to 32")
    if not set(detail_splits) <= set(splits):
        raise RecallError(
            "detail_split_invalid", "Detail splits must be measured splits"
        )
    depths = sorted(set(top_ks))
    sources = {
        name: file_sha256(_PROJECT_ROOT / name) for name in _SOURCE_FILES
    }
    items = _gold_items()
    blocks: dict[str, object] = {}
    timing: dict[str, object] = {}
    with open_frozen_catalog(catalog) as frozen:
        for split in splits:
            chosen = sorted(
                (item for item in items if item.split == split),
                key=lambda item: item.item_id,
            )
            blocks[split], timing[split] = _measure_split(
                frozen.sqlite_path, chosen, depths, split in detail_splits
            )
        identity = {
            "file_name": frozen.file_name,
            "file_sha256": frozen.file_sha256,
            "sqlite_sha256": frozen.sqlite_sha256,
            "catalog_hash": frozen.catalog_hash,
            "tshark_version": frozen.tshark_version,
        }
    return {
        "schema_version": _SCHEMA_VERSION,
        "source_revision": source_revision,
        "source_files": sources,
        "detail_splits": list(detail_splits),
        "catalog": identity,
        "top_ks": depths,
        "splits": blocks,
        "timing": timing,
        "timing_note": _TIMING_NOTE,
    }


def _print_error(code: str, message: str) -> None:
    """Writes the machine-readable error envelope to stderr."""
    envelope = {"error": {"code": code, "message": message}}
    print(canonical_json(envelope), file=sys.stderr)


def _source_revision(value: str) -> str:
    """Validates the human-readable revision supplied by the caller."""
    if _SOURCE_REVISION.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "source revision must be 1-128 safe, non-whitespace characters"
        )
    return value


def _run(arguments: argparse.Namespace) -> int:
    """Measures, writes the receipt once and prints the per-k counts."""
    output = cast(Path, arguments.output)
    # Refuse before the minutes-long measurement; the exclusive open below
    # still guards against a receipt that appears while it runs.
    if output.exists():
        raise RecallError("output_exists", _OUTPUT_EXISTS)
    splits = _SPLITS if arguments.include_test else ("dev",)
    receipt = measure(
        cast(Path, arguments.catalog),
        splits,
        _DEFAULT_TOP_KS,
        source_revision=cast(str, arguments.source_revision),
        detail_splits=_DETAIL_SPLITS,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(receipt) + "\n")
    except FileExistsError:
        raise RecallError("output_exists", _OUTPUT_EXISTS) from None
    blocks = cast(dict[str, dict[str, object]], receipt["splits"])
    print(canonical_json({split: blocks[split]["per_k"] for split in splits}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Runs one measurement and returns a process exit code.

    Args:
        argv: Command-line arguments; ``None`` reads ``sys.argv``.

    Returns:
        0 when the receipt is written, 2 on a reported failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--source-revision", type=_source_revision, required=True
    )
    parser.add_argument(
        "--include-test",
        action="store_true",
        help="add aggregate test-split counts; per-item detail stays dev-only",
    )
    arguments = parser.parse_args(argv)
    try:
        return _run(arguments)
    except DFilterForgeError as error:
        _print_error(error.code, str(error))
        return _FAILURE
    except ValidationError:
        _print_error(
            "schema_invalid", "Input does not match the required schema"
        )
        return _FAILURE
    except OSError:
        _print_error("io_error", "File operation failed")
        return _FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
