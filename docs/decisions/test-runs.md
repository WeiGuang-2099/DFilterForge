# Hosted test runs

## Question

Which hosted runs answer the frozen test prompts, under which run ids, models,
providers, settings and caps, in what order, and what happens when one stops?
`docs/protocol.md` requires each hosted test run's run id, model id, provider
and settings in writing before the first test request; this note, part of the
protocol, holds them. It was written on 2026-10-01, before any test request,
from the slot winners in the [bake-off note](model-bakeoff.md) (section "Smoke
verdicts and slot winners: 2026-10-01", `evidence/bakeoff/ruling-2026-10-01.json`).
[`evidence/test-runs.json`](evidence/test-runs.json) (schema `test-runs/1.0`)
holds the same rows machine-readably, with each run's status.
`tests/test_hosted_test_runs.py` checks that the two list the same rows, that
every run id follows the naming below, that each config is a committed bake-off
config sending the row's model, slug and switch, that each cap meets the cap
rule, and that every run answers the admitted test prompts.

## Prompts

Every run answers the frozen test prompt set committed as
`docs/results/test-qwen3-32b-2026-09-26`: 112 items in C1 to C4, 448 requests
per pass, `prepare.json` SHA-256 prefix `206599bb67e1`, the prompt set
`src/dfilterforge/held_out_freeze.json` admits. Each call reads the owner's
ignored copy `artifacts/model-eval/test-qwen3-32b-2026-09-26` (`prepare.json`
and `prepared/`, byte-identical to the committed files) and writes
`runs/<run id>` inside it. Pass A's run id is the prepare id, fixed by the
freeze, so pass A publishes into the committed directory beside its two
controls. Every other run publishes into `docs/results/<run id>/`, first seeded
with the committed `prepare.json` and `prepared/`, so `prepared_drift` refuses a
pass that answered other prompts.

## Runs

Roles: `aa_pass_a` and `aa_pass_b` are the A/A pair, qwen/qwen3-32b on DeepInfra
twice with identical settings. `winner_small`, `winner_mid` and
`winner_frontier` are the slot winners; each qualified through its first pass,
so by rule 7 of the bake-off note it sends that pass's model, slug and switch.
`fallback_<slot>` is that winner's listed fallback, unused in the bake-off.
Runs 1 to 5 are sent in this order. Runs 6 to 8 are sent only after the run
they name, or its outage re-run, stops at the gate on its first answer (rule
7). Runs 9 to 16 are sent only after the run they name is an outage; each keeps
the role, config and cap of that run. The anchor has no fallback.

Configs are the committed bake-off configs
`docs/decisions/evidence/bakeoff/configs/<config>.json`, reused unchanged. They
already record each route's settings and its prices from the 2026-09-26
endpoints snapshot; the quantization is the snapshot's for the endpoint the
slug matches.

| # | Role | Run id | Model id | Slug | Quant | Reasoning | Config | Cap USD | Runs |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 1 | `aa_pass_a` | `test-qwen3-32b-2026-09-26` | `qwen/qwen3-32b` | `deepinfra` | fp8 | `enabled_false` | `qwen3-32b_deepinfra_enabled-false` | 0.10 | always |
| 2 | `aa_pass_b` | `test-qwen3-32b-passb-2026-09-26` | `qwen/qwen3-32b` | `deepinfra` | fp8 | `enabled_false` | `qwen3-32b_deepinfra_enabled-false` | 0.10 | always |
| 3 | `winner_small` | `test-qwen3.5-9b-2026-09-26` | `qwen/qwen3.5-9b` | `deepinfra` | bf16 | `enabled_false` | `qwen3.5-9b_deepinfra_enabled-false` | 0.15 | always |
| 4 | `winner_mid` | `test-qwen3.5-122b-a10b-2026-09-26` | `qwen/qwen3.5-122b-a10b` | `novita` | bf16 | `enabled_false` | `qwen3.5-122b-a10b_novita_enabled-false` | 0.75 | always |
| 5 | `winner_frontier` | `test-deepseek-v4-pro-0813-2026-09-26` | `deepseek/deepseek-v4-pro-0813` | `deepinfra` | fp8 | `enabled_false` | `deepseek-v4-pro-0813_deepinfra_enabled-false` | 1.25 | always |
| 6 | `fallback_small` | `test-qwen3.5-9b-fb-2026-09-26` | `qwen/qwen3.5-9b` | `parasail` | bf16 | `enabled_false` | `qwen3.5-9b_parasail_enabled-false` | 0.15 | gate stop of `test-qwen3.5-9b-2026-09-26` |
| 7 | `fallback_mid` | `test-qwen3.5-122b-a10b-fb-2026-09-26` | `qwen/qwen3.5-122b-a10b` | `atlas-cloud` | fp8 | `enabled_false` | `qwen3.5-122b-a10b_atlas-cloud_enabled-false` | 0.75 | gate stop of `test-qwen3.5-122b-a10b-2026-09-26` |
| 8 | `fallback_frontier` | `test-deepseek-v4-pro-0813-fb-2026-09-26` | `deepseek/deepseek-v4-pro-0813` | `nextbit` | fp8 | `enabled_false` | `deepseek-v4-pro-0813_nextbit_enabled-false` | 1.25 | gate stop of `test-deepseek-v4-pro-0813-2026-09-26` |
| 9 | `aa_pass_a` | `test-qwen3-32b-r2-2026-09-26` | `qwen/qwen3-32b` | `deepinfra` | fp8 | `enabled_false` | `qwen3-32b_deepinfra_enabled-false` | 0.10 | outage of `test-qwen3-32b-2026-09-26` |
| 10 | `aa_pass_b` | `test-qwen3-32b-passb-r2-2026-09-26` | `qwen/qwen3-32b` | `deepinfra` | fp8 | `enabled_false` | `qwen3-32b_deepinfra_enabled-false` | 0.10 | outage of `test-qwen3-32b-passb-2026-09-26` |
| 11 | `winner_small` | `test-qwen3.5-9b-r2-2026-09-26` | `qwen/qwen3.5-9b` | `deepinfra` | bf16 | `enabled_false` | `qwen3.5-9b_deepinfra_enabled-false` | 0.15 | outage of `test-qwen3.5-9b-2026-09-26` |
| 12 | `winner_mid` | `test-qwen3.5-122b-a10b-r2-2026-09-26` | `qwen/qwen3.5-122b-a10b` | `novita` | bf16 | `enabled_false` | `qwen3.5-122b-a10b_novita_enabled-false` | 0.75 | outage of `test-qwen3.5-122b-a10b-2026-09-26` |
| 13 | `winner_frontier` | `test-deepseek-v4-pro-0813-r2-2026-09-26` | `deepseek/deepseek-v4-pro-0813` | `deepinfra` | fp8 | `enabled_false` | `deepseek-v4-pro-0813_deepinfra_enabled-false` | 1.25 | outage of `test-deepseek-v4-pro-0813-2026-09-26` |
| 14 | `fallback_small` | `test-qwen3.5-9b-fb-r2-2026-09-26` | `qwen/qwen3.5-9b` | `parasail` | bf16 | `enabled_false` | `qwen3.5-9b_parasail_enabled-false` | 0.15 | outage of `test-qwen3.5-9b-fb-2026-09-26` |
| 15 | `fallback_mid` | `test-qwen3.5-122b-a10b-fb-r2-2026-09-26` | `qwen/qwen3.5-122b-a10b` | `atlas-cloud` | fp8 | `enabled_false` | `qwen3.5-122b-a10b_atlas-cloud_enabled-false` | 0.75 | outage of `test-qwen3.5-122b-a10b-fb-2026-09-26` |
| 16 | `fallback_frontier` | `test-deepseek-v4-pro-0813-fb-r2-2026-09-26` | `deepseek/deepseek-v4-pro-0813` | `nextbit` | fp8 | `enabled_false` | `deepseek-v4-pro-0813_nextbit_enabled-false` | 1.25 | outage of `test-deepseek-v4-pro-0813-fb-2026-09-26` |

Run ids follow the bake-off note's naming over the test prompts' date: `test-`,
the model id after the slash, `-fb` for a fallback, `-r2` for an outage re-run,
then `-2026-09-26`. Pass B adds `-passb`; the tag collides with no repair arm
tag (`-res`, `-bare`, `-cx`), smoke tag (`-rs`, `-rs2` and on), `-fb` or `-r2`.
Every id fits the result-name pattern; the longest middle,
`deepseek-v4-pro-0813-fb-r2`, has 26 of its 32 characters.

## Settings

Every run sends temperature 0, seed 17, max_output_tokens 2048, JSON mode, a
120 s timeout, require_parameters true, allow_fallbacks false, no
data_collection key, and its row's slug and reasoning switch (`enabled_false`
sends `{"enabled": false}`), as its config records. A pass is one call from the
shell holding the key, at the repository root, with no shell between the
arguments and the call step:

```text
uv run --frozen python scripts/model_run.py call \
  --prepare-dir artifacts/model-eval/test-qwen3-32b-2026-09-26 \
  --run-id RUN_ID --config docs/decisions/evidence/bakeoff/configs/CONFIG.json \
  --max-usd CAP --source-revision "$(git rev-parse --short HEAD)" \
  --gate-first --max-attempts 3 --min-interval-seconds 1.0
```

Items a pass leaves pending after transient failures (HTTP 5xx, 408 or 429, a
timeout or a transport error) are sent again by the same command with
`--resume`, until every item is settled; `max_attempts` 3 bounds each item.
A complete run is published with `scripts/model_run.py publish --run-dir
artifacts/model-eval/test-qwen3-32b-2026-09-26/runs/RUN_ID --output
docs/results/RUN_ID`.

## Order and timing

1. Pass A, `test-qwen3-32b-2026-09-26`.
2. Pass B, whatever pass A shows: its first invocation starts within 24 hours
   of pass A's first invocation (each run manifest records its invocations'
   `started_at`), unless the A/A pair is reported not run. The two are never
   pooled.
3. The slot winners, small, mid, then frontier, one run at a time.

The 12 prepare-hashed files stay byte-unchanged until the last baseline
request, the last request of any run above, fallbacks and outage re-runs
included. Under owner decision OD4 of 2026-10-01, no test run is scored (no
`dfilterforge score` over a test run, no `scored/` under its `docs/results`
directory) before the `repair-cards` branch, which holds the counterexample
card code, is merged; publishing a run's answers is allowed before that.

## Stops, outages and caps raised

- Gate stop (rule 7 of the bake-off note): a run whose first answer shows
  thinking not honoured stops and is never resumed. A slot winner's fallback,
  runs 6 to 8, then runs once; if the fallback stops at the gate too, or a
  resumed pass stops at the gate, the slot's test row is reported not run. The
  anchor has no fallback, so a gate stop of pass A or pass B reports the A/A
  pair not run; after pass A's, pass B is not sent.
- Outage (rule 3 of the bake-off note): a pass that ends with no completed
  answer and is not a refusal (only transient failures, a cap spent on
  timeouts, or final provider errors) is re-run once from scratch under its
  `-r2` row. If the re-run is an outage too, or the owner does not re-run it,
  the row is reported not run.
- Any other budget stop is resumed only under a cap raised above the last
  `max_usd` and committed to this note and `test-runs.json` first. HTTP 401,
  402 or 403 (an account or guardrail problem) and a config or operator error
  stop the run until a resume with the same options. None is a model failure.

## Status

`test-runs.json` gives each row a `status`, updated by hand in the commit that
publishes the run or rules on it:

- `registered`: the run may still send requests. Runs 1 to 5 start here, and a
  conditional run becomes `registered` once its condition occurs, before its
  first request.
- `unused`: a conditional run whose condition has not occurred. Runs 6 to 16
  start here. One whose named run is `not_run` stays `unused` only with a
  `reason` saying why its condition did not occur, for instance an outage
  rather than a gate stop.
- `published`: complete and published in `docs/results/<run id>/`; `commit` is
  the source revision its first invocation recorded.
- `not_run`: not sent or not finished, with a `reason` (a gate stop, an outage,
  the A/A pair reported not run).

The frozen-prompt guard reads these statuses (owner ruling G of 2026-10-01; the
[test-freeze note](test-freeze.md), Limits). `tests/test_model_run.py` keeps
`docs/results/test-qwen3-32b-2026-09-26` and every registered run's directory
guarded against a prepare-hashed edit, pass A's run manifest beside the
prompts or not, while any row is `registered`, or is `unused` while the run it
names is `not_run` and it gives no reason. It fails on a `published` row whose
complete run is not in `docs/results/<run id>` with the row's run id, prepare
digest, config settings and `commit`, on any other row whose directory holds a
run manifest, on a `not_run` row without a reason, and on a registry that no
longer names the frozen test prompts. Once every row is final
the guard releases without a re-freeze, whether pass A was published or the
A/A pair was reported not run.

## Caps

Each cap is at least twice the run's expected spend plus one worst-case
request, the margin `scripts/dev_bakeoff.py` (`headroom_micro_usd`) required of
every bake-off cap, rounded up to the next 0.05 USD. The expected spend is the
model's counted dev bake-off pass's spend in its `scored/summary.json`, the
largest of the charged upper bound, the price-derived and the provider-reported
figure, times 448/160 (the test prompts average 3,336 bytes against the dev
prompts' 3,272). A fallback takes that pass's prompt and completion tokens at
its own prices where that is higher. The worst-case request is the call step's
pre-request bound at the config's prices over the 448 test prompts: prompt
bytes plus 64 as input tokens and 2,048 output tokens. An outage re-run has the
cap of the run it repeats.

| Config | Dev pass | Dev spend | x 448/160 | Worst request | Twice plus worst | Cap |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3-32b_deepinfra_enabled-false` | `dev-qwen3-32b-2026-09-26` | 0.016014 | 0.044839 | 0.001080 | 0.090758 | 0.10 |
| `qwen3.5-9b_deepinfra_enabled-false` | `dev-qwen3.5-9b-2026-09-26` | 0.018138 | 0.050786 | 0.000940 | 0.102513 | 0.15 |
| `qwen3.5-9b_parasail_enabled-false` | same pass, its tokens at 0.10 / 0.25 | 0.021688 | 0.060728 | 0.001145 | 0.122600 | 0.15 |
| `qwen3.5-122b-a10b_novita_enabled-false` | `dev-qwen3.5-122b-a10b-2026-09-26` | 0.125665 | 0.351862 | 0.009084 | 0.712808 | 0.75 |
| `qwen3.5-122b-a10b_atlas-cloud_enabled-false` | same pass (0.094199 at 0.30 / 2.40) | 0.125665 | 0.351862 | 0.006813 | 0.710537 | 0.75 |
| `deepseek-v4-pro-0813_deepinfra_enabled-false` | `dev-deepseek-v4-pro-0813-2026-09-26` | 0.215290 | 0.602813 | 0.013546 | 1.219172 | 1.25 |
| `deepseek-v4-pro-0813_nextbit_enabled-false` | same pass (0.192457 at 1.056 / 3.168) | 0.215290 | 0.602813 | 0.013167 | 1.218793 | 1.25 |

deepseek-v4-pro-0813's figure is its price-derived spend; its pass was charged
at most 0.191094 USD. Runs 1 to 5 hold 2.35 USD of caps against about 1.10 USD
expected; the three fallbacks add 2.15 USD and the eight outage re-runs 4.50
USD, 9.00 USD for all 16. The committed runs so far record at most 0.940 USD of
OpenRouter spend (0.929 for the dev runs in `docs/results`, 0.011 for the
smoke), so runs 1 to 5 at their caps bring it to 3.29 USD of the plan's 12 USD.

## Not registered here

Repair arm runs (`-res`, `-bare`, `-cx`) are not baseline runs; they are
registered with the repair round before the first test request. Pass B is never
repaired. Dev runs and smoke runs are not test runs.

## Limits

- Prices, quantizations and endpoints may change before a call; each run
  records its config's prices from the 2026-09-26 snapshot, and only the served
  provider, not its quantization.
- No code checks pass timing; run manifests record it.
