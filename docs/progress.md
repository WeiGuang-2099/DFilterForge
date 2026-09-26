# Implementation Progress

Last updated: 2026-09-26

## Current slice

The test split is frozen and the model bake-off registered; its dev passes are
next. Generated reports under the ignored `artifacts/` are not project evidence.

## Completed: pilot oracle, up to 2026-09-14

- Docker: a source-verified Wireshark 4.6.8 multi-stage Dockerfile, hardened
  Compose profiles, a locked Python environment, CI gates and the recorded Web
  application; no third-party runtime dependency, service, queue, database
  server, Docker socket or agent framework.
- Runner ([ablation 001](ablations/001-bounded-tshark-runner.md)): display
  filters go as argv with `shell=False`; captures are snapshotted and bounded
  in time, output and frames; the subprocess group is cleaned up.
- Catalog ([ablation 002](ablations/002-frozen-field-catalog.md)): 266,369
  field and 1,709,593 value rows, frozen read-only; two independent freezes
  gave identical bytes, and unsupported types fail closed. Full rejected 10/10
  invalid inputs before any capture ran, Simplified 2/10: `keep_protected`.
- Benchmark ([ablation 003](ablations/003-multi-probe-semantic-benchmark.md)):
  36 specifications, three probes and one near-wrong mutation each, 50
  distinct captures, a reviewed manifest. The Docker suite passed reference
  108/108, typed 108/108 and mutation kills 36/36 (324 tshark calls, 82.57 ms
  median, 91.97 ms p95). One probe alone missed `syn-no-ack`: `keep_full`.
- Trace and replay ([ablation 004](ablations/004-predicate-trace-executable-replay.md)):
  12/12 counterexamples traced on both sides and 12 broad-SYN extra frames
  diagnosed; a reference-label drift was rejected by Full and accepted by
  Simplified: `keep_full`. Traces are bounded (64 paths, 64 tshark calls, 1,024
  frames, 65,536 cells) and keep frame numbers, never payloads. Replay compares
  frame tuples; the benchmark runner restarts, resumes and rejects stale input.

## Replan and model evaluation path: 2026-09-15 to 2026-09-21

- `docs/protocol.md` and `docs/adr/0002-hosted-inference-and-small-model.md`
  replace the 200 AUD pilot PRD: hosted prompt baselines, QLoRA-SFT and
  verifier-labelled DPO on a 1.7B-class model, GRPO measured but not trained,
  total spend under 50 USD. `LICENSE` (MIT) and `NOTICE` (Wireshark
  GPL-2.0-or-later) were added. The Web keeps Evaluate and Methodology; its
  build, typecheck, ESLint, Playwright and axe checks passed locally.
- The field-name grammar accepts all 266,363 catalog names (149,890 before).
  Retrieval ranking at k=16 put every gold field in context for 10/16 dev
  items, up from 1/16; the test split, measured once after the rules froze,
  went from 2/32 to 12/32 (`docs/decisions/field-retrieval-ranking.md`).
- The runner reports an unknown field from tshark's own diagnosis (ablation
  001 addendum). `dfilterforge score` classifies stored completions, verifies
  gold first and reproduces its output with `--check`
  (`docs/decisions/offline-scoring.md`); CI re-scores every committed run.
- The dev prompts for C1 to C4 are frozen with their prepare receipt; a host
  test fails when a file such a receipt hashes changes before its call.

## Dev runs and gold corrections: 2026-09-23 and 2026-09-24

- qwen/qwen3-32b answered all 64 dev requests twice, served by DeepInfra with
  0 reasoning tokens, for 0.0059 and 0.0065 USD
  (`docs/decisions/first-dev-run.md`, `docs/decisions/typed-ir-prompt-v2.md`).
  Typed-IR prompt v2 says how each value is written; it took quoted typed
  values from 30 to 0. Byte-identical C1 and C2 prompts changed 6 of 32 answer
  texts and 1 outcome, so no single-item difference is an effect.
- The probes gained a 31-witness tail and `scripts/probe_adequacy.py` became a
  strict CI gate (ablation 005, `keep_full`): surviving single-site mutants
  fell from 65 to 4, all waived as equivalent, and three first-run answers that
  no probe had separated from the gold became silent-wrong.
- [DNS and FIN](decisions/dns-off-port-and-fin-ack.md): 3 of 192 mutants
  survived the 31-witness probes unwaived (dev 2, test 1); two witnesses make
  the tail 33 packets and leave 0. Re-scoring in place (gold 8a061589fe6c)
  flipped only v2 C3/mei-0011, strong exact to silent-wrong: v2 C3 is 7 of 16,
  C4 - C3 +0.188 [0.000, 0.500], inconclusive; controls stay 64/64 and 32/32.

## Shortcut policy, non-ready scoring and case expansion: 2026-09-24

- Shortcut policy pre-registered in `docs/protocol.md` (422d9fa) before the code
  and amended before any test call after a review found an octal-literal crash
  and rule gaps (8b2f578, 42274fd): a `shortcut` answer is never strong exact.
- Ablation 006, `keep_full`: catalog types catch 2,470 of 2,470 frame-number
  and time fields, names alone 21. Of 8 shortcut filters written up front, 6
  match their probes; Full flags all 6, names alone pass 3 as strong exact. No
  gold candidate (264) or committed answer (84) is flagged, and no committed
  outcome changes.
- Non-ready scoring pre-registered (8ba42c8) before the code (7b655b0), as
  `docs/protocol.md` states it. After the code and before any test item, 508cdda
  added false-ready per gold status and said what slot match counts, and a
  review closed 15 gaps (8285726). No committed outcome moved.
- [Case expansion](decisions/case-expansion.md): 52 ready cases (12 dev, 40
  test) and 24 non-ready (4+4 dev, 8+8 test), 152 items, numbered per split and
  gold kind. The 16 old test cases' 32 requests were rewritten, the 16 dev
  items of the published runs are unchanged, and a dev pass is 160 requests.
- Adequacy gate, strict, at bb39ab7: 344 mutants (72 dev, 272 test), 0 unwaived
  survivors, the same 4 waivers, 0 label mismatches.
- Under compose.yaml, pytest kept every tmp_path until the session ended, so at
  684c78f the 128 MB /tmp tmpfs filled and 21 tests failed with ENOSPC; b3fa85f
  keeps only failed tests' directories.

## Feedback probe: 2026-09-25

- Pre-registered (36cff89) before the code: a repair round shows packets only
  from one unscored probe per split, an item that probe cannot separate stays
  in the repair@1 denominator, and the gate checks it. Ablation 007 says why
  one capture per split, not per case, and why the ARP witness was dropped.
- `dfilterforge.model_feedback` (1db1b50) copies semantic-29 (dev) and
  semantic-35 (test) with the witness tail through the scored probes' helper
  (d47eb32) into `feedback/`. No scored capture, gold hash (8a061589fe6c) or
  model input changes; an import contract keeps scoring from the module and a
  test keeps it off `scripts/model_run.py`.
- Gate `probe-adequacy/1.2` (11e01d7, tests 52a29d5) checks the gold filters
  on all eight probes and runs every mutant on the feedback probe too; strict
  mode passes with the counts in ablation 007.
- [Ablation 007](ablations/007-feedback-probe.md), `keep_full`: without the
  tail, 112 mutants, 10 authored mutations and 6 of 24 committed silent-wrong
  answers get no packet; with it, 24 of 24, and none of 60 strong-exact
  answers gets a false one.
- CI python job in the test image at 52a29d5: 1,019 tests, 1 skipped, 96.55
  percent coverage, static checks and all gates pass. `score --check`
  reproduced all six committed outputs at 11e01d7; later commits change only
  docstrings and tests.

## Test freeze code: 2026-09-25

- Pre-registered in `docs/protocol.md` (d575ca2) before the code. A prepare
  hashes 12 files, up from 8 (7677129); the v2 typed-IR system prompts are
  pinned (6cd3e90). `prepare --split test` builds the 112 test items, and the
  call refuses a non-dev prompt set the committed record does not admit
  (eea7a41); `dfilterforge.held_out_digests` writes that record (e37a7a7).
- [Test freeze](decisions/test-freeze.md) holds the hashed files, refusal
  codes, lab control timings and a table before (ea4656f) and after (e37a7a7):
  a C4-only run now scores 40 items (dd7de1e) and manifest-less test answers
  are refused with `split_violation` (e4d0ed4).
- CI python job in the test image at e37a7a7: 1,050 tests, 2 skipped, 96.55
  percent coverage, peak /tmp 12.2 MiB; static checks and all gates pass, and
  `score --check` reproduced all six committed outputs.

## Test freeze: 2026-09-26

- At 7590e4d, with rebuilt images, `score --check` reproduced all six
  committed outputs and the strict gate passed: 344 mutants, 4 waived
  survivors, 0 unwaived (`decisions/evidence/test-freeze-gate.json`).
- Dev and test prompts were prepared ten seconds apart in one image: 40 and
  112 items, C1 to C4, top-k 16, no empty context; the dev set is 3d71c39.
  The 16 dev items of the v2 run are byte-identical in all four conditions.
  Lab controls: dev reference 96 strong exact and 64 abstained of 160,
  mutation 48 silent-wrong and 32 false-ready of 80; test reference 320 and
  128 of 448 in 183 s, mutation 160 and 64 of 224 in 102 s.
- `src/dfilterforge/held_out_freeze.json` admits only the committed test
  `prepare.json` (206599bb67e1) and holds the digests of the test inputs,
  gold with routing, gold hash, feedback labels and four captures, quoted in
  `docs/protocol.md`. The record test no longer skips, and a host test ties
  the committed test `prepare.json` and those quotes to the record.
- CI python job in the test image at the freeze commit: 1,059 tests, 1
  skipped (no docs/ in the image), 96.55 percent coverage; static checks and
  all gates pass, and `score --check` reproduced all ten committed outputs.

## Model bake-off registered: 2026-09-26

- Before any test request the owner turned the 70B- and DeepSeek-V3-class slots
  into about 120B-class and frontier open-weight MoE slots: deepseek-v3.2 leaves
  OpenRouter on 2026-09-28, and Llama 3.3 70B's coding index trails the 32B's.
- The [model bake-off](decisions/model-bakeoff.md), part of the protocol, lists
  per slot three ranked candidates and a reserve, their slugs, eight fallbacks,
  run ids, the rule and a two-turn smoke. `scripts/dev_bakeoff_configs.py` wrote
  the 21 call configs and endpoints snapshot keyless at 2026-09-26T10:05:28Z,
  matching the note. No bake-off request has been sent.
- `scripts/dev_bakeoff.py` runs the passes, resumes transient failures after
  60 s and refuses uncommitted tooling; 107 tests pass; keyless, it exits 3.

## Planned next

1. Merge the note, protocol, runner and configs, run `scripts/dev_bakeoff.py`,
   then the two-turn smoke as a second owner command; complete passes are
   published and scored, the rest kept as evidence.
2. Write each hosted test run's run id, model id, provider and settings into
   `docs/protocol.md` or the bake-off note before the first test request, then
   run qwen/qwen3-32b passes A and B and the slot winners on test. The 12 hashed
   files stay unchanged until the last baseline request.
3. Counterexample repair with three feedback arms, the feedback sent as a
   second conversational turn; hosted static page generated from receipts.
4. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed, and the
  standalone hash-validation phase was intentionally not run; the stopped local
  run reached 28 captures and 4,200 exact pairs without a difference, but
  partial measurements are not release evidence.
- Only one model has been measured, twice, on 8 dev cases and no non-ready
  gold; every comparison is inconclusive by construction, and false-ready rate
  and slot match are unmeasured. Test-split baselines, SFT, DPO and GRPO remain
  unmeasured; the complete Pilot Go/No-Go decision is unverified.
- The Web remains recorded-only; Linux CI teardown and the production
  container were not re-verified, so no live Web job boundary is enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Hosted CI on the freeze: the record test runs and ten outputs re-score.
2. Locked-test run replayed offline from a clean checkout without an API key.
3. Web numbers checked against the scored summary by a CI test.
