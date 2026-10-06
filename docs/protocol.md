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

## Claim boundary

Results hold for Wireshark 4.6.8, the isolated profile, and these synthetic IPv4
TCP/UDP/DNS captures. They say nothing about other versions, real traffic, or
protocols outside the recipe world. Negative results are published unchanged:
model answers are never edited, and a gold correction changes only the score,
under the rule above.
