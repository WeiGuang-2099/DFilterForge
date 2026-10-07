# Self-served runs

## Question

No hosted provider serves Qwen/Qwen3-1.7B with our adapters, so the small
model's rows are served by us. What stack serves them, which run ids answer
which prompts, and what happens when a run stops? The protocol (Models,
amended 2026-10-07) makes this note part of it; it was written on
2026-10-07, before any self-served request.

## Stack

Every self-served row, the base model and each SFT adapter, runs on this
one stack. `modal/serve_vllm.py` holds it and `tests/test_modal_glue.py`
checks it against this note and `training/train_sft.py`.

- Server: vLLM 0.21.0's OpenAI-compatible server on Modal, one L4 per
  container, at most one container, scale to zero after 5 idle minutes.
  The image is Modal's vLLM example's: `nvidia/cuda:12.9.0-devel-ubuntu22.04`
  with Python 3.12 and `vllm==0.21.0`.
- Model: `Qwen/Qwen3-1.7B` at `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`,
  weights and tokenizer (which carries the chat template), the commit
  `training/train_sft.py` pins, in bf16.
- Thinking: off by the server's default,
  `--default-chat-template-kwargs '{"enable_thinking": false}'`. The client
  sends no switch, so no prepare-hashed file changes, and the server renders
  each request as `render_prompt` in training does. vLLM runs without a
  reasoning parser, so a reply carries no reasoning reading and the
  `--gate-first` gate reads `uncontrolled`; it can never stop these runs, and
  thinking off rests on the server flag this note records.
- Adapters: `--enable-lora --max-lora-rank 16` on every row, the base rows
  included, so base and adapter rows share the flags. Seed s's adapter
  (`sft-v1-s<s>/adapter` on the Modal volume `dfilterforge-adapters`) is
  served as `qwen3-1.7b-sft-s17`, `qwen3-1.7b-sft-s42` or
  `qwen3-1.7b-sft-s2026` once its run manifest is there. The adapters were
  trained on the nf4-quantized base and are served on the bf16 base.
- Auth: vLLM's `--api-key`, read from `VLLM_API_KEY` in the Modal Secret
  `dfilterforge-vllm-key`, refuses `/v1` requests without the owner's key;
  the Modal proxy itself is open (`unauthenticated=True`).
- Training: `modal/train_sft.py` runs `training/train_sft.py` unchanged on
  the same GPU type, in the training lock's cu126 environment.

Why one L4: it is the cheapest Modal GPU with bf16 and 24 GB (USD 0.80/h
against 1.10 for an A10; a T4 has no bf16), the bf16 weights (3.4 GB) and
the 4-bit QLoRA run both fit, and its dense bf16 rate is about an A10's, so
training costs less on it. Decoding is memory-bound and an L4 has half an
A10's bandwidth, so a pass takes longer; at the measured prompt and answer
sizes of the hosted runs, either GPU answers a test pass in under an hour.
Prices: modal.com/pricing, 2026-10-07.

Why vLLM 0.21.0: it is the version Modal's vLLM example pins on that image
(modal.com/docs/examples/vllm_inference, read 2026-10-07), and every option
above is in its serve documentation (docs.vllm.ai/en/v0.21.0/cli/serve/).
Newer releases exist (0.31.0, 2026-10-05); what matters is that every row
uses the same one.

## Settings and caps

Each run sends the hosted runs' settings ([test-run
registry](test-runs.md), Settings) with `openrouter` null: temperature 0,
seed 17, max_output_tokens 2048, JSON mode, a 120 s timeout, and the call
options `--gate-first --max-attempts 3 --min-interval-seconds 1.0`. The
config is `modal/call-config.json` with the server's URL filled in and, for
an adapter row, the adapter's name as `model_id`; the filled copies stay
under the ignored `artifacts/modal/`.

Prices are nominal, 0.01 USD per million input and output tokens, because
`CallConfigV1` refuses zero prices; the run manifests' spend figures are
therefore not costs. The real cost is GPU time, read from Modal's usage page
and recorded per run below. Caps, also nominal, are 0.05 for a dev pass and
0.10 for a test pass: above the pre-request bound of every request at three
attempts (0.026091 and 0.073875), so no pass stops on budget. The real
bound is the Modal workspace budget.

## Prompts

- Dev: `dev-qwen3-1.7b-2026-10-07`, prepared at 637c788 in the test image,
  back to back with the test set; `prepare.json` SHA-256 prefix
  `8fb6a03c34f4`. Its four prompt files are byte-identical to
  `docs/results/dev-qwen3-32b-2026-09-26/prepared`, the bake-off's dev
  prompts.
- Test: `test-qwen3-1.7b-2026-10-07`, 112 items, top-k 16; `prepare.json`
  SHA-256 prefix `5dedf73169f6`, admitted 14th in
  `src/dfilterforge/held_out_freeze.json`. Its `prepared/C1.json` to
  `C4.json` are byte-identical to the frozen test prepare's, with the same
  items, catalog and system prompt digests. A new prepare was needed: the
  frozen one records model-side digests that `scripts/model_run.py` and
  `src/dfilterforge/generation.py` no longer match, and its call is refused
  with `prepare_code_mismatch`.

Both are seeded in `docs/results/<id>/` (`prepare.json`, `prepared/`). Every
row answers these two prompt sets: the call step writes each run to
`runs/<run id>` inside the owner's copy `artifacts/model-eval/<id>`, and a
run id only has to name the prepare's split, so one admitted test prepare
serves all four test rows. Before an adapter row's first call its results
directory is seeded with the same files and committed, so `publish` refuses
a pass that answered other prompts.

## Runs

| Row | Dev run id | Test run id | `model_id` |
| --- | --- | --- | --- |
| base | `dev-qwen3-1.7b-2026-10-07` | `test-qwen3-1.7b-2026-10-07` | `Qwen/Qwen3-1.7B` |
| SFT seed 17 | `dev-qwen3-1.7b-sft-s17-2026-10-07` | `test-qwen3-1.7b-sft-s17-2026-10-07` | `qwen3-1.7b-sft-s17` |
| SFT seed 42 | `dev-qwen3-1.7b-sft-s42-2026-10-07` | `test-qwen3-1.7b-sft-s42-2026-10-07` | `qwen3-1.7b-sft-s42` |
| SFT seed 2026 | `dev-qwen3-1.7b-sft-s2026-2026-10-07` | `test-qwen3-1.7b-sft-s2026-2026-10-07` | `qwen3-1.7b-sft-s2026` |

An outage re-run adds `-r2` after the tag, before the date
(`dev-qwen3-1.7b-r2-2026-10-07`, `test-qwen3-1.7b-sft-s2026-r2-2026-10-07`).

## Rules

- Each row answers dev first. It answers the frozen test prompts only if
  its dev run is complete, every item settled after its resumes. This is
  fixed now, before any score, and no dev score decides it.
- Items left pending by transient failures (HTTP 5xx, including the 503 a
  scaled-down server returns, 408, 429, a timeout or a transport error) are
  sent again by the same command with `--resume`.
- A resume refuses a new endpoint host (`settings_changed`). A redeploy of
  the same app keeps the host and the pass resumes; a pass whose host
  changed (another app name, workspace or region), or that ends with no
  completed answer, is re-run once from scratch under its `-r2` id. If that
  fails too, the row is reported not run.
- The base row and every adapter row use the stack above. A change of GPU
  type, dtype, vLLM version, image or model revision starts every row again
  under new run ids, registered here first.
- Scoring is offline in the lab container, as for every run. The adapter
  rows' C1 to C3 are marked untrained conditions and C4 is reported split by
  field coverage (protocol, Training rules).

## Measured

GPU time and cost per run, from Modal's usage page, go here as each run
finishes. Before any run, the estimates in `docs/usage.md` (Self-served runs
on Modal) put the base row's dev and test passes near USD 1 and the whole
plan, three seeds trained and four rows scored, near USD 7.

## Limits

- Only `vllm` is pinned in the server image; its other packages resolve when
  Modal first builds it, and Modal reuses that build while the image
  definition is unchanged. The owner records `/version` before each run.
- No test compares vLLM's rendered prompt with training's token by token;
  the pinned tokenizer revision and the thinking flag stand for it.
- Each run manifest records the endpoint host, which names the owner's
  Modal workspace.
- The nominal prices make the call step's spend cap a formality here.
