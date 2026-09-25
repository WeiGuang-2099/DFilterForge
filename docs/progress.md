# Implementation Progress

Last updated: 2026-09-25

## Current slice

Each split has an unscored feedback probe for the repair round, checked by
the adequacy gate; the test freeze is next. Generated reports under the
ignored `artifacts/` directory are not project evidence.

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

## Dev runs and gold corrections: 2026-09-23

- qwen/qwen3-32b answered all 64 dev requests twice, served by DeepInfra with
  0 reasoning tokens, for 0.0059 and 0.0065 USD
  (`docs/decisions/first-dev-run.md`, `docs/decisions/typed-ir-prompt-v2.md`).
  Typed-IR prompt v2 says how each value is written; it took quoted typed
  values from 30 to 0. Byte-identical C1 and C2 prompts changed 6 of 32 answer
  texts and 1 outcome, so no single-item difference is an effect.
- The probes gained a witness tail and `scripts/probe_adequacy.py` became a
  strict CI gate (ablation 005, `keep_full`): single-site mutants surviving
  the probes went from 65 to 4, all waived as equivalent. Three first-run
  answers that no probe had separated from the gold became silent-wrong.

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

## Non-ready scoring and case expansion: 2026-09-24

- Non-ready scoring pre-registered in `docs/protocol.md` (8ba42c8) before the
  code (7b655b0): a ready answer to needs_clarification or not_expressible
  gold is `false_ready`, never executed; ready and non-ready gold bootstrap
  separately. After the code and before any test item, 508cdda added
  false-ready per gold status and said slot match counts an answer naming at
  least one gold slot. A review closed 15 gaps (8285726); no committed outcome
  moved.
- [Case expansion](decisions/case-expansion.md): 52 ready cases (12 dev, 40
  test) and 24 non-ready (4+4 dev, 8+8 test), 152 items, numbered per split
  and gold kind. The 32 requests of the 16 old test cases were rewritten; the
  16 dev items of the published runs are unchanged. A dev pass is now 160
  requests.
- Adequacy gate, strict, at bb39ab7: 344 mutants (72 dev, 272 test), 0
  unwaived survivors, the same 4 waivers, 0 label mismatches. A review
  before the freeze found a test request the retriever would refuse,
  four wording or slot problems and item numbers that tied dev to test, all
  fixed. Tests now send every request through the real retriever, reject
  dotted field names and filter operators in requests, and check that the
  committed non-ready gold scores as matched end to end and under the
  reference control.
- The suite at bb037b8 was reported as passing in the test image, but under
  compose.yaml the same code and tests (at 684c78f) do not: pytest keeps every
  tmp_path, the 128 MB /tmp tmpfs fills and 21 tests fail with ENOSPC.
  b3fa85f keeps only failed tests' directories; the run then passes 1,004
  tests, 1 skipped, 96.50 percent coverage, and `score --check` reproduces all
  six committed outputs.

## Feedback probe: 2026-09-25

- Pre-registered in `docs/protocol.md` (36cff89) before the code: a repair
  round shows packets only from one unscored probe per split, an item that
  probe cannot separate stays in the repair@1 denominator, and the gate
  checks it. One capture per split, not per case: every capture holds all 20
  recipes and 33 witnesses. A planned ARP witness was dropped: requests say
  complete Ethernet/IPv4 packets, and it would change every scored capture.
- `dfilterforge.model_feedback` (1db1b50) copies semantic-29 (dev, client
  192.0.2.129) and semantic-35 (test, client .135) with the witness tail
  through the helper the scored probes use (d47eb32), into `feedback/`. No
  scored capture, gold hash (8a061589fe6c) or model input changes; an import
  contract keeps scoring from the module and a test keeps it off
  `scripts/model_run.py`.
- Gate `probe-adequacy/1.2` (11e01d7, tests 52a29d5) checks the gold filters
  on all eight probes and runs every mutant on the feedback probe too. Strict
  mode passes: 416 label checks per filter, 344 mutants, 4 waived survivors,
  0 feedback-blind mutants or mutations, 0 disproved waivers.
- [Ablation 007](ablations/007-feedback-probe.md), `keep_full`: without the
  tail, 112 mutants, 10 authored mutations and 6 of 24 committed silent-wrong
  answers get no packet; with it, 24 of 24, and none of 60 strong-exact
  answers gets a false one.
- CI python job in the test image at 52a29d5: 1,019 tests, 1 skipped, 96.55
  percent coverage, static checks and all gates pass. `score --check`
  reproduced all six committed outputs at 11e01d7; later commits change only
  docstrings and tests.

## Planned next

1. Freeze the test split: raise the 64-item prepare bounds (test holds 112
   items), widen prepare to test, hash every file that shapes a request,
   record the input and feedback label hashes in `docs/protocol.md` and
   pre-register the A/A rerun.
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
- The test input hashes are not frozen, and no run has answered non-ready
  gold, so false-ready rate and slot match are still unmeasured.
- The Web remains recorded-only; Linux CI teardown and the production
  container were not re-verified, so no live Web job boundary is enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Hosted CI on the tmp retention fix and the feedback probe, pylint
   included.
2. Locked-test run replayed offline from a clean checkout without an API key.
3. Web numbers checked against the scored summary by a CI test.
