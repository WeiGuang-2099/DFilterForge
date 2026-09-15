# Model evaluation protocol (v1, draft)

This page is the whole protocol. It replaces the earlier pilot PRD. Anything
not written here is not part of the protocol. Frozen items are marked; the
rest is filled in as the corresponding step lands.

## Task

Given a natural-language request about packets, produce either a Wireshark
display filter (direct-filter conditions) or a typed intent IR that the
deterministic compiler turns into one (typed-IR conditions), or a
`needs_clarification` / `not_expressible` response. Every ready answer is
executed by pinned tshark 4.6.8 on three probe captures whose expected frames
were labelled from packet recipes, never from a filter string.

## Conditions

| Condition | Output contract | Retrieval |
| --- | --- | --- |
| C1 | display filter | none |
| C2 | display filter | lexical top-k over the frozen field catalog |
| C3 | typed IR | none |
| C4 | typed IR | lexical top-k over the frozen field catalog |

Primary comparison: C4 versus C2 (does a typed contract help when both have
field context). Secondary: C2 versus C1 and C4 versus C3 (does retrieval
help). Repair (one round of structured counterexample feedback) is an
additional column on top of C4, with two control arms: a bare "your filter
was incorrect" message and a plain resample at the same temperature.

## Splits

| Split | Ready cases | needs_clarification | not_expressible | Paraphrases per case |
| --- | ---: | ---: | ---: | ---: |
| dev | 12 | 4 | 4 | 2 |
| test (frozen) | 40 | 8 | 8 | 2 |
| train (synthetic, models only) | about 1,000 to 1,500 | about 15 percent non-ready | | 3 |

Test captures use seeds that never appear in dev or train. Canonical IR
hashes, paraphrase families, capture seeds and capture bytes are disjoint
across splits; a test asserts this. Test input hashes are recorded below once
frozen and no test item is sent to any model before that commit.

Frozen test hashes: not yet frozen.

## Metrics (per condition, per model)

- compile validity: the output parses, every field exists in the frozen
  catalog with a compatible type and operator, and tshark accepts the filter.
- strong exact: the candidate frame set equals the labelled set on all three
  probes, with at least one non-empty expected set (empty-equals-empty is
  excluded).
- silent-wrong: compiles and runs, but at least one probe disagrees. Reported
  both as a share of all outputs and as a share of executable outputs.
- repair@1: share of silent-wrong or invalid items that become strong exact
  after one feedback round; feedback comes from a fourth probe that is never
  used for scoring.
- abstention: false-ready rate on non-ready gold, over-abstention rate on
  ready gold, and slot match (the model's missing_slots intersects the gold
  slot set) for clarification cases. No human rubric.
- cost and latency per item from provider usage fields.

The unit of analysis is the canonical case; paraphrases are averaged inside a
case. Intervals are case-level bootstrap (1,000 resamples). A comparison with
fewer than 10 discordant cases is reported as inconclusive. Provider failures
and malformed outputs are counted, never dropped.

## Decoding and provenance

Temperature 0, one greedy pass, fixed max output tokens, thinking disabled
where the provider exposes a switch. Every run records the requested and the
effective settings (returned model id, provider, finish reason, usage, whether
seed and thinking controls were honoured). A factor the endpoint did not
honour is reported as uncontrolled, not claimed.

Every completion is stored raw. Scoring runs offline inside the no-network
lab container and can be replayed from a clean checkout without an API key.

## Models

Hosted open-weight models via an OpenAI-compatible endpoint (exact ids and
prices recorded at run time): one 8B-class, one 27B to 32B-class, one
70B-class, one DeepSeek-V3-class. Optionally one closed model on C2 and C4
only as a ceiling, capped at 5 USD. Local: Qwen3-1.7B base, QLoRA-SFT (3
seeds), SFT plus verifier-labelled DPO (3 seeds), continued-SFT control (3
seeds, matched optimizer steps and tokens).

## Training rules

Training data is generated from an IR grammar on train-only capture seeds and
paraphrased by a hosted model; dev and test text never enters training.
Preference pairs are labelled by the same execution verifier on train probes
only. Checkpoints are chosen on dev, never on test. GRPO is gated on a
pre-registered measurement: the share of G=8 groups with non-zero reward
variance on train prompts must exceed 30 percent; the histogram is published
either way and GRPO is not funded in this plan.

## Claim boundary

Results hold for Wireshark 4.6.8, the isolated profile, and these synthetic
IPv4 TCP/UDP/DNS captures. They say nothing about other versions, real
traffic, or protocols outside the recipe world. Negative results are
published unchanged.
