# Ablation 004: Predicate Trace and Executable Replay

Status: measured

## Hypothesis

Re-executing both the recorded reference and candidate filters, then tracing
only actual counterexample frames at predicate level, should prevent stale
reference labels from being accepted while retaining actionable diagnosis.

## Frozen inputs

- Source revision: `9d885dc+working-tree`
- Environment: Docker image with tshark 4.6.8
- Curated cases: TCP SYN/no-ACK, DNS UDP query, UDP destination 53
- Repetitions: 3; 12 valid replay samples per variant
- Comparison: exact candidate frame tuples
- Standalone hash validation: not run, per task instruction
- 50 by 150 stability gate: not run; remains unverified

## Full

Production executable replay verifies the receipt/specification manifest,
re-executes the reference and candidate roots, and records bounded,
dual-sided predicate traces for actual counterexample frames. It fails closed on
reference-label drift.

## Simplified

The real simplified variant re-executes only the candidate filter and compares
its frame tuples with the recorded candidate tuples. It does not execute the
reference or produce predicate traces.

## Command

```text
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/trace_replay_ablation.py --output /workspace/artifacts/004-trace-replay-ablation.json --work-dir /workspace/artifacts/004-trace-replay-work --source-revision 9d885dc+working-tree --repetitions 3
```

## Results

| Measure | Full | Simplified |
| --- | ---: | ---: |
| Valid replay samples exact | 12/12 | 12/12 |
| Reference-verified samples | 12 | 0 |
| p50 wall time (ms) | 453.00 | 205.12 |
| p95 wall time (ms) | 832.88 | 210.67 |
| Predicate trace counterexample frames | 12 | 0 |
| Dual-sided trace coverage | 12/12 | 0/0 |
| Broad SYN extra frames diagnosed | 12/12 | 0/0 |
| Real reference drift | rejected | falsely candidate-exact |

The drift witness changed both the specification and receipt reference label
to broader `tcp`. Full returned `reference_label_mismatch` after one tshark
call; Simplified accepted the candidate as exact without executing the
reference.

## Decision

`keep_full`. The variants are not behaviorally equivalent: Full detects real
reference drift and supplies complete dual-sided diagnosis. The measured
stability gate and standalone hash validation remain intentionally unverified.

## Extension 2026-09: raw display-filter candidates

`evaluate_live` now also scores a candidate that is a display-filter string,
so the rule applies to it. The rejected alternative is
`_simplified_filter_eval` in `scripts/raw_filter_ablation.py`: a scorer-side
loop that runs only the candidate against the recorded labels. Its measured
cost, from `evidence/004-raw-filter-oracle.json` (measured 2026-09-19 at
revision `1c64140+working-tree`, five witnesses, one run each): it charged the
altered `semantic-11` label to the model where Full stopped with
`reference_label_mismatch` after one call, and it verified no reference on any
witness. Both variants agreed on the two honest specifications, and Full paid
16 tshark calls against 10. A catalog-binding variant rejects `ssl` with
`unknown_field`; tshark executes it with 0 frames. `keep_full`.

## Extension 2026-09: replaying a recorded filter string

Scope: replay for receipts that carry no typed IR, so `replay-run` has
nothing to recompile. The decision above is unchanged; this only adds the
string path to it.

Full is `replay_live` given a display-filter string: it compares that string
byte for byte with the receipt's recorded `candidate_filter` before anything
runs, then re-executes reference and candidate through the shared oracle.
The rejected alternative is `_simplified_string_replay` in
`scripts/raw_filter_ablation.py`, which re-runs only the supplied string and
compares its frames with the recorded candidate frames.

Measured 2026-09-19 at revision `1c64140+working-tree`, tshark 4.6.8, case
`tcp-expiring-ttl` with three probes, one run each, from
`evidence/004-raw-filter-replay.json`.

| Witness | Full | Simplified | Calls (F/S) |
| --- | --- | --- | ---: |
| Honest receipt | exact 3/3, reference run | exact 3/3, no reference | 6/3 |
| Corrupted label | `reference_label_mismatch` | candidate exact 3/3 | 1/3 |
| Tampered `udp` | `candidate_filter_mismatch` | 3 probes wrong | 0/3 |

The corrupted-label witness added one frame to the first probe's independent
label on both the specification and the receipt, and changed nothing else, so
the manifest check still passed and the corrupted label is the only drift the
witness carries.

Predicate traces are outside that table because the string path has none to
compare. Full replayed the same case once through the typed-IR path in the
same run, against a receipt recorded from the canonical IR, because the
compiler parenthesises that expression and the recorded string does not.
`typed_ir_replay` in the evidence file records `trace_present`, reference
verified, 3/3 exact in 6 tshark calls. On the string path Full recorded
`full_trace_present` false, and the simplified loop returns rows with no
trace field at all, so it has none by construction.

Full is the only variant that refuses a string the receipt does not vouch
for, and it refuses it before any capture is opened. The measured cost is
one extra tshark call per probe, 6 against 3 on the honest witness, plus the
loss of the predicate trace, which a raw filter has no expression to
produce. `keep_full`; no new ablation number.
