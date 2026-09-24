# Implementation Progress

Last updated: 2026-09-24

## Current slice

The shortcut policy (ablation 006) is implemented and verified. Generated
reports under the ignored `artifacts/` directory are not project evidence.

## Completed: pilot oracle, up to 2026-09-14

- Docker: a source-verified Wireshark 4.6.8 multi-stage Dockerfile, hardened
  Compose profiles, a locked Python environment, CI gates and the recorded Web
  application. No third-party runtime dependency, service, queue, database
  server, Docker socket or agent framework was added.
- Runner ([ablation 001](ablations/001-bounded-tshark-runner.md)): display
  filters go as argv with `shell=False`; captures are snapshotted and bounded
  in time, output and frames; the subprocess group is cleaned up.
- Catalog ([ablation 002](ablations/002-frozen-field-catalog.md)): 266,369
  field rows and 1,709,593 value rows, frozen read-only; two independent
  freezes gave identical bytes. Runtime binding checks tshark 4.6.8, the
  isolated profile, fields and projections; unsupported types fail closed.
  Full rejected 10/10 invalid inputs before any capture ran, Simplified 2/10:
  `keep_protected`.
- Benchmark ([ablation 003](ablations/003-multi-probe-semantic-benchmark.md)):
  36 specifications, three probes and one near-wrong mutation each, 50
  distinct captures, a reviewed manifest. The Docker suite passed reference
  108/108, typed 108/108 and mutation kills 36/36 (324 tshark calls, 82.57 ms
  median, 91.97 ms p95). One probe alone missed `syn-no-ack`: `keep_full`.
- Trace and replay ([ablation 004](ablations/004-predicate-trace-executable-replay.md)):
  12/12 counterexamples traced on both sides and 12 broad-SYN extra frames
  diagnosed; a reference-label drift was rejected by Full and accepted by
  Simplified: `keep_full`. Traces are bounded (64 paths, 64 tshark calls,
  1,024 frames, 65,536 cells) and keep frame numbers, never payloads; replay
  compares frame tuples, not recorded hashes. The benchmark runner restarts,
  resumes and rejects stale input.
- At that point the Docker suite passed 224 tests at 95.60 percent coverage,
  with pyright strict, pylint 10/10, pyink, isort and the core import
  contract clean.

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

- The typed-IR system prompt states how each bound type is written, that a
  protocol takes only exists, and that all and any need two children; it
  names no field. Scoring keeps every system prompt version, so the first run
  still re-scores. The Docker suite passed 887 tests at 96.34 percent.
- The v2 prompts were prepared at 33ad868: C1 and C2 byte-identical to the
  first run's, C3 and C4 differing only in the system message. Controls:
  64/64 strong exact and 32/32 silent-wrong.
- The v2 run (64 answers, 0.0065 USD, DeepInfra, 0 reasoning tokens) moved
  strong exact from 8, 9, 1, 7 to 9, 9, 8, 10 in C1 to C4; quoted typed values
  fell from 30 to 0 and C4 silent-wrong rose from 2 to 5. The byte-identical
  C1 and C2 prompts changed 6 of 32 answer texts and 1 outcome, so no
  single-item difference is an effect (`docs/decisions/typed-ir-prompt-v2.md`).

## DNS and FIN gold correction: 2026-09-24

- The pylint command CI runs failed in the test image from 33ad868 on
  (`generation.py` line 83 of 80 characters). 75ccc59 adds a targeted
  disable; all three system prompt hashes are unchanged.
- Two mutant families, protocol-as-port and flag-as-byte, bring the gate to
  192 mutants. On the 31-witness probes 3 survived without a waiver (dev 2,
  test 1). A DNS query to 10.2.3.6 port 52 and a FIN+ACK from port 443 make
  the tail 33 packets; strict mode then has 0 unwaived survivors and the same
  4 equivalent waivers, and every label check matches on all six probes.
- Both runs and their controls were re-scored in place (gold 8a061589fe6c).
  Only v2 C3/mei-0011 flipped, strong exact to silent-wrong: v2 C3 is 7 of 16
  and C4 - C3 +0.188 [0.000, 0.500], inconclusive. Controls stay 64/64 and
  32/32; `--check` reproduces all six outputs.
- Every step of the CI python job passes, run in the test image at 6079cec
  (888 tests, 1 skipped) and at a1d3724 (899 tests, 1 skipped, 96.35 percent
  branch-aware coverage).

## Shortcut policy: 2026-09-24

- Pre-registered in `docs/protocol.md` (422d9fa) before the code; a review
  then found an octal-literal crash and rule gaps, amended before any test
  call (8b2f578, 42274fd). A probe-exact answer naming capture position or
  state, a generator identifier or an unstated generator constant is
  `shortcut`, never strong exact; ORs are only counted.
- Ablation 006, `keep_full`: catalog types catch 2,470 of 2,470 frame-number
  and time fields, names alone 21. Of 8 shortcut filters written up front, 6
  match their probes; Full flags all 6, names alone pass 3 as strong exact.
  No gold candidate (264) or committed answer (84) is flagged; no outcome of
  the committed runs changes. The CI python job passes in the test image:
  973 tests, 1 skipped, 96.37 percent coverage.

## Planned next

1. Non-ready gold and the frozen test set (`docs/protocol.md` splits table).
2. Counterexample repair with three feedback arms; four hosted models on the
   frozen test; hosted static page generated from receipts.
3. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed, and
  the standalone hash-validation phase was intentionally not run. The stopped
  local run reached 28 captures and 4,200 exact pairs without a difference,
  but partial measurements are not release evidence.
- Only one model has been measured, twice, on 8 dev cases, and every
  comparison is inconclusive by construction. Test-split baselines,
  SFT, DPO, and GRPO remain unmeasured. The complete Pilot Go/No-Go decision is
  still unverified.
- The 12+4+4 dev split (8+0+0 built) and the frozen test hashes do not exist
  yet, so false-ready rate and slot match are unmeasurable.
- The Web remains recorded-only; Linux CI teardown and the production
  container were not re-verified, so no live Web job boundary is enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Hosted CI on the gold correction and shortcut policy, pylint included.
2. Locked-test run replayed offline from a clean checkout without an API key.
3. Web numbers checked against the scored summary by a CI test.
