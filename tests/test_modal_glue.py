"""The Modal glue serves and trains the stack the self-served note names.

modal/serve_vllm.py and modal/train_sft.py import modal, which no test
image installs, so each is loaded over a stub module: only their plain
functions and constants run, and nothing is built, deployed or sent.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import cast, Protocol
from unittest.mock import MagicMock

import pytest

from dfilterforge import held_out
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.model_client import OpenAiCompatibleBackend

_ROOT = Path(__file__).resolve().parents[1]
_NOTE = _ROOT / "docs" / "decisions" / "self-served-runs.md"
_TRAINER = _ROOT / "training" / "train_sft.py"
_RUN_ID = re.compile(r"`((?:dev|test)-qwen3-1\.7b[a-z0-9.-]*)`")


class _Serve(Protocol):
    """Typed view of modal/serve_vllm.py."""

    MODEL_ID: str
    MODEL_REVISION: str
    VLLM_VERSION: str
    GPU: str
    SEEDS: tuple[int, ...]
    LORA_RANK: int
    APP_NAME: str
    THINKING_OFF: str
    HF_CACHE_VOLUME: str
    ADAPTER_VOLUME: str
    CACHE_ROOT: Path
    ADAPTER_ROOT: Path

    def adapter_name(self, seed: int) -> str:
        ...

    def adapter_dir(self, seed: int) -> str:
        ...

    def vllm_command(self, adapter_root: Path) -> list[str]:
        ...


class _Train(Protocol):
    """Typed view of modal/train_sft.py."""

    GPU: str
    SEEDS: tuple[int, ...]
    HF_CACHE_VOLUME: str
    ADAPTER_VOLUME: str
    CACHE_ROOT: str
    REMOTE_ROOT: str
    FILES: tuple[str, ...]

    def output_dir(self, seed: int) -> str:
        ...

    def train_command(self, seed: int) -> list[str]:
        ...


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{path.name} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "modal", MagicMock())
        spec.loader.exec_module(module)
    return module


serve = cast(_Serve, _load(_ROOT / "modal" / "serve_vllm.py", "modal_serve"))
trainer = cast(_Train, _load(_ROOT / "modal" / "train_sft.py", "modal_train"))
# A name of its own, so test_model_run's module and its patches stay apart.
model_run = _load(_ROOT / "scripts" / "model_run.py", "modal_glue_model_run")


def _training_value(name: str) -> ast.expr:
    """Returns the expression training/train_sft.py assigns to a name.

    The script imports torch, which the test image lacks, so it is parsed.
    """
    for node in ast.parse(_TRAINER.read_text("utf-8")).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return value
    raise AssertionError(f"train_sft.py assigns no {name}")


def _recipe_lora_rank() -> object:
    recipe = _training_value("RECIPE")
    assert isinstance(recipe, ast.Dict)
    for key, value in zip(recipe.keys, recipe.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == "lora_r":
            return ast.literal_eval(value)
    raise AssertionError("the recipe sets no lora_r")


def _flags(command: list[str]) -> dict[str, list[str]]:
    """Maps each flag after ``vllm serve MODEL`` to the values it takes."""
    flags: dict[str, list[str]] = {}
    current: list[str] = []
    for token in command[3:]:
        if token.startswith("--"):
            assert token not in flags, f"{token} is given twice"
            current = flags.setdefault(token, [])
        else:
            current.append(token)
    return flags


def test_the_call_template_sends_the_hosted_settings_to_the_server() -> None:
    """The template is a call config the client accepts for the server.

    It sends the hosted runs' settings with no OpenRouter options and the
    served hub id; an adapter run swaps in that adapter's name. Its prices
    are nominal and say so, because the real cost is GPU time.
    """
    data = (_ROOT / "modal" / "call-config.json").read_bytes()
    config = model_run.CallConfigV1.model_validate_json(data)
    settings = cast(RequestSettingsV1, config.settings)

    OpenAiCompatibleBackend(config.endpoint_url, settings, api_key="unused")

    assert settings == RequestSettingsV1(model_id=serve.MODEL_ID)
    assert (settings.temperature, settings.seed) == (0.0, 17)
    assert (settings.max_output_tokens, settings.json_mode) == (2048, True)
    assert settings.openrouter is None
    host = cast(str, config.endpoint_url).split("/")[2]
    assert host.endswith(f"--{serve.APP_NAME}-server.us-east.modal.direct")
    assert cast(str, config.prices.source).startswith("nominal, not charged")


def test_the_server_serves_the_trained_revision_with_thinking_off(
    tmp_path: Path,
) -> None:
    """vLLM gets the training pins, thinking off and every finished seed.

    A seed's adapter is served once its run manifest, which the trainer
    writes last, is on the volume; all of them follow one flag.
    """
    model = ast.literal_eval(_training_value("MODEL"))
    finished = (17, 2026)
    for seed in serve.SEEDS:
        run = tmp_path / serve.adapter_dir(seed)
        (run / "adapter").mkdir(parents=True)
        if seed in finished:
            (run / "run_manifest.json").write_text("{}\n", encoding="utf-8")

    command = serve.vllm_command(tmp_path)
    flags = _flags(command)

    assert (serve.MODEL_ID, serve.MODEL_REVISION) == model
    assert serve.SEEDS == ast.literal_eval(_training_value("SEEDS"))
    assert serve.LORA_RANK == _recipe_lora_rank()
    assert command[:3] == ["vllm", "serve", serve.MODEL_ID]
    assert flags["--served-model-name"] == [serve.MODEL_ID]
    assert flags["--revision"] == [serve.MODEL_REVISION]
    assert flags["--tokenizer-revision"] == [serve.MODEL_REVISION]
    assert flags["--dtype"] == ["bfloat16"]
    (kwargs,) = flags["--default-chat-template-kwargs"]
    assert json.loads(kwargs) == {"enable_thinking": False}
    assert flags["--enable-lora"] == []
    assert flags["--max-lora-rank"] == [str(serve.LORA_RANK)]
    assert flags["--lora-modules"] == [
        f"{serve.adapter_name(seed)}="
        f"{tmp_path / serve.adapter_dir(seed) / 'adapter'}"
        for seed in finished
    ]
    assert "--lora-modules" not in serve.vllm_command(tmp_path / "empty")


def test_training_writes_where_the_server_reads_on_the_same_gpu() -> None:
    """One seed's run lands in the directory the server serves it from.

    The trainer keeps the repository paths of its script and data, since
    train_sft.py reads the data from its parent's parent.
    """
    assert (trainer.GPU, trainer.SEEDS) == (serve.GPU, serve.SEEDS)
    assert (trainer.HF_CACHE_VOLUME, trainer.ADAPTER_VOLUME) == (
        serve.HF_CACHE_VOLUME,
        serve.ADAPTER_VOLUME,
    )
    assert Path(trainer.CACHE_ROOT) == serve.CACHE_ROOT
    assert set(trainer.FILES) == {
        "training/train_sft.py",
        "data/train/v1/sft.jsonl.gz",
        "data/train/v1/sft-manifest.json",
    }
    assert all((_ROOT / name).is_file() for name in trainer.FILES)
    for seed in serve.SEEDS:
        output = trainer.output_dir(seed)
        assert Path(output) == serve.ADAPTER_ROOT / serve.adapter_dir(seed)
        assert trainer.train_command(seed)[1:] == [
            f"{trainer.REMOTE_ROOT}/training/train_sft.py",
            *("--seed", str(seed), "--output-dir", output),
        ]


def test_the_note_names_the_served_stack_and_usable_run_ids() -> None:
    """The self-served note records what the server runs, verbatim.

    Each run id it names is one the call step accepts, each prompt set it
    names is seeded under docs/results, and the freeze record admits the
    test one.
    """
    if not _NOTE.is_file():
        pytest.skip("the test image carries no docs/ tree")
    text = _NOTE.read_text("utf-8")
    run_ids = set(_RUN_ID.findall(text))
    result_dir = cast(re.Pattern[str], getattr(model_run, "_RESULT_DIR"))

    for value in (
        serve.MODEL_ID,
        serve.MODEL_REVISION,
        f"vLLM {serve.VLLM_VERSION}",
        f"one {serve.GPU}",
        serve.THINKING_OFF,
        *(serve.adapter_name(seed) for seed in serve.SEEDS),
    ):
        assert value in text, value
    assert len(run_ids) >= 8
    assert all(result_dir.fullmatch(run_id) for run_id in run_ids)
    for split in ("dev", "test"):
        prepare = _ROOT / "docs" / "results" / f"{split}-qwen3-1.7b-2026-10-07"
        assert prepare.name in run_ids
        held_out.admit_prepare(split, (prepare / "prepare.json").read_bytes())
