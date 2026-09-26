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
| committed `docs/results/*/prepared/*.json` re-serialized | 16 of 16 | 16 of 16 byte-identical |
| published and raw bake-off prompt files re-serialized | written by it | 116 of 116 byte-identical |
| tests collected in the test image | 1,172 | 1,247 |
| smokes prepared from the 2026-09-26 runner summary | none | 9, all with two items |

`FOLLOW_UP_TEXT` is the note's user turn, 81 ASCII bytes, SHA-256 prefix
`d903bc2e346b`, pinned by a test. `follow_up_prompt` appends the counted
answer verbatim and that text; all four messages share the 64 KiB budget.

## The smokes prepared

`prepare` read the runner summary and each counted pass's raw run directory
with publish's own checks, and checked each config file against the pass's
manifest. Items are the first two dev C4 items in prepare order whose counted
answer completed with finish_reason stop and parses as ready.

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

## Decision

Keep. The owner runs one command from this worktree; the key is not needed
before it, and the run with the key unset stopped at `api_key_missing` for
all nine calls with nothing sent.

## Limits

- `generation.py` and `model_run.py` are prepare-hashed: the branch merges
  only after the last baseline test request, and until the prompt sets
  awaiting a call have their runs, the host test on them fails here.
- Scoring rebuilds first turns only, so it refuses a second-turn prompt set
  (`prompt_mismatch`) until repair scoring exists; smoke runs are evidence.
- `judge` rebuilds prompts from the raw source runs the plan names, so it
  needs those directories, or byte-identical ones, to stay where they are.
- A fallback nemotron smoke's re-run id would exceed 32 characters; no
  survivor qualified through a fallback.
