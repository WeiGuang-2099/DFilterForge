# Implementation Progress

Last updated: 2026-09-10

## Current slice

The frozen tshark catalog, reviewed multi-probe semantic benchmark, predicate
trace, and executable replay slices are implemented and verified. The complete
50-capture by 150-filter stability gate remains unverified by explicit choice.
Local generated benchmark reports remain under the ignored `artifacts/`
directory and are not part of the uploadable project evidence.

## Completed

- A source-verified Wireshark 4.6.8 multi-stage Dockerfile, hardened Compose
  profiles, locked Python environment, CI quality gates, and the recorded Web
  application are present.
- The bounded runner passes display filters as argv with `shell=False`,
  snapshots bounded regular-file captures, limits time, output, and frame
  count, and cleans up the subprocess group. Ablation 001 retains it.
- The Docker build freezes the complete tshark inventory into a read-only
  SQLite catalog. The measured image contains 266,369 field rows and 1,709,593
  value rows.
- Two independent real tshark freezes produced identical SQLite bytes and
  matched the image catalog. Runtime binding verifies tshark 4.6.8, the
  isolated profile, requested fields, and any supplied field projection before
  compilation.
- Unsupported tshark types remain visible and fail closed. Tests cover unknown
  and conflicting fields, type and operator errors, runtime drift, malformed
  metadata, incorrect counts, truncated tables, and forged projections.
- Ablation 002 ran 27 paired valid-workload samples and 10 invalid safety
  witnesses. Both variants matched all valid results. Full rejected 10/10
  invalid inputs before capture execution; Simplified rejected 2/10 and crossed
  the capture boundary for eight. The decision is `keep_protected`.
- The pilot benchmark has 36 semantic specifications, three primary probes per
  specification, one near-wrong mutation per specification, and 50 generated
  captures with 50 distinct recipe layouts and byte contents.
- An independent read-only review checked every case, reference filter,
  mutation, recipe membership, direction witness, intentional negative probe,
  packet checksum, and final capture diversity. The generated manifest is
  `ready` and `reviewed`.
- A Docker semantic suite run passed reference agreement 108/108, typed
  candidate agreement 108/108, and mutation kills 36/36. Its 324 measured
  tshark calls had 82.57 ms median and 91.97 ms p95 latency.
- Ablation 003 compared all three probes with the first probe alone. Full
  killed 36/36 mutations; Simplified killed 35/36 and missed `syn-no-ack`.
  The decision is `keep_full` because the variants are not behaviorally
  equivalent.
- Ablation 004 measured 12 valid executable replay samples per variant using
  real tshark 4.6.8. Both variants were exact on valid candidate tuples. Full
  verified all 12 references, traced 12/12 counterexample frames on both
  candidate and canonical sides, and diagnosed all 12 broad-SYN extra frames.
  A real reference-label drift witness was rejected by Full and falsely
  accepted by candidate-only Simplified. The decision is `keep_full`.
- Predicate traces are bounded to 64 predicate paths, 64 tshark calls, 1,024
  counterexample frames, and 65,536 trace cells. Exact probes do not execute
  leaf predicates; mismatch probes retain only frame numbers and predicate
  memberships, never raw packet payloads.
- Executable replay compares actual frame tuples and does not trust recorded
  data, receipt, packet-set, or environment hash claims. Existing capture
  identity checks remain internal execution safety checks.
- The benchmark runner supports explicit restart, exact frame-tuple comparison,
  reversed second-pass filter order, atomic progress replacement, stale-input
  rejection, and resume from a validated completed capture.
- The Docker Python suite passed 224 tests with 95.60 percent total
  branch-aware coverage. After the final measurement-script change, all 45
  affected benchmark tests passed again.
- Pyright strict, Pylint 10/10 for production source, Pyink, isort, and the core
  import contract passed. The domain core remains independent of interfaces.
- The catalog and semantic benchmark add no third-party runtime dependency,
  service, queue, database server, Docker socket, or generic agent framework.
- The recorded Web routes and their previously measured TypeScript, ESLint,
  production-build, Playwright, and accessibility results are unchanged by
  this Python-only slice.

## Planned next

- Compare prompt-only, field-retrieval, and typed-IR baselines on a held-out
  model-facing evaluation split.
- Measure model compile validity and silent-wrong rate, then assemble the Pilot
  Go/No-Go report.
- Record the outstanding executable ablations for the earlier core and recorded
  Web slices.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed. The
  stopped local run reached 28 captures and 4,200 exact pairs without a
  difference, but partial measurements are not release evidence.
- Model compile validity, silent-wrong rate, prompt and retrieval baselines,
  SFT, DPO, and GRPO remain unmeasured. The complete Pilot Go/No-Go decision is
  still unverified.
- The complete 50-capture by 150-filter stability gate remains unverified, and
  the standalone hash-validation phase was intentionally not run.
- The Web remains recorded-only. Linux CI teardown and the current production
  container were not re-verified in this session, so no live Web job boundary
  should be enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Run prompt-only, retrieval, and typed-IR model baselines and measure compile
   validity, semantic accuracy, mutation sensitivity, and silent-wrong rate.
2. Add clarification and not-expressible cases, then produce the Pilot
   Go/No-Go report.
3. Re-verify the Web production container and Linux Playwright teardown before
   enabling any live Web execution boundary.
