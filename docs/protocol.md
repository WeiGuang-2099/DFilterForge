# Model evaluation protocol (v1, draft)

This page is the whole protocol. It replaces the earlier pilot PRD. Anything not
written here is not part of it; the rest is filled in as each step lands.

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
empty list. Repair adds one C4 counterexample round against a bare "your filter
was incorrect" arm and a same-temperature resample.

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
  an item that probe cannot separate stays in the denominator.
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
disagreeing with its labels, a gold filter or target that hits a shortcut
rule, a gold case with no non-empty expected set, or any capture, catalog or
harness failure stops scoring; a candidate timeout or output or frame limit
counts as invalid, not as a stop, if its gold case reruns clean. A/A:
qwen/qwen3-32b on DeepInfra answers the frozen test prompts in all four
conditions twice with identical settings; pass B starts within 24 hours of
pass A whatever A shows, and the two are never pooled. Per condition the pair
reports changed answers, outcome transitions and flipped cases (ready cases
whose strong-exact case mean differs). A comparison with 10 or more discordant
cases is within rerun noise if its net count is at most twice the square root
of its two conditions' mean flipped cases, and not replicated if the rerun
reverses its sign.

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
the first answer shows thinking not honoured, the run stops and the provider or
model is changed ([note](decisions/model-client-replies.md)). Scoring is offline
in the no-network lab container: `dfilterforge score --check` must reproduce the
committed outcomes and summary byte for byte from a clean checkout, no API key.
A gold correction (labels, probes or reference filters) is justified from the
packet specification and the adequacy gate, never from which answers it flips.
It re-scores every committed run in place; stored answers never change, the
previous outcomes stay in git history, and the correction's note gives the
numbers before and after and lists every flipped item in both directions.
After the freeze, a test gold or scorer correction also re-scores in place, as
CI requires, and keeps each run's original outcomes and summary beside it in
`scored-original/`. A waiver changes no outcome, so it triggers no re-score.

## Models

Hosted open-weight models via an OpenAI-compatible endpoint: one 8B-class, one
27B to 32B-class, one 70B-class, one DeepSeek-V3-class, plus an optional closed
ceiling on dev (C2 and C4 only, at most 5 USD). Every hosted test run's model
id, provider and request settings are written here before the first test
request. Local: Qwen3-1.7B base, QLoRA-SFT, SFT plus verifier-labelled DPO and
a continued-SFT control matched on optimizer steps and tokens, three seeds each.

## Training rules

Training data comes from an IR grammar on train-only capture seeds, paraphrased
by a hosted model; dev and test text never enters training. Preference pairs are
labelled by the same verifier on train probes only. Checkpoints are chosen on
dev, never on test. GRPO is gated on a pre-registered measurement: the share of
G=8 groups with non-zero reward variance on train prompts must exceed 30
percent; the histogram is published anyway and GRPO is unfunded here.

## Claim boundary

Results hold for Wireshark 4.6.8, the isolated profile, and these synthetic IPv4
TCP/UDP/DNS captures. They say nothing about other versions, real traffic, or
protocols outside the recipe world. Negative results are published unchanged:
model answers are never edited, and a gold correction changes only the score,
under the rule above.
