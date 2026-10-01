# Repair round: registration

## Question

Does one feedback round turn a silent-wrong or invalid C4 answer into a
strong-exact one, and does a structured counterexample from the unscored
feedback probe do better than a bare "your filter was incorrect" turn or a
plain resample of the first turn? The protocol's
[Repair section](../protocol.md#repair) and its repair@1 bullet hold the
binding rules. This note holds the run ids, schemas, caps and commands, plus
the measured before and after. It was written on 2026-10-01, before any test
request and before any repair request. Where this note restates a protocol
rule, the protocol wins.

## Owner decisions, 2026-10-01

The owner took four decisions on 2026-10-01, each as the repair design of that
day recommended:

- **OD1, when to register.** The whole Repair text (arms, card, run ids,
  settings and caps) is registered in the registration PR, before pass A.
  The alternatives were to register only the run ids, settings and caps now
  and the card text later, or to run dev first and register after it.
- **OD2, card content.** A card holds up to three feedback-probe frames
  where the answer and the labels disagree. Each frame carries 13 header
  fields, with raw addresses and ports. An answer that does not compile gets
  an error card naming its own refused field. Three alternatives were
  rejected: masked addresses, membership facts only, and the answer's own
  predicate truth values (which would execute gold leaves).
- **OD3, what the resample is.** Every repaired pass gets a separate `-res`
  run, the anchor's included. It re-sends the frozen first turn of each
  triggered item at temperature 0. Pass B stays the unpooled A/A rerun and is
  never repaired.
- **OD4, when the card code must be fixed.** Test passes may be sent once
  the registration merges. No test run is scored until the `repair-cards`
  branch, which holds the card code, is merged. Scoring a run means running
  `dfilterforge score` over it, or putting a `scored/` directory under its
  `docs/results` directory.

## What the protocol registers

This section is a reading aid. The protocol text is the rule.

**Triggered item.** A triggered item is a C4 item whose outcome in the
repaired pass's `scored/outcomes.jsonl` is `silent_wrong` or `invalid`,
whatever its finish reason. Once a correction exists, the outcome comes from
`scored-original/` instead.
- Both outcomes imply a ready answer.
- Non-ready gold can never trigger, because a ready answer to it is
  `false_ready`.
- C1 to C3 never trigger.

**Arms.** Every triggered item is sent once in each arm. The arms differ only
by the card.

| Arm | Run tag | Messages sent | Last user turn |
| --- | --- | --- | --- |
| resample | `-res` | system and user: the pass's C4 prompt byte for byte | the original request |
| bare | `-bare` | system, user, the counted answer verbatim as the assistant turn, then a user turn | `FOLLOW_UP_TEXT`: 81 bytes, SHA-256 prefix `d903bc2e346b`, the smoke's turn |
| counterexample | `-cx` | as bare | `FOLLOW_UP_TEXT`, then `"\nCOUNTEREXAMPLE_JSON\n"` (21 bytes), then the card; `FOLLOW_UP_TEXT` alone when the item has no card |

Each arm run sends its pass's config unchanged: model slug, provider order,
reasoning switch, temperature 0, seed 17, `max_output_tokens` 2048, JSON
mode, a 120 s timeout, `require_parameters` true and `allow_fallbacks` false.
It also sends `--gate-first --max-attempts 3 --min-interval-seconds 1.0`. A
model's arm runs go in this order: resample, then bare, then counterexample,
each after the one before is complete.

**Card.** A card is built offline, in the no-network lab container, from the
split's feedback probe alone: dev semantic-29, test semantic-35.

1. **Check the labels (test only).** The recomputed feedback label digest
   must equal the freeze record's `feedback_labels` (`c0b30949787e`), or the
   build refuses.
2. **Run the answer.** The answer IR, which must equal the committed
   `scored/intents/C4/<item>.json`, runs through the unchanged `evaluate_live`
   on the item's feedback spec. Only the probe's `reference_only` (missed)
   and `candidate_only` (wrongly selected) frames are kept.
3. **Choose the card.**
   - **Error card.** A run that raises a code making an answer invalid gives
     `{"error": code}`. For a catalog or compile code it adds `field`: the
     field of the first predicate, in reading order, that raises the same
     code when bound and compiled alone. `field` is omitted if it fails the
     field-name grammar or is over 128 bytes. A resource code counts against
     the answer only if the reference reruns clean. Any other error stops the
     build.
   - **No card.** The probe cannot separate the answer.
   - **Frames card.** In every other case. It lists at most three
     disagreeing frames, picked from the missed list M and the wrongly
     selected list X.
     - The order is M[0], X[0], M[1], X[1] and so on.
     - A frame is skipped when its entry, with the frame number removed and
       every port from 41000 to 51254 replaced by one constant, equals an
       entry already chosen.
     - Each frame shows `frame`, `answer_matched`, `should_match` and these
       13 fields: `ip.src`, `ip.dst`, `ip.ttl`, `ip.dsfield.ecn`,
       `tcp.srcport`, `tcp.dstport`, `tcp.flags` (the set flags' names in the
       order FIN, SYN, RST, PSH, ACK, URG, ECE, CWR, AE), `tcp.len`,
       `udp.srcport`, `udp.dstport`, `dns.flags.response`, `dns.flags.rcode`
       (responses only) and `dns.qry.type`.
     - The field values come from a bounded decoder. It reads classic
       little-endian PCAP with Ethernet II and IPv4 only, and only after the
       capture's SHA-256 matches the spec.
     - tshark 4.6.8 confirms each frame with one filter, built from the
       decoded typed values only. The filter is passed as argv, with no
       shell and no model text in it. If any value is not confirmed, the
       build stops.
4. **Encode it.** A card is canonical JSON (sorted keys, no whitespace) of at
   most 1,024 bytes. Over the cap, whole frames are dropped from the end, and
   at least one is kept.

A leak test in the card code fails, rather than warns, if a card ever shows
any of these:
- a gold filter, a canonical leaf with an operator, or a case, item or probe
  id;
- a recipe or witness name, a label, a count or a payload byte.

**Schemas** are pydantic models that reject extra keys. Their dotted keys are
the field names above.

```text
FrameFactV1:
  frame: int 1..100000; answer_matched: bool; should_match: bool  (answer_matched != should_match)
  optional: ip.src, ip.dst (IPv4 dotted quad); ip.ttl 0..255; ip.dsfield.ecn 0..3;
            tcp.srcport, tcp.dstport, tcp.len, udp.srcport, udp.dstport 0..65535;
            tcp.flags: tuple of the 9 names, unique, in fixed order;
            dns.flags.response: bool; dns.flags.rcode 0..15 (only if response true); dns.qry.type 0..65535
  invariants: never both tcp.* and udp.*
FramesCardV1:  {frames: tuple[FrameFactV1, 1..3]}
ErrorCardV1:   {error: one of the codes that make an answer invalid, field?: str}

RepairPlanV1 (repair-plan/1.0, docs/results/<pass>/repair/plan.json, canonical JSON, no timestamp):
  schema_version: "repair-plan/1.0"
  split: dev | test; base_run: str (result-name pattern)
  base_run_manifest_sha256, base_outcomes_sha256, feedback_labels_sha256: sha256 hex
  feedback_probe: semantic-29 | semantic-35
  items: tuple[RepairItemV1, ...] in base prepare order (may be empty: no arm runs, repair@1 null)
RepairItemV1:
  item_id: ^mei-[0-9]{4}$; base_outcome: silent_wrong | invalid
  card_kind: frames | error | none; card: str | null  (null iff none; a canonical JSON object <= 1,024 B)
```

The plan is the only gold-derived input that preparation reads. It carries
only the trigger set and the leak-tested cards. The closure test that keeps
`dfilterforge.model_feedback` out of `scripts/model_run.py` today will also
keep the card and plan modules out.

**Scoring.** Arm runs are ordinary C4 runs over the triggered items.
- `dfilterforge score` scores them. To do so, it rebuilds the first two
  messages of a four-message prompt.
- `dfilterforge repair --check` checks the rest of each arm prompt against
  the pass and the plan. It also checks the item set, the condition, the
  split, and the settings, prices, host, attempts and pacing.
- An item is repaired only if its arm outcome is `strong_exact`. A copied
  host address or ephemeral port is therefore a `shortcut`.

repair@1 uses these per-case shares, over the repaired pass's ready C4
cases:
- T_c is the share of the case's items in the plan.
- R_c is the share in the plan whose arm outcome is strong exact.

repair@1 is sum R_c over sum T_c, on the pass's ready-case bootstrap
vectors. This is the estimator the protocol uses for silent-wrong over
compile-valid items. The same estimator gives the silent-wrong and invalid
strata. T comes from the plan, so a later gold correction cannot move a
denominator.

**Comparisons.**
- Per model, three pairs are compared by discordant cases:
  counterexample against bare (primary), counterexample against resample,
  and bare against resample. Fewer than 10 discordant cases is inconclusive.
  The difference is repair@1(a) - repair@1(b), on the same vectors.
- The same three pairs pooled over the four models are secondary. There,
  each drawn case brings every model's cells.

**Diagnostics** are reported but never count as outcomes:
- transitions from pass outcome to arm outcome;
- `answer_unchanged`, an arm answer equal to the counted one;
- card kinds;
- `card_value_reuse`: a strong-exact or shortcut counterexample-arm answer
  holding a value the card showed for that field;
- spend and latency per arm.

**Outputs.**
- Each repaired pass's round: `repair-summary/1.0` in
  `docs/results/<pass>/repair/summary.{json,md}`.
- The pooled comparison: `repair-pool/1.0` in
  `docs/results/repair-pool/<split>.{json,md}`.
- Each arm run also gets an ordinary `scored/summary.json`. That file is a
  scoring record, never a reported number.

## Repaired passes and arm run ids

**Dev passes.** These are the four models' counted passes from the bake-off.
Their triggered items were counted on 2026-10-01 from each pass's committed
`scored/outcomes.jsonl`.

| Pass | Slot | Triggered items | Cases | Silent-wrong / invalid | Invalid codes |
| --- | --- | ---: | ---: | --- | --- |
| [`dev-qwen3-32b-2026-09-26`](../results/dev-qwen3-32b-2026-09-26/scored/summary.json) | anchor | 10 | 6 | 6 / 4 | 3 unknown_field, 1 type_mismatch |
| [`dev-qwen3.5-9b-2026-09-26`](../results/dev-qwen3.5-9b-2026-09-26/scored/summary.json) | 8B | 7 | 6 | 5 / 2 | 2 unknown_field |
| [`dev-qwen3.5-122b-a10b-2026-09-26`](../results/dev-qwen3.5-122b-a10b-2026-09-26/scored/summary.json) | 120B | 8 | 7 | 7 / 1 | 1 unknown_field |
| [`dev-deepseek-v4-pro-0813-2026-09-26`](../results/dev-deepseek-v4-pro-0813-2026-09-26/scored/summary.json) | frontier | 11 | 7 | 9 / 2 | 2 unknown_field |
| Total | | 36 | 26 | 27 / 9 | |

- Each pass has 24 ready C4 items.
- All 36 triggered items have ready gold and finished with `stop`.
- The dev round is therefore 108 requests: 36 items in each of 3 arms.

**Test passes.** These are the runs the [test-run registry](test-runs.md)
records as `published`:
- the run for `aa_pass_a`;
- for each slot, its `winner_<slot>` run, or else its `fallback_<slot>` run.
  An outage re-run counts.

`aa_pass_b` is never repaired. Test trigger counts will exist only once
those passes are scored, which OD4 holds back until `repair-cards` merges.

**Arm run ids for the planned passes:**

| Repaired pass | resample | bare | counterexample |
| --- | --- | --- | --- |
| `dev-qwen3-32b-2026-09-26` | `dev-qwen3-32b-res-2026-09-26` | `dev-qwen3-32b-bare-2026-09-26` | `dev-qwen3-32b-cx-2026-09-26` |
| `dev-qwen3.5-9b-2026-09-26` | `dev-qwen3.5-9b-res-2026-09-26` | `dev-qwen3.5-9b-bare-2026-09-26` | `dev-qwen3.5-9b-cx-2026-09-26` |
| `dev-qwen3.5-122b-a10b-2026-09-26` | `dev-qwen3.5-122b-a10b-res-2026-09-26` | `dev-qwen3.5-122b-a10b-bare-2026-09-26` | `dev-qwen3.5-122b-a10b-cx-2026-09-26` |
| `dev-deepseek-v4-pro-0813-2026-09-26` | `dev-deepseek-v4-pro-0813-res-2026-09-26` | `dev-deepseek-v4-pro-0813-bare-2026-09-26` | `dev-deepseek-v4-pro-0813-cx-2026-09-26` |
| `test-qwen3-32b-2026-09-26` | `test-qwen3-32b-res-2026-09-26` | `test-qwen3-32b-bare-2026-09-26` | `test-qwen3-32b-cx-2026-09-26` |
| `test-qwen3.5-9b-2026-09-26` | `test-qwen3.5-9b-res-2026-09-26` | `test-qwen3.5-9b-bare-2026-09-26` | `test-qwen3.5-9b-cx-2026-09-26` |
| `test-qwen3.5-122b-a10b-2026-09-26` | `test-qwen3.5-122b-a10b-res-2026-09-26` | `test-qwen3.5-122b-a10b-bare-2026-09-26` | `test-qwen3.5-122b-a10b-cx-2026-09-26` |
| `test-deepseek-v4-pro-0813-2026-09-26` | `test-deepseek-v4-pro-0813-res-2026-09-26` | `test-deepseek-v4-pro-0813-bare-2026-09-26` | `test-deepseek-v4-pro-0813-cx-2026-09-26` |

**Fallbacks and re-runs.**
- A fallback or outage re-run that becomes a slot's counted test pass gets
  the same three tags, for example `test-deepseek-v4-pro-0813-fb-cx-2026-09-26`.
- An arm's outage re-run adds `-r2` after the tag, for example
  `test-qwen3-32b-cx-r2-2026-09-26`.
- 18 runs can be repaired: the four dev passes and the 14 registry rows with
  a repaired role. With and without `-r2`, they give 108 arm run ids.

106 of those 108 ids fit the result-name pattern. The longest middle,
`deepseek-v4-pro-0813-fb-r2-cx-r2`, is exactly at the 32-character limit.
Two ids do not fit:
- `test-deepseek-v4-pro-0813-fb-r2-res-r2-2026-09-26` (middle of 33
  characters);
- `test-deepseek-v4-pro-0813-fb-r2-bare-r2-2026-09-26` (middle of 34).

Both need a chain of four failures, each one in turn:
1. the frontier pass stops at the gate on DeepInfra;
2. its nextbit fallback is an outage;
3. that fallback's re-run becomes the repaired pass;
4. its resample or bare arm run is an outage.

The call refuses an id that does not fit (`run_id_invalid`), so such an arm
cannot be re-run and is reported not run. `tests/test_hosted_test_runs.py` derives every id
from the registry and the bake-off ruling and checks this.

## Caps and worst cases

Cap rule: the call stops before any request whose pre-request bound, added to
what is already spent, would exceed `--max-usd` (`_worst_case_micro_usd` in
`scripts/model_run.py`).
- The bound charges the prompt bytes plus 64 as input tokens, and 2,048
  output tokens, at the config's prices.
- **Largest dev prompt.** This column takes the largest prompt over each dev
  pass's triggered items: first-turn prompt, plus counted answer, plus the
  81-byte turn, the 21-byte line and a full 1,024-byte card.
- **At 64 KiB.** This column takes the 64 KiB prompt budget, which no
  prompt can exceed.
- Fallback configs apply to test only, because the dev passes are fixed.

| Slot | Config | Dev cap | Test cap | Worst request, largest dev prompt | Worst request at 64 KiB |
| --- | --- | ---: | ---: | ---: | ---: |
| frontier | `deepseek-v4-pro-0813_deepinfra_enabled-false` | 0.20 | 0.50 | 0.014263 (6,811 B) | 0.090605 |
| frontier fallback | `deepseek-v4-pro-0813_nextbit_enabled-false` | | 0.50 | 0.013749 | 0.075762 |
| 120B | `qwen3.5-122b-a10b_novita_enabled-false` | 0.10 | 0.30 | 0.009566 (7,467 B) | 0.032794 |
| 120B fallback | `qwen3.5-122b-a10b_atlas-cloud_enabled-false` | | 0.30 | 0.007175 | 0.024596 |
| 8B | `qwen3.5-9b_deepinfra_enabled-false` | 0.05 | 0.05 | 0.001071 (7,568 B) | 0.006868 |
| 8B fallback | `qwen3.5-9b_parasail_enabled-false` | | 0.05 | 0.001276 | 0.007072 |
| anchor | `qwen3-32b_deepinfra_enabled-false` | 0.05 | 0.05 | 0.001192 (7,667 B) | 0.005822 |

- **Headroom.** Every cap covers at least two requests at the 64 KiB bound.
  The tightest is the dev frontier cap: 0.20 USD against 0.181 USD.
- **Total.** The 24 arm runs of the planned passes hold 3.90 USD of caps:
  1.20 on dev and 2.70 on test.
- **Against the plan's 12 USD.** The committed runs record at most 0.940
  USD. With the registry's runs 1 to 5 at their caps, the total is at most
  3.29 USD, and the arm caps bring it to 7.19 USD.
- **Raising a cap.** A budget stop is resumed only under a raised cap,
  committed first.

The repair design estimated the expected spend from `cost.py`. These figures
were not re-run, and they are lower bounds with no retries:
- dev: about 0.126 USD over 108 requests (0.0043 for the 8B pass, 0.036 for
  120B, 0.081 for frontier and 0.0052 for the anchor);
- test: about 0.42 USD over about 360 requests, projected from the dev trigger
  rates. If all 80 ready C4 items triggered, it would be 1.03 USD.

## Order

1. **Registration.** This registration merges before the first test request.
2. **Baselines.** The baseline test passes run in the
   [registry's](test-runs.md) order, on main. The 12 prepare-hashed files stay
   unchanged until the last baseline request.
3. **`repair-cards`.** This branch touches no hashed file. It carries:
   - the codes that make an answer invalid, named once;
   - the frame facts and the card, with the leak test;
   - the plan writer, `dfilterforge repair`;
   - the A/A pair report;
   - ablation 008 on counterexample facts;
   - the four dev plans, committed before any repair request.

   No test run is scored before it merges (OD4).
4. **`repair-arms`.** This branch starts from `repair-multiturn` at 281b2ce
   and is never rebased. Its only hashed edits are `generation.py` (a second
   turn may carry a card) and `scripts/model_run.py` (`follow-up --plan PATH
   --arm ARM`). It also lets scoring rebuild the first turn of a
   four-message prompt, and lets `repair` write and check round summaries.
   The dev round runs from that worktree, alongside the baselines: prepare,
   call, publish, score, then `repair`. Dev prompt sets need no admission.
5. **After the last baseline request, on main.**
   1. Commit the four test plans.
   2. Merge `repair-arms` with a merge commit.
   3. Seed the 12 test arm prompt sets in `docs/results/<arm run id>/`.
   4. Admit their digests in a commit of their own. That makes 13 of the
      record's 32 admitted prepares.
   5. Send, publish and score the test arm runs, then write the round and
      pooled summaries.
   6. Write the locked test result.

   After the merge, any first-turn test pass (a late baseline, a fallback or
   an outage re-run) stops at `prepare_code_mismatch`. So every registry row
   must be final before the merge.

## Commands to come

`dfilterforge repair`, `dfilterforge repair-pool` and the `--plan` and
`--arm` options of `follow-up` do not exist yet; the two branches above add
them. Run the commands from Git Bash at the repository root with
`MSYS_NO_PATHCONV=1`. The lab container sees `docs/results` at
`/workspace/results`.

```text
# 1 plan (lab, offline, no key); once all three arms are published and scored it also writes the summary
docker compose --profile pilot run --rm lab repair --run-dir /workspace/results/$PASS --code-revision $REV [--check]
# 2 one prepare per arm (host, no key; reads no gold but the plan)
uv run --frozen python scripts/model_run.py follow-up --from-run docs/results/$PASS \
  --plan docs/results/$PASS/repair/plan.json --arm $ARM --output-dir artifacts/repair/$ARM_RUN --source-revision $REV
# 3 test only: seed docs/results/$ARM_RUN with prepare.json and prepared/ (commit), then admit the digest (own commit)
# 4 owner, key set: the repaired pass's config and the slot's cap; a resume adds --resume with the same options
uv run --frozen python scripts/model_run.py call --prepare-dir artifacts/repair/$ARM_RUN --run-id $ARM_RUN \
  --config docs/decisions/evidence/bakeoff/configs/$CONFIG.json --gate-first --max-attempts 3 \
  --min-interval-seconds 1.0 --max-usd $CAP --source-revision $REV
uv run --frozen python scripts/model_run.py publish --run-dir artifacts/repair/$ARM_RUN/runs/$ARM_RUN --output docs/results/$ARM_RUN
docker compose --profile pilot run --rm lab score --run-dir /workspace/results/$ARM_RUN --code-revision $REV
# 5 check the round, then pool a split's four rounds
docker compose --profile pilot run --rm lab repair --run-dir /workspace/results/$PASS --code-revision $REV --check
docker compose --profile pilot run --rm lab repair-pool --split $SPLIT --base ... --code-revision $REV [--check]
```

The variables:
- `$ARM` is `resample`, `bare` or `counterexample`.
- `$ARM_RUN` is the arm run id from the table above.
- `$CONFIG` is the repaired pass's config.

No command carries a display filter or model text. CI then re-checks every
`repair/plan.json` and every `repair-pool/*.json` with `--check`, beside its
existing re-score loop.

## Before and after

Before, measured 2026-10-01:
- **No repair request has been sent.**
- **Second turns exist only as the two-turn smoke's bare turn.** Eight
  smokes gave 16 replies. Each completed with finish_reason stop and parsed
  under C4; kimi-k2.6's smoke was not measured
  ([bake-off note](model-bakeoff.md), "Smoke verdicts and slot winners";
  `evidence/bakeoff/smoke/`).
- **No summary has a repair number.** Every committed `scored/summary.json`
  records `not_measured.repair_at_1` as `not_run`.
- **Scoring refuses second turns.** It rebuilds first turns only, so it
  refuses a second-turn prompt set (`prompt_mismatch`).
- **Triggered items.** The dev passes hold the 36 triggered items above.

After: not measured. The dev round fills it in: per model and arm, the
repaired items, repair@1 with its strata, the transitions, `answer_unchanged`,
`card_value_reuse` and spend, each linked to its `repair/summary.json`.

## Receipts so far

- **The four dev passes.** Their `scored/summary.json` are linked in the
  table above.
- **Feedback labels.**
  [`evidence/test-freeze-gate.json`](evidence/test-freeze-gate.json) records
  them in `measurement_identity.feedback_labels_sha256`: dev `be0c91824bb5`,
  test `c0b30949787e`. The test digest is the freeze record's
  `feedback_labels`, and a test card build must reproduce it.
- **The two-turn smoke.** [`evidence/bakeoff/smoke/`](evidence/bakeoff/smoke/)
  holds the plan, summary and verdicts, and `evidence/bakeoff/<run id>/` holds
  each smoke run's manifest and attempt log.

## Not measured yet

- **Card figures.** These are measurements from the repair design's scratch
  scripts, not re-run here:
  - tshark confirmed 62 of 62 dev and 63 of 63 test feedback frames, at
    about 3.8 s per probe;
  - the 13 fields determine the feedback labels of 52 of 52 ready cases,
    against 37 without addresses and 9 with membership facts only;
  - the largest frame entry is about 333 B, so three frames come to about
    1,014 B.
- **Expected spend.** The figures in Caps above are design estimates.
- **Test trigger counts.**
- **Repair behaviour.** How hosted models answer a repair turn, repair@1,
  and the arm comparisons.
- **Ablation 008** on counterexample facts: Full (decode plus tshark
  confirmation) against Simplified (tshark membership facts only).
- **Running cost.** The runtime of the per-leaf `field` lookup, and the CI
  time the round adds.

## Limits

- **Comparisons will mostly be inconclusive.** Per-model comparisons on dev
  are inconclusive by construction: each model has 6 or 7 triggered cases,
  fewer than the 10 discordant cases a reading needs. They are likely
  inconclusive on test too. The pooled comparison is the realistic chance of
  a conclusive read.
- **The resample may repeat itself.** At temperature 0 it may return the
  counted answer; `answer_unchanged` shows this.
- **Card values may be reused.** A value that no shortcut rule covers, such
  as `tcp.len` or `ip.ttl`, may be copied from the card and still pass.
  `card_value_reuse` reports this. Copied addresses and ephemeral ports are
  already shortcuts.
- **Provider drift.** A pass and its arm runs are days apart. The served
  provider and model are recorded, not controlled.
- **Two re-run ids do not fit.** Two arm re-run ids are too long for the
  result-name pattern; see the run ids above.
