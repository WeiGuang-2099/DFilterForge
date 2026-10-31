# Model evaluation protocol (v1, draft)

This page and the notes it binds are the whole protocol. It replaces the pilot
PRD. Anything not written there is not part of it; the rest lands step by step.

## Task

Turn a natural-language packet request into one JSON envelope; the two contracts
share every key but the ready payload. `ready` carries a display filter (C1/C2)
or a typed IR the compiler turns into one (C3/C4); `needs_clarification` carries
one question and `missing_slots` from the closed list address, direction, field,
port, protocol, value; `not_expressible` neither. Ready answers run on pinned
tshark 4.6.8 over three probes labelled by packet recipes, not filter strings.
Each probe is a benchmark capture followed by a fixed tail of witness packets
that separate near misses the recipes alone cannot.

## Conditions

| Condition | Output contract | Retrieval |
| --- | --- | --- |
| C1 | display filter | none |
| C2 | display filter | lexical top-k over the frozen field catalog |
| C3 | typed IR | none |
| C4 | typed IR | lexical top-k over the frozen field catalog |

Primary comparison: C4 versus C2 (does a typed contract help when both have
field context); secondary, C2 versus C1 and C4 versus C3 (does retrieval help).
C2 and C4 see one [ranked list](decisions/field-retrieval-ranking.md) per item,
built from model inputs, never evaluator gold; an unmatched item is kept with an
empty list. Repair is one C4 counterexample round, a second conversational turn,
against a bare "your filter was incorrect" arm and a same-temperature resample.

## Splits

| Split | Ready cases (built / target) | needs_clarification | not_expressible | Paraphrases |
| --- | ---: | ---: | ---: | ---: |
| dev | 12 / 12 | 4 / 4 | 4 / 4 | 2 |
| test (frozen 2026-09-26) | 40 / 40 | 8 / 8 | 8 / 8 | 2 |
| train (synthetic, models only) | about 1,000 to 1,500 | about 15 percent non-ready | | 3 |

Canonical IR hashes, paraphrase families, capture seeds and bytes are disjoint
across splits; a test asserts it for probe ids and packet bytes. For non-ready
cases disjointness holds per case: each case's requests are written
separately, but the address, port, value and direction slots and most kinds of
inexpressible request repeat across splits by design. Each split and gold kind
numbers its items from its own block (dev ready from mei-0001, dev non-ready
0501, test ready 1001, test non-ready 1501), so a case added to one block moves
no other item. Before any test item is sent, one test prepare (112 items, C1 to
C4, top-k 16, latest prompt versions), made back to back with a dev prepare
from the same image, is frozen in `src/dfilterforge/held_out_freeze.json` with
its prompt, system prompt, catalog and source file digests, beside digests of
the test inputs, test gold with item routing, gold hash, captures and feedback
labels that CI recomputes. The call refuses every test request whose
`prepare.json` the record does not admit. Until the last baseline request (a
hosted model's pass over the frozen test prompts, A/A rerun included) the
files a prepare hashes stay unchanged; before the first, a re-freeze replaces
the record in a commit that says why. Frozen on 2026-09-26 at `7590e4d`;
digest prefixes: prepare `206599bb67e1`, inputs `9b1e8a83d775`, gold and routing
`9d10fff42212`, gold hash `a9632daadafe`, feedback labels `c0b30949787e`.

## Metrics (per condition, per model)

Every item has exactly one outcome: `provider_failed` (including a provider
error or empty content inside an HTTP 200 response), `malformed`, `abstained`,
`false_ready`, `invalid`, `shortcut`, `silent_wrong` or `strong_exact`. All
items are denominators. Ready and non-ready gold are two case universes, each
bootstrapped with its own seed-17 vectors, so non-ready cases move no ready
number; every rate below except false-ready and slot match covers ready gold.

- compile validity: the output parses under its contract and pinned tshark
  accepts and runs it; a rejected filter exits 4 ([ablation
  001](ablations/001-bounded-tshark-runner.md)). A typed IR must bind every
  field in the frozen catalog with exact case and pass type, operator and value
  checks; a wrong-case field is invalid, not malformed. A display filter reaches
  tshark unchanged with no catalog, type or operator check, so non-catalog names
  it accepts (`ssl`) are valid; one over 4 KiB or with a C0 control character is
  malformed, a compiled filter over 8 KiB invalid.
- strong exact: the candidate frame set equals the labelled set on all three
  probes, with at least one non-empty expected set, and no shortcut rule hit.
- shortcut: compiles, runs and matches all three probes, but mentions a field
  the frozen catalog types as a frame number or time, a `frame.` field other
  than len, cap_len and protocols, a `_ws.` field, a stream index or derived
  conversation state (tcp.analysis, tcp.completeness, dns.unsolicited, DNS
  retransmission); ip.id, dns.id, a checksum or a raw sequence number; or a
  literal the request does not write as a whole token: a host address other
  than the bounds of a network it states (by CIDR, shorthand such as 10/8, or
  TEST-NET-1 to 3), a network touching the servers' 198.51.100.0/24 but not the
  clients' 192.0.2.0/24, outside every stated network, a number from 41000 to
  51254 (the generator's ephemeral ports), a MAC address or a generated DNS
  name, in any spelling tshark accepts (`dfilterforge.shortcuts`). It counts
  as compile valid, never as strong exact; hits on a silent-wrong answer are
  recorded without changing it. The number of ORs in each executed answer is
  recorded, not judged.
- silent-wrong: compiles and runs, but at least one probe disagrees. Reported
  over all items and over compile-valid items.
- repair@1: share of silent-wrong or invalid items that become strong exact on
  the three scored probes after one feedback round, which shows packets only
  from its split's unscored feedback probe (dev semantic-29, test semantic-35);
  an item that probe cannot separate stays in the denominator. It is the sum
  over ready cases of each case's repaired share of its C4 items in the
  repaired pass, divided by the same sum of its triggered share, with the
  interval from that pass's ready-case vectors, as for silent-wrong over
  compile-valid items (see Repair).
- abstention (both contracts, no human rubric): over-abstention on ready gold.
  false-ready: a ready answer to needs_clarification or not_expressible gold,
  never executed, over non-ready items, reported overall and per gold status.
  Slot match: over needs_clarification items, the answer asks for
  clarification and its missing_slots name at least one gold slot. Whether an abstention names the gold status is recorded per item. The
  reference control answers non-ready gold with its status and slots, the
  mutation control with a ready filter (display-filter conditions only).
- field context (C2 and C4): share of cases, paraphrases averaged, with every
  gold field in the retrieved list, beside that condition's scores; a non-empty
  list limits the prompt to its names, so C2-C1 and C4-C3 are read against it.
- cost per item from provider usage fields and the per-token prices recorded
  with the run, a lower bound when usage is missing or an item was retried, kept
  beside the provider-reported charge; latency over completed items only.

The unit of analysis is the canonical case, paraphrases averaged inside it.
Intervals are the 2.5 and 97.5 percent nearest-rank percentiles of 1,000
case-level bootstrap resamples (seed 17). Discordant cases are counted on strong
exact for C4-C2, C2-C1 and C4-C3; fewer than 10 is inconclusive. A reference
disagreeing with its labels, a gold filter or target that hits a shortcut rule,
a gold case with no non-empty expected set, or any capture, catalog or harness
failure stops scoring; a candidate timeout or output or frame limit counts as
invalid, not as a stop, if its gold case reruns clean. A/A: qwen/qwen3-32b on
DeepInfra answers the frozen test prompts in all four conditions twice with
identical settings; pass B starts within 24 hours of pass A whatever A shows
(unless the bake-off note reports the pair not run), and the two are never
pooled. Per condition the pair reports changed answers, outcome transitions and
flipped cases (ready cases whose strong-exact case mean differs). A comparison
with 10 or more discordant cases is within rerun noise if its net count is at
most twice the square root of its two conditions' mean flipped cases, and not
replicated if the rerun reverses its sign.

The mutation-adequacy gate is part of the gold. For every ready dev and test
case, `scripts/probe_adequacy.py` requires the reference filter and the compiled
canonical IR to select exactly the labelled frames on all six scored and both
feedback probes, the authored mutation to select exactly its own authored
frames there and to differ from the labels on one scored probe of its split and
on its feedback probe, and every single-site mutant of the canonical IR from
the fixed operator set in `dfilterforge.mutants` to differ on one scored probe
of its split unless a waiver in `model_split.MUTANT_WAIVERS` names its case,
edit and filter with a reason (`equivalent` or `not_separable`). The feedback
probe decides no survivor, but every killed mutant must differ on it too and
no waived one may. A mismatch, a survivor without a waiver, a waiver without a
survivor, or a breach of either feedback rule fails CI.

## Repair

The repaired passes are qwen/qwen3-32b's pass A and each slot winner's counted
test pass (qwen/qwen3.5-9b, qwen/qwen3.5-122b-a10b and
deepseek/deepseek-v4-pro-0813, whose runs the [test-run
registry](decisions/test-runs.md) names), and first, as a pipeline check that
is never reported as an effect and changes no rule here, the same models'
counted 2026-09-26 dev passes. A C4 item whose outcome there is silent-wrong
or invalid is triggered, whatever its finish reason; that it failed is the
only thing a scored probe tells the round. `dfilterforge repair` writes the triggered items in prepare order, each
with its card, to `repair/plan.json` beside the pass, committed before any
repair request. Each triggered item is sent once in each of three arms with
its pass's model, provider, settings, `--gate-first`, `--max-attempts 3` and
`--min-interval-seconds 1.0`, and stays in every arm's denominator:
`resample` sends its C4 prompt from that pass again as a first turn; `bare`
sends that prompt, the counted answer verbatim as the assistant turn and the
user turn "Your filter was incorrect. Reply with a corrected answer in the
same JSON format."; `counterexample` sends the same turns with a line
`COUNTEREXAMPLE_JSON` and the item's card appended to that user turn, or the
bare turn when the item has no card. A repair request, the resample included,
is not a baseline request.

A card comes from running the answer on its split's feedback probe and
nothing else. An answer that raises there a code that makes an answer invalid
gets `{"error": code}`, with `field`, the answer's own field in the first
predicate in reading order that raises that code alone, when the catalog or
compiler raised it. An answer that selects exactly the labelled frames gets no
card. Otherwise the card lists at most three frames where answer and labels
disagree, taken alternately from the missed and the wrongly selected frames in
frame order, skipping a frame equal to one already listed but for its number
and any port from 41000 to 51254. Each frame gives its number,
`answer_matched`, `should_match` and only ip.src, ip.dst, ip.ttl,
ip.dsfield.ecn, tcp.srcport, tcp.dstport, tcp.flags (the names of the set
flags), tcp.len, udp.srcport, udp.dstport, dns.flags.response,
dns.flags.rcode (responses only) and dns.qry.type, read from the capture and
confirmed frame by frame by tshark 4.6.8. A card shows no other label, no gold
filter, IR or predicate, no recipe or witness name, no count and no payload
byte; it is canonical JSON of at most 1,024 bytes, and a test fails if one
breaks this.

Arm answers are scored like any C4 answer, against the item's request: an item
is repaired only if its arm outcome is strong exact, so an answer that copies a
shown host address or ephemeral port is a shortcut, and every other outcome, a
provider failure included, is not repaired. repair@1 is reported per model and
arm, beside its silent-wrong and invalid parts. Per model, counterexample
against bare (primary), counterexample against resample and bare against
resample are compared on each case's repaired share by discordant cases, fewer
than 10 inconclusive; the same three over the four models, each drawn case
bringing every model's items, are secondary, and their unit is the case too
(owner ruling OD9 of 2026-10-05 in the [repair
note](decisions/repair-round.md)): a case is discordant when the two arms
repaired a different number of its items, the four models' taken together, and
it counts for the arm that repaired more, never once per model. The owner ruled
it after seeing the dev pool and before any test repair prompt was prepared.
The A/A noise reading covers only the condition comparisons.

Arm runs are named after their pass's run id with `-cx`, `-bare` or `-res`
before its date (`test-qwen3-32b-cx-2026-09-26`); an outage is re-run once
from scratch with `-r2` after the tag, and an arm run stopped at the gate is
reported as not run, never moved to another provider. Each sends `--max-usd`
0.20, 0.10, 0.05 and 0.05 on dev and 0.50, 0.30, 0.05 and 0.05 on test for the
frontier, about 120B-class, 8B-class and qwen/qwen3-32b passes; a budget stop
is resumed only under a raised cap committed first. A test arm's prompt set is
admitted in its own commit before its first request. If an item's second turn
would exceed the 64 KiB prompt budget, that model's round is not run and is
reported so. A defect the dev round shows is fixed only by a correction that
names it, before any test repair prompt is prepared. A gold correction
re-scores the arm runs in place and lists the triggered items whose pass
outcome changed; the triggered set stays the plan's. The [repair
note](decisions/repair-round.md) holds the run ids, commands, schemas and the
measured before and after.

Amended 2026-10-04, as the correction this section requires for a defect the
dev round shows, before any test repair prompt is prepared. The move is owner
ruling OD5 of 2026-10-04 in the [repair note](decisions/repair-round.md); the
dev re-run (OD6), the outage rule on NextBit (OD7) and the kept test ids (OD8)
are maintainer defaults there, which the owner confirmed on 2026-10-05. The
dev round showed that deepseek/deepseek-v4-pro-0813's arm runs got no answer
between 02:23 and 02:41 UTC on its DeepInfra-pinned route (provider order
`deepinfra`, fallbacks off). All 198 attempts of its three dev arm runs and
their `-r2` re-runs were HTTP 429, nothing was charged, and the test baseline
had already met 776 HTTP 429 on the same route, 754 of them before an item's
last attempt. The run records keep only the error code, 429, and no served
provider, so they do not say where the 429 arose. One request the owner sent
afterwards got an HTTP 429 whose body names `engine_overloaded` and
`upstream_provider_shared_pool`. That model's arm runs, on dev (OD6) and on
test, therefore send the bake-off note's listed frontier fallback config,
`deepseek-v4-pro-0813_nextbit_enabled-false` (NextBit, fp8). It differs from
the pass's DeepInfra config only in provider order and prices. For those arm
runs alone this overrides:

- in this section, "with its pass's model, provider, settings", and "an
  outage is re-run once" and "never moved to another provider" (the dev
  frontier arms are sent again as new runs, OD6);
- under Decoding and provenance, that a new run changes the provider only as
  the bake-off note lists (that note now lists this move);
- under Models, that a test run's provider is written before the first test
  request (the test frontier arms' provider is written now, after it and
  before any test repair request).

The counted first turns stay the answers DeepInfra served. Every other
setting, call option and cap, and every other model's arm runs, are
unchanged. On NextBit every gate, outage, refusal and budget rule of this
section applies (OD7). The six DeepInfra runs are reported not run and kept as
evidence (OD6). The repair note gives the new run ids and the maintainer
defaults behind them (OD6 to OD8).

Amended 2026-10-26, before any 1.7B repair request (owner rulings of that
day; the [self-served note](decisions/self-served-runs.md), Repair round,
holds the run ids, plans and order). When this was written every
self-served row, seed 2026's second test pass and the hosted repair round
had been scored. The three SFT adapters' 2026-10-07 test passes (seeds 17,
42 and 2026) are repaired too, and first, as a pipeline check never
reported as an effect, the same adapters' dev passes. Every rule of this
section applies, each adapter read as a model: the trigger, the arms, the
card, the follow-up text, scoring, repair@1 and its parts, the per-model
comparisons with counterexample against bare primary, the plan committed
first, each test arm prompt set admitted in its own commit, the 64 KiB rule,
and a dev defect corrected before any test repair prompt is prepared. These
differ:

- Each arm sends its pass's self-served config, endpoint host and call
  options, under the self-served note's nominal caps (0.05 on dev, 0.10 on
  test) instead of the caps above. The gate cannot stop these runs, and an
  outage is handled under the self-served note's rules.
- The secondary comparisons pool the three seeds by case, the OD9 unit, in
  `repair-pool/<split>-qwen3-1.7b-sft.json`, never with the hosted models.
- A comparison, per seed or pooled, reads as a difference only if its
  interval excludes 0 and at least 10 cases are discordant, as the SFT
  headline is read under Training rules. That is stricter than the round
  and pool summaries' verdict, which counts discordant cases only, and an
  interval with an endpoint at 0 does not exclude 0; where a summary
  prints "conclusive" and this rule does not hold, this rule holds.
- On greedy single-stream serving the resample arm re-sends identical bytes
  to an unchanged stack, so it measures whether the stack repeats itself
  across sessions, not a second chance, and it is labelled so.
- These rounds are never compared with the hosted rounds, and their cards
  and arm answers never enter training or preference data.

## Judge study

Registered 2026-10-20, before any judge request. The [judge
note](decisions/judge-study.md), part of this protocol, holds the
decisions, the prompts, the configs, the caps, the commands and the
outputs. When this was written every hosted and self-served test answer
was scored and committed, and no judge reply existed.

The question is how often an LLM judge, asked whether a display filter
selects what its request asks for, accepts a filter that tshark disproves.
The judged answers are the Disproof Reel's test pool under rule `reel-v1`:
the published passes `test-qwen3-32b-2026-09-26` (pass A),
`test-qwen3.5-9b-2026-09-26`, `test-qwen3.5-122b-a10b-2026-09-26` and
`test-deepseek-v4-pro-0813-2026-09-26`, each ready C1 to C4 item whose
outcome is strong exact, shortcut or silent-wrong: 971 answers, 804, 2 and
165, pinned by the SHA-256 of each pass's `scored/outcomes.jsonl`. The
judge sees the item's request and user assumptions, as the answering model
saw them, and the filter that ran: the answer's display filter (C1, C2) or
the one the compiler made from its IR (C3, C4), as the receipt records it.
In the primary mode it sees nothing else; in the secondary mode it also
sees the item's reference filter, named as one that selects exactly the
requested packets. Answers with the same item and filter make one request
per mode, whose verdict counts for each of them: 508 test requests per
mode.

The judge is deepseek/deepseek-v4-pro-0813 through OpenRouter, with the
benchmark's decoding (temperature 0, seed 17, JSON mode, thinking off), at
most 256 output tokens, one provider pinned, fallbacks off and
`data_collection` set to deny. If its first reply shows thinking, the run
stops, as a model run's gate does. A reply counts only as one JSON object
whose `verdict` is `correct` or `incorrect`, after a one-sentence
`reason`. Any other reply, a reply cut at the token limit and a request
left with no completed reply after three attempts all give no verdict,
and an answer with no verdict never counts as rated correct. On a
silent-wrong answer, `correct` is a false
acceptance, since tshark holds a frame that disproves the filter. A
verdict on a strong-exact or shortcut answer is neither right nor wrong,
since strong exact holds on three probes, not on every capture: agreement
there is reported, not scored. The judge wrote 274 of the 971 answers, 27
of the 165 silent-wrong among them; every table lists those rows apart,
and the headline gives them beside the count over all 165.

First, as a pipeline check that is never reported and changes no rule
here, the judge rates the same four models' counted 2026-09-26 dev answers
(284 answers, 141 requests per mode). A defect it shows is fixed only by a
correction the judge note names, before any test judge request. Requests
are paced at 1 s. A timeout, a transport error or HTTP 408, 429 or 5xx is
sent again in a later sweep, at most three attempts in all, and HTTP 401,
402 or 403 stops the run. Once a test request is sent, the provider never
changes. The verdicts are counted over answers, per mode, outcome,
condition and model, by committed code that CI rebuilds with `--check`.
They are plain counts with no interval, and none is read as a property of
the answering models.

This path sends test requests, the answers' filters and, in the secondary
mode, the reference filters to a provider outside the admission guard: the
freeze record admits model prepares, and the judge's requests are not one.
All of them are already public in the committed receipts. Under Splits,
"the call refuses every test request whose `prepare.json` the record does
not admit" holds for the call step; this study is its one exception.

Amended 2026-10-21, after the dev check and before any test judge
request, by the correction the judge note names. The dev check gave every
request a completed reply, but 114 of its 282 replies gave no verdict:
109 reached the token limit, 108 of them while the reason ran on, 57 of
those repeating one sentence. The prompts, version `judge-v2`, ask for
the `verdict` first and the one-sentence `reason` after it. A completed
reply gives the verdict it opens with: a brace, the key `verdict` and
`correct` or `incorrect`, then a comma. The reason is not read, so a
reply cut in it at the token limit keeps its verdict, and a reply whose
whole text parses as JSON and gives a key twice gives none. This replaces
the reply rule above, as the dev check's defect route allows; every other
rule stands, and the dev check is sent again with `judge-v2` before any
test request.

## Decoding and provenance

Temperature 0, one greedy pass, fixed max output tokens, thinking disabled where
the provider offers a switch. Every run records the requested settings, prices,
endpoint host and spend, and each answer's served model id, provider, finish
reason, usage and reasoning tokens. Answers are stored verbatim up to 64 KiB,
reasoning and refusal text never, only whether reasoning was present. Requests
are paced; a timeout, a transport error or HTTP 408, 429 or 5xx is retried and
HTTP 401, 402 or 403 stops the pass until a resume, up to the recorded
`max_attempts` (at most three), every attempt kept, the last counted. A control
counts as honoured only where a response reports it: thinking is honoured, not
honoured or uncontrolled; the seed stays uncontrolled (no reply echoes it). If
the first answer shows thinking not honoured, the run stops
([gate](decisions/model-client-replies.md)), and a new run changes the provider,
endpoint or reasoning switch only as the [bake-off
note](decisions/model-bakeoff.md) lists. Scoring is offline in the no-network
lab container: `dfilterforge score --check` must reproduce the committed
outcomes and summary byte for byte from a clean checkout, no API key.
A gold correction (labels, probes or reference filters) is justified from the
packet specification and the adequacy gate, never from which answers it flips.
It re-scores every committed run in place; stored answers never change, the
previous outcomes stay in git history, and the correction's note gives the
numbers before and after and lists every flipped item in both directions.
After the freeze, a test gold or scorer correction also re-scores in place, as
CI requires, and keeps each run's original outcomes and summary beside it in
`scored-original/`. A waiver changes no outcome, so it triggers no re-score.

Amended 2026-10-04: the frontier repair arm runs' provider change is listed in the bake-off note and ruled under Repair.

## Models

Hosted open-weight models via OpenRouter: an 8B-class (7B to 12B dense), an
about 120B-class (100B to 130B total), a frontier open-weight MoE (about 0.75T
to 1.6T total) and qwen/qwen3-32b on DeepInfra, plus an optional closed ceiling
on dev (C2 and C4 only, at most 5 USD). A dev bake-off fills each slot under the
[bake-off note](decisions/model-bakeoff.md), which is part of this protocol: of
the candidates its drop rule and smoke leave, the earliest-listed one at most 4
below the best survivor's C1-C4 strong-exact ready count wins, else the reserve,
else the slot is empty. Each hosted test run's run id, model id, provider and
settings are written here, in that note or in the [test-run
registry](decisions/test-runs.md), also part of this protocol, before the
first test request; the registry holds the A/A pair's and the slot winners'
runs. Local: Qwen3-1.7B base, QLoRA-SFT, SFT plus verifier-labelled DPO and a
continued-SFT control matched on optimizer steps and tokens, three seeds each.

Amended 2026-10-04: the test frontier arm runs' provider, NextBit, was written after the first test request and before any test repair request; see Repair.

Amended 2026-10-07, before any self-served request (owner ruling of
2026-10-06: GPU work runs on Modal). "Local" above means self-served: the
base model and each seed's adapter answer through vLLM's OpenAI-compatible
server on Modal (`modal/serve_vllm.py`), serving Qwen/Qwen3-1.7B at the
revision `training/train_sft.py` pins, in bf16, on one pinned GPU type with
one pinned vLLM version, and the adapters are trained on that GPU type
(`modal/train_sft.py`). Thinking is off by the server's default
`--default-chat-template-kwargs '{"enable_thinking": false}'`: the client
sends no switch, no prepare-hashed file changes, and the run note records
it. Each run sends the hosted runs' settings and call options with
`openrouter` null (temperature 0, seed 17, 2048 output tokens, JSON mode,
`--gate-first`, three attempts, 1 s pacing). Prices are nominal, because a
config needs non-zero ones; the real cost is GPU time, recorded per run. A
pass whose endpoint host changed cannot resume and is re-run under `-r2`.
The base row and every adapter row use the same stack. Each row answers dev
first and the frozen test prompts only if its dev run settles every item, a
rule fixed before any score. The [self-served note](decisions/self-served-runs.md),
part of this protocol, holds the stack, the run ids and the rules, written
before the first test request.

## Training rules

Training data comes from an IR grammar on train-only capture seeds, paraphrased
by a hosted model; dev and test text never enters training. Preference pairs are
labelled by the same verifier on train probes only. Checkpoints are chosen on
dev, never on test. GRPO is gated on a pre-registered measurement: the share of
G=8 groups with non-zero reward variance on train prompts must exceed 30
percent; the histogram is published anyway and GRPO is unfunded here.

Amended 2026-10-06 (owner ruling). The local model is Qwen/Qwen3-1.7B, the
hybrid release, with thinking off; "base" under Models means it before
fine-tuning, not Qwen3-1.7B-Base. The SFT set (`data/train/v1`, built by
`scripts/train_data.py`) samples one to three predicates at depth at most 2
from exactly the 38 predicates the dev and test gold uses: unseen
compositions in a closed world, not unseen fields, operators or values. Its
labels are the frames pinned tshark selects with the gold IR itself on three
train-only probes (seeds 7001 to 7003, clients no other probe has), not a
second semantics. Dropped: a canonical key (All and AnyOf flattened and
sorted) or train-probe frames equal to a dev or test gold's, a shortcut hit,
no frame or every frame, an 8-word run shared with a dev or test request.
About 15 percent ask for clarification with one slot removed. They use all
six slots, which repeat across splits by design (see Splits); field and
protocol are open in test cases only, in no dev case. The wording does not
repeat: no clarification wording shares a 4-word run, other than one of
numbers and protocol names alone, with a dev or test non-ready request. v1
has no not_expressible rows, so fine-tuning on it never shows that status;
not_expressible test items are reported separately, as false-ready per gold
status already is. `tests/test_train_split.py` asserts each rule on the
committed set, and the wording rule on every clarification template.

Amended 2026-10-06, before any training run: the SFT recipe and its
checkpoint. Each row of `data/train/v1/sft.jsonl.gz` (built by
`scripts/sft_dataset.py`) pairs the C4 request scoring prepares for that
row, with the same system prompt, assumptions and top-16 retrieval, with
the row's target envelope, which the scorer's parser reads back unchanged;
`tests/test_sft_dataset.py` compares the prompts with `model_run.py
prepare`. In 540 of the 1,088 ready rows the target uses a field the row's
retrieved list leaves out (`ready_with_unretrieved_field` in
`sft-manifest.json`), so the SFT targets override the C4 rule to use only
the listed names; the base and adapter C4 scores are therefore each
reported split by field coverage, over items with every gold field
retrieved and over the rest. `training/train_sft.py` renders the rows with
the Qwen3-1.7B chat template and thinking off, and puts the loss on
completion tokens only;
`training/tests/test_parity.py` checks every row's sequence against the
served render. A served run must render prompts the same way, with thinking
off by default on the server, because the client sends no switch. The
recipe is fixed now: 4-bit nf4 QLoRA, r 16, alpha 32, all attention and MLP
projections, 3 epochs, learning rate 2e-4 with a cosine schedule, effective
batch 16. For SFT the checkpoint is the adapter after the final epoch, for
every seed, so no checkpoint is chosen on dev or test; this replaces
"chosen on dev" above. Seeds 17, 42 and 2026 are each trained, scored on
dev and test, and reported. The base model (thinking off) and each seed's
adapter answer the dev prompts and the frozen test prompts in all four
conditions and are scored by the same scorer; the adapters trained on C4
prompts only, so their C1 to C3 rows are marked as untrained conditions.
The SFT headline is adapter C4 minus base C4 on strong exact, per seed and
as the three-seed mean, with the case bootstrap; C4 against C2 is not read
for adapters.

Corrected 2026-10-18 (owner ruling of that day): no hosted model
paraphrased the training requests. `dfilterforge.train_combos` writes each
request of `data/train/v1` from a fixed sentence frame, fixed connectives
and, for each atom, one of the two handwritten wordings it carries in
`src/dfilterforge/train_atoms.py`, picked by the seeded sampler; a
needs_clarification row swaps one atom's wording for the handwritten
wording that leaves its slot open. "Paraphrased by a hosted model" above
was the plan, not what was built, and so is the train row of the Splits
table: v1 holds 1,299 compositions, 1,088 ready and 211
needs_clarification, each with one request, not three. No published
number changes.

Amended 2026-10-18, before seeds 17 and 42 are scored on test: the SFT
headline's estimator. When this was written the base row's dev and test
scores and seed 2026's were known (test C4 strong exact 0.062 and 0.475
[0.338, 0.600]). Seeds 17 and 42 had answered every test item and
settled every dev item (26 of seed 42's dev C1 items ended in HTTP 503);
no score of theirs had been computed, and their runs are committed
unscored before one is. A seed's difference is paired by case: over
the 40 ready test cases, the seed's C4 strong-exact case mean
(paraphrases averaged, every item in the denominator) minus the base
row's on the same case. Its interval uses `draw_indices(40)` from
`dfilterforge.score_summary` (1,000 resamples, seed 17) over the ready
case ids in sorted order, the vectors behind every other ready-case test
interval, with the nearest-rank 2.5 and 97.5 percentiles. The three-seed
mean is taken inside each resample: a vector's statistic is the mean of
the three seeds' differences on that vector's draw. The interval
therefore covers case sampling with the three trained adapters fixed;
the spread between seeds is shown as the three per-seed rows, not folded
into it. Discordant cases are counted for each seed against base, and
once more on the seed-averaged case differences. A seed's difference, or
the mean, reads as a gain or a loss only if its interval excludes 0 and
at least 10 cases are discordant, and as inconclusive otherwise. That is
stricter than the summaries' inconclusive flag, which counts discordant
cases only, and an interval with an endpoint at 0 does not exclude 0.
Pages and the README open with the three-seed mean and its reading; the
seeds follow in seed order. Self-served rerun noise is not measured, and
the headline says so. The C4 split by field coverage uses the estimator
of silent-wrong over compile-valid items: per case, the share of its C4
items that are in the stratum and strong exact, over the share of its
items in the stratum, each summed over a resample's drawn cases; a
resample with no item in the stratum is skipped, and the number used is
reported. Retrieval depends only on the prompt, so the base row and
every seed put each item in the same stratum. Within a stratum, a seed's
difference to base and the three-seed mean's sum the case differences of
the numerators over that one denominator, and a case with an item in the
stratum is discordant there when its numerators differ. Stratum
differences are shown with their intervals and discordant counts and are
never read as a gain or a loss. No mean is quoted before all three seeds
are scored, and none is computed by hand: `scripts/sft_headline.py`,
committed before seeds 17 and 42 are scored, writes
`docs/results/sft-v1/headline.json`, CI rebuilds it with `--check`, and
where this text is silent that script decides.

Amended 2026-10-18, before seeds 17 and 42 are scored on test:
descriptive analyses of the self-served rows. They describe; they decide
nothing. No training data, prompt, checkpoint, seed or later design
choice changes because of them, and no test failure becomes training
data. The error classes and the proximity strata were defined after seed
2026's test scores were known and are labelled post hoc wherever they are
shown. Code written after this text computes each one and CI rebuilds
its output with `--check`; where that code and this text differ, this
text holds. All are on test C4, for the base row and each seed unless
stated, and none is read as a gain or a loss.

- Transitions: per seed, the base row's outcome against the seed's on the
  same item, over the 80 ready and, separately, the 32 non-ready C4 items.
- Error classes: each ready C4 item that is not strong exact takes the
  first class that applies, in this order: `provider_failed`; `truncated`
  (malformed with finish_reason `length`); `malformed`; `abstained`;
  `unknown_field` (invalid with error code `unknown_field`, a field the
  frozen catalog lacks); `invalid_other`; `shortcut`; then, for
  silent-wrong, comparing sets taken from the answer's IR and the gold IR,
  in this order: a gold field absent from the answer (`missing_field`);
  an answer field absent from the gold (`extra_field`); differing sets of
  (field, operator) pairs (`operator`); differing sets of predicates in
  canonical form (`in` lists sorted), negation ignored (`value`);
  differing canonical forms, with All and AnyOf flattened and sorted as
  `dfilterforge.train_combos` keys them (`structure`); else `same_form`.
  Ten items drawn by `random.Random(17).sample` from every classified item
  of the four rows, listed by row (base, then seeds 17, 42 and 2026) and
  item id, are checked by hand, and the check is recorded.
- Field coverage: the C4 split of the base row, each seed and the four
  counted hosted test rows (the slot winners and qwen/qwen3-32b's pass A,
  not pass B or a repair arm), with the estimator above.
- Proximity to training: a ready test case's atoms are the predicates of
  its gold IR, negation and grouping ignored. Against the atoms of each of
  the 1,088 ready targets in `data/train/v1`, the case takes the first
  stratum that applies: `same_atoms` (a target has exactly those atoms,
  composed differently, since no target has a gold's canonical key),
  `inside_one_target` (a target has them all and more), `pairs_seen`
  (every two of them appear together in some target), `apart`. No target
  joins two atoms on one field, so a case that does is `apart` by
  construction. Strong exact is reported per stratum and row, as case
  means.
- Copies and unlisted fields: per row, over ready C4 items with a stored
  IR (outcome invalid, shortcut, silent_wrong or strong_exact), the share
  whose canonical key equals one of the 1,088 ready targets' keys, and the
  share whose IR tests a field missing from the item's retrieved list,
  each split by field coverage, with how many of them are strong exact.
  The base row never saw the training set, so its copy share is the
  untrained reference rate.

Amended 2026-10-20, before its request: one self-served rerun. Seed
2026's adapter answers the frozen test prompts a second time on the same
stack, and `dfilterforge pair` reads the two passes as the A/A pair under
Metrics is read, by the rules of the [self-served
note](decisions/self-served-runs.md). The second pass is not a row, no
comparison is read against it, and it sets no noise bound. "Self-served
rerun noise is not measured" above holds until its pair report is
committed; from then on the headline and the pages point to that report.

Amended 2026-10-26, before any of their requests: two untrained baseline
rows (owner rulings of 2026-10-25 and 2026-10-26; the [self-served
note](decisions/self-served-runs.md), Baseline rows, holds the run ids and
rules). They ask whether constrained decoding or prompting closes what
fine-tuning closed. Both serve the base model (thinking off) on C4 alone,
each on its own admitted prompt sets, dev first and test only if dev
settles every item, with the base row's settings otherwise. The schema row
decodes under the typed-IR JSON schema (`response_schema` `typed-ir/1`,
from `dfilterforge.answer_schema`) instead of plain JSON mode, on prompts
byte for byte the base row's C4 prompts. The few-shot row adds to the same
prompts eight training examples from `data/train/v1` (rule
`word-overlap/1`, `dfilterforge.few_shot`) and decodes under the same
schema, so it differs from the schema row in the examples alone. The
system prompt is unchanged in both. For these rows only, this overrides
"JSON mode" under Models (amended 2026-10-07) and the self-served note's
"Every row answers these two prompt sets". Both were designed after every
base and SFT test score was known, and the schema row after reading the
base row's malformed test answers, against the 2026-10-18 rule above that
no later design choice changes because of the descriptive analyses. That
is why both are labelled post hoc wherever they are shown, and they change
no registered row, headline or training choice. Three differences are
read, each paired by case over the 40
ready test cases on C4 strong exact with the SFT headline's estimator and
reading rule above: the schema row minus the base row, the few-shot row
minus the schema row, and the three-seed SFT mean minus the few-shot row,
the mean taken inside each resample. Each reads as a gain or a loss only if
its interval excludes 0 and at least 10 cases are discordant. Per row, over
the 80 ready test C4 items, the outcome counts are shown, malformed split
into truncated (finish reason `length`) and the rest, and C4 is split by
field coverage with the estimator above; these describe and are never read
as a gain or a loss. The cost of these rows and of the 1.7B repair round is
reported as the Modal bills of the sessions that sent them, summed, over
the requests those sessions sent, beside the GPU time their latencies sum
to at the L4 price; neither is a price for any other serving. Code committed before these rows' test passes are scored
computes every number here, and CI rebuilds its output with `--check`;
where that code and this text differ, this text holds.

Amended 2026-10-31, as the correction of a pipeline defect the two baseline
rows' dev passes showed, before any request of their re-runs (owner ruling
of 2026-10-29; the [self-served note](decisions/self-served-runs.md),
Baseline rows, holds the run ids). The client sent each request body as
canonical JSON, which sorts object keys, so the typed-IR schema reached
vLLM with the keys of every object, its properties included, in
alphabetical order, and xgrammar, vLLM 0.21.0's default grammar engine,
emits properties in their declared order. Once an answer opened with
`schema_version` and `status`, the order in which the prompt lists the
keys, only `not_expressible` could follow: both rows' dev passes, sent on
2026-10-28, answered the object
`{"schema_version": "1.0", "status": "not_expressible"}` on all 80 items,
where the base row, on the schema row's prompts byte for byte, abstained on
none of its 40. Compiled offline as vLLM compiles it, with xgrammar 0.2.8,
the schema as sent on 2026-10-28 admits none of the base row's 40 dev C4
answers and allows only `n`, `no` and `not` at the status value; in
declared order it admits 22 of them and allows `ready`, and llguidance
1.3.0, vLLM's fallback engine, allows `ready` too; neither engine's version
in the server image is recorded. The client now sends every object's keys
in the order the code built them, and nothing else in a request changes.
Both rows run again under new run ids, on new prepares whose prompt files
are byte for byte the 2026-10-26 ones, with the same schema, settings, call
options, caps, endpoint host, probe and reading, both dev passes first, and
each test pass waits while every answer of its dev pass is one string, as
both were on 2026-10-28, a check that reads no answer's status and no
score. The two 2026-10-26 dev passes stay committed as the record of the
defect and are not rows. The two 2026-10-26 test passes are reported not
run: they were never published or scored, the session scripts read them
only for their census (item and attempt counts, run status, fingerprints,
think blocks) and copied them into the owner's backups, and they stay out
of the repository, unread; their admissions stay in the freeze record.
Their requests were billed in the session of 2026-10-28; how they enter the
cost, which may not open them, is ruled before the cost is written. No
other row, number or rule changes: every other row sent `json_object`,
whose grammar has no properties to order.

## Claim boundary

Results hold for Wireshark 4.6.8, the isolated profile, and these synthetic IPv4
TCP/UDP/DNS captures. They say nothing about other versions, real traffic, or
protocols outside the recipe world. Negative results are published unchanged:
model answers are never edited, and a gold correction changes only the score,
under the rule above.
