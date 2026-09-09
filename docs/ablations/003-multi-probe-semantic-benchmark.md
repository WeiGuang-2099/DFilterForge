# Ablation 003: Multi-probe Semantic Benchmark

Status: keep_full

Measured: 2026-09-09

## Hypothesis

One probe per semantic specification could replace three probes while
preserving independently reviewed label agreement and near-wrong mutation
detection, with fewer tshark calls.

## Frozen inputs

- Code revision label: `705ed13+working-tree`.
- Environment: pinned tshark 4.6.8 Docker test image with the frozen catalog
  and isolated default profile.
- Dataset: 36 reviewed semantic specifications, three primary probes per
  specification, 50 generated captures with 50 distinct recipe tuples, and one
  authored near-wrong mutation per specification.
- Quality thresholds: reference agreement 100 percent, typed candidate
  agreement 100 percent for this deterministic compiler suite, mutation kill
  rate at least 95 percent, median call latency at most 500 ms, and p95 at most
  two seconds.

An independent review agent checked the case meanings, recipe memberships,
reference filters, mutations, directional counterexamples, packet checksums,
and final capture diversity. It did not modify the reviewed source.

## Full

Full evaluates every specification on three actual PCAP probes. Each probe
runs the typed candidate, independently authored reference filter, and
near-wrong mutation through the bounded runner. The probes vary packet order
and membership so a case can include both positive and negative witnesses.

## Simplified

Simplified retains only the first probe for every specification. The
executable benchmark records this variant from the actual first-probe results
inside the Full run, so no result is inferred from filter syntax. This removes
two thirds of the capture executions but also removes their witnesses. Its
latency sample is a deterministic subset rather than a separate interleaved
timing experiment.

## Commands

Run from the repository root with Docker Desktop in Linux-container mode:

```text
docker compose --profile dev --profile pilot build test lab
docker compose --profile dev run --rm test pyink --check src tests scripts
docker compose --profile dev run --rm test isort --check-only src tests scripts
docker compose --profile dev run --rm test pyright
docker compose --profile dev run --rm test pylint src
docker compose --profile dev run --rm test lint-imports --no-cache
docker compose --profile dev run --rm test
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/benchmark_gate.py --phase suite --source-revision 705ed13+working-tree --output-dir /workspace/artifacts/benchmark-final
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/benchmark_gate.py --phase stability --source-revision 705ed13+working-tree --output-dir /workspace/artifacts/benchmark-final --restart-stability
```

## Results

| Measure | Full | Simplified | Delta |
| --- | ---: | ---: | ---: |
| Reference labels agree | 108/108 | 36/36 | 0 failures |
| Typed candidate labels agree | 108/108 | 36/36 | 0 failures |
| Near-wrong mutations killed | 36/36 | 35/36 | +1 case |
| Mutation kill rate | 100% | 97.22% | +2.78 points |
| Actual tshark calls | 324 | 108 | +216 |
| Measured call samples | 324 | 108 | +216 |
| Median call latency | 82.574 ms | 82.760 ms | -0.186 ms |
| p95 call latency | 91.966 ms | 91.966 ms | 0.000 ms |
| Probes per specification | 3 | 1 | +2 |
| Production modules | 1 | 1 | 0 |

The only mutation missed by Simplified was `syn-no-ack`. Probe one
intentionally omits a SYN-ACK packet, so the incorrect mutation cannot be
distinguished there. Probes two and three contain the positive counterexample
and kill it. The `syn-and-ack` case has an intentional negative-only first
probe and positive witnesses in probes two and three. The measured Docker suite
passed all 36 cases: reference 108/108, typed candidate 108/108, and mutation
kills 36/36.

The local raw suite report remains under the ignored `artifacts/` directory
and is not intended for upload.

## Decision

`keep_full`. Simplified remains above the aggregate 95 percent mutation gate,
but it demonstrably loses a semantic counterexample. Behavior is therefore
not equivalent, so the two additional probes remain. This result is limited
to curated synthetic captures and the pinned runtime. It does not establish
model compile validity, model silent-wrong rate, held-out generalization, or
global display-filter equivalence.
