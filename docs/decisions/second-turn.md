# Second turn: the two-turn smoke's prompts, batch and judge

## Question

The [bake-off note](model-bakeoff.md) makes every run-gate survivor take a
two-turn smoke, and repair later sends the same shape. Can a prepared prompt
carry the model's own answer and one more user turn, chosen and judged by the
note's rule, without moving a byte of any recorded prompt set?

## Before and after

Before is 431df73 (main); after is this branch. Nothing here sends a request.

| Measure | 431df73 | after |
| --- | --- | --- |
| (system, user, assistant, user) as a `PreparedPromptV1` | refused (`too_long`) | accepted |
| any other role order, or 1, 3 or 5+ messages | refused | refused |
| `model_run.py follow-up` | invalid choice, exit 2 | C4-only dev prepare |
| `docs/results/*/prepared/*.json` committed at 431df73, re-serialized | 16 of 16 | 16 of 16 byte-identical |
| recorded prompt files in the main checkout re-serialized (see below) | 116 of 116 | 116 of 116 byte-identical |
| tests collected in the test image | 1,172 | 1,247 |
| smokes prepared from the 2026-09-26 runner summary | none | 9, all with two items |

The 116 are the 52 files in `docs/results/*/prepared/` on bakeoff-results (16
of them the committed files above, the same bytes at the same paths) and the 64
under the ignored `artifacts/model-eval/`, raw run copies included. 84 belong to
the bake-off (40 published, 44 raw) and 32 to the earlier 2026-09-21, 2026-09-23
and test sets (12 and 20). They hold only 14 distinct contents: the ten
bake-off passes share one prompt set, and each raw run repeats its prepare
directory's. Recounted on 2026-09-27 with the code of 431df73 and of this
branch; an earlier count of 132 added the worktree's copies of the 16 committed
files a second time.

`FOLLOW_UP_TEXT` is the note's user turn, 81 ASCII bytes, SHA-256 prefix
`d903bc2e346b`, pinned by a test. `follow_up_prompt` appends the counted
answer verbatim and that text; all four messages share the 64 KiB budget.

## The smokes prepared

`prepare` read the runner summary and each counted pass's raw run directory
with publish's own checks, and checked each config file against the pass's
manifest. Items are the first two dev C4 items in prepare order whose counted
answer completed with finish_reason stop and parses as ready. The command,
from this worktree at `.worktrees/repair-multiturn` in the main checkout, is:

```sh
uv run --frozen python scripts/two_turn_smoke.py prepare \
  --summary ../../artifacts/bakeoff/summary-2026-09-26.json
```

That is the bake-off runner's own summary, the only copy with the raw runs
beside it, since its `prepare_dir` is relative to the checkout that ran the
bake-off. `prepare` refuses a summary anywhere but
`<checkout>/artifacts/bakeoff/`, such as the committed copy in
`evidence/bakeoff/`, and one of another shape, before it writes anything.

| Smoke run id | Items | Prompt bytes | Worst case, 6 attempts (USD) |
| --- | --- | --- | ---: |
| dev-qwen3-32b-rs-2026-09-26 (anchor, informational) | mei-0001, mei-0002 | 5,689, 5,679 | 0.0062 |
| dev-qwen3.5-9b-rs-2026-09-26 | mei-0001, mei-0003 | 5,689, 5,787 | 0.0054 |
| dev-ministral-8b-2512-rs-2026-09-26 | mei-0001, mei-0002 | 5,797, 6,026 | 0.0081 |
| dev-granite-4.2-8b-rs-2026-09-26 | mei-0001, mei-0003 | 5,689, 5,780 | 0.0052 |
| dev-qwen3.5-122b-a10b-rs-2026-09-26 | mei-0001, mei-0002 | 5,689, 5,679 | 0.0531 |
| dev-nemotron-3-super-120b-a12b-rs-2026-09-26 | mei-0001, mei-0002 | 5,677, 5,787 | 0.0079 |
| dev-deepseek-v4-pro-0813-rs-2026-09-26 | mei-0001, mei-0002 | 5,394, 5,369 | 0.0745 |
| dev-glm-5.2-rs-2026-09-26 | mei-0001, mei-0002 | 5,478, 5,544 | 0.0698 |
| dev-kimi-k2.6-rs-2026-09-26 | mei-0001, mei-0002 | 5,483, 5,611 | 0.0685 |

qwen3.5-9b and granite-4.2-8b answered mei-0002 with needs_clarification, so
it is passed over. Every worst case is under the 0.20 USD cap.

## How a run is read

`scripts/two_turn_smoke.py judge`, and `run` between calls, read each run in
this order. Settings, prices, host, prompts or cap other than the counted
pass's owe a re-run. Then a model failure fails the smoke: a reply that shows
reasoning (any model), a completed reply that does not stop or parse, or a
final error or refusal. Then a harness failure owes a re-run: HTTP 401, 402 or
403, a budget stop, or an item with no completed reply only through transient
failures. A pending item owes a resume. A complete run passes unless a model
sent a switch reports no reasoning-token count. A model failure is final even
beside a harness failure, so no re-run can replace an observed failure.
Re-runs are `-rs2`, `-rs3` and so on before the prepare's date.

Each run also records what served it against the counted pass's model and
pinned route, by `run_store.served_values`, the rule scoring publishes as
`provider_changed` and `served_model_changed`: `providers`,
`provider_changed`, `served_models` and `model_changed`, per run and for the
smoke in its verdict file, and each item records its `response_model`. The
summary line prints `served <providers>`, then `PROVIDER CHANGED` or `MODEL
CHANGED` when one is set. The owner ruled on 2026-09-27 that these are flags
only: a smoke served by another provider or model is read like any other, its
verdict does not change, and the bake-off note is not amended.

## Readings the owner confirmed

The owner confirmed these five readings of the bake-off note's smoke rule on
2026-09-27. They read the [note](model-bakeoff.md); they do not amend it, and
neither it nor `docs/protocol.md` changes. `scripts/two_turn_smoke.py`
implements each as stated, and a test in `tests/test_two_turn_smoke.py` fails
if it is broken.

1. A run whose settings, prices, host, prompts or cap differ from the counted
   pass's is void and owes a re-run under a new run id, whatever its replies
   show (`_config_problems`; `test_harness_and_operator_failures_owe_a_re_run`).
   The batch also voids a run whose call options are not the registered
   `--max-attempts 3` and `--min-interval-seconds 1.0`.
2. An observed model failure fails the smoke even when the other item met a
   harness failure (`_rule`;
   `test_a_model_failure_is_final_beside_a_harness_failure` and
   `test_a_model_failure_is_final_beside_an_account_refusal`).
3. `client_error`, `redirect_rejected`, `response_too_large` and
   `empty_content` are final errors that fail the smoke, not harness failures
   (`_failed`, by the call step's own retry classes;
   `test_each_model_failure_fails_the_smoke`).
4. Reasoning is checked over every recorded attempt, not only each item's
   counted one (`_rule`;
   `test_reasoning_on_an_attempt_that_is_not_counted_fails`).
5. `run` makes one new run per smoke per execution, and a smoke may be re-run
   up to `-rs9` without a further ruling (`drive`, `run_ids`;
   `test_a_budget_stop_owes_a_re_run_and_the_batch_goes_on` and
   `test_smoke_run_ids_fit_the_result_names`). With `-rs9` used, the batch
   stops for the owner.

## Decision

Keep. The owner runs one command from this worktree; the key is not needed
before it, and the run with the key unset stopped at `api_key_missing` for
all nine calls with nothing sent.

## Limits

- `generation.py` and `model_run.py` are prepare-hashed: the branch merges
  only after the last baseline test request, and until the prompt sets
  awaiting a call have their runs, the host test on them fails here.
- CI skips that host test,
  `test_frozen_prompts_awaiting_a_call_match_the_model_side_code`: the test
  image has no `docs/` tree, so the suite skips it, and this branch's CI has
  no step that runs it with `docs/` mounted. CI here would pass a merge of
  this branch into main. What stops the calls is the call step's own
  `prepare_code_mismatch`, before any request, and reverting `generation.py`
  and `model_run.py` restores them with no re-freeze. The CI step added on
  bakeoff-results (04fa035) runs the test with `docs/` mounted and fails on a
  merge of this branch; it guards main once that branch lands.
- Scoring rebuilds first turns only, so it refuses a second-turn prompt set
  (`prompt_mismatch`) until repair scoring exists; smoke runs are evidence.
- `judge` rebuilds prompts from the raw source runs the plan names, so it
  needs those directories, or byte-identical ones, to stay where they are.
  A source run that is missing, edited or otherwise refused by `follow-up`
  makes that smoke unjudgeable (`source_refused_<code>`, exit 2), never a
  pass or a fail; so does a smoke prepared without ready answers whose source
  now has them. `run` does not rebuild the sources before paying: its prompts
  are the prepared ones, pinned by `prepare_sha256`.
- After a commit that changes any of the 12 prepare-hashed files, a smoke
  still owed a call would stop at `prepare_code_mismatch`. `run --dry-run`
  and `run` refuse it first (exit 2, nothing started) and say what to do:
  with no `runs/` directory under any smoke, remove `artifacts/two-turn-smoke`
  and run `prepare` again, and the smoke ids then carry that day's date; with
  one, delete nothing and restore the files to the revision the prompts were
  prepared at. The maintainer does this before handing over. The final free
  check is still the keyless `run`, which makes every due call once with the
  key withheld; `--dry-run` starts no call step.
- Rule 6's reserve smoke: once every run-gate survivor of a slot has failed
  its smoke, the owner runs `scripts/dev_bakeoff.py --only reserve-<slot>
  --after-smoke-failures` from the main checkout, which holds the bake-off's
  runs and the unchanged hashed files, then from this worktree
  `scripts/two_turn_smoke.py prepare --reserve <slot> --summary <main
  checkout>/artifacts/bakeoff/summary-<date>.json` and `run`. `prepare
  --reserve` refuses unless every ranked smoke of the slot reads `fail` as
  `judge` reads it and the reserve passes the run gates in that summary. It
  appends one smoke named after that day's date and records the summary's
  path and digest in `plan.json`; the judged smokes, their runs and verdicts
  stay as they are. Never prepare every survivor again into another out dir:
  that would re-send the judged smokes and give a candidate that failed its
  smoke a second one.
- A result name allows 32 characters between `dev-` and the date. A smoke id,
  `dev-<middle>-rs-<prepare date>` with `<middle>` the counted pass's
  `<model>[-fb][-r2]`, therefore needs a middle of at most 29 characters, and
  its re-runs `-rs2` to `-rs9` one of at most 28. Of the listed passes,
  nemotron's `-fb` and `-r2` (29) get a smoke id but no re-run id, so a harness
  failure there stops the batch for the owner, and nemotron's `-fb-r2` (32)
  and the mid reserve's `-r2` (30) get no smoke id, so `prepare` refuses them
  before writing anything. The 2026-09-26 summary counts none of them; only the
  mid reserve's `-r2` can still arise, if that reserve runs by rule 6 and its
  first pass is an outage. A test checks the rule on every listed pass.
- Do not press Ctrl-C while a smoke request is in flight: that request may be
  billed but not recorded. The call step shares the console, so the interrupt
  can end it between the reply and its attempt-log line; the request is then
  missing from the attempt log, `requests_sent` and the charged upper bound,
  and the next `run` sends it again. The owner ruled on 2026-09-27 to keep the
  bake-off runner's invoker with this rule rather than isolate the call step.
  After an interrupt the batch prints `INTERRUPTED` and logs an `interrupted`
  step. A call step still running after the wait keeps
  `artifacts/two-turn-smoke/.lock`; delete it once that process has exited.
