# Model bake-off: filling the hosted slots

## Question

Which open-weight models answer the frozen test prompts beside qwen/qwen3-32b,
chosen before any test answer is read? This note is part of `docs/protocol.md`.

## Slot rewrite

The owner rewrote the slots on 2026-09-26, before any test request, for the
reasons below, from the keyless OpenRouter models API that day:

| Before | After | Total parameters |
| --- | --- | --- |
| 8B-class | 8B-class | 7B to 12B, dense |
| 27B to 32B-class | qwen/qwen3-32b on DeepInfra, also the A/A pair | 32.8B, dense |
| 70B-class | about 120B-class | 100B to 130B, dense or MoE |
| DeepSeek-V3-class | frontier open-weight MoE | about 0.75T to 1.6T |

- `deepseek/deepseek-v3.2`, `-v3.1-terminus`, `-v3.2-exp` and
  `-r1-distill-llama-70b` carry `expiration_date` 2026-09-28; the V3 ids that
  stay are `deepseek-chat` (2024-12-26), `-chat-v3-0324` and `-chat-v3.1`.
- The list's Artificial Analysis coding index gives the anchor 15.3 and
  `meta-llama/llama-3.3-70b-instruct` 11.9, the only indexed 65B to 79B model
  (the other eight date from 2024-07 to 2025-02); the expiring V3s 44.2, 43.5.

## Candidates

Rank order is the owner's; R is the slot's reserve. Prices are USD per million
input and output tokens from the keyless endpoints API on 2026-09-26 (snapshot
`docs/decisions/evidence/bakeoff/endpoints.json`), as the configs in
`docs/decisions/evidence/bakeoff/configs/` record them. Totals are Hugging Face
safetensors totals; Mistral Medium 3.5's weights are public as
`mistralai/Mistral-Medium-3.5-128B` (127.7B). The AA index reorders nothing.

| Slot | # | Model | Total | Slug sent | Quant | Reasoning | USD in / out | Fallback: slug, quant, reasoning | USD in / out | AA |
| --- | --- | --- | ---: | --- | --- | --- | ---: | --- | ---: | ---: |
| 8B | 1 | qwen/qwen3.5-9b | 9.7B | deepinfra | bf16 | enabled_false | 0.10 / 0.15 | parasail, bf16, enabled_false | 0.10 / 0.25 | 28.7 |
| 8B | 2 | mistralai/ministral-8b-2512 | 8.9B | mistral | unknown | null | 0.165 / 0.165 | none | | 9.7 |
| 8B | 3 | ibm-granite/granite-4.2-8b | 8.8B | deepinfra | bf16 | enabled_false | 0.06 / 0.25 | coreweave, bf16, enabled_false | 0.10 / 0.15 | 22.4 |
| 8B | R | meta-llama/llama-3.1-8b-instruct | 8.0B | deepinfra | fp8 | null | 0.02 / 0.04 | none | | 5.4 |
| 120B | 1 | qwen/qwen3.5-122b-a10b | 125B | novita | bf16 | enabled_false | 0.40 / 3.20 | atlas-cloud, fp8, enabled_false | 0.30 / 2.40 | 45.7 |
| 120B | 2 | mistralai/mistral-medium-3-5 | 128B | mistral | unknown | effort_none | 1.65 / 8.25 | mistral, unknown, enabled_false | 1.65 / 8.25 | 46.9 |
| 120B | 3 | nvidia/nemotron-3-super-120b-a12b | 124B | deepinfra | bf16 | enabled_false | 0.085 / 0.40 | dekallm, fp8, enabled_false | 0.08 / 0.45 | 37.7 |
| 120B | R | qwen/qwen3-next-80b-a3b-instruct | 81B | alibaba | unknown | null | 0.0975 / 0.78 | none | | none |
| Frontier | 1 | deepseek/deepseek-v4-pro-0813 | 1.65T | deepinfra | fp8 | enabled_false | 1.30 / 2.60 | nextbit, fp8, enabled_false | 1.056 / 3.168 | 68.8 |
| Frontier | 2 | z-ai/glm-5.2 | 0.75T | alibaba/fp8 | fp8 | enabled_false | 0.966 / 3.036 | novita, fp8, enabled_false | 0.6496 / 2.0416 | 68.8 |
| Frontier | 3 | moonshotai/kimi-k2.6 | 1.03T | parasail | int4 | enabled_false | 0.75 / 3.50 | inceptron, int4, enabled_false | 0.4344 / 2.39 | 61.8 |
| Frontier | R | moonshotai/kimi-k2-0905 | 1.03T | novita | fp8 | null | 0.60 / 2.50 | none | | none |
| Anchor | | qwen/qwen3-32b | 32.8B | deepinfra | fp8 | enabled_false | 0.08 / 0.28 | none | | 15.3 |

- A provider's base slug is sent when it serves exactly one endpoint of the
  model, and the full endpoint tag when it serves more than one, except for the
  two Mistral models (next bullet). Alibaba serves glm-5.2 on `alibaba/fp8` and
  on `alibaba/fast`, the priority tier (2.31 / 7.26); a base slug does not match
  a service tier, and the tag names fp8 explicitly.
- Both Mistral models are sent the base slug `mistral`, which matches the
  `mistral`, `mistral/zdr` and `mistral/eu` endpoints of the same weights. The
  served variant is not recorded; each config records `mistral/eu`'s price, the
  highest (the other two list 0.15 / 0.15 and 1.50 / 7.50).
- ministral-8b-2512 has no fallback: it has no thinking and one vendor. The
  fallback of mistral-medium-3-5 is the same model on `mistral` with
  `enabled_false`; every other fallback sends its candidate's switch.
- Every endpoint above lists temperature, seed, max_tokens and response_format,
  plus reasoning where a switch is sent, so require_parameters can route to it.
  For kimi-k2.6, inceptron/int4 has the best one-day uptime (98.5 percent) of
  the other int4 endpoints listing all of them. That comparison and the
  `alibaba/fast` price come from the live endpoints list on 2026-09-26.
- `enabled_false` sends `{"enabled": false}`, `effort_none` `{"effort": "none"}`
  (Mistral Medium 3.5 lists high and none); null sends no reasoning key.
- Two listed candidates are exceptions to the slot bands: the 120B reserve
  qwen3-next-80b-a3b-instruct (81B) and deepseek-v4-pro-0813 (about 1.65T).

## Selection rule

Fixed, with the smoke below, before any bake-off request.

1. The anchor runs its dev pass first as run id `dev-qwen3-32b-2026-09-26`, the
   prepare id, unranked and with no fallback, and must pass rule 4's run gates
   (at least 152 completed, no reasoning, a reasoning-token count). A stop that
   can still be resumed or ruled on prints STOPPED; a final failure prints
   ANCHOR FAILED and exits 1 before any candidate runs. The bake-off then stops;
   the owner's decision on it and on the A/A pair is added to this note, dated,
   before any further request.
2. Each ranked candidate gets one gated pass over the 160 frozen dev items, and
   exactly one pass on its listed fallback when its recorded manifest and
   attempts show (a) the run's first completed answer read as not honoured by
   `completions.thinking_state`, whatever the recorded stop reason, or (b) a
   complete pass with no completed answer, at least one HTTP 400 or 404, and
   every attempt that is neither transient nor an account refusal (rule 3) a 400
   or 404, a routing or parameter refusal. A pass that earns the fallback is
   never resumed; with no listed fallback the candidate drops. The counted pass
   is the fallback pass when one ran, else the first.
3. Within one execution the runner resumes a pass left with pending items after
   transient failures (HTTP 5xx, 408, 429, timeouts, transport errors), after a
   60 s wait with the same options, until every item is settled; `max_attempts`
   3 bounds each item, and one not completed after 3 attempts counts under the
   152 rule. A pass that ends with no completed answer and is not a refusal (say
   only transient failures, a cap spent on timeouts, which are charged their
   worst case, or final provider errors) is an outage and stops the batch; the
   owner may re-run it once from scratch as `dev-<model>-r2-2026-09-26`
   (`-fb-r2-` for a fallback), else, or if the re-run is an outage too, the
   candidate is not measured and its slot goes on. A ruling (`--rerun`,
   `--not-measured`) is repeated on every later command. Any other budget stop
   is resumed only under a cap raised above the last `max_usd` and committed;
   else it stops the batch, as do HTTP 401, 402 and 403 (account or guardrail
   problems) and a config or operator error. None is a model failure.
4. A candidate drops if any answer of its counted pass shows reasoning (thinking
   not honoured), other than a first answer that earns the fallback, if it is a
   hybrid (sent a switch) and the pass reports no reasoning-token count
   (thinking uncontrolled), if fewer than 152 of 160 items end with a completed
   final attempt after retries and resumes, or if its two-turn smoke fails.
5. Its count is its counted pass's strong-exact ready items summed over C1 to C4
   (24 each, 96). The earliest-listed survivor at most 4 below the best
   survivor's count (inclusive margin 4) wins the slot, so a small dev
   difference does not override the order.
6. With no survivor, and only then, the reserve runs under rules 2 to 4 with its
   own smoke and no fallback, and takes the slot if it survives; else the slot
   stays empty and is reported so. The runner refuses `--only reserve-<slot>`
   (exit 2, before any call) unless every ranked candidate of the slot is final
   and either none passes the run gates or `--after-smoke-failures` (recorded in
   the step log and summary) is given because every run-gate survivor failed its
   smoke. A passing reserve is the slot's run-gate survivor.
7. A slot winner that qualified through its fallback runs its test passes with
   that pass's model, slug and reasoning switch. A test pass (A/A or a slot
   winner's) that stops at the gate on its first answer is re-run once on the
   candidate's listed fallback if its qualifying pass did not already use it;
   otherwise that test row, or the A/A pair, is reported as not run, as is one
   whose resumed pass stops at the gate. Such fallback test runs are registered
   with the rest before the first test request.

## Two-turn smoke

Repair sends a real second turn, so each candidate must take one. The smoke uses
the counted pass's model, slug and settings, no fallback, and `--gate-first`,
`--max-attempts 3`, `--min-interval-seconds 1.0` and `--max-usd 0.20`. Its items
are the first two dev C4 items in prepare order whose counted-pass answer
completed with finish_reason stop and parses under the C4 contract with status
ready; with fewer than two, the smoke fails. Each is sent as its system and user
messages, that answer verbatim as the assistant turn, and the user turn "Your
filter was incorrect. Reply with a corrected answer in the same JSON format." It
passes when both items end completed with finish_reason stop, no reply shows
reasoning (any model), thinking is honoured for a model sent a switch
(uncontrolled fails it), and both replies parse under the C4 contract. A harness
or operator failure (HTTP 401, 402 or 403, a budget stop, no completed reply
only through transient failures, a wrong config) is re-run under a new run id
ending in its prepare's date, never a fail; a final error or refusal of the
second turn fails it. The anchor's smoke is informational; smoke runs are
evidence, not scored. The second turn needs a hashed `generation.py` change, so
the owner sends the smoke from a branch after the bake-off; main keeps the 12
hashed files unchanged until the last baseline test request.

## Settings

Every bake-off, smoke and test run sends temperature 0, seed 17,
max_output_tokens 2048, JSON mode, a 120 s timeout, require_parameters true,
allow_fallbacks false, no data_collection key, and its pass's slug and reasoning
switch above. A pass is one `scripts/model_run.py call` with `--gate-first`,
`--max-attempts 3`, `--min-interval-seconds 1.0` and `--max-usd` at the
candidate's cap in `scripts/dev_bakeoff.py`, plus rule 3's resumes with
`--resume` and the same options. After the note, tooling and configs are
committed, the owner runs `uv run --frozen python scripts/dev_bakeoff.py` from
the shell holding the key; its docstring lists exit codes 0, 1, 2, 3 and 130.

## What gets published

- Run ids are `dev-<model>-2026-09-26`, `<model>` being the id after the slash;
  a fallback adds `-fb` and an outage re-run `-r2` before the date
  (`dev-glm-5.2-fb-2026-09-26`). All fit the result-name pattern; the longest
  middle, `nemotron-3-super-120b-a12b-fb-r2`, is at its 32-character limit.
- The runner records each run's `commit_to` in its JSON summary. The
  maintainer's publish step puts every pass the runner reads as done in
  `docs/results/<run id>/`, first seeding a new directory with the committed dev
  `prepare.json` and `prepared/` (sha256 prefix `c7cfabf91dd1`), so
  `prepared_drift` refuses a pass that answered other prompts. The anchor's pass
  joins the two controls in `docs/results/dev-qwen3-32b-2026-09-26/` (an anchor
  re-run gets its own seeded `-r2-` directory), where `publish` refuses any
  other entry (`output_exists`). It is scored offline; CI re-scores it.
- Every other pass (incomplete, gate-stopped, refused or an outage) and every
  smoke run has its `run_manifest.json` and attempt logs copied to
  `docs/decisions/evidence/bakeoff/<run id>/`, beside the runner's final
  summary, which records the rulings. They hold dev answers only; reasoning and
  refusal text are never stored.

## Not an effect

Bake-off counts choose models and are never reported as an effect or a
comparison: one dev pass each, no interval, a preset order. Test passes are the
results.

## Limits

- Prices, quantizations and endpoints may change before the calls; each run
  records its config's prices from the 2026-09-26 snapshot. The glm-5.2 fallback
  on novita records the listed price after a 53.6 percent discount off 1.40 /
  4.40, so its bound understates the charge if the discount ends.
- Only the served provider is recorded (`provider_changed` flags another one),
  not its endpoint, so `mistral/eu` against `mistral/zdr` cannot be checked.
- A hybrid that reports no reasoning-token count is judged only when its pass
  ends, so it spends up to its cap before it drops; this is accepted.

## Smoke verdicts and slot winners: 2026-10-01

Added after the smoke; the rules above are unchanged. The owner sent the
smokes on 2026-10-01 between 11:50 and 12:06 UTC with
`scripts/two_turn_smoke.py` from the branch `repair-multiturn` at 281b2ce,
which had prepared them at 2d305e0 from the runner summary committed here as
`evidence/bakeoff/summary-2026-09-26.json` (same SHA-256) and then judged them.
That branch, with its note `second-turn.md`, merges only after the last
baseline test request. Every run sent its counted pass's config with the
registered call options; each served provider was the pinned one and each
served model the one requested, and the runs were charged at most 0.0115 USD in
all. `evidence/bakeoff/<run id>/` holds each smoke run's manifest and attempt
log, and `evidence/bakeoff/smoke/` the smoke plan, its summary and the nine
verdicts.

| Slot | # | Candidate | Smoke run | Items | Served | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Anchor | A | qwen3-32b | dev-qwen3-32b-rs-2026-09-26 | mei-0001, mei-0002 | DeepInfra | pass (informational) |
| 8B | 1 | qwen3.5-9b | dev-qwen3.5-9b-rs-2026-09-26 | mei-0001, mei-0003 | DeepInfra | pass |
| 8B | 2 | ministral-8b-2512 | dev-ministral-8b-2512-rs-2026-09-26 | mei-0001, mei-0002 | Mistral | pass |
| 8B | 3 | granite-4.2-8b | dev-granite-4.2-8b-rs-2026-09-26 | mei-0001, mei-0003 | DeepInfra | pass |
| 120B | 1 | qwen3.5-122b-a10b | dev-qwen3.5-122b-a10b-rs-2026-09-26 | mei-0001, mei-0002 | Novita | pass |
| 120B | 2 | mistral-medium-3-5 | none: dropped at the run gates (134 of 160) | | | |
| 120B | 3 | nemotron-3-super-120b-a12b | dev-nemotron-3-super-120b-a12b-rs-2026-09-26 | mei-0001, mei-0002 | DeepInfra | pass |
| Frontier | 1 | deepseek-v4-pro-0813 | dev-deepseek-v4-pro-0813-rs-2026-09-26 | mei-0001, mei-0002 | DeepInfra | pass |
| Frontier | 2 | glm-5.2 | dev-glm-5.2-rs-2026-09-26 | mei-0001, mei-0002 | Alibaba | pass |
| Frontier | 3 | kimi-k2.6 | dev-kimi-k2.6-rs-2026-09-26 and dev-kimi-k2.6-rs2-2026-09-26 | mei-0001, mei-0002 | none | not measured (ruling K) |

In every pass both replies completed with finish_reason stop, parsed under the
C4 contract, showed no reasoning and reported 0 reasoning tokens.

Ruling K. The owner ruled on 2026-10-01 that kimi-k2.6's smoke is not measured
and is not retried. Parasail, its pinned provider, answered HTTP 429 to all 12
attempts of its two runs (two items, three attempts each), so nothing was
served and 0 USD was charged. The smoke rule reads that as a harness failure
owed a re-run, never a fail, so kimi-k2.6 neither survives nor drops by its
smoke. The ruling changes no winner: kimi-k2.6's count, 68, is below glm-5.2's
72, so the best survivor's count is 72 whether or not kimi-k2.6 survives, and
deepseek-v4-pro-0813, listed first at 70, is within 4 of it either way.

Rule 5, with mistral-medium-3-5 dropped at the run gates and no smoke failed:

| Slot | Survivors (count) | Best | Floor | Winner |
| --- | --- | ---: | ---: | --- |
| 8B | qwen3.5-9b 42, ministral-8b-2512 39, granite-4.2-8b 18 | 42 | 38 | qwen/qwen3.5-9b |
| 120B | qwen3.5-122b-a10b 57, nemotron-3-super-120b-a12b 37 | 57 | 53 | qwen/qwen3.5-122b-a10b |
| Frontier | deepseek-v4-pro-0813 70, glm-5.2 72 (kimi-k2.6 68, not measured) | 72 | 68 | deepseek/deepseek-v4-pro-0813 |

The floor is the best survivor's count less 4, and each winner is the
earliest-listed survivor at or above it. Every slot has a survivor, so no
reserve runs (rule 6). Each winner qualified through its first pass, so by rule
7 its test passes send that pass's model, slug and switch: qwen/qwen3.5-9b on
`deepinfra`, qwen/qwen3.5-122b-a10b on `novita` and
deepseek/deepseek-v4-pro-0813 on `deepinfra`, each `enabled_false`. No other
candidate gets a test pass, and these counts are no effect (see Not an effect).
`evidence/bakeoff/ruling-2026-10-01.json` (schema `bakeoff-ruling/1.0`) holds
this ruling; `tests/test_dev_bakeoff.py` checks it against the ranking, the
runner summary, the verdicts and the copied evidence, and checks that each
winner stays the same however a smoke not measured would have ended.

## Repair arms' provider: 2026-10-04

Added after the test baselines; rules 1 to 7 and the sections above are
unchanged. The protocol's Decoding and provenance section lets a new run
change its provider only as this note lists, so this section lists the one
move the protocol's Repair section rules on.

deepseek/deepseek-v4-pro-0813's repair arm runs, on dev and on test, send its
listed fallback `deepseek-v4-pro-0813_nextbit_enabled-false` (nextbit, fp8,
`enabled_false`, 1.056 / 3.168 USD per million), although no gate stop
occurred. Its three dev arm runs and their `-r2` re-runs got no answer from
DeepInfra: all 198 attempts were HTTP 429, and nothing was charged. Only the
arm runs move. Its passes do not: the counted dev pass and the counted test
pass stay the DeepInfra ones, with the answers DeepInfra served, and rule 7
still governs every test pass. No other candidate's route changes.

The ruling is OD5 in the [repair note](repair-round.md), which also gives the
new dev run ids. `evidence/repair-arms/ruling-2026-10-04.json` holds it.
