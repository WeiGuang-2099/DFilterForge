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
