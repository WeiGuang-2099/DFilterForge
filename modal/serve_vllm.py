"""Serve Qwen/Qwen3-1.7B, thinking off, as an OpenAI-compatible endpoint.

One command deploys it from the repository root (docs/usage.md,
"Self-served runs on Modal"):

    modal deploy modal/serve_vllm.py

Every self-served row runs this stack (docs/decisions/self-served-runs.md):
vLLM VLLM_VERSION on one GPU of type GPU, the weights and the tokenizer,
which carries the chat template, at the commit training/train_sft.py
pins, in bf16, with enable_thinking false as the server's default
chat-template argument, because the scoring client sends no switch. LoRA
is on for the base rows too, so base and adapter rows share the flags;
each trained seed's adapter on the adapters volume is served under its
own model name, and the base keeps the hub id.

Modal's proxy checks every request, on every path, for a Proxy Auth
Token of the owner's workspace, which the client sends unchanged as its
bearer key (`Authorization: Bearer wk-<id>.ws-<secret>`). It answers any
other request with 401 before a container starts, so the public host
alone cannot start the GPU; vLLM itself checks no key. At most one
container runs. It scales to zero after SCALEDOWN_SECONDS without a
request; a request while none runs gets HTTP 503 and starts one, so the
runbook polls /v1/models until it answers before a call.

Sources, read 2026-10-07: Modal's vLLM example, which pins the image and
the vLLM version used here (modal.com/docs/examples/vllm_inference); Modal
Servers, which require proxy auth unless unauthenticated=True
(modal.com/docs/guide/servers); Proxy Auth Tokens
(modal.com/docs/guide/webhook-proxy-auth); App.server's parameters
(modal.com/docs/reference/modal.App); vLLM's serve options
(docs.vllm.ai/en/v0.21.0/cli/serve/).
"""

from __future__ import annotations

import json
from pathlib import Path
from pathlib import PurePath
from pathlib import PurePosixPath
import socket
import subprocess
import time

import modal

MODEL_ID = "Qwen/Qwen3-1.7B"
# training/train_sft.py's MODEL commit: weights and chat template.
MODEL_REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
VLLM_VERSION = "0.21.0"
# The cheapest Modal GPU with bf16 and 24 GB; modal/train_sft.py uses it.
GPU = "L4"
# training/train_sft.py's SEEDS and its recipe's LoRA rank.
SEEDS = (17, 42, 2026)
LORA_RANK = 16
PORT = 8000
SCALEDOWN_SECONDS = 5 * 60
STARTUP_SECONDS = 15 * 60
APP_NAME = "dfilterforge-vllm"
HF_CACHE_VOLUME = "dfilterforge-hf-cache"
ADAPTER_VOLUME = "dfilterforge-adapters"
# Paths in the Linux container. Path would write them with backslashes
# when the owner deploys from Windows, and the image build rejects those.
CACHE_ROOT = PurePosixPath("/cache")
ADAPTER_ROOT = PurePosixPath("/adapters")
THINKING_OFF = json.dumps({"enable_thinking": False})


def adapter_name(seed: int) -> str:
    """The model name a request sends to reach one seed's adapter."""
    return f"qwen3-1.7b-sft-s{seed}"


def adapter_dir(seed: int) -> str:
    """The directory modal/train_sft.py writes one seed's run to."""
    return f"sft-v1-s{seed}"


def vllm_command(adapter_root: PurePath = ADAPTER_ROOT) -> list[str]:
    """The vllm serve argv, with every adapter already trained.

    --lora-modules takes all adapters after one flag: given twice, the
    last one replaces the first.
    """
    command = [
        *("vllm", "serve", MODEL_ID, "--served-model-name", MODEL_ID),
        *("--revision", MODEL_REVISION, "--tokenizer-revision", MODEL_REVISION),
        *("--dtype", "bfloat16"),
        *("--default-chat-template-kwargs", THINKING_OFF),
        *("--enable-lora", "--max-lora-rank", str(LORA_RANK)),
        *("--host", "0.0.0.0", "--port", str(PORT)),
    ]
    # train_sft.py writes run_manifest.json last, after the adapter.
    root = Path(adapter_root)
    modules = [
        f"{adapter_name(seed)}={root / adapter_dir(seed) / 'adapter'}"
        for seed in SEEDS
        if (root / adapter_dir(seed) / "run_manifest.json").is_file()
    ]
    if modules:
        command += ["--lora-modules", *modules]
    return command


def wait_until_listening(
    process: subprocess.Popen[bytes], port: int = PORT
) -> None:
    """Returns once the server accepts connections on its port.

    Raises as soon as the process has exited, so a vLLM that dies on
    startup fails its container at once instead of holding the GPU for
    STARTUP_SECONDS; Modal's startup timeout bounds any other wait.
    """
    while True:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"vllm serve exited with code {code}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)


image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.9.0-devel-ubuntu22.04", add_python="3.12"
    )
    .entrypoint([])
    .uv_pip_install(f"vllm=={VLLM_VERSION}")
    .env({"HF_HOME": str(CACHE_ROOT / "hf"), "HF_XET_HIGH_PERFORMANCE": "1"})
)
app = modal.App(APP_NAME)


@app.server(
    image=image,
    gpu=GPU,
    volumes={
        str(CACHE_ROOT): modal.Volume.from_name(
            HF_CACHE_VOLUME, create_if_missing=True
        ),
        "/root/.cache/vllm": modal.Volume.from_name(
            "dfilterforge-vllm-cache", create_if_missing=True
        ),
        str(ADAPTER_ROOT): modal.Volume.from_name(
            ADAPTER_VOLUME, create_if_missing=True
        ),
    },
    port=PORT,
    startup_timeout=STARTUP_SECONDS,
    scaledown_window=SCALEDOWN_SECONDS,
    min_containers=0,
    max_containers=1,
)
class Server:
    """One vLLM process; the container is ready once it listens."""

    @modal.enter()
    def start(self) -> None:
        """Starts vLLM with the adapters the volume holds now.

        Returns once vLLM listens; raises at once if it exits first.
        """
        # pylint: disable-next=attribute-defined-outside-init,consider-using-with
        self.process = subprocess.Popen(vllm_command())
        wait_until_listening(self.process)

    @modal.exit()
    def stop(self) -> None:
        """Stops vLLM when the container scales down."""
        self.process.terminate()
