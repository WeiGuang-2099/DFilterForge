# Ablation 002: Frozen tshark Field Catalog

Status: complete on 2026-09-09

## Hypothesis

The catalog freeze and runtime binding can be replaced by a version-only
compile path while preserving valid packet results, rejecting untrusted field
input before capture execution, and staying within the five percent p95
performance threshold.

## Frozen inputs

- Code revision label: `705ed13+working-tree`.
- Environment: project Docker test image derived from the pinned tshark 4.6.8
  runtime image, isolated default profile, name resolution disabled.
- Dataset: three curated semantic cases, nine captures, and seeds 17, 42, 2026.
- Repetitions: three, producing 27 paired valid-workload samples and 81
  bounded capture calls per variant.
- Quality threshold: both fresh freezes must be byte-identical to each other
  and to the catalog baked into the image; all valid labels, paired packet
  sets, and mutation results must match; Full must reject every invalid safety
  witness before capture execution.
- Simplification threshold: Simplified must not reach capture execution for an
  input that Full rejects before capture execution.
- Performance threshold: Simplified total p95 may regress by no more than five
  percent relative to Full.

## Full

Full freezes the complete `tshark -G fields` and `tshark -G values` inventory
into indexed SQLite using canonical record order. At compilation time it binds
only fields referenced by the IR, while checking the actual tshark version and
isolated runtime profile against the immutable image catalog. A supplied field
projection cannot add, remove, or alter definitions. The compiler then checks
field existence, field type, operator compatibility, and value type before any
capture is opened.

## Simplified

Simplified is the executable `_simplified_compile` candidate in
`scripts/catalog_ablation.py`. It retains the actual pinned-version check, but
deletes frozen-inventory lookup, runtime-profile binding, and typed field
validation. Valid candidates are compiled and all compiled, reference, and
mutation filters are executed through the same bounded `TsharkRunner` as Full.

Safety witnesses also execute this real candidate against a curated capture.
The evidence separately counts Full and Simplified calls that reach
`TsharkRunner.run`; a tshark rejection after that call is not treated as a safe
pre-execution rejection.

## Commands

Run from the repository root with Docker Desktop in Linux-container mode:

```text
docker compose --profile dev --profile pilot build test lab
docker compose --profile pilot run --rm lab fixtures generate --output-dir /workspace/artifacts/ablation-002-fixtures
docker compose --profile dev run --rm --volume "${PWD}/artifacts:/workspace/artifacts" test python scripts/catalog_ablation.py --fixtures /workspace/artifacts/ablation-002-fixtures --output /workspace/artifacts/002-catalog-ablation.json --code-revision REVISION+working-tree --repetitions 3
docker image inspect dfilterforge-test:0.1.0 dfilterforge-lab:0.1.0 --format "{{.RepoTags}} {{.Id}}"
docker compose --profile dev run --rm test pyink --check src tests scripts
docker compose --profile dev run --rm test isort --check-only src tests scripts
docker compose --profile dev run --rm test pyright
docker compose --profile dev run --rm test pylint src
docker compose --profile dev run --rm test lint-imports --no-cache
docker compose --profile dev run --rm test
```

The two generated 299 MB-class SQLite files were temporary and were removed
after the experiment.

## Results

Both independent freezes produced the same 299,327,488-byte SQLite image and
the same bytes as the catalog baked into the tested Docker image. Each contains
266,369 field rows and 1,709,593 value rows. The runtime binding verified the
pinned tshark version, executable, isolated profile, and catalog identity.

| Measure | Full | Simplified |
| --- | ---: | ---: |
| Exact valid labels | 27/27 | 27/27 |
| Paired packet sets equal | 27/27 | 27/27 |
| Near-wrong samples killed | 27/27 | 27/27 |
| Safety witnesses rejected before capture | 10/10 | 2/10 |
| Median bind/compile latency | 14.759 ms | 0.013 ms |
| p95 bind/compile latency | 15.616 ms | 0.015 ms |
| Median total paired-workload latency | 223.421 ms | 207.078 ms |
| p95 total paired-workload latency | 236.602 ms | 223.981 ms |
| Compared nonblank source lines | 370 | 7 |
| Modules in the compared abstraction | 1 | 0 |

The Simplified total p95 was 5.335 percent lower, within the stated performance
threshold. It nevertheless reached capture execution for eight inputs that
Full rejected first, including a mistyped Boolean comparison, wrong profile,
wrong catalog identity, stale field inventory, and tampered field type.

## Decision

`keep_protected`. Full and Simplified were equivalent on the measured valid
workload, and Simplified was faster, but it failed the pre-execution safety
criterion in eight of ten witnesses. The frozen inventory, runtime binding,
and typed validation therefore remain in the production path. This
nine-capture experiment does not verify the separate 50-capture and 150-filter
Pilot stability gate.
