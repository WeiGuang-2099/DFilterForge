"""Train one SFT adapter on Modal with training/train_sft.py, unchanged.

From the repository root, one command per seed (17, 42, 2026):

    modal run --detach modal/train_sft.py --seed 17

It runs the pre-registered QLoRA recipe on the GPU type modal/serve_vllm.py
serves on, in the training lock's cu126 environment, and writes adapter/,
log.jsonl and run_manifest.json to sft-v1-s<seed>/ on the adapters
volume, where the server finds it at its next start. The model weights are
cached on the volume the server reads them from. Copy a run into the
ignored artifacts/ tree with the two lines below; `modal volume get` needs
the local directory to exist, or it writes every file to the same path.

    New-Item -ItemType Directory -Force artifacts/sft | Out-Null
    modal volume get dfilterforge-adapters sft-v1-s17 artifacts/sft

train_sft.py refuses a non-empty output directory, so a seed is trained
again only after `modal volume rm -r dfilterforge-adapters sft-v1-s<seed>`.

Sources, read 2026-10-07: Image.uv_sync and add_local_file
(modal.com/docs/reference/modal.Image); `modal volume get`
(modal.com/docs/reference/cli/volume); the GPU driver, 580.95.05 with CUDA
13.0, which runs the lock's cu126 wheels (modal.com/docs/guide/cuda).
"""

from __future__ import annotations

import subprocess
import sys

import modal

# modal/serve_vllm.py's GPU, volumes and adapter layout.
GPU = "L4"
SEEDS = (17, 42, 2026)
HF_CACHE_VOLUME = "dfilterforge-hf-cache"
ADAPTER_VOLUME = "dfilterforge-adapters"
CACHE_ROOT = "/cache"
ADAPTER_ROOT = "/adapters"
# training/Dockerfile's uv, which wrote training/uv.lock.
UV_VERSION = "0.9.28"
TIMEOUT_SECONDS = 3 * 60 * 60
# train_sft.py reads its data from its parent's parent, so the files keep
# their repository paths under REMOTE_ROOT.
REMOTE_ROOT = "/root/dfilterforge"
FILES = (
    "training/train_sft.py",
    "data/train/v1/sft.jsonl.gz",
    "data/train/v1/sft-manifest.json",
)


def output_dir(seed: int) -> str:
    """Where one seed's adapter, log and run manifest are written."""
    return f"{ADAPTER_ROOT}/sft-v1-s{seed}"


def train_command(seed: int) -> list[str]:
    """The unchanged training script's argv for one seed."""
    script = f"{REMOTE_ROOT}/training/train_sft.py"
    seed_args = ["--seed", str(seed), "--output-dir", output_dir(seed)]
    return [sys.executable, script, *seed_args]


image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync("training", extras=["cu126"], uv_version=UV_VERSION)
    .env({"HF_HOME": f"{CACHE_ROOT}/hf", "HF_XET_HIGH_PERFORMANCE": "1"})
)
for path in FILES:
    image = image.add_local_file(path, f"{REMOTE_ROOT}/{path}")
adapters = modal.Volume.from_name(ADAPTER_VOLUME, create_if_missing=True)
app = modal.App("dfilterforge-sft")


@app.function(
    image=image,
    gpu=GPU,
    volumes={
        CACHE_ROOT: modal.Volume.from_name(
            HF_CACHE_VOLUME, create_if_missing=True
        ),
        ADAPTER_ROOT: adapters,
    },
    timeout=TIMEOUT_SECONDS,
)
def train(seed: int) -> None:
    """Trains one seed and commits its output to the adapters volume."""
    subprocess.run(train_command(seed), check=True)
    adapters.commit()


@app.local_entrypoint()
def main(seed: int) -> None:
    """Runs train remotely; train_sft.py refuses a seed it does not list."""
    train.remote(seed)
