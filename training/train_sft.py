"""QLoRA SFT of Qwen/Qwen3-1.7B on the frozen C4 training set.

One run per seed on a CUDA host, in the cu126 environment (README.md):

    python training/train_sft.py --seed 17 --output-dir artifacts/sft/s17

It writes adapter/ (the LoRA weights after the final epoch, the
pre-registered checkpoint), log.jsonl and run_manifest.json (dataset
digest, model and tokenizer revisions, libraries, seed, recipe, steps,
loss). --cpu-smoke runs the same path on CPU: a tiny random Qwen3, no
4-bit, a few rows and steps.

Prompts are the scorer's C4 messages rendered by the Qwen3-1.7B chat
template with thinking off, as a server renders a scored request; the
completion is the target envelope and <|im_end|>. Only completion tokens
carry labels, and the run stops if TRL prepared any row differently.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time
from typing import Any

from datasets import Dataset
from peft import LoraConfig
import torch
from transformers import AutoModelForCausalLM
from transformers import AutoTokenizer
from transformers import BitsAndBytesConfig
from transformers import PreTrainedModel
from transformers import PreTrainedTokenizerBase
from transformers import set_seed
from trl import SFTConfig
from trl import SFTTrainer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "train" / "v1" / "sft.jsonl.gz"
MANIFEST = ROOT / "data" / "train" / "v1" / "sft-manifest.json"
# Hub ids and the commits they are pinned to.
MODEL = ("Qwen/Qwen3-1.7B", "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e")
SMOKE_MODEL = (
    "trl-internal-testing/tiny-Qwen3ForCausalLM",
    "25bb9b8963688237e94750f6f3e48f1947d3c7a3",
)
SEEDS = (17, 42, 2026)
STOP = "<|im_end|>"
LIBRARIES = (
    "torch transformers trl peft accelerate datasets bitsandbytes".split()
)
# The pre-registered recipe. The smoke overrides only what makes it small.
RECIPE: dict[str, Any] = {
    "quantization": "nf4, double quant, bf16 compute",
    "lora_r": 16,
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "lora_targets": (
        "q_proj k_proj v_proj o_proj gate_proj up_proj down_proj".split()
    ),
    "epochs": 3,
    "max_steps": -1,
    "batch_size": 4,
    "gradient_accumulation": 4,
    "learning_rate": 2e-4,
    "lr_scheduler": "cosine",
    "warmup": 0.03,
    "max_grad_norm": 0.3,
    "optim": "adamw_torch",
    "logging_steps": 5,
    "rows": None,
}
SMOKE: dict[str, Any] = {
    "quantization": None,
    "max_steps": 12,
    "batch_size": 2,
    "gradient_accumulation": 1,
    "learning_rate": 5e-3,
    "logging_steps": 1,
    "rows": 8,
}


def load_rows(
    path: Path = DATA, manifest: Path = MANIFEST
) -> list[dict[str, Any]]:
    """Reads the SFT set, refusing lines whose digest the manifest lacks."""
    lines = gzip.decompress(path.read_bytes())
    expected = json.loads(manifest.read_text("utf-8"))["files"]["sft.jsonl"]
    if hashlib.sha256(lines).hexdigest() != expected:
        raise SystemExit(f"{path.name} does not match {manifest.name}")
    return [json.loads(line) for line in lines.decode("utf-8").splitlines()]


def load_tokenizer() -> PreTrainedTokenizerBase:
    """The Qwen3-1.7B tokenizer and chat template, smoke included."""
    return AutoTokenizer.from_pretrained(MODEL[0], revision=MODEL[1])


def render_prompt(
    tokenizer: PreTrainedTokenizerBase, messages: Sequence[dict[str, str]]
) -> str:
    """The text a server renders for a scored request, thinking off."""
    return tokenizer.apply_chat_template(
        list(messages),
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def encode(
    tokenizer: PreTrainedTokenizerBase, row: dict[str, Any]
) -> dict[str, list[int]]:
    """Prompt ids as served, then completion ids and the stop token."""
    prompt = tokenizer(
        render_prompt(tokenizer, row["messages"]), add_special_tokens=False
    )["input_ids"]
    completion = tokenizer(row["completion"], add_special_tokens=False)[
        "input_ids"
    ] + [tokenizer.convert_tokens_to_ids(STOP)]
    return {
        "input_ids": prompt + completion,
        "completion_mask": [0] * len(prompt) + [1] * len(completion),
    }


def load_model(smoke: bool) -> PreTrainedModel:
    """The tiny fp32 model for the smoke, else Qwen3-1.7B in 4-bit nf4."""
    if smoke:
        return AutoModelForCausalLM.from_pretrained(
            SMOKE_MODEL[0], revision=SMOKE_MODEL[1], dtype=torch.float32
        )
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    return AutoModelForCausalLM.from_pretrained(
        MODEL[0],
        revision=MODEL[1],
        quantization_config=quantization,
        dtype=torch.bfloat16,
        device_map={"": 0},
    )


def sft_config(
    recipe: dict[str, Any], seed: int, output: Path, smoke: bool
) -> SFTConfig:
    """Maps the recipe onto TRL's config; rows are never truncated."""
    return SFTConfig(
        output_dir=str(output),
        seed=seed,
        data_seed=seed,
        num_train_epochs=recipe["epochs"],
        max_steps=recipe["max_steps"],
        per_device_train_batch_size=recipe["batch_size"],
        gradient_accumulation_steps=recipe["gradient_accumulation"],
        learning_rate=recipe["learning_rate"],
        lr_scheduler_type=recipe["lr_scheduler"],
        warmup_steps=recipe["warmup"],
        max_grad_norm=recipe["max_grad_norm"],
        weight_decay=0.0,
        optim=recipe["optim"],
        logging_steps=recipe["logging_steps"],
        logging_first_step=True,
        save_strategy="no",
        report_to="none",
        disable_tqdm=True,
        bf16=not smoke,
        use_cpu=smoke,
        gradient_checkpointing=not smoke,
        max_length=None,
        packing=False,
        completion_only_loss=True,
        dataloader_num_workers=0,
    )


def check_prepared(
    trainer: SFTTrainer, encoded: Sequence[dict[str, list[int]]]
) -> None:
    """Stops unless TRL kept every row whole with prompt labels masked."""
    prepared = trainer.train_dataset
    if prepared is None or len(prepared) != len(encoded):
        raise SystemExit("the trainer dropped or added training rows")
    for row, ready in zip(encoded, prepared, strict=True):
        labels = [
            token if keep else -100
            for token, keep in zip(row["input_ids"], row["completion_mask"])
        ]
        if ready["input_ids"] != row["input_ids"] or ready["labels"] != labels:
            raise SystemExit("a prepared row differs from its encoding")


def versions() -> dict[str, str | None]:
    """Installed versions of the libraries that shape a run."""
    found: dict[str, str | None] = {}
    for name in LIBRARIES:
        try:
            found[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found[name] = None
    return found


def train(args: argparse.Namespace) -> dict[str, Any]:
    """Trains one adapter and returns its run manifest."""
    smoke = bool(args.cpu_smoke)
    if not smoke and not torch.cuda.is_available():
        raise SystemExit("the QLoRA run needs CUDA; use --cpu-smoke on CPU")
    recipe = {**RECIPE, **SMOKE} if smoke else dict(RECIPE)
    output: Path = args.output_dir
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"{output} is not empty")
    set_seed(args.seed)
    tokenizer = load_tokenizer()
    rows = load_rows()[: recipe["rows"]]
    encoded = [encode(tokenizer, row) for row in rows]
    trainer = SFTTrainer(
        model=load_model(smoke),
        args=sft_config(recipe, args.seed, output, smoke),
        train_dataset=Dataset.from_list(encoded),
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=recipe["lora_r"],
            lora_alpha=recipe["lora_alpha"],
            lora_dropout=recipe["lora_dropout"],
            target_modules=recipe["lora_targets"],
            task_type="CAUSAL_LM",
        ),
    )
    check_prepared(trainer, encoded)
    started = time.monotonic()
    result = trainer.train()
    runtime = time.monotonic() - started
    trainer.save_model(str(output / "adapter"))
    history = trainer.state.log_history
    with (output / "log.jsonl").open("w", encoding="utf-8") as log:
        log.writelines(json.dumps(entry) + "\n" for entry in history)
    model_id = SMOKE_MODEL if smoke else MODEL
    return {
        "schema_version": "sft-run/1.0",
        "mode": "cpu-smoke" if smoke else "qlora",
        "model": {"id": model_id[0], "revision": model_id[1]},
        "tokenizer": {"id": MODEL[0], "revision": MODEL[1]},
        "dataset": {
            "file": DATA.relative_to(ROOT).as_posix(),
            "lines_sha256": hashlib.sha256(
                gzip.decompress(DATA.read_bytes())
            ).hexdigest(),
            "rows": len(rows),
            "max_tokens": max(len(row["input_ids"]) for row in encoded),
            "completion_tokens": sum(
                sum(row["completion_mask"]) for row in encoded
            ),
        },
        "seed": args.seed,
        "recipe": recipe,
        "checkpoint": "final step; no selection on dev or test",
        "steps": trainer.state.global_step,
        "epochs": trainer.state.epoch,
        "train_loss": result.training_loss,
        "loss_curve": [
            [entry["step"], entry["loss"]]
            for entry in history
            if "loss" in entry
        ],
        "runtime_seconds": round(runtime, 1),
        "device": "cpu" if smoke else torch.cuda.get_device_name(0),
        "libraries": versions(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Parses the command line, trains, and writes the run manifest."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, choices=SEEDS, default=SEEDS[0])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cpu-smoke", action="store_true")
    args = parser.parse_args(argv)
    manifest = train(args)
    (args.output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: manifest[k] for k in ("steps", "train_loss")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
