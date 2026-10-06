# Training

One command trains a QLoRA adapter for Qwen/Qwen3-1.7B, thinking off, on
the frozen training set, and writes the adapter, its training log and a run
manifest. The same script runs unchanged on any CUDA machine.

## What a run does

- Reads `data/train/v1/sft.jsonl.gz`: 1,299 rows (1,088 ready, 211
  needs_clarification), built by `scripts/sft_dataset.py`. Each prompt is
  the C4 request scoring prepares for that row; each completion is the
  row's target envelope. It refuses the file if its lines do not match the
  digest in `sft-manifest.json`.
- Renders every prompt with the Qwen3-1.7B chat template and
  `enable_thinking=False`, then appends the completion and `<|im_end|>`.
  Only completion tokens carry labels. Before training it checks that TRL
  prepared every row exactly that way, and stops otherwise.
- Trains 4-bit nf4 QLoRA (r 16, alpha 32, dropout 0.05, all attention and
  MLP projections) for 3 epochs: learning rate 2e-4, cosine schedule,
  effective batch 16.
- Writes `adapter/` (the adapter after the final epoch, which is the
  pre-registered checkpoint), `log.jsonl` and `run_manifest.json` (dataset
  digest, model and tokenizer revisions, library versions, seed, recipe,
  steps, loss curve, runtime, device).

The protocol's Training rules fix the recipe: seeds 17, 42 and 2026, every
one reported, and no checkpoint chosen on dev or test.

## CPU smoke and parity test

These need Docker, no GPU, and no network after the build. The build
fetches the pinned tokenizer and a tiny random Qwen3 model.

```text
docker compose --profile train build train
docker compose --profile train run --rm train
docker compose --profile train run --rm train python -m pytest -q -p no:cacheprovider training/tests
```

The smoke trains the tiny model on 8 rows for 12 steps, on CPU without
4-bit, and writes to `artifacts/sft-smoke` (the directory must not exist).
It proves the path, not learning: the tiny model's 8-wide hidden state
keeps its output near uniform, so the loss stays near ln(151,936) = 11.93.
The parity test checks every row: the trained token sequence is the served
prompt, then the completion, then the stop token.

## On a CUDA host

With Docker and the NVIDIA container toolkit. The run uses the host user,
so the mounted `artifacts/` is writable, and keeps the model cache there,
so the weights download once for all three seeds:

```text
docker build -f training/Dockerfile --build-arg TORCH_EXTRA=cu126 -t dfilterforge-train:cu126 .
docker run --rm --gpus all --user "$(id -u):$(id -g)" -e HF_HOME=/workspace/artifacts/hf -v "$PWD/artifacts:/workspace/artifacts" dfilterforge-train:cu126 python training/train_sft.py --seed 17 --output-dir /workspace/artifacts/sft/seed-17
```

Without Docker (Linux x86_64, Python 3.12, uv):

```text
uv sync --project training --frozen --extra cu126
uv run --project training --no-sync python training/train_sft.py --seed 17 --output-dir artifacts/sft/seed-17
```

The first run downloads the model weights (about 4 GB) into the Hugging
Face cache. The run trains in bf16, so it needs an Ampere or newer GPU, and
the cu126 wheels need a driver that supports CUDA 12.6. Repeat with
`--seed 42` and `--seed 2026`.

## Serving the adapter

The scoring client sends no thinking switch. Whatever serves the adapter
must therefore render prompts as `render_prompt` does, with thinking off
by default (for vLLM, a server-side default for the chat template's
`enable_thinking`). Check the first served answer for `<think>`.
