# Implementation Progress

Last updated: 2026-09-23

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

## Model evaluation path: 2026-09-21

- The field-name grammar accepts all 266,363 distinct names in the image
  catalog. The 1c64140 grammar accepted 149,890 of them, and retrieval raised
  on 10 of the 16 dev items at top_k 16.
- Retrieval ranking at k=16: dev items with every gold field in context went
  from 1/16 to 10/16, and gold fields found from 4/36 to 27/36. The test split
  was measured once, after the rules were frozen on dev, and is reported as
  aggregates only: 2/32 to 12/32 and 10/68 to 44/68. The receipts are under
  `docs/decisions/evidence/`.
- The runner classifies tshark exit status and reports an unknown field from
  tshark's own diagnosis; all six exit-status witnesses were `tshark_failed`
  before (ablation 001 addendum).
- `dfilterforge score` classifies stored completions into the six outcomes,
  verifies gold before it reads any answer, and reproduces its output with
  `--check` without writing (`docs/decisions/offline-scoring.md`).
- The gold-derived reference control is strong exact on 16/16 items in each
  of C1 to C4, and the authored mutations are silent-wrong on 16/16 in C1 and
  C2. `--check` reproduces both with no differences.
- The dev prompts for C1 to C4 and their prepare receipt are frozen under
  `docs/results/dev-qwen3-32b-2026-09-21/`, prepared against the image
  catalog; the gzip archive on the host gives the same four prompt files byte
  for byte. A later docstring edit to `scripts/model_run.py` made the call
  refuse the receipt (`prepare_code_mismatch`), so it was re-frozen the same
  UTC day with identical prompt bytes and both controls re-scored; a host
  test now fails whenever a file such a receipt hashes changes before its call.
- The Docker Python suite passed 796 tests with 96.07 percent total
  branch-aware coverage; the freeze guard skips there, as the image carries
  no `docs/` tree, and passes on the host.
- CI has a step that re-scores every committed output directory offline with
  `--check`. It ran green on the hosted runner for the merge of PR #2 (as
  reported from the GitHub Actions page; not re-checked locally).
- No model had run by then. Nothing in this entry is a model result.

## First dev run: 2026-09-23

- qwen/qwen3-32b answered all 64 dev requests (C1 to C4), every one served by
  DeepInfra with 0 reasoning tokens, for 0.0059 USD. The raw answers, attempts,
  manifest and offline score are under
  `docs/results/dev-qwen3-32b-2026-09-21/`; `score --check` reproduces them.
- Strong exact out of 16: C1 10, C2 9, C3 1, C4 8. Silent-wrong: 2, 4, 0, 1.
  Every comparison is inconclusive by construction with 8 cases.
- An independent audit re-derived every outcome and summary number and found
  no scoring error. It found that the typed-IR prompt never defines how a
  value is written, so C3 and C4 - C3 mostly measure value typing; that three
  strong exact answers (C1 mei-0005 and mei-0006, C4 mei-0013) are wrong but
  no probe separates them; and that provider_changed true in the summary is a
  case-sensitive false alarm. Details and item ids are in
  `docs/decisions/first-dev-run.md`.

## Planned next

1. Fix the report: provider_changed compares the pinned slug with the served
   name case-insensitively; the cost column and the exec-rate denominator are
   labelled. No metric changes; regenerate the three committed summaries.
2. Typed-IR prompt v2 that states value encodings, protocol presence and the
   all/any arity, then a new dev run of all four conditions, which also
   repeats C1 and C2 under unchanged prompts.
3. Witness recipes for the three probe gaps (ACK sent from port 443, ACK with
   an acknowledgment number other than 1, ECE without SYN), then re-score the
   stored dev answers offline; boundary witnesses, shortcut policy, non-ready
   gold, frozen test set (`docs/protocol.md` splits table).
4. Counterexample repair with three feedback arms; four hosted models on the
   frozen test; hosted static page generated from receipts.
5. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed. The
  stopped local run reached 28 captures and 4,200 exact pairs without a
  difference, but partial measurements are not release evidence.
- Only one model has been measured, on 8 dev cases under prompt v1, and its
  typed-IR rows are confounded by the prompt gap above. Test-split baselines,
  SFT, DPO, and GRPO remain unmeasured. The complete Pilot Go/No-Go decision is
  still unverified.
- The 12+4+4 dev split (8+0+0 built) and the frozen test hashes do not exist
  yet, so false-ready rate and slot match are unmeasurable.
- The complete 50-capture by 150-filter stability gate remains unverified, and
  the standalone hash-validation phase was intentionally not run.
- The Web remains recorded-only. Linux CI teardown and the current production
  container were not re-verified in this session, so no live Web job boundary
  should be enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Typed-IR prompt v2 dev run beside v1, with the witness-corrected gold.
2. Boundary-witness ablation: count of loosened-threshold mutations that were
   reward-identical before and after witnesses.
3. Locked-test run replayed offline from a clean checkout without an API key.
4. Web numbers checked against the scored summary by a CI test.
