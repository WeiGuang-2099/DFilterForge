# Implementation Progress

Last updated: 2026-09-23

## Current slice

Probe witnesses and the mutation-adequacy gate for the model split (ablation
005) are implemented and verified. Local generated benchmark reports stay under
the ignored `artifacts/` directory and are not uploadable project evidence.

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

## Replan: 2026-09-15

- The 200 AUD pilot PRD is withdrawn for `docs/protocol.md` and
  `docs/adr/0002-hosted-inference-and-small-model.md`: hosted prompt
  baselines, QLoRA-SFT and verifier-labelled DPO on a 1.7B-class model, GRPO
  measured but not trained, total spend under 50 USD. `LICENSE` (MIT) and
  `NOTICE` (Wireshark GPL-2.0-or-later) were added. The Web keeps two routes,
  Evaluate (a labelled hand-written example) and Methodology; its build,
  typecheck, ESLint, Playwright and axe checks passed locally.

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
  Every comparison is inconclusive by construction with 8 cases. (Before the
  gold correction of the next entry, which moved C1 to 8 and C4 to 7.)
- An independent audit found no scoring error, but a typed-IR prompt that
  never defines value encoding, three strong exact answers no probe separated
  from the gold, and a case-sensitive provider_changed false alarm
  (`docs/decisions/first-dev-run.md`).
- The report now matches route slugs to provider names, prints cost per
  item, the executed count, thin intervals and inconclusive-by-construction;
  the re-score changed only provider_changed, timings and revisions. The
  Docker suite passed 803 tests at 96.10 percent coverage.

## Probe witnesses: 2026-09-23

- Each model split probe is now its benchmark capture byte for byte plus 31
  witness packets (`dfilterforge.witnesses`), which tshark 4.6.8 decodes with
  no malformed frame or TCP analysis flag; dev and test share no packet.
  Reference, canonical IR and authored mutation match their labels on all six
  probes (144/144 each); review removed one wrong mutation label.
- `scripts/probe_adequacy.py`, now strict in CI: of 182 single-site mutants,
  65 survived before (dev 19, test 46) and 4 after, all on test and waived as
  equivalent. Interleaved per-call tshark p50 60.123 against 59.945 ms (one
  session; the level varies by session). Ablation 005: `keep_full`.
- The dev run was re-scored in place: C1 mei-0005 and mei-0006 and C4 mei-0013
  are now silent-wrong (25 strong exact and 10 silent-wrong; C1 8, C4 7), the
  controls stay 64/64 and 32/32, and `--check` reproduces all three trees. The
  old summary is at 1b5d230. The Docker suite passed 879 tests (1 skipped) at
  96.34 percent coverage; static gates and the benchmark gate (108/108, 36/36)
  are clean.
- Leftovers: no tail on the 36-spec suite probes; semantic-43 frame 28 is still
  malformed Manolito (udp 41170); ablation 004 evidence predates the tail; the
  mDNS reading of fin-or-dns-response is in evaluator gold only.

## Typed-IR prompt v2: 2026-09-23

- The typed-IR system prompt now states how each bound type is written, that
  a protocol takes only exists, and that all and any need two children. It
  names no field. Scoring keeps every system prompt version, so the first run
  still re-scores; tests pin its four system prompt hashes.
- `docs/results/dev-qwen3-32b-v2-2026-09-23/` holds the prompts prepared at
  33ad868: C1 and C2 are byte-identical to the first run's, C3 and C4 differ
  only in the system message. The reference control is strong exact on 64/64
  and the mutation control silent-wrong on 32/32.
- The Docker suite passed 887 tests (1 skipped) at 96.34 percent coverage;
  every committed tree reproduces with `score --check`.

## Planned next

1. Call the v2 dev run (the only paid step), score it, and write a decision
   note comparing C3 and C4 with the first run; C1 and C2 give a repeat.
2. Shortcut policy, non-ready gold, frozen test set (`docs/protocol.md`
   splits table); witnesses for the 36-spec suite only if it is ever used to
   score a model.
3. Counterexample repair with three feedback arms; four hosted models on the
   frozen test; hosted static page generated from receipts.
4. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed, and
  the standalone hash-validation phase was intentionally not run. The stopped
  local run reached 28 captures and 4,200 exact pairs without a difference,
  but partial measurements are not release evidence.
- Only one model has been measured, on 8 dev cases under prompt v1, and its
  typed-IR rows are confounded by the prompt gap above. Test-split baselines,
  SFT, DPO, and GRPO remain unmeasured. The complete Pilot Go/No-Go decision is
  still unverified.
- The 12+4+4 dev split (8+0+0 built) and the frozen test hashes do not exist
  yet, so false-ready rate and slot match are unmeasurable.
- The Web remains recorded-only; Linux CI teardown and the production
  container were not re-verified, so no live Web job boundary is enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Typed-IR prompt v2 dev run beside v1, with the witness-corrected gold.
2. Locked-test run replayed offline from a clean checkout without an API key.
3. Web numbers checked against the scored summary by a CI test.
