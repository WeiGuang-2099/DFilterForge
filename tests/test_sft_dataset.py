"""The SFT set holds the prompts scoring sends and rebuilds byte for byte.

This is the message half of the train/serve parity: each training row's
messages are what ``scripts/model_run.py prepare`` sends for a C4 request.
The chat-template half, the tokens those messages become with thinking
off, is training/tests/test_parity.py in the training image.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import pytest

from dfilterforge.catalog_runtime import DEFAULT_CATALOG_PATH
from dfilterforge.generation import parse_typed_ir_response
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.intent_ir import GenerationResultV1

_ROOT = Path(__file__).resolve().parents[1]
_DATA = _ROOT / "data" / "train" / "v1"
_INPUT_PREFIX = "INPUT_JSON\n"
_IMAGE = pytest.mark.skipif(
    not DEFAULT_CATALOG_PATH.is_file(),
    reason="needs the frozen catalog and tshark of the test image",
)


def _load(script: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "scripts" / f"{script}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{script} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sft_dataset = _load("sft_dataset", "sft_dataset")
# A name of its own, so test_model_run's module and its patches stay apart.
model_run = _load("model_run", "sft_parity_model_run")


def _jsonl(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines()]


def test_every_completion_is_its_rows_target_to_the_scorer() -> None:
    lines = gzip.decompress((_DATA / sft_dataset.DATA).read_bytes())
    manifest = json.loads((_DATA / sft_dataset.MANIFEST).read_text("utf-8"))
    assert hashlib.sha256(lines).hexdigest() == (
        manifest["files"][sft_dataset.LINES]
    )
    rows = _jsonl(lines.decode("utf-8"))
    train = _jsonl((_DATA / "train.jsonl").read_text("utf-8"))
    assert [row["id"] for row in rows] == [row["id"] for row in train]
    assert manifest["rows"] == len(rows) == 1299
    for row, source in zip(rows, train, strict=True):
        target = GenerationResultV1.model_validate(source["target"])
        assert parse_typed_ir_response(row["completion"]) == target
        assert row["status"] == target.status.value
        assert list(json.loads(row["completion"]))[:2] == [
            "schema_version",
            "status",
        ]


@_IMAGE
def test_train_prompts_are_the_prompts_scoring_prepares(
    tmp_path: Path,
) -> None:
    prepared = tmp_path / "dev-parity"
    argv = ["prepare", "--output-dir", str(prepared)]
    assert model_run.main([*argv, "--source-revision", "parity"]) == 0
    scored = PreparedBatchV1.model_validate_json(
        (prepared / "prepared" / "C4.json").read_text("utf-8")
    ).prompts
    items = [
        (
            prompt.item_id,
            json.loads(prompt.messages[1].content[len(_INPUT_PREFIX) :])[
                "intent"
            ],
        )
        for prompt in scored
    ]
    assert sft_dataset.c4_prompts(items, "dev") == scored
    first = _jsonl(
        gzip.decompress((_DATA / sft_dataset.DATA).read_bytes()).decode()
    )[0]
    assert first["messages"][0]["content"] == scored[0].messages[0].content


@_IMAGE
def test_the_committed_set_is_its_rebuild() -> None:
    assert sft_dataset.main(["--check"]) == 0
