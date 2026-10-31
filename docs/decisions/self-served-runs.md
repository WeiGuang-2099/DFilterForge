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
- Auth: Modal documents that its proxy refuses every request, on every
  path, that lacks a Proxy Auth Token of the owner's workspace, with 401
  and before a container starts; the call step sends the token as its
  bearer key. vLLM checks no
  key. The owner stops the app at the end of every session, so none stays
  deployed between them.
- Training: `modal/train_sft.py` runs `training/train_sft.py` unchanged on
  the same GPU type, in the training lock's cu126 environment.

Why one L4: it is the cheapest Modal GPU with bf16 and 24 GB (USD 0.80/h
against 1.10 for an A10; a T4 has no bf16), the bf16 weights (3.4 GB) and
the 4-bit QLoRA run both fit, and its dense bf16 rate is about an A10's, so
training costs less on it. Decoding is memory-bound and an L4 has half an
A10's bandwidth, so a pass takes longer; at the prompt and answer sizes
the hosted runs measured, a test pass should still take under an hour.
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
- A resume refuses a new endpoint host (`settings_changed`). A pass whose
  host changed (another app name, workspace or region), or that ends with
  no completed answer, is re-run once from scratch under its `-r2` id; if
  that fails too, the row is reported not run. A redeploy of the same app
  should keep the host, since the URL names the workspace, app and class.
- The base row and every adapter row use the stack above. A change of GPU
  type, dtype, vLLM version, image or model revision starts every row again
  under new run ids, registered here first.
- Scoring is offline in the lab container, as for every run. The adapter
  rows' C1 to C3 are marked untrained conditions and C4 is reported split by
  field coverage (protocol, Training rules).
- Added 2026-10-26, for every run sent from that day on. The call step now
  ends a pass at its first HTTP 5xx or 408, timeout or dropped connection,
  with `stop_reason` `transient_failure`, while an HTTP 429 is retried by
  the next pass as before. Such a pass is resumed with `--resume` once the
  server answers again, not re-run, so "ends with no completed answer"
  above means a run that holds no completed answer when the session stops
  calling it. Every reply must carry the fingerprint
  `vllm-0.21.0-84f508c7` and the deploy must reuse the image of
  2026-10-08; a run that breaks either is reported as such and not read.

## Seed 2026's test pass, sent twice

Added 2026-10-20, before its request. Seed 2026's adapter answers the
frozen test prompts a second time, so the repeatability of this stack is
measured once. When this was written every self-served row had been
scored, seed 2026's first test pass included (C4 strong exact 0.475); the
second pass changes no row, score, headline estimate or analysis.

- Run: `test-qwen3-1.7b-sft-s2026-passb-2026-10-07`, `model_id`
  `qwen3-1.7b-sft-s2026`, on the prepare `test-qwen3-1.7b-2026-10-07` in
  all four conditions (448 items), with the first pass's config, settings,
  endpoint host, call options and 0.10 cap, on the stack above. Its
  results directory is seeded with the prepare's files and committed with
  this text.
- Why seed 2026: its first test pass is the only adapter test pass that
  ran as one invocation with every item settled on its first attempt
  (2026-10-08, 10:28 to 10:45 UTC).
- Reading: `dfilterforge pair`, first pass first, reads the two passes as
  the hosted A/A pair is read: per condition, changed answers, changed
  outcomes, outcome transitions and flipped cases (ready cases whose
  strong-exact case mean differs). Its output is committed as
  `docs/decisions/evidence/aa-test-qwen3-1.7b-sft-s2026-2026-10-07.json`,
  and a CI test rebuilds it byte for byte. Pages quote the answers changed
  over all 448 items and the C4 cases flipped over the 40 ready cases, C4
  being the condition the adapter was trained on; the other conditions'
  counts stay in the report. The condition comparisons the report also
  prints are not read, as C4 against C2 is not read for adapters.
- Scope: the second pass is not a row. It is never pooled with the first,
  never scored into the headline or the analyses, never repaired, and it
  sets no noise bound for later training. The hosted A/A's 24-hour rule
  does not apply: the first pass ran on a container that had just answered
  seed 2026's dev pass, and the second starts cold, weeks later, so the
  pair measures whether the same image, adapter and greedy decoding give
  the same answers across sessions.
- Rules: every reply must carry the fingerprint `vllm-0.21.0-84f508c7`,
  and the deploy must reuse the image of 2026-10-08; a pass that breaks
  either is reported as such and not read as repeatability. Items left
  pending by transient failures are resumed with `--resume` under the
  rules above. A pass whose host changed, or that ends with no completed
  answer, is re-run once as
  `test-qwen3-1.7b-sft-s2026-passb-r2-2026-10-07`; if that fails too, the
  rerun is reported not run and its seeded directory is removed in the
  same commit.
- Expectation, not a claim: greedy decoding on an unchanged stack should
  change few answers or none. The counts are published as measured.

Result, 2026-10-20. The registration was pushed first: GitHub records the
branch `passb` created at 08:51:44 UTC, and PR #38 merged it into `main`
at 08:55:11 UTC. The pass ran from 11:03:49 to 11:19:46 UTC as one
invocation at source revision c9dddb8, each of its 448 requests settled on
its first attempt, and every reply carries the fingerprint
`vllm-0.21.0-84f508c7`. The session's script would have stopped on an
image build, and none happened, so the deploy reused the image of
2026-10-08. Prompts and settings were identical in every condition. The
second pass changed 33 of the 448 answers, and none of the 40 ready C4
cases flipped. The report,
[`evidence/aa-test-qwen3-1.7b-sft-s2026-2026-10-07.json`](evidence/aa-test-qwen3-1.7b-sft-s2026-2026-10-07.json),
holds the other conditions' counts, the outcome transitions, the items
whose outcome changed and the flipped cases. Greedy decoding on this
stack does not repeat itself exactly across sessions; for contrast, the
hosted A/A pair changed 39 to 46 of 112 answers per condition.

## Baseline rows

Added 2026-10-26, before their requests (protocol, Training rules, amended
2026-10-26; owner rulings of 2026-10-25 and 2026-10-26). Two rows of the
base model ask whether constrained decoding or prompting closes what
fine-tuning closed.
When this was written every self-served row had been scored on dev and
test (base test C4 strong exact 0.063, three-seed SFT mean 0.396), so both
rows are post hoc and labelled so.

| Row | Dev run id | Test run id |
| --- | --- | --- |
| base + JSON schema | `dev-qwen3-1.7b-schema-2026-10-26` | `test-qwen3-1.7b-schema-2026-10-26` |
| base + 8 examples + JSON schema | `dev-qwen3-1.7b-fs8-2026-10-26` | `test-qwen3-1.7b-fs8-2026-10-26` |

An outage re-run adds `-r2` after the tag (`test-qwen3-1.7b-fs8-r2-2026-10-26`).

- Prompts: each row answers the prepare named after its first run id,
  made at 32660dc in the test image and seeded in `docs/results/<id>/`;
  `prepare.json` SHA-256 prefixes `f8d348edb9d2` and `0e6c9e04df1a`
  (schema, dev and test) and `7eb5fee3c38f` and `b2477f881d92`
  (few-shot). The two test prepares are admitted 15th and 16th in
  `src/dfilterforge/held_out_freeze.json`. The schema prepares hold C4
  alone (`prepare --conditions C4`), and their `C4.json` are byte for
  byte the base row's (`7d4c9ec4`, `874e5166`), so that row differs from
  base only in how it decodes.
- Examples: the few-shot prepares (`--conditions C4 --few-shot`) put
  eight training examples in each prompt's INPUT_JSON as `examples`: the
  request and SFT target of rows of `data/train/v1/sft.jsonl.gz`
  (decompressed SHA-256 prefix `4677e902ebd4`), chosen by the words they
  share with the item's request (`word-overlap/1` in
  `dfilterforge.few_shot`), best last. The system prompt is unchanged,
  byte for byte the base row's and the SFT prompt's, so the row differs
  from the schema row only in that key. About nine in ten ready examples
  use a field outside the item's retrieved list, which the C4 clause tells
  the model to keep to; the SFT targets override that rule the same way
  (protocol, Training rules, amended 2026-10-06).
- Settings: the base row's config with `"response_schema": "typed-ir/1"`,
  as `artifacts/modal/qwen3-1.7b-schema.json`, so the server gets
  `response_format` `json_schema` with `dfilterforge.answer_schema`'s
  schema instead of `json_object`; every other setting, call option, cap
  and the endpoint host are the base row's. The schema follows the
  scorer's parser as far as JSON Schema can and names no field;
  `tests/test_answer_schema.py` lists where it is looser or stricter.
- Probe: after a wake and before the schema row's dev pass the session
  sends one request, dev `mei-0001`'s C4 prompt under the schema, which
  must come back with HTTP 200 and an answer the parser reads. A 503, a
  502 or a timeout means the server was not up, and the probe is sent
  again after another wake. Any other failure means neither row is run,
  and this note says why. The probe is not a run and its answer is
  never scored.
- Order: both dev passes, then each test pass only if its own dev pass
  settled every item.
- Reading (protocol): the schema row minus the base row, the few-shot row
  minus the schema row and the three-seed SFT mean minus the few-shot row,
  each paired by case on test C4 strong exact and read only if its
  interval excludes 0 and at least 10 cases are discordant. Outcome counts
  and the field-coverage split are shown and never read. The dev passes
  are pipeline checks.
- Cost: the session's Modal bill over the requests it sent, beside the GPU
  time the runs' latencies sum to at USD 0.80 an hour; both cover the
  repair round's runs too.

Corrected 2026-10-31, before the re-runs' requests (protocol, Training
rules, amended 2026-10-31; owner ruling of 2026-10-29). The dev passes
sent on 2026-10-28 showed a pipeline defect, not a result: the client sent
each request body through `canonical_json`, which sorts object keys, so
the schema reached vLLM with its properties in alphabetical order, and
xgrammar, vLLM 0.21.0's default grammar engine, emits them in declared
order. Once an answer opened with `schema_version` and `status`, only
`not_expressible` could follow, and both dev passes wrote the object
`{"schema_version": "1.0", "status": "not_expressible"}` on all 80 items
(c3374bf): one answer each, where the base row gave 40 different answers
to the schema row's 40 prompts. The client now encodes the body with each
object's keys in the order the code built them (`_encode_body` in
`dfilterforge.model_client`, 548084b), and `tests/test_model_client.py`
checks the order the server receives. Before this text, the body the
corrected client sends for the probe was compiled offline as vLLM 0.21.0
compiles it, with xgrammar 0.2.8 (vLLM 0.21.0 allows any xgrammar from 0.2
to before 1.0, and the server image's own version is not recorded):
`ready`, `needs_clarification` and `not_expressible` can each follow the
prompt's opening, and it admits the same 22 of the base row's 40 dev C4
answers as the schema in declared order, where the sorted body admits
none. Both rows run again:

| Row | Dev run id | Test run id |
| --- | --- | --- |
| base + JSON schema | `dev-qwen3-1.7b-schema-ord-2026-10-26` | `test-qwen3-1.7b-schema-ord-2026-10-26` |
| base + 8 examples + JSON schema | `dev-qwen3-1.7b-fs8-ord-2026-10-26` | `test-qwen3-1.7b-fs8-ord-2026-10-26` |

The tag `ord` names the one change, as `nb` named the frontier arms' new
provider ([repair note](repair-round.md), OD6), and the date stays the
rows' registration date. An outage re-run adds `-r2` after the tag
(`test-qwen3-1.7b-fs8-ord-r2-2026-10-26`).

- Prompts: each corrected row answers the prepare named after its first
  run id, made at 548084b in the test image with the 2026-10-26 commands
  and seeded in `docs/results/<id>/`; `prepare.json` SHA-256 prefixes
  `f9c2a947612e` and `a22465598c3d` (schema, dev and test) and
  `219677265037` and `64867837ab10` (few-shot). Each `prepared/C4.json` is
  byte for byte its 2026-10-26 counterpart (`7d4c9ec4`, `874e5166`,
  `79065612`, `21167efa`), and each manifest differs from its counterpart
  only in its id, creation time, source revision and the digests of
  `model_client.py` and `answer_schema.py`. The two test prepares are
  admitted 26th and 27th in `src/dfilterforge/held_out_freeze.json`, which
  leaves 5 of its 32 slots.
- Order: both dev passes, then each test pass only if its own dev pass
  settled every item and its completed answers are not all one string. A
  dev pass whose answers are all one string shows the 2026-10-28 defect
  again: its test pass waits for a later session, and the maintainer
  checks the pipeline first. It compares whole answers and reads no
  answer's status and no score.
- Unchanged: the schema, the settings and config, the caps, the endpoint
  host, the call options, the probe, and the reading above, which now
  reads the corrected runs.
- The 2026-10-26 runs: the two dev passes stay committed as the record of
  the defect and are not rows. The two test passes,
  `test-qwen3-1.7b-schema-2026-10-26` and
  `test-qwen3-1.7b-fs8-2026-10-26`, are reported not run. They were never
  published or scored, and the session scripts read them only for their
  census (item and attempt counts, run status, fingerprints, think blocks)
  and copied them into the owner's backups. They hold answers, so unlike
  OD6's DeepInfra runs, which held none and are committed as evidence,
  they stay out of the repository, unread, in the owner's ignored
  `artifacts/` and its backups. Their seeded directories are removed with
  this text, as a rerun reported not run is (Seed 2026's test pass, sent
  twice), since no call may answer them; their admissions, 15th and 16th,
  stay. Their requests were billed in the session of 2026-10-28; how they
  enter the cost, which may not open them, is ruled before the cost is
  written.
- No other row, number or rule changes.

## Repair round

Added 2026-10-26, before its first request (protocol, Repair, amended
2026-10-26; owner rulings of that day). The three SFT adapters' test
passes are repaired with the hosted round's trigger, arms and cards, and
first their dev passes, as a pipeline check never read as an effect. When
this was written every 1.7B score, seed 2026's second test pass and the
hosted round's results (pooled test repair@1: counterexample 35 of 75,
bare 21, resample 4) were known, so the round is post hoc. Where this
restates the protocol, the protocol holds.

Plans, written by `lab repair` at 203f0f2 and committed with
`--check`, one per pass; every triggered item has a card, frames for a
silent-wrong answer and an error for an invalid one:

| Pass | Triggered | Silent-wrong / invalid | Cases |
| --- | ---: | ---: | ---: |
| `dev-qwen3-1.7b-sft-s17-2026-10-07` | 14 | 10 / 4 | 9 of 12 |
| `dev-qwen3-1.7b-sft-s42-2026-10-07` | 17 | 11 / 6 | 10 of 12 |
| `dev-qwen3-1.7b-sft-s2026-2026-10-07` | 15 | 10 / 5 | 10 of 12 |
| `test-qwen3-1.7b-sft-s17-2026-10-07` | 45 | 32 / 13 | 31 of 40 |
| `test-qwen3-1.7b-sft-s42-2026-10-07` | 44 | 32 / 12 | 30 of 40 |
| `test-qwen3-1.7b-sft-s2026-2026-10-07` | 36 | 25 / 11 | 26 of 40 |

The 125 test items are 58 distinct items in 36 of the 40 cases.

- Arm runs: the pass's id with `-res`, `-bare` or `-cx` before its date
  (`test-qwen3-1.7b-sft-s17-cx-2026-10-07`), and an outage re-run with
  `-r2` after the tag (`dev-qwen3-1.7b-sft-s2026-bare-r2-2026-10-07`):
  eighteen runs, 513 requests, 46 per arm on dev and 125 per arm on test.
  The nine dev arm prompt sets were written by `follow-up --plan --arm` at
  203f0f2 and are seeded in `docs/results/<arm id>/`.
- Settings: each arm sends its pass's config
  (`artifacts/modal/qwen3-1.7b-sft-s<seed>.json`), endpoint host and call
  options, under the caps above (0.05 dev, 0.10 test); `lab repair`
  refuses an arm whose settings or host differ from its pass.
- Order: in the session, the nine dev arm runs first (seeds 17, 42, 2026;
  resample, bare, counterexample within each), then the baseline rows.
  Meanwhile the dev arms are published and scored, the three dev rounds
  and the dev pool written and checked, and the dev round reviewed for
  defects. Only then are the nine test arm prompt sets prepared,
  committed, admitted in a commit of their own and pushed, and the test
  arm runs sent. If that point is not reached in the session, the test
  arms run in a later one.
- A dev defect is a refused follow-up, call, publish, score,
  `repair --check` or `repair-pool --check`, a reply with another
  fingerprint, or a think block. A low repair@1, malformed second turns
  or loops are results.
- Outages: as under Rules; a test `-r2` answers its arm's admitted
  prompt set and waits for a later session. An arm lost after its `-r2`,
  or sent across a host or image change, is not run under Rules; `lab
  repair` records only a gate stop as not run, so the owner rules how
  that round is summarized before its summary is written, and no seed
  pool is written while any seed has an arm not run.
- Reading (protocol): per seed, counterexample against bare (primary),
  counterexample against resample and bare against resample; the same
  three pooled over the seeds by case in
  `repair-pool/<split>-qwen3-1.7b-sft.json` (secondary). A comparison
  reads as a difference only if its interval excludes 0 and at least 10
  cases are discordant. The resample arm is shown as "the same prompt
  again (repeatability check)": seed 2026's second test pass repeated 34
  of its 36 triggered answers byte for byte and made none strong exact.
  No seed-against-seed, base or hosted comparison is read.
- Outputs: six `repair/plan.json`, eighteen arm runs, six
  `repair/summary.json` and `.md`, and
  `repair-pool/{dev,test}-qwen3-1.7b-sft.json` and `.md`.
- Limits: the adapters were trained on single-turn prompts, so bare and
  counterexample are four-message chats they never saw in training; the
  interval covers case sampling with the three adapters fixed; the spend
  columns of the repair summaries are nominal, never a cost.

## Measured

Each pass and each training run below ran on 2026-10-08, except adapter
sessions 3 and 4, on 2026-10-18 and 2026-10-20; every pass records source
revision e1f61bd, except seed 2026's rerun in session 4, which records
c9dddb8. Costs are each Modal app's bill, from deploy or start to stop,
read with `modal billing report` (hourly, local time, by resource) on
2026-10-08 and again on 2026-10-18, whose rows are in
[`evidence/self-served/modal-billing-2026-10-07-to-18.json`](evidence/self-served/modal-billing-2026-10-07-to-18.json),
and for session 4 on 2026-10-20, in
[`evidence/self-served/modal-billing-2026-10-20.json`](evidence/self-served/modal-billing-2026-10-20.json);
the dev total equals the owner's reading of the usage page. The L4 share
at USD 0.80 an hour gives the GPU time. The estimates in `docs/usage.md`
put the base row's dev and test passes near USD 1 and the whole plan near
USD 7; Modal billed USD 5.16 in all, the failed first build and the rerun
included, of which USD 4.87 before the rerun.

| Run | Work | Total, USD | L4, USD (about) |
| --- | --- | ---: | ---: |
| `dev-qwen3-1.7b-2026-10-07` | 160 requests, each settled on its first attempt | 0.35 | 0.32 (24 min) |
| `test-qwen3-1.7b-2026-10-07` | 448 requests, each settled on its first attempt | 0.67 | 0.62 (47 min) |
| `sft-v1-s17` | 246 steps, 3 epochs, 3,057 s of training | 0.78 | 0.69 (52 min) |
| `sft-v1-s42` | 246 steps, 3 epochs, 3,006 s | 0.76 | 0.68 (51 min) |
| `sft-v1-s2026` | 246 steps, 3 epochs, 3,048 s | 0.78 | 0.69 (51 min) |
| Adapter session 1, 2026-10-08 | Seed 2026's dev and test passes, each item settled on its first attempt; the first passes of dev s17 (160 HTTP 503s) and dev s42 (134 answers, 26 HTTP 503s) | 0.63 | 0.59 (44 min) |
| Adapter session 2, 2026-10-08 | dev s17 resumed (160 answers); test s17 (292 answers, then 154 HTTP 503s and 2 HTTP 502s); dev s42's two resumes (26 HTTP 503s each); test s42 (234 answers, 214 HTTP 503s) | 0.63 | 0.58 (44 min) |
| Adapter session 3, 2026-10-18 | test s17 (156 answers) and test s42 (214) resumed, each on its first attempt | 0.26 | 0.24 (18 min) |
| Adapter session 4, 2026-10-20 | Seed 2026's test rerun: 448 requests, each settled on its first attempt | 0.29 | 0.27 (20 min) |

The adapter passes needed three sessions, and seed 2026's rerun a
fourth. In the first, dev s17's first pass found the server down and got
503 for every item. In the
second, Modal preempted the container at 21:44:09 local time, during test
s17; the replacement stopped 11 s after it came up at 21:51:48, and the
next was ready at 21:58:33. Every request in those gaps got 503 or 502,
and each spent one attempt, so seed 42's 26 dev C1 items failed three
times and score `provider_failed` under the rules above, while the 370
test items left pending kept two attempts each. On 2026-10-18 a first try
from the University of Adelaide network sent nothing: the network reset
every TLS connection to `*.modal.direct`, no container started and
nothing was billed. The third session ran from another network, and
each call under a watchdog that would have stopped it at its first
failed answer. The fourth sent the rerun in one invocation, every item
on its first attempt. All 2,246 adapter answers, 1,056 of seed 2026's and
1,190 of seeds 17 and 42, carry the fingerprint `vllm-0.21.0-84f508c7`.

The first deploy from Windows failed in the image build until
`modal/serve_vllm.py` wrote its container paths as POSIX (PR #29); that
build cost under USD 0.01. The working deploy printed
`https://weiguang-2099--dfilterforge-vllm-server.us-east.modal.direct`
with Modal's proxy-auth marker. With the token, requests were answered 503
while the container started and 200 once vLLM listened. The first cold
start took about six minutes from deploy to the first answer, of which
vLLM's engine start took 249 s (78 s compiling, 36 s capturing CUDA
graphs). Every reply records the fingerprint `vllm-0.21.0-84f508c7`, and
no reply holds a think block. On all 608 dev and test items the served
prompt's token count equals a local render of the pinned template with
thinking off, which is 4 tokens longer than the thinking-on render; on
the 160 dev items it also equals hosted Qwen3-32B's count. Each seed's
run manifest and loss log are committed in `docs/results/sft-v1/`, with
the SHA-256 of each adapter's weights and config in `adapters.sha256`
(paths relative to `artifacts/sft/`, the copy of the
`dfilterforge-adapters` volume). They record the pre-registered recipe,
the final-step checkpoint and run-average train losses of 0.024, 0.023
and 0.023 (seeds 17, 42, 2026); the last logged losses are about 1e-4 per
target token, up to 8e-4 for seed 17.

## Limits

- Only `vllm` is pinned in the server image; its other packages resolve when
  Modal first builds it, and Modal reuses that build while the image
  definition is unchanged. The owner records `/version` before each run.
- No test in CI compares vLLM's rendered prompt with training's token by
  token. A check on 2026-10-08 rendered all 1,299 training rows and all
  608 dev and test prompts with the pinned template, thinking off, and got
  the same token ids under transformers 5.18 (training), 5.19 and 4.57;
  vLLM renders adapter requests with the base model's tokenizer and
  template, not the copies in each adapter directory.
- Each run manifest records the endpoint host, which names the owner's
  Modal workspace. The host is public; by Modal's documentation a request
  to it without the token starts no container.
- The nominal prices make the call step's spend cap a formality here.
- Measured on Modal: the image, the deploy, the URL form, requests with
  the token, the cold start and the costs above. Not observed: a request
  without the token, which should get 401, and scale to zero, since each
  session was stopped by hand.
- The response parser accepts a reply that leaves `missing_slots` out but
  refuses an explicit `"missing_slots": null`, although the prompt says it
  is [] unless the status is `needs_clarification`. The base row wrote
  null in 14 of 40 C1 dev replies and 31 of 112 C1 test replies, and in
  no other condition; all were refused as malformed, 1 and 2 of them also
  cut at the token cap. Re-scored offline with null read as [] (lab image,
  pinned tshark, 2026-10-08; the unchanged replies reproduce the committed
  outcomes), 2 dev and 3 test items become strong exact: C1 `mei-0003`
  and `mei-0004` on dev, `mei-1005`, `mei-1039` and `mei-1071` on test.
  C1 strong exact would be 0.083 instead of 0 on dev and 0.088 instead of
  0.050 on test, and the test C2 - C1 difference 0.075 (7 cases against
  5) instead of 0.113 (8 against 3). The other rewritten replies become
  invalid, silent-wrong or false-ready, or stay malformed. No hosted reply
  wrote null, C4 is unaffected, and the scorer stays as it is for every
  row.
- The training manifests record no commit. The owner's checkout was
  `main` at e1f61bd during the session, and `training/` and `data/train/`
  are unchanged on `main` since PR #27 (9cf7ea1).
- Every row decodes greedily (temperature 0), as the protocol fixes for
  all models. The Qwen3 model card at the pinned revision suggests
  temperature 0.7, top_p 0.8 and top_k 20 for thinking-off use, and warns
  that greedy decoding can repeat endlessly in thinking mode. 7 of 160
  base dev replies and 18 of 448 base test replies ran to the 2048-token
  cap, the dev ones checked as loops. At temperature 0 vLLM ignores the
  model's generation_config sampling defaults.
- The base rows are served with `--enable-lora` and no adapter, as the
  stack requires; whether that changes any logit against a plain bf16
  serve is not measured.
