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
`scripts/test_passes.py` sends them (Owner command below), and
`tests/test_test_passes.py` checks it against a scripted call step.

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
  `-r2` row, 60 s after the outage. If the re-run is an outage too, or the
  owner rules the `-r2` row `not_run` (or `unused` with a reason) before it
  starts, the row is reported not run.
- Refusal: a complete pass with no completed answer whose every attempt that is
  neither transient nor an account refusal is an HTTP 400 or 404 earned the
  fallback in the bake-off (rule 2), but rule 7 gives a test pass its fallback
  for a gate stop only, so no row here is conditional on a refusal and the row
  is reported not run.
- Any other budget stop is resumed only under a cap raised above the last
  `max_usd` and committed to this note and `test-runs.json` first. HTTP 401,
  402 or 403 (an account or guardrail problem) and a config or operator error
  stop the run until a resume with the same options. None is a model failure.

## Owner command

`scripts/test_passes.py` sends every run above from one command. The owner runs
it at the root of the main checkout, in the one shell that holds the key, once
this note, the registry and the batch are merged and pulled. It reads
`test-runs.json` and refuses to start unless
`artifacts/model-eval/test-qwen3-32b-2026-09-26` exists, its `prepare.json` is
a prompt set the freeze record admits, and it and every prompt file are
byte-identical to the committed copy; a missing copy prints the commands that
restore it from `docs/results/test-qwen3-32b-2026-09-26` in both shells. It
then calls every run it may send once with the key withheld, and each must stop
at `api_key_missing`, which proves that the run id, cap, prompts, source
digests and config pass the call step's own checks while no request is
possible. Paid calls start only when the key variable is set and this note, the
registry, the configs, the batch and the rules it reads are committed, so the
commit each call records covers them. Each run is one `scripts/model_run.py
call` with exactly the arguments under Settings, started as an argument list
with no shell; the batch never reads, prints or writes the key, and never
publishes or scores.

It sends pass A, pass B straight after a complete pass A, then the small, mid
and frontier winners, one run at a time, and applies the rules above by itself:
pending items are resumed after 60 s with the same options and `--resume`; a
gate stop on a winner's first answer sends that winner's fallback once; an
outage is re-run once under its `-r2` row; a gate stop of pass A or pass B, a
refusal, and a resumed pass that stops at the gate are reported not run. Pass B
starts only within 24 hours of the counted pass A's first invocation; when that
window has closed, the batch stops until the owner records pass B's rows
`not_run` with a reason. A row this file marks `published`, `not_run`, or
`unused` with a reason is never sent. Every step is read back from the run
directories, so running the same command again skips finished runs and resumes
unfinished ones. `--dry-run` prints each row's state and the calls the batch
would make next, and sends nothing.

The step log `steps.jsonl` and the summaries `summary-<date>.json` and `.txt`
go to `artifacts/test-passes/` (ignored). The summary gives every row its state
(`done`, `not_run`, `unused`, `owed` or `waiting`), the reason, its first
invocation's start and source revision, the directory the maintainer commits it
to, and the `status`, `reason` and `commit` its entry here gets. A `done` run
is published into `docs/results/<run id>/`. A run that left a directory but is
not published keeps its `run_manifest.json` and attempt logs as evidence in
`docs/decisions/evidence/test-runs/<run id>/`, as the bake-off note does for
dev runs. A conditional run is sent in the same execution as the stop that
triggers it, so its `registered` status is written afterwards, in the commit
that publishes or rules on it.

Git Bash, at the owner's main checkout (`read -rsp` keeps the key off the screen
and out of the history):

```bash
cd /d/codeproject/acourse-code/DFilterForge
git pull --ff-only
uv run --frozen python scripts/test_passes.py --dry-run
read -rsp "OpenRouter key: " DFILTERFORGE_MODEL_API_KEY && echo && export DFILTERFORGE_MODEL_API_KEY
uv run --frozen python scripts/test_passes.py; echo "exit code: $?"
unset DFILTERFORGE_MODEL_API_KEY
```

Windows PowerShell 5.1, at the same checkout:

```powershell
Set-Location D:\codeproject\acourse-code\DFilterForge
git pull --ff-only
$env:PYTHONIOENCODING = "utf-8"
uv run --frozen python scripts/test_passes.py --dry-run
$secure = Read-Host -AsSecureString "OpenRouter key"
$env:DFILTERFORGE_MODEL_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure
uv run --frozen python scripts/test_passes.py
"exit code: $LASTEXITCODE"
Remove-Item Env:DFILTERFORGE_MODEL_API_KEY
```

| Exit | Meaning | What the owner does |
| --- | --- | --- |
| 0 | Every row has a final state: `done`, `not_run` or `unused`. | Publish each `done` run, copy each other run's evidence, and commit the status, reason and commit the summary gives each row. |
| 1 | Stopped for the owner: a budget stop after an answer, pass B's window closed, a call step that ended with an error or left no run directory, the invocation limit, an unreadable run directory, or an error the batch did not expect after a paid call may have been sent. | Read the `STOPPED` line, the summary and `steps.jsonl`. For a budget stop, raise the row's `cap_usd` here and in `test-runs.json` above the last `max_usd` and commit; for pass B's window, record pass B's rows `not_run` with a reason and commit. Then run the same command. |
| 2 | Refused before any request: the registry, the prompt copy, a config, the lock, git, uncommitted tooling or the keyless preflight. | Fix what the `refused` or `REFUSED` line names (a missing copy prints its restore commands; delete a held `artifacts/test-passes/.lock` only when no batch or call step is running) and run the same command. |
| 3 | Aborted: the key variable is not set (after the keyless preflight; nothing was sent), or the account refused a request with HTTP 401, 402 or 403. | Set the key, or fix the key, the credit or the account's guardrail, and run the same command. |
| 130 | Interrupted with Ctrl-C after the request in flight finished; that request may be billed but not recorded. | Run the same command. If it says a call step is still running, let it exit and delete `artifacts/test-passes/.lock` first. |

## Status

`test-runs.json` gives each row a `status`, updated by hand in the commit that
publishes the run or rules on it:

- `registered`: the run may still send requests. Runs 1 to 5 start here, and a
  conditional run is `registered` from the moment its condition occurs; the
  batch sends it in the same execution (Owner command), so the file records it
  in the commit that publishes or rules on it.
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

Repair arm runs are not baseline runs and are not rows here. The protocol's
Repair section registers them by rule before the first test request: the run
of `aa_pass_a` and each slot's published `winner_<slot>` or `fallback_<slot>`
run, an outage re-run included, is repaired by three arm runs named after its
run id with `-res`, `-bare` or `-cx` before the date, and an arm's outage
re-run adds `-r2` after the tag (`test-qwen3-32b-cx-r2-2026-09-26`). Each arm
run sends its repaired run's config and call options under the Repair
section's cap for that slot. `test-runs.json` states the rule under
`repair_arms`, and the [repair note](repair-round.md) lists the ids. Pass B is
never repaired. A test arm's prompt set is prepared only after the last
baseline request and admitted in its own commit; as the test-freeze note's
Limits say, it is guarded until its own `run_manifest.json` sits beside it, so
no arm run keeps a row here, or the frozen test prompts, guarded. Dev runs and
smoke runs are not test runs.

## Limits

- Prices, quantizations and endpoints may change before a call; each run
  records its config's prices from the 2026-09-26 snapshot, and only the served
  provider, not its quantization.
- `scripts/test_passes.py` starts pass B only within 24 hours of the counted
  pass A's first invocation; a call made by hand is not checked, and the run
  manifests record the timing either way.
