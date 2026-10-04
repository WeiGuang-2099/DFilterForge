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

## Owner decisions, 2026-10-04

The owner took one decision on 2026-10-04, OD5. The maintainer took three
defaults with it, OD6 to OD8, which the owner was told of. They are kept apart
below: a default stays one until the owner confirms it. The protocol's Repair
section registers the move (its paragraph amended 2026-10-04), and
[`evidence/repair-arms/ruling-2026-10-04.json`](evidence/repair-arms/ruling-2026-10-04.json)
(schema `repair-arms-ruling/1.0`) holds the four decisions, the moved ids and
the evidence figures, which `tests/test_repair_arms.py` recounts from the
committed evidence.

- **OD5, by the owner: the frontier arms move to NextBit.** The frontier
  slot's repair arms move from DeepInfra to NextBit, using the committed
  config `deepseek-v4-pro-0813_nextbit_enabled-false`, for every frontier arm
  run still to be sent: the test round's, and the dev round's if it is
  re-run, which is OD6. All other slots are unchanged, and the counted first
  turns stay the answers DeepInfra served.
  - Evidence:
    - The six DeepInfra runs, sent from bff373c. Each made 33 attempts (3
      invocations of 11 requests), 198 in all. Every attempt was HTTP 429:
      0 answers and 0 USD charged. The first attempt was sent at
      2026-10-04T02:23:26.403803Z and the last at 2026-10-04T02:41:50.888604Z.
      Each run's `run_manifest.json` and `attempts/` are in
      `evidence/repair-arms/<run id>/`.
    - The runner summary,
      [`evidence/repair-arms/summary-dev-2026-10-04.json`](evidence/repair-arms/summary-dev-2026-10-04.json).
    - The owner's single-request diagnostics,
      [`evidence/repair-arms/frontier-provider-diagnostics-2026-10-04.md`](evidence/repair-arms/frontier-provider-diagnostics-2026-10-04.md).
      Its one HTTP 429 body, from a request sent after the round, names
      `engine_overloaded` and `upstream_provider_shared_pool`; the runs'
      own records keep only the error code, 429, and no served provider.
      The later HTTP 200 was still served
      from DeepInfra's shared pool (`is_byok` false). The NextBit request,
      with seed 17, JSON mode and `require_parameters` true, returned HTTP
      200 with 0 reasoning tokens, billed at the committed prices.
    - The test baseline's 776 HTTP 429 in all, 754 of them before an
      item's last attempt, the figure the
      [locked test result](../results/locked-test-v1.md) states.
  - The config, each fact cited from its own table:
    - It was committed in de05cad on 2026-09-26; its SHA-256 prefix is
      `2942954e0c68`.
    - It differs from the DeepInfra config only in `provider_order` and
      prices: 1.056 / 3.168 against 1.3 / 2.6 USD per million (the
      [bake-off note](model-bakeoff.md), Candidates).
    - It is the registry's `fallback_frontier` config (the
      [test-run registry](test-runs.md), runs 8 and 16, baseline cap 1.25).
    - The Caps table below gives its "frontier fallback" row a test cap of
      0.50 and no dev cap.
  - The endpoint readings the owner reported on 2026-10-04 (NextBit's status,
    uptime and prices) are not a committed snapshot.
  - Rejected alternatives:
    - DeepSeek official: its endpoint lists no seed, and `require_parameters`
      is true;
    - waiting on DeepInfra: the runs record no cause, and the one later
      HTTP 429 body names a shared pool, with no bound on recovery;
    - reporting the frontier round not run.
  - Decided with 0 frontier repair answers on dev and no test repair request
    sent.
- **OD6, default taken: dev is re-run first.** The dev frontier round is
  re-run on NextBit before the test round, as new runs with the tag `nb`
  after the arm tag. The owner was told and did not object; the owner's paid
  dev command is the confirmation.
- **OD7, default taken: the outage rule stays.** On NextBit an arm run keeps
  the protocol's outage rule: one re-run from scratch, `-nb-r2` on dev and
  `-r2` on test. A second outage is not run, and no arm moves again.
- **OD8, default taken: the test ids stay.** The test frontier arms keep
  their registered ids, which no request has used.

**The ids.** The dev frontier arm runs on NextBit, each with the one outage
re-run OD7 allows:

| Arm | Run | Outage re-run |
| --- | --- | --- |
| resample | `dev-deepseek-v4-pro-0813-res-nb-2026-09-26` | `dev-deepseek-v4-pro-0813-res-nb-r2-2026-09-26` |
| bare | `dev-deepseek-v4-pro-0813-bare-nb-2026-09-26` | `dev-deepseek-v4-pro-0813-bare-nb-r2-2026-09-26` |
| counterexample | `dev-deepseek-v4-pro-0813-cx-nb-2026-09-26` | `dev-deepseek-v4-pro-0813-cx-nb-r2-2026-09-26` |

The test frontier arms keep the ids in the arm run id table below, and their
`-r2` re-runs, now sent on NextBit (OD8).

**The ruling on the six DeepInfra runs.**
`dev-deepseek-v4-pro-0813-res-2026-09-26`,
`dev-deepseek-v4-pro-0813-bare-2026-09-26`,
`dev-deepseek-v4-pro-0813-cx-2026-09-26` and their `-r2` re-runs are not run.
They are kept as evidence in `evidence/repair-arms/<run id>/`, are never
published, and are replaced by the NextBit runs above. The frontier dev
round's summary is written from the NextBit runs.

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

Amended 2026-10-04 (OD5). As registered, every arm run sends its pass's config
unchanged. deepseek/deepseek-v4-pro-0813's arm runs, on dev and on test, now
send provider order `nextbit` and its prices, 1.056 / 3.168 USD per million,
from `deepseek-v4-pro-0813_nextbit_enabled-false`. Every other setting and
call option above, and every other model's arm runs, are unchanged.

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

  Amended 2026-10-04 (OD5). As registered, each arm run is held to its
  pass's settings and prices. For a moved pass, `repair --check` holds each
  arm run to the pass's settings except the provider order, which must be
  the move's, and to the move's prices object. A moved dev run's
  `prepare.json` names its arm's registered first run (for example
  `dev-deepseek-v4-pro-0813-cx-2026-09-26`), the only name the follow-up
  step builds under; the check accepts that one name, and only for a
  registered moved run.
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

`aa_pass_b` is never repaired. The four counted test passes were scored once
`repair-cards` had merged (OD4), and their triggered items were counted on
2026-10-02 from each pass's committed `scored/outcomes.jsonl`. The four test
plans hold them, committed in b3a7d40 before any repair request. (Corrected
2026-10-02: the registered text said these counts did not exist yet.)

| Pass | Slot | Triggered items | Cases | Silent-wrong / invalid | Invalid codes |
| --- | --- | ---: | ---: | --- | --- |
| [`test-qwen3-32b-2026-09-26`](../results/test-qwen3-32b-2026-09-26/repair/plan.json) | anchor | 28 | 20 | 25 / 3 | 3 unknown_field |
| [`test-qwen3.5-9b-2026-09-26`](../results/test-qwen3.5-9b-2026-09-26/repair/plan.json) | 8B | 15 | 11 | 11 / 4 | 3 unknown_field, 1 type_mismatch |
| [`test-qwen3.5-122b-a10b-2026-09-26`](../results/test-qwen3.5-122b-a10b-2026-09-26/repair/plan.json) | 120B | 20 | 16 | 14 / 6 | 4 unknown_field, 1 type_mismatch, 1 unsupported_operator |
| [`test-deepseek-v4-pro-0813-2026-09-26`](../results/test-deepseek-v4-pro-0813-2026-09-26/repair/plan.json) | frontier | 12 | 9 | 4 / 8 | 6 unknown_field, 2 type_mismatch |
| Total | | 75 | 56 | 54 / 21 | |

- Each pass has 80 ready C4 items.
- All 75 triggered items have ready gold and finished with `stop`.
- The test round is therefore 225 requests before retries: 75 items in each
  of 3 arms.

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

Amended 2026-10-04 (OD5). As registered, the 108 ids above are every arm run
id. The move adds six dev ids outside the 108, listed under Owner decisions,
2026-10-04: each is a registered dev frontier id with `-nb` after the arm
tag. The 108 stay as registered. All six fit the result-name pattern; the
longest is `dev-deepseek-v4-pro-0813-bare-nb-r2-2026-09-26`, with a middle of
31 characters. The test frontier arms keep their registered ids.

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

Amended 2026-10-04 (OD5). As registered, fallback configs apply to test only.
The NextBit config now also carries the dev frontier arm runs, under the
frontier row's dev cap of 0.20, and the test frontier arm runs, under the
test cap of 0.50 that both frontier rows give. The table below is unchanged.
Its frontier fallback row already prices both worst requests, at the largest
dev prompt and at 64 KiB, at NextBit's prices, and each is below the frontier
row's, so the headroom bullet below holds on NextBit too.

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
- **Against the plan's 12 USD.** The committed runs record at most 0.941
  USD (0.940394). With the registry's runs 1 to 5 at their caps, the total is
  at most 3.291 USD, and the arm caps bring it to at most 7.191 USD.
- **Raising a cap.** The table above keeps the caps the protocol registers,
  and a raise never edits it. A budget stop after an answer is resumed only
  under a cap raised for that arm run alone, above its last invocation's
  `max_usd`, in a row of the raised caps table below, committed first. The
  slot's other arm runs, and an outage re-run, keep the registered cap.
  `scripts/repair_arms.py` reads each arm run's cap from its slot's row
  above, or from its own row below. It refuses a raise of a run that has no
  budget stop to resume, a raise not above the slot's cap, and a row naming
  no arm run of its split.

Raised caps, one arm run per row (none so far):

| Arm run | Raised cap |
| --- | ---: |

The repair design estimated the expected spend from `cost.py`. These figures
were not re-run, and they are lower bounds with no retries:
- dev: about 0.126 USD over 108 requests (0.0043 for the 8B pass, 0.036 for
  120B, 0.081 for frontier and 0.0052 for the anchor);
- test: about 0.42 USD over about 360 requests, projected from the dev trigger
  rates. If all 80 ready C4 items triggered, it would be 1.03 USD. The
  committed test plans superseded this design estimate: they give 225
  requests (Test passes above), and the spend estimate was not re-run for
  them.

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
   - ablation 008 on counterexample facts.

   No test run is scored before it merges (OD4).
4. **`repair-arms`.** This branch starts from `repair-multiturn` at 281b2ce
   and is never rebased. Its only hashed edits are `generation.py` (a second
   turn may carry a card) and `scripts/model_run.py` (`follow-up --plan PATH
   --arm ARM`). It also lets scoring rebuild the first turn of a
   four-message prompt, lets `repair` write and check round summaries, and
   adds the owner's batch `scripts/repair_arms.py`. It carries the four dev
   plans (5eb2bae) and the four test plans (b3a7d40), each committed before
   any repair request. Both rounds run from the main checkout on `main` after
   it merges (Commands below). Dev prompt sets need no admission.
5. **After the last baseline request, on main.**
   1. Commit the four test plans. Done on `repair-arms` in b3a7d40, before
      the merge.
   2. Merge `repair-arms` with a merge commit.
   3. The dev round: the owner's dev command, then the maintainer's
      publish, score, `repair` and pool for dev, each round committed whole.
   4. A correction for any defect the dev round shows, in a commit that
      names it. It comes before any test repair prompt is prepared, the
      seeds below included.

      Amended 2026-10-04 (OD5). As registered, the dev round is the owner's
      dev command, then the maintainer's publish, score, `repair` and pool.
      The dev round now ends with the NextBit re-run of the frontier arms
      (OD6), its publish, score and `repair`, and then the pool, all before
      any further correction or test seed. The correction for the defect
      the owner's first dev batch showed, the frontier arms' outage on
      DeepInfra, is OD5's move, committed before that re-run in 725bb5e,
      c57142a and 1d07612. A defect the NextBit re-run shows needs a
      correction of its own.
   5. Seed the 12 test arm prompt sets in `docs/results/<arm run id>/`.
   6. Admit their digests in a commit of their own. That makes 13 of the
      record's 32 admitted prepares.
   7. Send, publish and score the test arm runs, then write the round and
      pooled summaries.
   8. Write the locked test result.

   After the merge, any first-turn test pass (a late baseline, a fallback or
   an outage re-run) stops at `prepare_code_mismatch`. So every registry row
   must be final before the merge.

   Corrected 2026-10-02. As registered, item 3 listed the four dev plans
   under `repair-cards`, item 4 ran the dev round from the `repair-arms`
   worktree alongside the baselines, and item 5 gave the dev round no place
   between the merge and the test seeds. Every baseline request was sent
   before `repair-arms` merged, and both rounds' plans were committed on
   `repair-arms`, so items 3 to 5 now say so, as the Commands section does.

## Commands

Every row of the [test-run registry](test-runs.md) was final before
`repair-arms` merged, so both rounds run from `main` after that merge, with the
commands below. `scripts/repair_arms.py` is the owner's one command per split;
`tests/test_repair_arms.py` checks it against a scripted follow-up step and a
scripted call step. No command carries a display filter or model text, and no
argument passes through a shell.

### Owner command

The batch takes every row from the protocol and this note:
- **Passes.** Dev: the four dev passes above. Test: the registry's `published`
  rows in a repaired role, one per slot; pass B is never repaired. The test
  split is refused while any registry row is still `registered`.
- **Order.** Anchor, 8B, 120B, then frontier. Each pass's arms go resample,
  bare, then counterexample, each after the one before has a final state; an
  arm not run does not hold back the next.
- **Run id, config and cap.** The arm run ids above; the repaired pass's own
  config, checked against its run manifest; and the slot's registered cap for
  the split, which the batch reads from the Caps table above, or the run's own
  raised cap once a budget stop of that run is resumed.

  Amended 2026-10-04 (OD5). As registered, each arm run sends its repaired
  pass's own config. The frontier arm runs send the move's config,
  `deepseek-v4-pro-0813_nextbit_enabled-false`, under the same caps. The dev
  frontier rows take the ids in the table under Owner decisions,
  2026-10-04; the test frontier rows keep their registered ids.
- **Prompt sets.** Each arm run answers `artifacts/repair/<arm run id>`
  (ignored by git), which `scripts/model_run.py follow-up --plan --arm`
  builds. Before anything is sent, the batch builds each owed set again in a
  temporary directory and refuses an existing set that differs from that
  build, its creation time and source revision aside.
  - Dev: a missing set is that build. Dev sets need no admission.
  - Test: the committed seed `docs/results/<arm run id>/prepare.json` and
    `prepared/` must equal that build, and the freeze record must admit its
    `prepare.json`. The ignored set is the seed byte for byte; a missing one is
    copied from it. With no seed the batch refuses and names every missing one.
    While no test arm run has a seed, it builds nothing before that refusal,
    and it checks a seed's admission before building it, so no test repair
    prompt is prepared before the seeding step.
- **Committed runs.** The batch reads each run's state from its directory under
  `artifacts/repair`, which git ignores. So before anything is built or sent
  it refuses a run the repository records while that directory is gone: a run
  published in `docs/results/<run id>/`, one whose evidence is kept in
  `docs/decisions/evidence/repair-arms/<run id>/`, or an arm the pass's
  `repair/not_run.json` names. It would otherwise send that run again. Run
  both rounds from the one checkout that keeps `artifacts/`.
- **Calls.** Each owed run is first called with the key withheld and must stop
  at `api_key_missing`. Paid calls start only with the key set and with the
  tooling, this note, the plans and any test seeds committed. Each is
  `scripts/model_run.py call` with the pass's config, `--max-usd` at the cap,
  `--source-revision` at HEAD, `--gate-first`, `--max-attempts 3` and
  `--min-interval-seconds 1.0`.
- **After a call.**
  - Pending items are resumed after 60 s with the same options and `--resume`.
  - A gate stop, or a resumed pass that stops at the gate, is not run and is
    never moved to another provider.
  - An outage is re-run once from scratch as the arm's `-r2` run, from its own
    prompt set (on test, its own seed and admission). A second outage, or an
    `-r2` id too long for a result name, is not run.
  - A refusal (no answer, and only HTTP 400 or 404) is not run: an arm has no
    fallback.
  - Amended 2026-10-04 (OD5). As registered, no arm run is moved to another
    provider. The frontier arms' move is the one exception: its config and
    ids apply, and the same dev command re-runs only the frontier rows.
  - HTTP 401, 402 or 403 aborts. A budget stop after an answer stops the batch
    until that run's cap is raised in the raised caps table and committed.
- **Not run by rule.** If a second turn would exceed the 64 KiB prompt budget,
  or its answer is empty, `follow-up` refuses every arm of that pass, so the
  round is reported not run. A plan with no item leaves its three rows unused.

The batch never publishes, scores or reads gold. `--dry-run` makes the same
checks, builds each owed prompt set in a temporary directory only, and prints
each row's state and the follow-up and call steps it would take; it sends and
writes nothing.

The step log `steps.jsonl`, the summaries `summary-<split>-<date>.json` and
`.txt`, and the lock go to `artifacts/repair-arms/` (ignored). For each row,
the summary gives:
- its state (`done`, `not_run`, `unused` or `owed`) and the reason;
- the run it counts, its first run or its `-r2` re-run;
- for a `done` run, its publish command;
- for a run not run that left a directory, the evidence directory
  `docs/decisions/evidence/repair-arms/<run id>/`, which keeps its
  `run_manifest.json` and `attempts/`;
- for a row counted by its `-r2` re-run, the same evidence directory for the
  first run the re-run replaces;
- the charged upper bound of its run and of any first run its re-run
  replaces. The total counts both, and every printed bound is rounded up.

For each round it gives the `dfilterforge repair` arguments, with `--not-run
ARM` for each arm the gate stopped.

Windows PowerShell 5.1, the dev round, at the main checkout. If `git switch
main` or `git pull --ff-only` fails, for instance on uncommitted changes, stop
there and fix that first:

```powershell
Set-Location D:\codeproject\acourse-code\DFilterForge
git switch main
git pull --ff-only
$env:PYTHONIOENCODING = "utf-8"
uv run --frozen python scripts/repair_arms.py --split dev --dry-run
$secure = Read-Host -AsSecureString "OpenRouter key"
$env:DFILTERFORGE_MODEL_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure
uv run --frozen python scripts/repair_arms.py --split dev
"exit code: $LASTEXITCODE"
Remove-Item Env:DFILTERFORGE_MODEL_API_KEY
```

The test round, the same way, once its seeds and their admission are on main:

```powershell
Set-Location D:\codeproject\acourse-code\DFilterForge
git switch main
git pull --ff-only
$env:PYTHONIOENCODING = "utf-8"
uv run --frozen python scripts/repair_arms.py --split test --dry-run
$secure = Read-Host -AsSecureString "OpenRouter key"
$env:DFILTERFORGE_MODEL_API_KEY = [System.Net.NetworkCredential]::new("", $secure).Password
Remove-Variable secure
uv run --frozen python scripts/repair_arms.py --split test
"exit code: $LASTEXITCODE"
Remove-Item Env:DFILTERFORGE_MODEL_API_KEY
```

Git Bash, at the same checkout (`read -rsp` keeps the key off the screen and
out of the history), the dev round:

```bash
cd /d/codeproject/acourse-code/DFilterForge
git switch main
git pull --ff-only
uv run --frozen python scripts/repair_arms.py --split dev --dry-run
read -rsp "OpenRouter key: " DFILTERFORGE_MODEL_API_KEY && echo && export DFILTERFORGE_MODEL_API_KEY
uv run --frozen python scripts/repair_arms.py --split dev; echo "exit code: $?"
unset DFILTERFORGE_MODEL_API_KEY
```

and the test round:

```bash
cd /d/codeproject/acourse-code/DFilterForge
git switch main
git pull --ff-only
uv run --frozen python scripts/repair_arms.py --split test --dry-run
read -rsp "OpenRouter key: " DFILTERFORGE_MODEL_API_KEY && echo && export DFILTERFORGE_MODEL_API_KEY
uv run --frozen python scripts/repair_arms.py --split test; echo "exit code: $?"
unset DFILTERFORGE_MODEL_API_KEY
```

| Exit | Meaning | What the owner does |
| --- | --- | --- |
| 0 | Every row has a final state: `done`, `not_run` or `unused`. | Hand the summary to the maintainer, who publishes, scores and checks each round (below). |
| 1 | Stopped for the owner. The cause is one of: a budget stop after an answer; a call step that ended with an error or left no run directory; the invocation limit; an unreadable run directory; a test outage re-run whose seed is not committed yet; or an error the batch did not expect, after a paid call may have been sent. | Read the `STOPPED` line, the summary and `steps.jsonl`. For a budget stop, add a row for the stopped run alone to the raised caps table, with a cap above its last `max_usd`, and commit; the Caps table stays as registered. For a re-run without a seed, seed it and admit it (below). Then run the same command. |
| 2 | Refused before any request. The cause is one of: a pass, its plan or its config; the Caps table or the raised caps table; a committed arm run whose run directory under `artifacts/repair` is gone; a prompt set; a test seed that is missing or not admitted; a registry row still `registered`; the lock; git; uncommitted tooling; or the keyless preflight. | Fix what the `refused` or `REFUSED` line names, then run the same command. A missing test seed means the seed and admission commits come first (below). Delete a held `artifacts/repair-arms/.lock` only when no batch or call step is running. |
| 3 | Aborted: the key variable is not set (after the keyless preflight; nothing was sent), or the account refused a request with HTTP 401, 402 or 403. | Set the key, or fix the key, the credit or the account's guardrail, and run the same command. |
| 130 | Interrupted with Ctrl-C after the request in flight finished; that request may be billed but not recorded. | Run the same command. If it says a call step is still running, let it exit and delete `artifacts/repair-arms/.lock` first. |

### Maintainer: seed, publish, score and check

These run from the main checkout's root in Git Bash, with the lab image
rebuilt from main (`docker compose --profile pilot build lab`). The lab
container sees `docs/results` at `/workspace/results`.

The variables:
- `$REV` is `$(git rev-parse --short HEAD)`.
- `$PASS` is a repaired pass's run id, and `$SPLIT` is `dev` or `test`.
- `$ARM` is `resample`, `bare` or `counterexample`, and `$ARM_RUN` is its arm
  run id from the table above.

  Amended 2026-10-04 (OD5). As registered, `$ARM_RUN` comes from the table
  above. On the dev frontier pass it comes from the table under Owner
  decisions, 2026-10-04.
- `$RUN` is the run a `done` row counts: its arm run id, or its `-r2` re-run.

```bash
REV=$(git rev-parse --short HEAD)
# test only, after the dev round and any correction it names: a pass's three seeds in one commit,
# then their prepare.json digests appended to admitted_prepares in src/dfilterforge/held_out_freeze.json in a commit of its own
uv run --frozen python scripts/model_run.py follow-up --from-run docs/results/$PASS \
  --plan docs/results/$PASS/repair/plan.json --arm $ARM --output-dir docs/results/$ARM_RUN --source-revision $REV
sha256sum docs/results/$ARM_RUN/prepare.json
# after an execution that exits 0: each done row, published and scored
uv run --frozen python scripts/model_run.py publish --run-dir artifacts/repair/$RUN/runs/$RUN --output docs/results/$RUN
MSYS_NO_PATHCONV=1 docker compose --profile pilot run --rm lab score --run-dir /workspace/results/$RUN --code-revision $REV
# each run not run that left a directory, and each first run an -r2 re-run replaced:
# copy its run_manifest.json and attempts/ to docs/decisions/evidence/repair-arms/<its run id>/
# each pass, once its three rows are final: the round summary (add --not-run ARM for each gate-stopped arm), then its check
MSYS_NO_PATHCONV=1 docker compose --profile pilot run --rm lab repair --run-dir /workspace/results/$PASS --code-revision $REV
MSYS_NO_PATHCONV=1 docker compose --profile pilot run --rm lab repair --run-dir /workspace/results/$PASS --code-revision $REV --check
# each split, once its rounds are written: the pool, then its check
MSYS_NO_PATHCONV=1 docker compose --profile pilot run --rm lab repair-pool --results-dir /workspace/results \
  --split $SPLIT --base $PASS1 --base $PASS2 --base $PASS3 --base $PASS4 --code-revision $REV
MSYS_NO_PATHCONV=1 docker compose --profile pilot run --rm lab repair-pool --results-dir /workspace/results \
  --split $SPLIT --code-revision $REV --check
```

- **Commit a round whole.** Commit a pass's published arm runs, their
  `scored/` trees and its `repair/` files together. CI's repair step refuses a
  pass that has some arm runs or seeds beside it but not all three (or
  `repair/not_run.json` for the missing ones).
- **Not run beyond the gate.** `repair --not-run` records only gate stops,
  and at most two arms. An arm not run for another reason (an outage on its
  re-run, a refusal), or a round with no arm run, has no record in the repair
  tooling yet: the owner rules on it before that round's summary is written.

  Amended 2026-10-04 (OD5, OD6). As registered, such an arm waits for the
  owner's ruling. The dev frontier round's three arms were each an outage on
  its re-run, so its six DeepInfra runs are not run, as the outage rule under
  Owner command says of a second outage, and are kept as evidence. Under
  Owner decisions, 2026-10-04, the owner's OD5 moves the frontier arms to
  NextBit. Re-running the dev round there, so that the NextBit runs replace
  the six, is OD6, a default the maintainer took and the owner has not yet
  confirmed. The owner's paid dev command is that confirmation, and it comes
  before that round's summary is written.
- **CI re-checks.** CI then re-checks every `repair/plan.json` and every
  `repair-pool/*.json` with `--check`, beside its existing re-score loop.

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
- **Triggered items.** The dev passes hold the 36 triggered items above, and
  the test passes the 75 counted on 2026-10-02.

After: not measured. The dev round fills it in: per model and arm, the
repaired items, repair@1 with its strata, the transitions, `answer_unchanged`,
`card_value_reuse` and spend, each linked to its `repair/summary.json`.

Amended 2026-10-04 (OD5). As registered, the dev round fills in each model's
After from its arm runs. The frontier After is measured on NextBit, from the
runs in the table under Owner decisions, 2026-10-04; the six DeepInfra runs
give it no number.

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

Added 2026-10-04 with the frontier arms' move to NextBit (OD5):

- **The resample also measures a provider change.** The frontier resample
  arm sends the first-turn prompt DeepInfra answered to NextBit, so beside
  the temperature-0 resample of OD3 it measures a change of provider.
- **Same label, different stacks.** Both endpoints are labelled fp8, but the
  serving stacks differ: NextBit counted 135 prompt tokens for a short
  message in the owner's diagnostics.
- **A DeepInfra answer continued on NextBit.** The bare and counterexample
  arms put the answer DeepInfra served in the assistant turn and ask NextBit
  for the correction.
- **NextBit is untried in a run.** NextBit never served a dev pass or a
  two-turn smoke; the frontier smoke was served by DeepInfra.
- **The pool mixes providers.** In the pooled comparison, the frontier slot's
  triggered items come from a DeepInfra pass and its arm answers from
  NextBit.
- **Written after the first test request.** The test frontier arms' provider
  was written after the first test request, against the protocol's Models
  rule, though before any test repair request.
- **A shared prepare id.** A moved run's `prepare_id` equals the replaced
  DeepInfra run's, its arm's registered first id, so only the run id and the
  run manifest's provider order tell the two apart.
