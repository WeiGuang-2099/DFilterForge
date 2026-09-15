# Implementation Progress

Last updated: 2026-09-15

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

## Replan: 2026-09-15

- The 200 AUD cloud pilot PRD is withdrawn. The public protocol is now
  `docs/protocol.md` (four prompt conditions, splits, metrics, decoding and
  provenance rules, training rules) and the decision is recorded in
  `docs/adr/0002-hosted-inference-and-small-model.md`: hosted endpoints for
  prompt baselines, a 1.7B-class model for QLoRA-SFT and verifier-labelled
  DPO, GRPO measured but not trained, total spend under 50 USD.
- Added `LICENSE` (MIT) and `NOTICE` (Wireshark GPL-2.0-or-later attribution
  for the tshark build and the frozen catalog).
- The Web now has two routes, Evaluate and Methodology. The hand-written
  benchmark table, the placeholder ablation, receipt and workbench pages are
  removed. The Evaluate page is labelled as a hand-written illustrative
  example until it is regenerated from a real receipt. Web build, typecheck,
  ESLint, Playwright and axe checks pass locally.
- Shared `dfilterforge.errors.DFilterForgeError` base introduced; the model
  scaffolding is being committed behind tests and the core modules are
  getting a duplication and dead-code pass. No measured behaviour changes.
- No model inference or training has run yet. Nothing in this entry is a
  measured result.

## Planned next

1. By 2026-09-21: one hosted model on the dev split under all four conditions,
   scored offline in the lab container, with the table committed and one real
   number in the README.
2. Boundary witnesses, shortcut policy, non-ready gold, frozen test set
   (`docs/protocol.md` splits table).
3. Counterexample repair with three feedback arms; four hosted models on the
   frozen test; hosted static page generated from receipts.
4. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

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

1. First dev-split model table committed with raw completions and receipts.
2. Boundary-witness ablation: count of loosened-threshold mutations that were
   reward-identical before and after witnesses.
3. Locked-test run replayed offline from a clean checkout without an API key.
4. Web numbers checked against the scored summary by a CI test.
