"""Build the SFT prompt-completion set from training set v1.

Each row of ``data/train/v1/train.jsonl`` becomes one C4 request built the
way ``scripts/model_run.py prepare`` builds a scored one: lexical field
retrieval over the frozen catalog at top-k 16, the two user assumptions
every dev and test item carries, and :func:`prepare_batch` under the
typed-IR contract, with split ``train``. The completion is the row's
target envelope as compact JSON in the key order the system prompt lists,
so the model writes the status before the IR, with ``value`` left out
under ``exists`` as the prompt asks. Every completion must parse back with
the scorer's own parser to the row's target, and a ready one must compile
against the pinned catalog to the row's filter.

The prompt says to use only the retrieved field names, but a ready target
keeps its gold IR whatever retrieval served, so where a gold field is not
in the list the completion trains the model past that rule. The manifest
counts those rows, because they change what an SFT C4 gain means.

The rows are about 9 MB of text, mostly the repeated system prompt and
field lists, so ``sft.jsonl.gz`` is committed (gzip, no timestamp) beside
``sft-manifest.json``, which records the digest of the uncompressed lines;
the trainer refuses a set whose lines do not match it. ``--check``
rebuilds both and compares them. Runs where the frozen catalog and tshark
are, which is the test image. Exit 0 on success, 1 on a mismatch, 2 on an
execution failure.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
import gzip
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import cast

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import file_sha256
from dfilterforge.catalog_runtime import bind_catalog
from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.compiler import compile_intent
from dfilterforge.errors import DFilterForgeError
from dfilterforge.field_retrieval import FieldRetrievalItemV1
from dfilterforge.field_retrieval import retrieve_fields
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import parse_typed_ir_response
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import prompt_versions
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.runner import TsharkRunner

TRAIN_DIR = Path(__file__).resolve().parents[1] / "data" / "train" / "v1"
# model_run.py's default retrieval depth and the assumptions model_split.py
# gives every dev and test item. Both are private there; a test prepares
# the dev split with model_run.py and requires the same prompts from here.
TOP_K = 16
ASSUMPTIONS = (
    "Interpret the request at packet scope over complete Ethernet/IPv4 "
    "packets.",
    "Treat source and destination constraints as directional.",
)
DATA = "sft.jsonl.gz"
MANIFEST = "sft-manifest.json"
# The line digest the manifest records is of the uncompressed lines, so a
# zlib that compresses differently cannot fail a check.
LINES = "sft.jsonl"
# retrieve_fields serves at most this many items per batch.
_CHUNK = 128


class SftDataError(DFilterForgeError):
    """A training row whose completion is not its target."""


def c4_prompts(
    items: Sequence[tuple[str, str]], split: str
) -> tuple[PreparedPromptV1, ...]:
    """Prepares C4 prompts for (item id, request) pairs as scoring does.

    Args:
        items: Item ids and requests, in the order to keep.
        split: Split metadata recorded on each prompt, never sent.

    Returns:
        One first-turn C4 prompt per item, in item order.

    Raises:
        SftDataError: If a retrieval result is not its item's.
    """
    prompts: list[PreparedPromptV1] = []
    for start in range(0, len(items), _CHUNK):
        chunk = items[start : start + _CHUNK]
        results = retrieve_fields(
            DEFAULT_CATALOG_PATH,
            [FieldRetrievalItemV1(item_id=i, intent=text) for i, text in chunk],
            top_k=TOP_K,
        )
        inputs: list[GenerationInputV1] = []
        for (item_id, text), result in zip(chunk, results, strict=True):
            if result.item_id != item_id:
                raise SftDataError("retrieval_misaligned", "Result order broke")
            inputs.append(
                GenerationInputV1(
                    item_id=item_id,
                    intent=text,
                    user_assumptions=ASSUMPTIONS,
                    retrieved_fields=result.fields,
                    split=split,
                )
            )
        batch = prepare_batch(
            inputs,
            output_contract=OutputContractV1.TYPED_IR,
            retrieval=RetrievalV1.LEXICAL,
        )
        prompts.extend(batch.prompts)
    return tuple(prompts)


def _without_exists_value(node: object) -> object:
    """Drops the null ``value`` of every ``exists`` predicate."""
    if isinstance(node, dict):
        mapping = cast(dict[str, object], node)
        return {
            key: _without_exists_value(value)
            for key, value in mapping.items()
            if not (key == "value" and mapping.get("operator") == "exists")
        }
    if isinstance(node, list):
        items = cast(list[object], node)
        return [_without_exists_value(item) for item in items]
    return node


def completion_text(target: GenerationResultV1) -> str:
    """Writes an envelope as compact JSON in the prompt's key order."""
    return json.dumps(
        _without_exists_value(target.model_dump(mode="json")),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_lines(
    rows: Sequence[dict[str, object]], runner: TsharkRunner
) -> tuple[list[str], str | None, int]:
    """Returns one SFT line per training row, the catalog hash and a count.

    Args:
        rows: Rows of ``train.jsonl``, in file order.
        runner: The pinned tshark the catalog binding checks.

    Returns:
        The canonical JSON lines, the bound catalog's hash, and the number
        of ready rows whose target uses a field the prompt's retrieved
        list leaves out.

    Raises:
        SftDataError: If a completion does not parse to its target or a
            ready target does not compile to its row's filter.
    """
    targets = [GenerationResultV1.model_validate(row["target"]) for row in rows]
    catalog = bind_catalog(
        runner, tuple(t.intent_ir for t in targets if t.intent_ir is not None)
    )
    requests = [(str(row["id"]), str(row["request"])) for row in rows]
    prompts = c4_prompts(requests, "train")
    lines: list[str] = []
    unretrieved = 0
    for row, prompt, target in zip(rows, prompts, targets, strict=True):
        completion = completion_text(target)
        if parse_typed_ir_response(completion) != target:
            raise SftDataError("completion_mismatch", f"{row['id']} differs")
        if target.intent_ir is not None:
            if compile_intent(target.intent_ir, catalog) != row["filter"]:
                raise SftDataError("filter_mismatch", f"{row['id']} differs")
            used = {
                predicate.field
                for _, predicate in walk_predicates(target.intent_ir.expression)
            }
            shown = {field.abbreviation for field in prompt.retrieved_fields}
            if not used <= shown:
                unretrieved += 1
        messages = [
            {"role": message.role, "content": message.content}
            for message in prompt.messages
        ]
        lines.append(
            canonical_json(
                {
                    "id": row["id"],
                    "status": target.status.value,
                    "messages": messages,
                    "completion": completion,
                }
            )
        )
    return lines, catalog.source_catalog_hash, unretrieved


def build(source: Path, directory: Path, runner: TsharkRunner) -> None:
    """Writes ``sft.jsonl.gz`` and its manifest from ``source``'s rows."""
    train = source / "train.jsonl"
    rows = [
        cast(dict[str, object], json.loads(line))
        for line in train.read_text("utf-8").splitlines()
    ]
    lines, catalog_hash, unretrieved = build_lines(rows, runner)
    text = "".join(line + "\n" for line in lines).encode("utf-8")
    first = cast(dict[str, list[dict[str, str]]], json.loads(lines[0]))
    statuses = Counter(cast(str, json.loads(line)["status"]) for line in lines)
    manifest = {
        "schema_version": "sft-set/1.0",
        "source": {train.name: file_sha256(train)},
        "condition": "C4",
        "prompt_version": prompt_versions(OutputContractV1.TYPED_IR),
        "system_prompt_sha256": hashlib.sha256(
            first["messages"][0]["content"].encode("utf-8")
        ).hexdigest(),
        "top_k": TOP_K,
        "catalog": catalog_hash,
        "rows": len(lines),
        "status": dict(sorted(statuses.items())),
        "ready_with_unretrieved_field": unretrieved,
        "completion": "prompt key order, compact JSON, no value under exists",
        "files": {LINES: hashlib.sha256(text).hexdigest()},
    }
    directory.mkdir(parents=True, exist_ok=True)
    packed = gzip.compress(text, compresslevel=9, mtime=0)
    (directory / DATA).write_bytes(packed)
    (directory / MANIFEST).write_text(
        canonical_json(manifest) + "\n", encoding="utf-8", newline="\n"
    )


def check(directory: Path, runner: TsharkRunner) -> bool:
    """Rebuilds the committed set and compares lines and manifest."""
    with TemporaryDirectory(prefix="dfilterforge-sft-check-") as staging:
        rebuilt = Path(staging)
        build(directory, rebuilt, runner)
        return gzip.decompress((rebuilt / DATA).read_bytes()) == (
            gzip.decompress((directory / DATA).read_bytes())
        ) and (rebuilt / MANIFEST).read_bytes() == (
            (directory / MANIFEST).read_bytes()
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Builds or checks the SFT set; returns the exit status."""
    parser = argparse.ArgumentParser(description="Build the SFT set.")
    parser.add_argument("--train-dir", type=Path, default=TRAIN_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    directory = cast(Path, args.train_dir)
    try:
        if args.check:
            if check(directory, TsharkRunner()):
                return 0
            print("the SFT set differs from its rebuild", file=sys.stderr)
            return 1
        build(directory, directory, TsharkRunner())
    except DFilterForgeError as error:
        print(f"{error.code}: {error}", file=sys.stderr)
        return 2
    manifest = json.loads((directory / MANIFEST).read_text("utf-8"))
    print(f"{LINES} sha256 {manifest['files'][LINES]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
