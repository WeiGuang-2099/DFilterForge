# Implementation Progress

Last updated: 2026-10-07

## Current slice

The site is live on GitHub Pages at
https://weiguang-2099.github.io/DFilterForge/: PR #25 merged as 210e100 on
2026-10-06, and the deployed methodology page links its sources at 210e100.
It serves the Reel on `/` and `/methodology`. Branch `site-board` adds
`/board`, the test repair round and the counted test passes, and has
`main` merged in, so the board sits beside the Reel's ladder. The
readability pass on the live pages is on that branch too: digests shown as
twelve-digit prefixes, the methodology page in two columns, the Reel's
witness tail as one break row and its repair card as a table. The README
there is the owner's results page: the pitch, the live URL, the GIF of the
home page (`docs/media/reel.gif`), the repair numbers and their limits; the
run instructions moved to `docs/usage.md`. Branch `sft`
holds the SFT code on training set v1 (PR #24). GPU work comes next, on
Modal (owner ruling), with Qwen/Qwen3-1.7B, thinking off (Planned next 3).
Reports under the ignored `artifacts/` are not project evidence.

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
  in the repair@1 denominator, and the gate checks it (ablation 007 has why).
- `dfilterforge.model_feedback` (1db1b50) copies semantic-29 (dev) and -35
  (test) with the witness tail via the scored probes' helper (d47eb32). No
  scored capture, gold hash (8a061589fe6c) or model input changes; an import
  contract and a test keep it from scoring and `scripts/model_run.py`.
- Gate `probe-adequacy/1.2` (11e01d7, tests 52a29d5) checks the gold filters
  on all eight probes and runs every mutant on the feedback probe too; strict
  mode passes with the counts in ablation 007.
- [Ablation 007](ablations/007-feedback-probe.md), `keep_full`: without the
  tail, 112 mutants, 10 authored mutations and 6 of 24 committed silent-wrong
  answers get no packet; with it, 24 of 24, and none of 60 strong-exact
  answers gets a false one.
- CI python job at 52a29d5: 1,019 tests, 1 skipped, 96.55 percent coverage;
  static checks, gates and `score --check` (at 11e01d7) pass.

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
- CI python job at e37a7a7: 1,050 tests, 2 skipped, 96.55 percent, peak /tmp
  12.2 MiB; static checks, gates and `score --check` pass.

## Test freeze: 2026-09-26

- At 7590e4d, with rebuilt images, `score --check` reproduced all six
  committed outputs and the strict gate passed: 344 mutants, 4 waived
  survivors, 0 unwaived (`decisions/evidence/test-freeze-gate.json`).
- Dev (3d71c39) and test prompts were prepared ten seconds apart in one image:
  40 and 112 items, C1 to C4, top-k 16; the v2 run's 16 dev items are
  byte-identical. Lab controls: dev reference 96 strong exact and 64 abstained,
  mutation 48 silent-wrong and 32 false-ready; test 320 and 128 (183 s), 160
  and 64 (102 s).
- `src/dfilterforge/held_out_freeze.json` admits only the committed test
  `prepare.json` (206599bb67e1) and holds the digests of the test inputs,
  gold with routing, gold hash, feedback labels and four captures, quoted in
  `docs/protocol.md`. The record test no longer skips, and a host test ties
  the committed test `prepare.json` and those quotes to the record.
- CI python job at the freeze commit: 1,059 tests, 1 skipped, 96.55 percent;
  static checks, gates and `score --check` of all ten outputs pass.

## Model bake-off registered: 2026-09-26

- Before any test request the owner turned the 70B- and DeepSeek-V3-class slots
  into about 120B-class and frontier open-weight MoE slots: deepseek-v3.2 leaves
  OpenRouter on 2026-09-28, and Llama 3.3 70B's coding index trails the 32B's.
- The [model bake-off](decisions/model-bakeoff.md), part of the protocol, lists
  per slot three ranked candidates and a reserve, their slugs, eight fallbacks,
  run ids, the rule and a two-turn smoke. `scripts/dev_bakeoff_configs.py` wrote
  the 21 call configs and endpoints snapshot keyless at 2026-09-26T10:05:28Z,
  matching the note. `scripts/dev_bakeoff.py` runs the passes, resumes
  transient failures after 60 s and refuses uncommitted tooling.

## Model bake-off dev passes: 2026-09-26

- The owner ran `scripts/dev_bakeoff.py` at 0e1f1e6: ten passes completed in
  one execution with no fallback or reserve, every hybrid reported 0 reasoning
  tokens, and providers reported 0.916 USD. mistral-medium-3-5 dropped at 134
  of 160: 26 items met HTTP 429 on all three attempts, a provider rate limit.
- Strong-exact ready items of 96, before the smoke: anchor 50; 8B qwen3.5-9b
  42, ministral 39, granite 18; 120B qwen3.5-122b 57, nemotron 37 (the dropped
  mistral-medium scores 51); frontier deepseek-v4-pro 70, glm-5.2 72, kimi-k2.6
  68. The rule picks qwen3.5-9b, qwen3.5-122b and deepseek-v4-pro, within 4 of
  glm-5.2 (`decisions/evidence/bakeoff/ranking-2026-09-26.json`). The anchor
  answered non-ready gold for the first time: 6 of its 64 were false-ready.

## Two-turn smoke tooling: 2026-09-26, branch repair-multiturn

- A prepared prompt may be (system, user, assistant, user) inside 64 KiB, with
  the note's follow-up text pinned; all 116 recorded prompt files (14 distinct
  contents) still re-serialize byte for byte
  ([second turn](decisions/second-turn.md)).
- `model_run.py follow-up` and `scripts/two_turn_smoke.py prepare` built nine
  smokes offline, two items each; a keyless `run` stopped at
  `api_key_missing` for all nine with nothing sent. No smoke request is sent.
- Test image with the branch mounted: 1,242 passed, 5 skipped (no docs/), 96
  percent coverage; static checks pass. It merges after the last baseline.

## CI frozen-prompt guard: 2026-09-27

- The suite skips `test_frozen_prompts_awaiting_a_call_match_the_model_side_code`
  (no `docs/` in the test image), so CI now runs it alone with `docs/` mounted
  read-only behind `test -d docs/results`. In the test image with each tree
  mounted: 1 passed on this branch (04fa035); on a throwaway merge of
  repair-multiturn (851e037) it failed with `test-qwen3-32b-2026-09-26:
  re-freeze after scripts/model_run.py, src/dfilterforge/generation.py`;
  without the mount the step exits 1.
- The guard stops at pass A's publish, not at the last baseline test request.
  It skips a prompt set with a `run_manifest.json` beside it, `publish` wants
  the directory named after the run id, and pass A publishes into
  `docs/results/test-qwen3-32b-2026-09-26`, the only prompt set awaiting a call.
  Pass B and the slot winners' test passes call from that prepare but publish
  under their own run ids. In the test image with the repair-multiturn code
  (23fc4cd, hashed files as at 851e037) and a scratch copy of that directory,
  the step failed (exit 1) and, with a `run_manifest.json` added, passed (exit
  0). After A's publish an early merge passes CI; what is left is the call's
  `prepare_code_mismatch`, which refuses each later test call before any
  request, and the rule that the 12 hashed files stay unchanged until the last
  baseline test request.
- Only that publish releases the guard: `publish` refuses an incomplete run
  (`run_incomplete`) and a directory not named after the run id
  (`output_name_mismatch`). If pass A publishes under another run id, or rule 7
  of the bake-off note reports the A/A pair not run, the step fails every
  hashed-file edit, the merge after the last baseline test request included,
  and asks for a re-freeze the protocol allows only before the first test
  request. In the test image with the repair-multiturn code (1f64784, hashed
  files as at 851e037) and a scratch results tree whose manifest-less frozen
  directory sat beside a `test-qwen3-32b-r2-2026-09-26/` holding `prepare.json`
  and `run_manifest.json`, the step failed (exit 1) with the same re-freeze
  message. The ci.yml comment and the test-freeze Limits now say so.

## Smoke review fixes: 2026-09-27, branch repair-multiturn

- An 89-agent review of the branch at 851e037 confirmed 17 minor findings and
  proposed 15 commits here and one CI step on main's side. The owner ruled on
  2026-09-27. D1: Ctrl-C gets documentation and messages only, under the rule
  "do not press Ctrl-C while a request is in flight: that request may be billed
  but not recorded"; `scripts/dev_bakeoff.py` is unchanged. D2: a served
  provider or model other than the counted pass's is a flag in the verdict file
  and summary line, never another verdict; the note is not amended. D3: all 15
  commits land before the paid smoke, plus the frozen-prompt guard in CI on
  bakeoff-results (04fa035). D4: five readings of the smoke rule, recorded in
  [second turn](decisions/second-turn.md) (0afc76a) and pinned by tests
  (58a1731): a run with other settings, prices, host, prompts or cap is void
  and owes a re-run; an observed model failure fails the smoke beside a harness
  failure; `client_error`, `redirect_rejected`, `response_too_large` and
  `empty_content` are final errors; reasoning is read over every attempt; one
  new run per smoke per execution, with re-runs up to `-rs9`.
- Commits after 851e037: 24f0dd2 judge refuses a smoke whose source run no
  longer rebuilds; 0521e29 interrupt messages name the cost and the smoke's own
  lock; c3bc2e3 a finish_reason that is not a short code reads `other`; b4e5468
  an unexpected error stops with exit 1, never a refusal, and judging still
  runs; bd573c0 a malformed key is blamed on the key; 58a1731 and 0afc76a D4;
  62e3d76 dry-run refuses a prompt set the code no longer matches; 1424967
  prepare never writes over a smoke directory; f8e361e `prepare --reserve SLOT`
  for rule 6; 74b6e11 served providers and models are flagged (D2); 92904e6
  prepare reads only the runner's own summary; 3cebe1a run-id limits, prompt
  counts and the CI skip corrected in the docs; 29fee1c the Ctrl-C text as a
  constant, since 0521e29 had made CI's pylint step fail (R0801, rc 8); 4a00c97,
  6a2dba8 and ba570fd tests only.
- For the owner's run: no prepare-hashed file changed since 851e037, so the
  nine prepared smokes stay valid without a re-prepare, and the command is the
  same. Its messages now say what an interrupt costs, keep and name
  `artifacts/two-turn-smoke/.lock` when a call step outlives the wait, print
  STOPPED with exit 1 after an unexpected error, and name the run directory a
  judge cannot read with what may be done with it. Summary lines end with
  `served X`, plus PROVIDER CHANGED or MODEL CHANGED when that happened.
- Tests: the smoke tests went from 49 at 851e037 to 107, and follow-up's in
  `tests/test_model_run.py` from 12 to 15. In scratch copies, each of the
  review's named mutants (S10, S14, S15, S32, S44, S49, S51 to S54, S61, S62)
  and the deletion of each of 15 follow-up guards alone fails at least one
  test; at 29fee1c, before the three test commits, five of those guards and
  nine of those mutants failed none. The one deletion no test can catch, `ready_answer`'s status
  check, is equivalent: a failed reply carries no text, and empty text never
  parses.
- Test image with the branch mounted, full suite at ba570fd: 1,304 passed, 5
  skipped (no docs/ tree in the image), 96.45 percent coverage, in 747 s.
  CI's static commands pass: pyink, isort, pylint on CI's file list (rc 0),
  pyright (0 errors) and lint-imports (5 contracts kept). The keyless gate
  against the real out dir is the maintainer's; expect nine `preflight ok`
  lines, then ABORTED and exit 3.
- A re-review of cb9be26 confirmed four more minor findings, two of them the
  same stale count, fixed on 2026-09-27 with no prepare-hashed file touched.
  73136bb (tests only) holds `prepare --reserve`'s refusal of an existing smoke
  or `.partial` directory: with that one line deleted, all 107 smoke tests had
  passed while the cleanup deleted a `runs/` it did not make; the new case fails
  on both seeds. b9c9c4b makes the ABORTED line after an account refusal read
  the smoke as `judge` does: a run that already shows a model failure is named
  failed with no re-run (reading 2), where it had said a re-run was owed; the
  exit code, verdict and calls are unchanged, and the new tests fail on the
  cb9be26 script. 6182054: the decision note's test count said 1,247, the
  851e037 count, and now reads 1,313 at b9c9c4b. Smoke tests: 111.
- Test image, full suite at b9c9c4b: 1,308 passed, 5 skipped (no docs/ tree),
  96.45 percent coverage, in 753 s. CI's static commands pass: pyink, isort,
  pylint on CI's file list (rc 0), pyright (0 errors) and lint-imports (5
  contracts kept).
- A second review of 23fc4cd confirmed seven more minor findings, three of
  them the same Limits bullet, fixed on 2026-09-27 with no prepare-hashed file
  touched: `git diff 851e037..HEAD --stat` lists none of the 12, so the nine
  prepared smokes stay valid. No script changed; each test commit was checked
  on scratch copies with the named mutants applied, and every test that
  existed before it still passed under each mutant.
  - 7317e9b: follow-up's race test writes its file as bytes, so a host run of
    `tests/test_model_run.py` is back to the three failures it had at 851e037
    (two scoring end-to-end tests that need the image's catalog, and the
    frozen-prompt guard), from four.
  - 257621a pins that reading 1 comes before reading 2: a void run whose first
    reply shows reasoning or ends with `length` owes a re-run. Two mutants of
    `assess` that let such a model failure read `fail` passed all 111 smoke
    tests; each fails the new test's 14 cases. The note names the test.
  - be7006c: the note's Limits now say bakeoff-results' CI step guards a merge
    of this branch only until pass A publishes. In the test image, with this
    branch's code and bakeoff-results' `docs/results`, the step's command
    exited 1 (re-freeze after `model_run.py` and `generation.py`), and 0 once a
    scratch copy of `test-qwen3-32b-2026-09-26` held a `run_manifest.json`.
  - bd85932: rule 6's refusal of a survivor that passed its smoke and of
    another slot's reserve; N24 and N21 each fail one new case.
  - a9d3a6c: the batch's catch-all tested with OSError, ValueError and
    KeyError, and through `main()` for a ValueError (exit 1, no refusal).
    Narrowing it to OSError (N28) fails three cases, to (OSError, ValueError)
    one.
  - ffd452a: D2's flags when only one item, or only an earlier run, was served
    by another provider or model; N07 and N08 each fail three cases, N09 one.
- Smoke tests: 111 to 135. Test image, full suite at ffd452a: 1,332 passed, 5
  skipped (no docs/ tree), 96.48 percent coverage, in 778 s. CI's static
  commands pass: pyink, isort, pylint on CI's file list (rc 0), pyright (0
  errors) and lint-imports (5 contracts kept).
- A third review of 1f64784 confirmed five more minor findings, fixed on
  2026-09-27 with no prepare-hashed file touched: `git diff 851e037..HEAD
  --stat` lists none of the 12, so the nine prepared smokes stay valid. Each
  test commit was checked on scratch copies with its named mutant applied.
  - a656aad: the STOPPED line for `endpoint_invalid` said "nothing is owed" in
    every state, while the summary printed after it could read `rerun_owed` or
    `resume_owed`. It now says nothing was sent and no run was started or
    changed, and points at the summary. The test covers a not_run, a rerun_owed
    and a resume_owed anchor and fails on the old text in all three.
  - 72f5fb3 pins both halves of `_verify_source`'s check on a source with no
    ready answers. D00b (the smoke's status not checked) fails one new case;
    D00c (the refusal code not checked) fails two, one of them rule 6 no
    longer refusing a reserve while beta's source is gone.
  - 1b4eaf8: a paid call that leaves an unreadable run stops the batch before
    the next smoke is paid for. With drive's check deleted (D05d), the batch
    paid for alpha too, and the new test fails.
  - 90a6612: MODEL CHANGED when only an earlier run was served by another
    model, and `served -` with no flag for a smoke with no run. M08 and M07
    (any() read as all()) each fail two cases. The ffd452a line above
    overstates its earlier-run case: that test varied the provider only.
  - ddd1281: a reserve that fails its smoke ends its slot with "the reserve
    failed its smoke too". With that branch disabled (M12) the summary told the
    owner to run the reserve again; the new test fails.
- Smoke tests: 135 to 143. Test image, full suite at ddd1281: 1,340 passed, 5
  skipped (no docs/ tree), in 604 s. CI's static commands pass: pyink, isort,
  pylint on CI's file list (rc 0), pyright (0 errors) and lint-imports (5
  contracts kept).

## Two-turn smoke and slot winners: 2026-10-01

- The owner sent the nine smokes from `repair-multiturn` at 281b2ce (prepared
  at 2d305e0 from the committed runner summary, same SHA-256) between 11:50
  and 12:06 UTC, charged at most 0.0115 USD. The anchor's smoke
  (informational) and seven candidates' smokes passed (kimi-k2.6's was not
  measured; see the next bullet): both replies completed with finish_reason
  stop, parsed under C4 and reported 0 reasoning tokens; every served provider
  and model was the pinned one.
- kimi-k2.6 met HTTP 429 from Parasail on all 12 attempts of two runs (0 USD);
  the owner ruled its smoke not measured and not retried (ruling K). It moves
  no winner: deepseek-v4-pro-0813 (70) is within 4 of glm-5.2 (72) whether or
  not kimi-k2.6 (68) survives.
- Rule 5 winners: qwen/qwen3.5-9b (42 of 96, best 42), qwen/qwen3.5-122b-a10b
  (57, best 57), deepseek/deepseek-v4-pro-0813 (70, best 72), each through its
  first pass, so no fallback or reserve runs. Evidence: smoke manifests and
  attempt logs in `decisions/evidence/bakeoff/<run id>/`, plan, summary and
  verdicts in `decisions/evidence/bakeoff/smoke/`, the ruling in the [bake-off
  note](decisions/model-bakeoff.md) and `ruling-2026-10-01.json`, which three
  host tests in `tests/test_dev_bakeoff.py` check (116 passed in the test
  image with `docs/` mounted; 111 passed and 5 skipped without it).

## Hosted test runs registered: 2026-10-01

- [`decisions/test-runs.md`](decisions/test-runs.md), linked from the
  protocol's Models paragraph and part of the protocol, registers 16 hosted
  runs over the frozen test prompts before any test request: the A/A pair
  `test-qwen3-32b-2026-09-26` and `test-qwen3-32b-passb-2026-09-26`, the three
  slot winners on their counted passes' routes, their listed fallbacks for a
  rule 7 gate stop, and one `-r2` outage re-run for each of those eight. Every
  run uses a committed bake-off config. `evidence/test-runs.json`
  (`test-runs/1.0`) holds the same rows and each run's status: 5 registered,
  11 unused.
- Caps are twice the counted dev pass's spend times 448/160 plus one worst-case
  test request, rounded up to 0.05 USD: 0.10 per A/A pass, 0.15 small, 0.75
  mid, 1.25 frontier, and the same for each fallback and re-run. The five
  planned runs hold 2.35 USD of caps (about 1.10 USD expected), all 16 hold
  9.00 USD, and the committed runs so far record at most 0.941 USD
  (0.940394).
- `tests/test_hosted_test_runs.py` (6 host tests) checks the run ids, the
  ruled winners and the anchor, the configs and quantizations, the admitted
  prepare, the cap rule, and that the note lists the JSON's rows. In the test
  image with `docs/` mounted 6 passed; without it 6 skipped. Eight deliberate
  breakages (a cap too low or too high, pass B tagged `-res`, a swapped
  fallback config, a quantization in the note, a winner's model, a slug, the
  prepare) each failed it.
- The frozen-prompt guard now reads the registry (owner ruling G):
  `test_frozen_prompts_awaiting_a_call_match_the_model_side_code` keeps
  `docs/results/test-qwen3-32b-2026-09-26` and every registered run's
  directory guarded while any row is `registered`, or is `unused` while the run
  it names is `not_run` and it gives no reason, even with pass A's run manifest
  beside the prompts. It also fails on a row `docs/results` contradicts and
  when no row names the frozen prompts; other prompt sets keep the manifest
  rule. 14 unit tests on tmp fixtures cover a
  registered row beside a manifest, a finished registry, a triggered fallback
  and ten contradicted statuses.
- In the test image with `docs/` mounted the CI step command passed on this
  tree (exit 0). On a scratch copy with `src/dfilterforge/text_limits.py`
  edited it failed (exit 1, `test-qwen3-32b-2026-09-26 awaits a call;
  ['src/dfilterforge/text_limits.py'] changed`), and failed the same way with a
  pass A run manifest beside the prompts and its row published, where the
  guard as at 4111d8d passed. With every row published or not run it passed
  despite the edit; a row marked published without its manifest, and a
  deleted registry beside pass A's manifest (`no registered run`), failed.

## Repair round registered: 2026-10-01

- `docs/protocol.md` now registers the repair round before any test request,
  as the owner decided on 2026-10-01 (OD1 to OD4 in the [repair
  note](decisions/repair-round.md)):
  - The repair@1 bullet defines the estimator: repaired over triggered case
    shares on the repaired pass's ready-case vectors.
  - A new section, Repair, fixes the trigger, the three arms (`-res`,
    `-bare`, `-cx`), the feedback-probe card and its 13 header fields, the
    scoring and comparisons, the arm run ids and per-slot caps, admission and
    corrections.
  - No freeze quote changed: `tests/test_held_out.py` passes on the host.
- **Repaired passes.** These are pass A and the three winners' counted test
  passes, plus the four counted dev passes as a pipeline check.
  - The dev passes hold 36 triggered C4 items (anchor 10, qwen3.5-9b 7,
    qwen3.5-122b-a10b 8, deepseek-v4-pro-0813 11; 27 silent-wrong, 9 invalid),
    counted from the committed outcomes. All have ready gold and finished
    with `stop`.
  - So the dev round is 108 requests.
- **Arm run ids.** Arm runs are not registry rows.
  - `test-runs.json` states their naming rule under `repair_arms`, and the
    note lists the 24 ids of the planned passes.
  - Over all 18 runs that can be repaired, 106 of the 108 arm and re-run ids
    fit the result-name pattern.
  - Two do not fit. Both are outage re-runs of an arm over the frontier
    fallback's own outage re-run, and such an arm is reported not run.
- **Caps.** The arm caps total 3.90 USD (1.20 dev, 2.70 test). With the
  at most 0.941 USD recorded so far and the registry's runs 1 to 5 at their
  caps, OpenRouter spend stays within 7.191 USD of the plan's 12 USD.
  - Each cap covers at least two requests at the 64 KiB prompt bound, the
    call step's pre-request bound at the config's prices.
  - The largest dev counterexample prompt with a full card is 7,667 B.
- **New host test.** `test_repair_arm_runs_follow_the_registered_naming` in
  `tests/test_hosted_test_runs.py` passes (7 passed in that file). Each of
  five deliberate breakages made it fail: a listed id, an unnamed unfit id,
  a changed tag, the protocol's example id, and pass B made repairable.
- **Not measured.** No repair request has been sent, and every committed
  summary still records `repair_at_1` as `not_run`. The card figures and
  expected costs in the note are the repair design's scratch measurements and
  have not been re-run.

## Disproof Reel rule registered: 2026-10-01

- [`decisions/disproof-reel.md`](decisions/disproof-reel.md) fixes rule
  `reel-v1`, the headline definition and the dev-display rule, with the text
  of the web design that the owner approved as decision D2. It is committed
  before any test or repair answer exists.
  - The note adds the repair round's repair-trajectory sentence. That
    sentence applies when the pick has no repair row of its own.
  - It also gives a dated reading of the rule against the committed registry
    (`test-runs/1.0` statuses and roles, and the winners' dev passes from
    the bake-off ruling). No choice made today changes.
- **Checked on today's data.** A script applied steps 1 to 4 to the
  committed files. It read only the registry, the ruling, the pool runs'
  outcomes and their C4 receipts.
  - The test phase is off, so the pool is the dev anchor and the three
    winners' dev passes.
  - 27 C4 silent-wrong candidates. Three tie at 3 disagreeing frames, and
    pool order picks `dev-qwen3-32b-2026-09-26` C4 `mei-0015`. The filter
    `(dns.aaaa || dns.flags.rcode == 3)` misses one labelled frame on each
    scored probe.
  - The highlight is semantic-17, frame 3.
  - Headline over the dev pool: M is 284 and N is 65.
- **No code yet.** No exporter exists. `scripts/export_web_data.py` is the
  web track's.

## Test-pass batch and registration check: 2026-10-01

- `scripts/test_passes.py` is the owner's one command for the 16 registered
  runs (Owner command in the [test-run note](decisions/test-runs.md), for Git
  Bash and Windows PowerShell 5.1, with exit codes 0, 1, 2, 3 and 130). It
  reads `evidence/test-runs.json` and sends pass A, pass B within 24 hours of
  the counted pass A's first invocation whatever pass A shows unless a gate
  stop reports the A/A pair not run (corrected on 2026-10-02; until then the
  batch sent pass B only after a complete pass A), then the small, mid and
  frontier winners. Each run is one `scripts/model_run.py call`
  argument list, no shell, with the row's run id, config and cap and
  `--gate-first --max-attempts 3 --min-interval-seconds 1.0`.
  - It resumes pending items after 60 s, sends a winner's listed fallback
    after a gate stop on the first answer, and re-runs an outage once under its
    `-r2` row. A gate stop of pass A or pass B, a refusal and a resumed pass
    that stops at the gate are reported not run.
  - It stops for the owner on a budget stop after an answer, a closed pass B
    window or a call step error, and aborts on HTTP 401, 402 or 403. A row
    the registry marks `published`, `not_run`, or `unused` with a reason is
    never sent.
  - It reuses the bake-off batch's run reading, gate, resume and outage
    decisions, invoker and lock; `scripts/dev_bakeoff.py` is unchanged. Its
    summary in `artifacts/test-passes/` gives each row its state, publish or
    evidence target and registry update.
  - The note now states that a refusal has no registered fallback (rule 7
    gives test passes one for a gate stop only) and that a triggered fallback
    or re-run is sent in the same execution, its status written in the
    publishing commit.
- `tests/test_test_passes.py` holds 54 tests: 52 drive the batch with a
  scripted call step over an eight-item synthetic test prompt set (order,
  pass B after A and its 24-hour window, rule 7, the anchor's gate stop, the
  outage re-run, 401 to 403, the budget stop and a raised cap, a missing or
  unadmitted prompt copy, the keyless preflight, a resume after exit 1,
  rulings, the lock and interrupts, and 21 unusable registries or configs);
  2 read the committed registry, prompts and note and skip without `docs/`.
  In the mirror's suite they cover 97% of the script (statements and
  branches). CI's pylint list and pyright include it.
- Keyless check from this worktree, the key unset in the process, user and
  machine scopes: with no prompt copy the batch refused (exit 2) and printed
  the restore commands for both shells. After the printed Git Bash restore,
  `--dry-run` exited 0 and wrote nothing, and the batch called all 16 runs
  with the key withheld, each stopping at `api_key_missing`, then aborted
  (exit 3); no run directory was created and no request was sent.
- Branch `register-test-runs` holds ten commits over 4111d8d, and none of the
  12 prepare-hashed files changed (`git diff --name-only 4111d8d`). The four
  sections above record the smoke verdicts, ruling K and the slot winners;
  the registry and the guard it holds (ruling G); the repair round (OD1 to
  OD4); and the Reel rule `reel-v1`.
- Tests: in the test image with `docs/` mounted, `tests/test_held_out.py`,
  `tests/test_hosted_test_runs.py`, `tests/test_dev_bakeoff.py`,
  `tests/test_test_passes.py` and the frozen-prompt guard gave 201 passed, and
  the CI guard step's command alone exited 0; the four files on the host gave
  200 passed. The CI mirror (`artifacts/ci/ci_mirror.sh
  register-test-runs-impl`, working tree, read-only mounts, at b6a1beb)
  returned rc 0 for pyink, isort, pylint, pyright, lint-imports, pytest (1235
  passed, 16 skipped, coverage 96.52%), the benchmark gate, adequacy, prepare,
  recall and the 20 committed re-score checks: overall status 0. The mirror's
  pylint list predates the bake-off scripts; CI's list, `scripts/test_passes.py`
  included, rated 10.00/10 (rc 0).

## Registration review fixes: 2026-10-02

- A review of this branch at 12df7ba confirmed ten findings, three of them
  the same freeze-note sentence. Eight commits fix them; none of the 12
  prepare-hashed files changed (`git diff --name-only 4111d8d`).
- **A ruling no longer cuts a chain** (4ca3d9a). At an exit-1 stop the
  summary proposes statuses such as pass A `not_run` with its `-r2`
  published, or a winner `not_run` with its fallback `registered`. Once the
  owner committed them, the batch read the ruling as the chain's end: it
  never resumed the re-run or fallback, exited 0, and proposed a false
  "ended not_run without ..." `unused` reason whose commit would release the
  frozen-prompt guard. Now a run ruled `not_run` that left a directory
  triggers what that directory shows, read without sending, and a
  conditional row that is `registered` or has a directory is never called
  unused; if no chain reaches it, the batch stops (exit 1). Four new cases
  commit the summary's statuses and a raised cap after a budget stop and run
  the same command again (pass B after pass A's re-run, a fallback left
  registered or unused, pass A's re-run); each resumes the stopped run and
  ends with exit 0. They and two cases of an unreached conditional row failed
  on the batch as at 12df7ba (6 failed).
- **Pass B whatever pass A shows but the gate** (fd5027e). The batch skipped
  pass B after any pass A that was not complete; the protocol sends it
  whatever A shows unless the bake-off note reports the pair not run, which
  rule 7 does only at the gate. Pass B is now held back only when pass A's
  chain ends at the gate (pass A, its `-r2` run or a resumed pass); after a
  refused pass A, or an outage on its re-run too, pass B is sent. Its 24
  hours run from the counted pass A's first invocation, the `-r2` run's once
  that has a manifest, else pass A's; with neither, the batch stops for the
  owner. On the batch before it, 7 tests failed: the new cases (a refusal,
  an outage twice, a refused pass A at 24 h and at 24 h plus 1 s, a pass A
  ruled published or not run with no run) and the owner-ruling test, whose
  pair reason now reads "incomplete". The gate cases now also cover pass A's
  re-run and its resumed pass.
- **Caps** (60a819b). The note's Caps table carries the registered caps;
  `tests/test_hosted_test_runs.py` checks the cap rule (each table figure
  equals the recomputed one to 5e-7 USD) and the 2.35 and 9.00 USD totals
  against it, and each row's cap only for being at or above its config's
  registered cap. On a scratch copy of `docs/`, test-qwen3.5-9b-2026-09-26
  raised from 0.15 to 0.20 USD in both the note and the JSON passed (8
  passed); the JSON at 0.25 against the note's 0.20 failed the row equality,
  and 0.10 in both failed the floor.
- **CI** (19b80e4). The docs-mounted step now also runs
  `tests/test_hosted_test_runs.py`, `tests/test_dev_bakeoff.py`,
  `tests/test_test_passes.py` and `tests/test_held_out.py`. Its command, in
  the test image under compose's hardening (read-only root, no network, caps
  dropped) with the worktree's code and `docs/` mounted read-only: 215 passed,
  exit 0, no skip; without the `docs/` mount, exit 1 at `test -d`; with the
  0.15 USD caps raised in `test-runs.json` but not in the note, 1 failed,
  exit 1.
- **Notes.** The test-freeze Limits now says `scripts/test_passes.py` checks
  pass B's timing (79a0761); the smoke line counts seven passing candidates
  besides the anchor (2871005); both owner blocks run `git switch main`
  before `git pull --ff-only`, which a note test checks (7f98e18; in a
  scratch clone on `bakeoff-results` the batch was absent, and after the
  switch `--dry-run` reached the missing-prompt-copy refusal); the spend
  bounds round up to 0.941, 3.291 and 7.191 USD (exact sum 0.940394,
  010b204).
- **Checks.** `tests/test_test_passes.py` holds 67 tests (2 read the
  committed docs) and `tests/test_hosted_test_runs.py` 8. In the test image
  with `docs/` mounted, pyink, isort, pylint over CI's list (10.00/10),
  pyright and lint-imports returned 0; the five files of the CI docs step
  gave 215 passed there and 215 passed on the host. The CI mirror
  (`artifacts/ci/ci_mirror.sh register-test-runs-fix`, working tree at
  010b204, read-only mounts) returned rc 0 for pyink, isort, pylint,
  pyright, lint-imports, pytest (1248 passed, 17 skipped, coverage 96.53%;
  `scripts/test_passes.py` 97%), the benchmark gate, adequacy, prepare,
  recall and the 20 committed re-score checks: overall status 0.

## Repair cards: 2026-10-01

- **Branch.** `repair-cards` (079ba82 to cc96d36) starts from 86cd624. It is
  local and unmerged, it changes none of the 12 prepare-hashed files, and no
  model request was sent for it.
- **Shared codes.** Scoring names its 13 codes that make an answer invalid in
  one place (079ba82: `CANDIDATE_ERROR_CODES`, `candidate_error_code`), so a
  card and the scorer charge the same code.
- **Cards** (`dfilterforge.counterexample`, 9e6cb85 and a0289d3).
  - A bounded decoder reads 13 header fields of each feedback frame from one
    hash-checked copy of the capture.
  - tshark confirms every frame with a filter built only from the typed values.
  - A card comes from running the answer on its split's feedback probe alone.
    It is one of three:
    - the invalid code and the answer's first refused field;
    - no card, when the probe cannot separate the answer;
    - at most three disagreeing frames, as canonical JSON of at most 1,024 B.
- **Commands** (7b0a66f, ba9418d, f29066e).
  - The paired-case statistics of `score_summary` are public.
  - `dfilterforge repair` writes or checks `repair/plan.json`
    (`repair-plan/1.0`) for a scored base pass, and CI checks every committed
    plan.
  - Import contracts keep scoring and prompt building from loading
    `counterexample` or `repair`.
  - `dfilterforge pair` reports the changed answers, outcome transitions and
    flipped cases of two scored passes.
- **[Ablation 008](ablations/008-counterexample-facts.md), `keep_full`**
  (cc96d36).
  - Full confirms 62/62 and 63/63 feedback frames (961 shown values). Its card
    entries determine the feedback labels of 52/52 ready cases; membership
    facts alone determine 0/52.
  - The four counted 2026-09-26 dev passes trigger 36 items: qwen3.5-9b 7,
    qwen3.5-122b-a10b 8, deepseek-v4-pro-0813 11, qwen3-32b 10. They get 27
    frames cards and 9 error cards; every item gets a card, and the largest is
    717 B.
  - Facts and cards take 10.7 percent longer, all of it the one-time facts
    read of the two captures.
  - No repair plan is committed yet.
- **CI python job mirror at cc96d36:** 1,329 tests passed, 5 skipped, 96.73
  percent coverage.
  - pyink, isort, pylint, pyright (0 errors) and lint-imports (5 contracts
    kept) pass. The mirror's pylint covered `src` and four scripts, not CI's
    `scripts/dev_bakeoff.py` and `scripts/dev_bakeoff_configs.py`, and it
    ran no docs-mounted CI step. CI's own pylint command, run later on a
    `git archive` export of cc96d36, also returns 0.
  - The benchmark gate, the adequacy gate (344 mutants, 4 waived survivors,
    0 unwaived), prepare and recall pass.
  - `score --check` of all 20 committed outputs passes with no difference.
- **Review fixes** (8f1b811, 493026b, 6d587a2): three test gaps a mutation
  review of the branch confirmed, each closed by a test that kills its mutant
  in the test image.
  - The plan stage's prompt check: a base whose triggered item asks something
    else, with every digest derived from those bytes, is refused with
    `prompt_mismatch`, no card built and no plan written. With the
    `check_prompts` call removed, the test fails and the other 57 pass.
  - The DNS name bound: a 256-byte question name is refused with "DNS
    question name exceeds 255 bytes" and a 255-byte one is read. Counting the
    name without its terminator, the test fails.
  - The committed-pair test (dev-qwen3-32b C1 and C2 rerun) ran nowhere in CI,
    because the test image has no docs/ tree. A second docs-mounted CI step
    now runs it, and it skips only when docs/results is absent: with the tree
    present and the two passes missing, it fails.
- **CI python job mirror at 6d587a2:** 1,330 tests passed, 5 skipped, 96.73
  percent coverage.
  - Static checks, the gates, prepare and recall pass as at cc96d36, with
    the same pylint scope; CI's own pylint command on an export of 6d587a2
    returns 0.
  - The mirror now runs both docs-mounted CI steps: the frozen-prompt guard
    and the committed-pair test each pass (1 passed).
  - `score --check` of all 20 committed outputs passes with no difference.

## Repair arms: 2026-10-01 to 2026-10-02, branch repair-arms

- **Branch.** `repair-arms` starts from repair-multiturn 281b2ce and merges
  repair-cards at 0a941e6 (e5cb093). It is local, unmerged and never rebased,
  and no model request was sent for it.
  - Of the 12 prepare-hashed files only `src/dfilterforge/generation.py`
    (fbf9aff) and `scripts/model_run.py` (3839586) change; `_MODEL_SIDE_FILES`
    still lists 12.
  - CI's frozen-prompt guard therefore fails here until pass A publishes, as
    the repair design expects: in the test image with `docs/` mounted it exits
    1 with `test-qwen3-32b-2026-09-26: re-freeze after ['scripts/model_run.py',
    'src/dfilterforge/generation.py']`. The branch merges only after the last
    baseline test request.
- **A second turn may carry a card** (fbf9aff).
  - `follow_up_prompt(prompt, answer, card)` appends a line
    `COUNTEREXAMPLE_JSON` and the card to the follow-up text; the prefix's
    SHA-256 `5918ae3a...` is pinned.
  - A card must be one canonical JSON object of at most 1,024 B, else
    `follow_up_invalid`, and it counts in the 64 KiB prompt budget.
  - Without a card the output is unchanged: the nine smoke prompt sets rebuild
    byte for byte.
- **A second turn is scored by its first turn** (e56b35e). `check_prompts`
  rebuilds only the system and user messages; `repair` checks the tail.
- **Arms** (3839586). `model_run.py follow-up --plan PATH --arm
  {resample,bare,counterexample}` prepares one arm of a dev or test pass from
  its canonical `repair-plan/1.0` file.
  - resample sends the base C4 prompt byte for byte; bare adds the counted
    answer and the follow-up; counterexample adds the item's card as well.
  - The run id is the base's with `-res`, `-bare` or `-cx` before its date,
    and `-r2` after the tag for the one re-run.
  - Without `--plan` the smoke path is unchanged.
- **Round and pool** (1c7df3c, a1c7179).
  - `dfilterforge repair` is the plan stage alone while no arm run sits beside
    the base pass. Once one does, all three must (`repair_arms_incomplete`),
    and the committed plan is checked and never rewritten.
  - Each arm must be a C4 run of the base's split and prepared inputs named
    after itself, over the plan's items in plan order, with exactly the
    prompts its arm builds. Prompt sets committed before their calls are
    checked alone (stage `prompts`).
  - Once all three are published and scored, each must match the base's
    settings, prices, endpoint host, attempt limit and pacing
    (`repair_settings_mismatch`), be complete, and be scored on the base's
    cases. Then `repair/summary.json` and `.md` (`repair-summary/1.0`) are
    written or checked.
  - repair@1 per arm is `ratio_rate` of the summed repaired case shares over
    the summed triggered case shares, on the base pass's ready-case vectors,
    with its silent-wrong and invalid parts; only strong exact repairs.
  - The three arm pairs are compared by discordant cases, inconclusive below
    10. Transitions, unchanged answers, card value reuse, latency and spend
    are reported, never outcomes.
  - `dfilterforge repair-pool --results-dir DIR --split SPLIT [--base RUN]`
    pools committed summaries into `repair-pool/<split>.json` and `.md`, each
    drawn case bringing every model's cells; `--check` re-derives the bases
    the committed pool names. CI checks committed pools after the plans.
  - The code is in `repair_round.py` (546 lines), `repair_summary.py` (682)
    and `repair_report.py` (229). `repair.py` (now 520) and `pair_report.py`
    only make their readers public.
- **Tests.** `tests/test_repair.py` goes from 57 to 108 cases.
  - On a synthetic dev round, 7 items trigger in 5 of 12 ready cases, so the
    triggered shares sum to 3.5. repair@1 is then 0.5/3.5, 1.5/3.5 and 2.5/3.5
    for resample, bare and counterexample, and the paired differences are 1/3.5,
    2/3.5 and 1/3.5. Every one of these numbers was counted by hand.
  - a1c7179 adds nine cases. In a scratch copy of `src`, deleting any one of
    nine guards (an incomplete arm, an unscored base, six summary validators,
    an unreadable committed pool) left the 99 earlier cases passing, and each
    deletion now fails exactly one new case.
- **Real data, offline, on a scratch copy** of `dev-qwen3.5-9b-2026-09-26`.
  - `repair` wrote a plan of 7 items (5 frames cards, 2 error cards) whose
    SHA-256 `387a3309...` is the one ablation 008's receipt records.
  - `follow-up --plan` wrote the three arm prompt sets, 7 prompts each.
  - `repair --check` read them at stage `prompts` with no difference (exit 0).
  - No plan, arm run or summary is committed yet.
- **CI python job mirror at a1c7179:** 1,611 tests passed, 6 skipped, 96.8
  percent coverage (1,602 and 96.65 at 1c7df3c).
  - pyink, isort, pylint, pyright (0 errors) and lint-imports (5 contracts
    kept) pass. The mirror's pylint covered `src` and four scripts, not CI's
    `scripts/dev_bakeoff.py`, `scripts/dev_bakeoff_configs.py` and
    `scripts/two_turn_smoke.py`, and it ran neither docs-mounted CI step;
    the guard's expected failure here is recorded above. CI's own pylint
    command, run later on an export of a1c7179, also returns 0.
  - The benchmark gate, the adequacy gate (344 mutants, 4 waived survivors,
    0 unwaived), prepare and recall pass.
  - `score --check` of all 20 committed outputs passes with no difference.
    The repair loops check no plan and no pool, since none is committed.
- **repair-cards merged again** (cdbc25f) for its three review fixes; the
  only conflict was one import line of `tests/test_repair.py`.
- **Review fixes** (839a1c3, 1b4ce7f, 184939c, c8eef3b, b261c31): six
  confirmed findings, each with a test that fails on its mutant in the test
  image. No prepare-hashed file changed after 3839586.
  - **The committed plan is the round's record** (839a1c3). `round_run`
    derived the plan again even with arm runs present, so a dev correction,
    which re-scores `scored/` in place, or one that moved a feedback label or
    a card, made `repair --check` differ and `repair` refuse for good. Once
    an arm run exists the committed plan is now read and never derived
    again: it must name the pass's split, run and manifest digest, list
    ready C4 items in prepare order whose answers are their scored intents,
    and, while the outcomes it recorded are unchanged, list exactly their
    trigger set (`repair_plan_changed`; `repair_plan_unreadable`). Moved
    outcomes are listed by the summary, which `repair` may now rewrite.
    On a scratch copy of `dev-qwen3.5-9b-2026-09-26` with the three arm
    prompt sets seeded, changing the C1 mei-0001 outcome in place left
    `repair --check` at exit 0 and the plan at `387a3309...`; the code at
    cdbc25f gave exit 1 with `repair/plan.json` differing (`a3f437ba...`).
  - **An arm the gate stopped is reported as not run** (1b4ce7f).
    `dfilterforge repair --not-run ARM` writes `repair/not_run.json`
    (`repair-not-run/1.0`, one or two arms, reason `thinking_not_honoured`).
    That arm may stay a seed or be absent and must never be published
    (`repair_arm_mismatch`); the summary lists the arms run, their one
    comparison and `arms_not_run`, and `repair-pool` refuses the base
    (`repair_pool_not_run`).
  - **card_value_reuse counts shortcut answers** (184939c): a direct test
    of `summarize_round` counts a strong-exact and a shortcut answer.
  - **Second turns no plan checks are refused** (c8eef3b). A new
    docs-mounted CI step runs
    `test_every_committed_second_turn_is_an_arm_a_plan_checks`, which fails
    on any committed run with a prompt of more than two messages that is not
    an arm, first run or re-run of a base with a committed plan; it lists
    none today. A first run an `-r2` re-run replaced now has its prompts
    checked too.
  - **The mirror's scope** (b261c31): the three mirror entries above now say
    which pylint files and docs-mounted steps they left out; CI's own pylint
    command returns 0 on exports of cc96d36, 6d587a2 and a1c7179. The local
    mirror now reads its static commands and docs-mounted test nodes from
    `ci.yml`.
  - `tests/test_repair.py` goes from 109 to 131 cases. `repair_round.py` is
    now 776 lines, `repair_summary.py` 715, `repair.py` 579 and
    `repair_report.py` 241.
- **CI python job mirror at b261c31:** 1,633 tests passed, 7 skipped, 96.82
  percent coverage.
  - pyink, isort, pylint on CI's file list (rc 0), pyright (0 errors) and
    lint-imports (5 contracts kept) pass.
  - Of the three docs-mounted CI steps, the committed-pair and second-turn
    tests pass; the frozen-prompt guard fails with `re-freeze after
    ['scripts/model_run.py', 'src/dfilterforge/generation.py']`, as expected
    on this branch, and the mirror counts only that failure as expected.
  - The benchmark gate, the adequacy gate (344 mutants, 4 waived survivors,
    0 unwaived), prepare and recall pass.
  - `score --check` of all 20 committed outputs passes with no difference;
    no repair plan or pool is committed.

## Test baselines sent and published: 2026-10-02

The owner sent every registered baseline test pass with one
`scripts/test_passes.py` run from `main` at 7aaade8 (summary in the ignored
`artifacts/test-passes/summary-2026-10-01.json`; its date is UTC). All five
ended `done (complete)`; no fallback (`-fb`) or outage re-run (`-r2`) row was
needed, so those eleven rows stay `unused`.

| Run | Completed | Served | Charged at most (USD) |
| --- | ---: | --- | ---: |
| `test-qwen3-32b-2026-09-26` (pass A) | 448 / 448 | DeepInfra | 0.0483 |
| `test-qwen3-32b-passb-2026-09-26` (pass B) | 448 / 448 | DeepInfra | 0.0493 |
| `test-qwen3.5-9b-2026-09-26` | 444 / 448 | DeepInfra | 0.0530 |
| `test-qwen3.5-122b-a10b-2026-09-26` | 448 / 448 | Novita | 0.3988 |
| `test-deepseek-v4-pro-0813-2026-09-26` | 426 / 448 | DeepInfra | 0.5473 |

- Total charged upper bound 1.0967 USD. Thinking was honoured on every pass.
- Pass B started at 19:29:54Z, 45 minutes after pass A (18:45:12Z), inside the
  24-hour window.
- The 26 items without a completed answer all ended on HTTP 429 after three
  attempts: 22 for deepseek-v4-pro-0813 (21 in C1, 1 in C4) and 4 for
  qwen3.5-9b (all C4). Under the protocol's retry rule the last attempt counts,
  so they will score as `provider_failed` and stay in every denominator.
  deepseek's C1 row is therefore depressed by rate limiting, which any reading
  of its C2-C1 comparison must state.
- Each run was published with `scripts/model_run.py publish` into
  `docs/results/<run id>/`; the four new directories were first seeded with the
  committed test `prepare.json` and `prepared/`, and pass A's directory kept
  its committed prompts and controls byte for byte. The five rows in
  `test-runs.json` are now `published` with commit `7aaade8`, so every row is
  final and the frozen-prompt guard releases (guard, registry, test-pass and
  held-out tests: 99 passed with `docs/` mounted).
- Nothing is scored yet: owner decision OD4 holds scoring until the
  `repair-cards` branch is merged.

## Test baselines scored: 2026-10-02

- **Branch.** `score-test-baselines` starts from `origin/main` at 0623248,
  where PR #16 merged `repair-cards`, so OD4 no longer holds scoring. It adds
  thirteen commits: four for the scoring, seven for the review fixes and two
  for the final check. `git diff --name-only 0623248` lists only the five `scored/`
  trees, `docs/results/locked-test-v1.md`, the pair evidence,
  `tests/test_pair_report.py`, the CI workflow and this file: no
  prepare-hashed file and no runner, live or replay code changed. No model
  request was sent.
- **Scored** (c3b9c5c). `dfilterforge score` with the code at 0623248, in
  `dfilterforge-test:0.1.0` with `src/` mounted read-only and no network,
  wrote `scored/` for the five published runs; `score --check` then reported
  no difference for each (logs in the ignored `artifacts/ci/`). Outcomes over
  each pass's 448 items:

  | Run | `strong_exact` | `shortcut` | `silent_wrong` | `invalid` | `malformed` | `abstained` | `false_ready` | `provider_failed` |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | [`test-qwen3-32b-2026-09-26`](results/test-qwen3-32b-2026-09-26/scored/summary.json) | 185 | 0 | 49 | 60 | 9 | 135 | 10 | 0 |
  | [`test-qwen3-32b-passb-2026-09-26`](results/test-qwen3-32b-passb-2026-09-26/scored/summary.json) | 184 | 1 | 47 | 59 | 12 | 135 | 10 | 0 |
  | [`test-qwen3.5-9b-2026-09-26`](results/test-qwen3.5-9b-2026-09-26/scored/summary.json) | 154 | 0 | 51 | 43 | 27 | 161 | 8 | 4 |
  | [`test-qwen3.5-122b-a10b-2026-09-26`](results/test-qwen3.5-122b-a10b-2026-09-26/scored/summary.json) | 218 | 2 | 38 | 34 | 6 | 146 | 4 | 0 |
  | [`test-deepseek-v4-pro-0813-2026-09-26`](results/test-deepseek-v4-pro-0813-2026-09-26/scored/summary.json) | 247 | 0 | 27 | 22 | 4 | 106 | 20 | 22 |

  The 26 HTTP 429 items scored `provider_failed`, as expected. CI's re-score
  loop globs `docs/results/*/scored`, so it now checks 25 committed outputs
  (20 before) with no workflow change.
- **A/A pair evidence** (f6ea9e8). `dfilterforge pair` over pass A and
  pass B, in the same image, wrote
  [`evidence/aa-test-qwen3-32b-2026-09-26.json`](decisions/evidence/aa-test-qwen3-32b-2026-09-26.json).
  - Settings and prompts are identical in all four conditions. From C1 to
    C4, the changed answers are 42, 42, 39 and 46 of 112, the changed
    outcomes 8, 9, 12 and 19, and the flipped cases 4, 5, 5 and 7 of 40.
  - The noise bounds are 4.899 for C4-C2 and C4-C3 and 4.243 for C2-C1.
    C4-C2 (net -1 of 21 discordant; pass B -3 of 23) and C2-C1 (-2 of 12;
    -1 of 11) are within rerun noise in both passes. C4-C3 (-5 of 21; -9 of
    21) is beyond it in both, with the sign not reversed.
  - A new docs-mounted test derives the report again from the committed
    passes and requires the evidence byte for byte, plus those counts. CI's
    pair step now runs it beside the dev rerun test. With an evidence copy
    whose first `changed_answers` reads 41 instead of 42, mounted over the
    committed file, it failed (1 failed).
- **Locked test result, baseline half** (e3aaf65):
  [`results/locked-test-v1.md`](results/locked-test-v1.md). A local script
  (`artifacts/ci/locked_test_v1.py`, ignored, with `--check`) generates it
  from the files it links, and asserts the preconditions of each sentence
  the page makes. Repair is marked not measured. The findings:
  - **Primary, C4-C2.** No model's interval excludes zero: -0.075
    (qwen3-32b), -0.100 (qwen3.5-9b), -0.063 (qwen3.5-122b-a10b) and 0.088
    (deepseek-v4-pro-0813). Only qwen3.5-9b (net -6) and deepseek (+7)
    exceed the bound, which is extrapolated beyond qwen3-32b, and they point in
    opposite directions. qwen3.5-9b's reading is confounded by rate
    limiting: over the 37 ready cases its C4 failures do not touch, its net
    is -4 of 18, within the bound. The page states this as a negative result
    for the typed contract.
  - **C2-C1.** The only interval of the 12 comparisons that excludes zero is
    deepseek's 0.138 [0.013, 0.263]. It is confounded by rate limiting: C1
    lost 20 ready items in 15 cases, and 10 of the 11 cases where C2 was
    better hold a C1 provider failure. Over the 25 ready cases its C1
    failures do not touch, C2 is better in 1 and C1 in 3 (net -2, mean
    difference -0.040, too few discordant cases for a reading): the sign
    reverses.
  - **C4-C3.** qwen3-32b's -0.100 [-0.250, 0.063] (net -5) is beyond rerun
    noise, and so is pass B's -0.138 [-0.275, 0.000] (net -9); the sign is
    not reversed. Both intervals include zero, so only the net count is
    beyond noise. qwen3.5-122b-a10b's -0.125 [-0.263, 0.000] (net -9) is
    beyond the extrapolated bound. No interval excludes zero.
  - **Field context.** It is the same for every model: full coverage 0.350
    and mean recall 0.592, at 16 names.
  - **qwen3.5-9b's rate limiting.** Its 3 ready C4 failures touch 2 of the 13
    cases where C2 was better and 3 of the 8 where C3 was better. Its C4-C3
    reading stays within the bound over the untouched cases (net +3 of 13).
- **Review fixes to the page** (c33dd18 to 6b6aac8, seven commits with
  this log). Independent checkers recomputed the page from the committed
  files; every finding was confirmed against the JSON and fixed in the
  generator, and the page was regenerated, never hand-edited.
  - **Spend.** deepseek-v4-pro-0813's charged bound, 0.547306 USD, had been
    printed as 0.5473, below the bound. Bounds now round up (0.5474), and
    the total reads at most 1.0967 USD with the exact sum, 1.096681, beside
    it. qwen3.5-9b's price-derived spend is a lower bound too (139 retried
    items, 4 without usage), as is deepseek's (440, 22).
  - **Requests.** "448 requests per pass" held only for the three passes
    with one invocation. The manifests record 597 requests for qwen3.5-9b
    (448 + 139 + 10) and 1,202 for deepseek-v4-pro-0813 (448 + 440 + 314),
    equal to the attempt log lines. The page now says 448 prompts per pass
    and gives requests sent per pass.
  - **Retries.** Every non-final attempt in every pass is a failed request
    with HTTP 429. deepseek retried 440 of 448 items (C1 112, C2 111, C3
    112, C4 105), 292 completed only on their third attempt, and it met 754
    HTTP 429 responses before an item's last attempt; qwen3.5-9b retried 139
    items and met 149. The other three passes retried none.
  - **Rounding.** The page had printed exact halves with Python's float
    formatting, so 51/80 = 0.6375 showed as 0.637 but 59/80 = 0.7375 as
    0.738. Rates, differences and bounds now round the summaries' recorded
    decimals with halves away from zero; 80 cells moved one unit away from
    zero and no reading changed. All 152 rate cells equal their item count
    rounded that way. Each run's `scored/summary.md` still formats the
    binary float.
  - **Wording.** The ready-gold note now says silent-wrong over compile-valid
    items is a ratio of sums and that a failed request lowers silent-wrong
    over all ready items and over-abstention, where lower reads as better,
    rather than "counting against" every rate. The A/A rule bounds the
    absolute net count. The rerun column gives pass B's reading and "sign
    not reversed" instead of "replicated", which the protocol does not
    define. The C4-C3 heading no longer states that field context did not
    raise strong exact. The intro says the generator and the `score
    --check` logs are local and that no CI step checks the page.
  - **Receipts.** Every comparison row links its summary, outcomes and the
    pair report; the lost-item rows link outcomes; the noise-bound rows
    link both passes' summaries. All 211 links on the page resolve.
  - No test reads the page or this log, so the changes need no test run;
    `python artifacts/ci/locked_test_v1.py --check` reports that the page
    matches.
- **Checks.**
  - **CI's two docs-mounted steps.** These ran in the test image under
    compose's hardening, with the worktree's code and `docs/` mounted
    read-only. The guard, registry, bake-off, test-pass and held-out step
    gave 215 passed; the pair step gave 2 passed. The same seven targets on
    the host gave 217 passed.
  - **Static checks**, all rc 0: pyink, isort, pylint over CI's list (10.00/10),
    pyright (0 errors) and lint-imports (5 contracts kept).
  - **`tests/test_pair_report.py` in the image without `docs/`:** 26 passed,
    2 skipped (the two committed-pair tests).
  - **Re-checks of the committed trees.** `score --check` of all five runs
    from a `git archive` export of e3aaf65, in the test image with no
    network, reported no difference for each. The deepseek run, checked
    again under the lab service's limits (1 CPU, 512 MB, read-only root, a
    64 MB noexec `/tmp`), also reported none, in 143 s. The `lab` image
    itself was not rebuilt, so CI's own re-score step has not run yet.
- **Final check** (8bbad5f and this log).
  - **Wording fix.** The page's lost-items section said each
    `provider_failed` item "stays in every denominator", while its
    ready-gold note says such an item is outside the denominator of
    silent-wrong over compile-valid items, which counts only answers that
    ran. The generator now says each stays in every rate over its gold's
    items and names that exception, and the non-ready note says the same.
    The page was regenerated, no number moved, and
    `python artifacts/ci/locked_test_v1.py --check` reports that it matches.
  - **Facts rechecked from the committed files.** `outcomes.jsonl` holds 26
    `provider_failed` items, and `attempts/` gives each three attempts, all
    HTTP 429: qwen3.5-9b C4 3 ready and 1 not_expressible; deepseek-v4-pro-0813
    C1 20 ready (in 15 cases) and 1 needs_clarification, C4 1 not_expressible.
    The discordant, first-better, second-better and net counts of all 15
    condition comparisons (pass B included) equal the page's.
  - **Pair report.** `dfilterforge pair` over pass A and pass B, run again
    in the test image with no network, printed a report byte-identical to
    the committed evidence (SHA-256 prefix `246d4294f93c`).
  - **CI mirror** (`artifacts/ci/ci_mirror.sh score-test-final`, the test
    image with the worktree's code mounted read-only and no network). It
    started at 511a9b2; 8bbad5f landed during the run and changed only the
    page, which no step reads. pyink, isort, pylint, pyright (0 errors) and
    lint-imports (5 contracts kept) gave rc 0; pytest gave 1410 passed and 19
    skipped, coverage 96.76 percent; the benchmark gate, adequacy, prepare
    and recall steps gave rc 0; and `score --check` of all 25 committed
    outputs (17 `scored/`, 4 `control-reference/`, 4 `control-mutation/`)
    reported no difference.
  - **CI's exact pylint line**, which adds `scripts/dev_bakeoff.py`,
    `scripts/dev_bakeoff_configs.py` and `scripts/test_passes.py` to the
    mirror's list, in the test image with a tmpfs `/tmp`: 10.00/10.
  - **CI's two docs-mounted steps** at 8bbad5f, under compose's hardening:
    215 passed and 2 passed.
  - No repair plan is committed, so CI's repair-plan step checks none.

## Repair plans committed: 2026-10-02, branch repair-arms

- **Main merged** (846fc7b). `repair-arms` merged `origin/main` at 7a8ec03
  with a merge commit, never rebased. Every test-run registry row is final
  (five published, eleven unused), so the frozen-prompt guard releases:
  `test_frozen_prompts_awaiting_a_call_match_the_model_side_code` now passes
  on this branch, whose only hashed edits are still `generation.py` and
  `scripts/model_run.py`.
  - Conflicts in `ci.yml`, `pyproject.toml` and this file kept both sides:
    CI's pylint line and pyright's include list name both
    `scripts/test_passes.py` and `scripts/two_turn_smoke.py`, and the pair
    step runs main's two committed-pair tests beside the arms' second-turn
    step.
  - With both owner batches on one pylint line, R0801 flagged the sibling
    loader and ending dispatch that `test_passes.py` repeats from
    `two_turn_smoke.py` (pylint rc 8). `two_turn_smoke.py` now disables
    `duplicate-code` with its reason, as `retrieval_recall.py` does; CI's
    exact pylint line then gives 10.00/10, rc 0.
- **Dev plans** (5eb2bae). `dfilterforge repair` in plan mode, in
  `dfilterforge-test:0.1.0` with the branch's `src/` mounted, no network and
  `docs/results` mounted read-write, wrote `repair/plan.json` for the four
  dev passes; `repair --check` with `docs/results` read-only reported no
  difference for each (exit 0). Feedback probe `semantic-29`, labels
  `be0c91824bb5`.

  | Pass | Triggered | Silent-wrong / invalid | Cases | Cards: frames / error / none | Plan SHA-256 |
  | --- | ---: | --- | ---: | --- | --- |
  | [`dev-qwen3-32b-2026-09-26`](results/dev-qwen3-32b-2026-09-26/repair/plan.json) | 10 | 6 / 4 | 6 | 6 / 4 / 0 | `53e110395c3e` |
  | [`dev-qwen3.5-9b-2026-09-26`](results/dev-qwen3.5-9b-2026-09-26/repair/plan.json) | 7 | 5 / 2 | 6 | 5 / 2 / 0 | `387a330981b6` |
  | [`dev-qwen3.5-122b-a10b-2026-09-26`](results/dev-qwen3.5-122b-a10b-2026-09-26/repair/plan.json) | 8 | 7 / 1 | 7 | 7 / 1 / 0 | `6f746e8e067b` |
  | [`dev-deepseek-v4-pro-0813-2026-09-26`](results/dev-deepseek-v4-pro-0813-2026-09-26/repair/plan.json) | 11 | 9 / 2 | 7 | 9 / 2 / 0 | `c2e75d74b17a` |

  - The counts equal the [repair note's](decisions/repair-round.md) table
    (36 items in 26 cases, 27 silent-wrong and 9 invalid). Each plan's item
    ids equal the C4 items whose committed `scored/outcomes.jsonl` outcome
    is `silent_wrong` or `invalid`, all with ready gold and finish_reason
    `stop`. The error cards' codes are those of the note's table.
  - The qwen3.5-9b plan's digest is the one ablation 008's receipt and the
    earlier scratch run recorded.
- **Test plans** (b3a7d40), the same way, for the four counted test passes
  the registry publishes: `aa_pass_a` and the three slot winners; pass B is
  never repaired. The plan stage reproduced the freeze record's
  feedback-label digest `c0b30949787e` (full digest equal in each plan), so
  it did not refuse with `feedback_labels_mismatch`; `repair --check`
  reported no difference for each (exit 0). Feedback probe `semantic-35`.

  | Pass | Triggered of 80 ready C4 | Silent-wrong / invalid | Cases of 40 | Cards: frames / error / none | Plan SHA-256 |
  | --- | ---: | --- | ---: | --- | --- |
  | [`test-qwen3-32b-2026-09-26`](results/test-qwen3-32b-2026-09-26/repair/plan.json) | 28 | 25 / 3 | 20 | 25 / 3 / 0 | `67ba5bcbfa4d` |
  | [`test-qwen3.5-9b-2026-09-26`](results/test-qwen3.5-9b-2026-09-26/repair/plan.json) | 15 | 11 / 4 | 11 | 11 / 4 / 0 | `c0f297cb96e0` |
  | [`test-qwen3.5-122b-a10b-2026-09-26`](results/test-qwen3.5-122b-a10b-2026-09-26/repair/plan.json) | 20 | 14 / 6 | 16 | 14 / 6 / 0 | `a66dca952c6e` |
  | [`test-deepseek-v4-pro-0813-2026-09-26`](results/test-deepseek-v4-pro-0813-2026-09-26/repair/plan.json) | 12 | 4 / 8 | 9 | 4 / 8 / 0 | `9281abbc3631` |

  - 75 items in all, every one with ready gold and finish_reason `stop`, so
    the test round is 225 requests, not the note's design estimate of about
    360. The 21 error cards are 16 `unknown_field`, 4 `type_mismatch` and 1
    `unsupported_operator`, each with `field`. The largest card is 715 B.
  - Only plans are committed: `docs/results` holds no arm run directory
    (`-res`, `-bare`, `-cx`), and CI's second-turn test passes. No test
    repair prompt was prepared, since a defect the dev round shows must be
    corrected first.
- **CI python job mirror at b3a7d40** (`artifacts/ci/ci_mirror.sh
  merge-plans-b3a7d40`, the test image with the worktree's code mounted
  read-only and no network): 1,713 tests passed, 21 skipped, 96.84 percent
  coverage.
  - pyink, isort, pylint on CI's exact line (rc 0), pyright (0 errors) and
    lint-imports (5 contracts kept) pass.
  - The four docs-mounted test nodes pass, the frozen-prompt guard among
    them. CI's whole registration step, which the mirror reads only one
    node of, run alone with `docs/` mounted: 215 passed.
  - The benchmark gate, the adequacy gate (344 mutants, 4 waived survivors,
    0 unwaived), prepare and recall pass.
  - `score --check` of all 25 committed outputs and `repair --check` of the
    8 committed plans report no difference; no pool is committed.
- No model request was sent.

## Repair arm runner: 2026-10-02, branch repair-arms

- **Owner command** (d9e43fc). `scripts/repair_arms.py --split dev|test
  [--dry-run]` sends one split's arm runs. It is a new file rather than a mode
  of `scripts/test_passes.py`: that batch is driven by the test-run registry
  over one shared prompt copy, while an arm run has its own prompt set, built
  by `follow-up` from a plan, on both splits. It loads `test_passes.py` by path
  and reuses its registry reading, refusals, row states, prompt-copy check,
  layout and exit codes, and through it `dev_bakeoff.py`'s reading of a run,
  invoker, lock and endpoint pricing. It never publishes, scores or reads gold.
  - **Rows.** Dev: the four dev passes. Test: the registry's `published` rows
    in a repaired role, one per slot; pass B is never repaired, and the split
    is refused while a row is still `registered`. Passes go anchor, 8B, 120B,
    frontier; arms go resample, bare, counterexample.
  - **Config and cap.** Each row sends its pass's config, checked against the
    pass's run manifest (settings, prices, host, attempts and pacing). Its cap
    is read from the repair note's caps table for the slot and split, so a
    raised cap is an edit of that table.
  - **Prompt sets.** `artifacts/repair/<arm run id>`, built by the in-process
    `follow-up` step. An existing set must equal a fresh build, its creation
    time and source revision aside. On test the set must be the committed,
    admitted seed `docs/results/<arm run id>/` byte for byte, and the seed
    must equal a fresh build.
  - **Chains.** Resumes, gate stops, refusals and aborts follow the bake-off
    runner's reading of a run; an outage is re-run once as `-r2` from its own
    prompt set. A `follow-up` refusal for `prompt_too_large` or
    `follow_up_invalid` reports the round not run, and `plan_empty` leaves its
    rows unused.
- **Tests.** `tests/test_repair_arms.py`: 56 tests against a scripted
  follow-up step and a scripted call step, 3 of them on the committed passes,
  plans and note. Those 3 skip without `docs/`, so CI's registration step,
  which mounts `docs/`, now runs the file. With `docs/` mounted, the real
  follow-up step builds all 12 dev arms in a temporary directory, with 10, 7,
  8 and 11 items, the plans' counts. CI's pylint line and pyright's include
  list name the script.
- **Repair note.** "Commands to come" is replaced by "Commands": the owner's
  command for each split in Windows PowerShell 5.1 and Git Bash, the
  exit-code table, and the maintainer's seed, publish, score, `repair` and
  `repair-pool` commands.
- **Keyless dev run.** Run on the host with `uv run --frozen` in a temporary
  git copy of d9e43fc's code, configs, note, registry and the eight repaired
  passes; `DFILTERFORGE_MODEL_API_KEY` unset; `UV_OFFLINE=1`.
  - `--split dev --dry-run`: exit 0, nothing written.
  - `--split dev`: built the 12 prompt sets, then all 12 rows stopped at
    `api_key_missing` in the keyless preflight; exit 3, nothing sent.
  - The same command again: the 12 sets were found equal to a fresh build,
    and the 12 preflight calls stopped at `api_key_missing`; exit 3.
  - Worst request against the cap, by pass (resample, bare, counterexample):

    | Pass | Items | Worst request (USD) | Full-arm worst (USD) | Cap |
    | --- | ---: | --- | --- | ---: |
    | `dev-qwen3-32b-2026-09-26` | 10 | 0.000995, 0.001109, 0.001115 | 0.0098, 0.0105, 0.0108 | 0.05 |
    | `dev-qwen3.5-9b-2026-09-26` | 7 | 0.000854, 0.000966, 0.001040 | 0.0058, 0.0066, 0.0070 | 0.05 |
    | `dev-qwen3.5-122b-a10b-2026-09-26` | 8 | 0.008662, 0.009148, 0.009343 | 0.0687, 0.0720, 0.0736 | 0.10 |
    | `dev-deepseek-v4-pro-0813-2026-09-26` | 11 | 0.012175, 0.012904, 0.013584 | 0.1306, 0.1391, 0.1447 | 0.20 |

    The full-arm figure is one attempt per item at its worst case.
- **Test split.** `--split test`, with and without `--dry-run`: exit 2,
  refused before any call, naming all 12 missing seeds
  (`docs/results/test-*-{res,bare,cx}-2026-09-26`). Corrected after review:
  this line first said no test prompt set was built, which was false. At
  d9e43fc the batch built each owed test arm's prompt set with `follow-up`
  in a temporary directory before it found the seed missing, so all 12 were
  built and deleted before that refusal; nothing was kept and nothing was
  sent. This branch adds no seed and admits no digest.
- **CI python job mirror at d9e43fc** (`artifacts/ci/ci_mirror.sh
  runner-d9e43fc`, the test image with the worktree's code mounted read-only
  and no network): overall status 0. 1,766 tests passed and 24 skipped (53
  and 3 more than at b3a7d40, the 56 new tests), with 96.77 percent
  coverage; the new script alone is at 96 percent.
  - pyink, isort, pyright (0 errors) and lint-imports (5 contracts kept)
    pass. The four docs-mounted test nodes, the benchmark gate, the adequacy
    gate (344 mutants, 4 waived survivors, 0 unwaived), prepare and recall
    pass.
  - `score --check` of all 25 committed outputs and `repair --check` of the
    8 committed plans report no difference; no pool is committed.
  - CI's registration step with `docs/` mounted: 271 passed (215 before, plus
    the 56 new tests). The pair-report and second-turn steps: 3 passed.
  - CI's exact pylint line gives rc 0. Against `origin/main`, the only
    prepare-hashed files changed are still `generation.py` and
    `scripts/model_run.py`.
- No model request was sent.

## Repair arms PR check: 2026-10-02, branch repair-arms

- **Branch.** At eb7ebcd, `repair-arms` holds 61 commits that `origin/main`
  (7a8ec03) does not. 58 are ordinary commits and three are merges: two of
  `repair-cards` (e5cb093, cdbc25f) and one of `origin/main` (846fc7b, with
  parents 58114f6 and 7a8ec03). It carries `repair-multiturn` up to 281b2ce
  without a rebase, because the smoke manifests record that head.
  - `git diff --stat origin/main..HEAD` gives 34 files, 15,727 insertions
    and 139 deletions.
  - The files are CI's workflow, `pyproject.toml`, the repair and
    second-turn notes, this file and the eight plans.
  - Also three scripts (`model_run.py`, `two_turn_smoke.py`,
    `repair_arms.py`), eight `src/dfilterforge` modules, nine test files and
    one test data file.
- **Hashed files.** The frozen test prompt set's `prepare.json` records 12
  source digests.
  - Every digest equals its blob on `origin/main`. On this branch exactly two
    differ: `src/dfilterforge/generation.py` and `scripts/model_run.py`.
  - The test-run registry and the freeze record are unchanged from
    `origin/main`. The registry holds five `published` and eleven `unused`
    rows, and the record still admits one prepare.
- **Plans recounted from the committed `plan.json` files.**
  - Dev: 36 items, 27 silent-wrong and 9 invalid. Probe `semantic-29`,
    labels `be0c91824bb5`.
  - Test: 75 items, 54 silent-wrong and 21 invalid. Probe `semantic-35`,
    labels `c0b30949787e`. The 21 error cards are 16 `unknown_field`, 4
    `type_mismatch` and 1 `unsupported_operator`.
  - Each pass's item and outcome counts and each plan's SHA-256 equal the
    tables in "Repair plans committed" above.
  - The largest card is 717 B on dev and 715 B on test.
  - `docs/results` holds no arm run directory and no seed.
- **Runner.** `tests/test_repair_arms.py` collects 56 tests.
- **CI python job mirror at eb7ebcd.** Run as `artifacts/ci/ci_mirror.sh
  repair-arms-pr`, in the test image with the worktree's code mounted
  read-only and no network. Overall status 0.
  - The mirror reads pyink, isort, pylint, pyright and lint-imports from
    `ci.yml`. All gave rc 0: pylint 10.00/10 on CI's line with
    `scripts/repair_arms.py`, pyright 0 errors, lint-imports 5 contracts
    kept.
  - pytest: 1,766 passed and 24 skipped, coverage 96.77 percent.
    `scripts/repair_arms.py` alone is at 96 percent.
  - The four docs-mounted test nodes passed, the frozen-prompt guard among
    them.
  - The benchmark gate passed. The adequacy gate passed with 344 mutants, 4
    waived survivors and 0 unwaived. Prepare and recall passed.
  - `score --check` of all 25 committed outputs (17 `scored/`, 4
    `control-reference/`, 4 `control-mutation/`) reported no difference.
    `repair --check` of the 8 committed plans reported none either, and no
    pool is committed.
- **CI's three docs-mounted steps.**
  - Each node list was run exactly as `ci.yml` gives it, in the test image
    under the compose `test` service's limits. Those limits are: no network,
    all capabilities dropped, read-only root, init, 128 pids,
    no-new-privileges, 2 CPUs, 2 GB, and a 128 MB exec `/tmp`.
  - The worktree's code and `docs/` were mounted read-only.
  - Results: registration 271 passed, pair report 2 passed, second turn 1
    passed.
- **CI's exact pylint line**, under the same limits: 10.00/10, rc 0.
- **Not run locally.** CI's `lab`-image steps did not run. The mirror runs
  `score --check` and `repair --check` in the test image with the branch's
  `src/` mounted, and the `lab` image was not rebuilt. The web and container
  jobs did not run either; this branch touches neither `apps/` nor
  `compose.yaml`.
- No fix was needed, and no model request was sent.

## Repair arms review fixes: 2026-10-02, branch repair-arms

A review of def2b8a confirmed ten findings; eight commits fix them, each with
a test where one is possible. Every check below ran in the test image with
the worktree's code mounted read-only and no network.

- **Raised caps (bfd1ad2).** A budget-stop raise used to be an edit of the
  slot's row in the note's Caps table, which gave the raise to all three arms
  and their `-r2` re-runs, and the docs test pinned that table, so the
  documented remedy turned CI's registration step red. The Caps table now
  keeps the registered caps. A new raised caps table in the repair note holds
  one arm run per row, and the batch gives that cap to that run alone. It
  refuses a raise of a run with no budget stop to resume, one not above its
  slot's cap, and one naming no arm run of its split. The docs test ties the
  registered caps to the protocol's sentence and holds every run's cap at or
  above them.
  - Checked: with a row raising `dev-deepseek-v4-pro-0813-res-2026-09-26` to
    0.30 in a copy of `docs/`, the batch gave that run 0.30 and its bare and
    cx runs and every `-r2` 0.20. CI's registration step over that copy
    passed (282 at bfd1ad2).
  - The docs test of the committed dev plans now builds each arm with the
    real follow-up step directly, rather than through the batch's state
    reading, which a committed raise or a published arm run would change in
    CI.
- **Seeds before builds (daf8cf7).** While no test arm run has a committed
  seed, the batch names every missing seed and builds nothing. It checks a
  seed's admission before building it. Once seeding has begun, a missing seed
  is still built, so a pass whose second turns `follow-up` refuses (a round
  not run, which can never get a seed) reaches its final state.
  - Checked over the committed tree: the test split's refusal came after 0
    `follow-up` builds, where d9e43fc made 12.
- **Committed runs (8ed7d1d).** Before anything is built or sent, the batch
  refuses (exit 2) a run that the repository records while its directory
  under `artifacts/repair` is gone. Such a run is published in
  `docs/results/<run id>/`, keeps a manifest in
  `docs/decisions/evidence/repair-arms/<run id>/`, or is an arm the pass's
  `repair/not_run.json` names (or a record the batch cannot read).
  - Before this fix, a published dev or test round whose ignored copies were
    deleted was sent again in full.
  - The three new tests fail with the guard removed.
- **Spend summary (c8c692d).** Each summary row carries `first_run`, the
  charged bound of the first run an `-r2` re-run replaced, and the total
  adds it. Every printed bound is rounded up to four decimals, the total with
  its exact value beside it.
  - Checked: an outage followed by a complete `-r2` and 11 complete rows gives
    a total equal to the sum of all 13 run manifests (0.000260 USD), printed
    as 0.0003.
- **Keyless invoker test (0a141d6).** A new test runs the batch's own
  invoker against a child that reports whether the key variable reached it:
  absent for a keyless call, present for a paid one. Changing the invoker to
  pass the key to every child now fails that test; before, all 56 tests
  passed with that change.
- **Second-turn prompt files (a578066).** A committed prompt now holds two
  messages, or four in a bare or counterexample arm run, first run or re-run,
  named after a pass with a committed plan.
  `tests/test_generation.py::test_committed_prepared_files_reserialize_byte_for_byte`
  now runs in CI's second-turn step with `docs/` mounted.
  - Checked: with the three `test-qwen3.5-9b` arm seeds built into a copy of
    `docs/`, the old test failed on `test-qwen3.5-9b-bare-2026-09-26`, and the
    new step's two nodes passed.
- **Repair note (f856409).** Order items 3 to 5 now say that the plans were
  committed on `repair-arms` and that both rounds run from `main` after its
  merge. They also place the dev round and any correction it names between
  the merge and the test seeds, and they say they were corrected.
  - The Test passes section gives the per-pass test counts, recounted from
    the committed plans and outcomes: 75 items in 56 cases, 54 silent-wrong
    and 21 invalid, 225 requests.
  - The "about 360 requests" figure is marked as the superseded design
    estimate, and "Test trigger counts" left "Not measured yet".
- **This log (f70432b).** The keyless test-split line above no longer says
  that no test prompt set was built. The mirror rise from b3a7d40 is 53
  passed and 3 skipped, the 56 new tests.
- **Prepare-hashed files.** Against `origin/main`, still only
  `src/dfilterforge/generation.py` and `scripts/model_run.py` differ from the
  digests the frozen test prompt set records.
- **CI's docs-mounted steps and pylint at f70432b**, under the compose `test`
  service's limits (no network, all capabilities dropped, read-only root,
  init, 128 pids, no-new-privileges, 2 CPUs, 2 GB, a 128 MB exec `/tmp`):
  - registration: 290 passed (271 before, plus the 19 new tests in
    `tests/test_repair_arms.py`, which now collects 75);
  - pair report: 2 passed;
  - second turn: 2 passed, the reserialize node included;
  - CI's exact pylint line: 10.00/10, rc 0.
- **CI python job mirror at f70432b** (`artifacts/ci/ci_mirror.sh
  review-fixes-f70432b`): overall status 0.
  - pyink, isort, pylint, pyright (0 errors) and lint-imports (5 contracts
    kept) pass.
  - pytest: 1,785 passed and 24 skipped (19 and 0 more than at d9e43fc), with
    96.82 percent coverage; `scripts/repair_arms.py` alone is at 97 percent.
  - The five docs-mounted test nodes the mirror finds in `ci.yml` pass, the
    reserialize node and the frozen-prompt guard among them.
  - The benchmark gate, the adequacy gate (344 mutants, 4 waived survivors,
    0 unwaived), prepare and recall pass.
  - `score --check` of all 25 committed outputs (17 `scored/`, 4
    `control-reference/`, 4 `control-mutation/`) and `repair --check` of the
    8 committed plans report no difference; no pool is committed.
- **Not run locally.** CI's `lab`-image steps, the web job and the container
  job did not run; the mirror runs the `lab` checks in the test image with
  the branch's `src/` mounted.
- No model request was sent.

## Dev repair rounds published: 2026-10-04, branch dev-repair-round

The owner ran the dev repair batch (`scripts/repair_arms.py --split dev`)
from the main checkout at bff373c on 2026-10-04. Its runner summary, now
committed as
[`evidence/repair-arms/summary-dev-2026-10-04.txt`](decisions/evidence/repair-arms/summary-dev-2026-10-04.txt)
and `.json`, gives every row a final state: nine arm runs `done` and the
three frontier arms `not_run` after an outage on their `-r2` re-runs. Its
total charged upper bound is 0.0459 USD, rounded up (0.045822 exact), every
first run an `-r2` re-run replaced included. On `dev-repair-round` the three
done rounds are published, scored and summarized, and the frontier runs'
evidence is kept. No model request was sent from this branch, and no command
set the key variable.

- **The nine runs.** Each is complete at bff373c and answered every
  triggered item of its plan; each scored tree covers that many items.
  - Anchor, `qwen/qwen3-32b`: 10 of 10 per arm, all served by DeepInfra,
    one invocation each and no retry.
  - 8B, `qwen/qwen3.5-9b`: 7 of 7 per arm, all served by DeepInfra. The
    resample took three invocations (7, 3 and 1 requests sent): 11 attempts,
    4 of them HTTP 429, so `mei-0022` took 3 attempts and `mei-0023` and
    `mei-0024` took 2. Bare and counterexample took one invocation and no
    retry.
  - 120B, `qwen/qwen3.5-122b-a10b`: 8 of 8 per arm, all served by Novita,
    one invocation each and no retry.
- **repair@1 per arm**, from each committed `repair/summary.json`, with the
  bootstrap's 2.5 and 97.5 percentiles and the repaired items. These are dev
  numbers. Every arm comparison is inconclusive (fewer than 10 discordant
  cases), as the [repair note's](decisions/repair-round.md) Limits expected.

  | Round | Triggered | Resample | Bare | Counterexample |
  | --- | --- | --- | --- | --- |
  | [`dev-qwen3-32b-2026-09-26`](results/dev-qwen3-32b-2026-09-26/repair/summary.md) | 10 items in 6 cases | 0.000 [0.000, 0.000], 0/10 | 0.200 [0.000, 0.417], 2/10 | 0.400 [0.143, 0.750], 4/10 |
  | [`dev-qwen3.5-9b-2026-09-26`](results/dev-qwen3.5-9b-2026-09-26/repair/summary.md) | 7 items in 6 cases | 0.000 [0.000, 0.000], 0/7 | 0.143 [0.000, 0.500], 1/7 | 0.429 [0.000, 0.818], 3/7 |
  | [`dev-qwen3.5-122b-a10b-2026-09-26`](results/dev-qwen3.5-122b-a10b-2026-09-26/repair/summary.md) | 8 items in 7 cases | 0.125 [0.000, 0.400], 1/8 | 0.250 [0.000, 0.600], 2/8 | 0.625 [0.250, 1.000], 5/8 |

- **Commits.** Each round is committed whole: its three published arm runs
  with their `scored/` trees, and the pass's `repair/summary.json` and
  `summary.md`. Each round's `repair/plan.json` is unchanged, and no
  `not_run.json` exists.
  - 68556a4: the frontier evidence, 15 files.
  - 8a6e90d: the anchor round, 95 files.
  - d070b56: the 8B round, 78 files.
  - 389c8ed: the 120B round, 91 files.
  - e810150: the [locked test page](results/locked-test-v1.md) now says that
    no test repair request has been sent, with a dated correction. Its old
    "No repair request has been sent" stopped being true when the dev batch
    ran.
- **The frontier pass** `dev-deepseek-v4-pro-0813-2026-09-26` got no answer.
  Its three arm runs and their `-r2` re-runs each made 33 attempts (11 items,
  3 each, over 3 invocations at `max_usd` 0.2), 198 in all. Every attempt was
  HTTP 429 from the DeepInfra-pinned route, between 02:23:26 and 02:41:50 UTC.
  Each manifest's `charged_usd_upper_bound` is 0.0, and the attempt logs'
  `charged_micro_usd` sum to 0.
  - Each run's `run_manifest.json` and `attempts/C4.jsonl` are kept in
    `docs/decisions/evidence/repair-arms/<run id>/` (68556a4). They are
    byte-equal (`cmp`) to the runner's copies, and these runs are never
    published.
  - Beside them sit the runner summary and the owner's
    [provider diagnostics](decisions/evidence/repair-arms/frontier-provider-diagnostics-2026-10-04.md),
    with the user id and the owner's location redacted.
  - The pass's `repair/plan.json` is still at the plan stage, and no round
    summary or `not_run.json` is written for it. `repair --not-run` records
    only gate stops, so these arms have no record in the repair tooling.
- **Images.** Both were built from the worktree at bff373c under their own
  tags, so the shared `0.1.0` tags were not rebuilt:
  - `dfilterforge-lab:dev-repair-round`
    `sha256:15af4fbb765d8bee57aefa6f5bb7eb0b3818d261a204270e9f769527fa419fe8`.
    Its doctor reported tshark 4.6.8, and its ID was unchanged before the
    last score.
  - `dfilterforge-test:dev-repair-round`
    `sha256:16772cade7884576aa4ad2d02d75c2dfe80c55b4208971e2a79f0787e8b1b643`.
- **Checks**, in those images with no network:
  - Before anything was written, `repair --check` of the four dev plans at
    the plan stage reported no difference.
  - Each new arm run's `score --check` and each round's `repair --check`
    reported no difference.
  - At 389c8ed, CI's re-score loop checked 34 outputs (the 25 checked before
    plus the 9 new `scored/` trees), and CI's repair loop checked 8 plans.
    Neither found a difference. Three plans are at the summary stage;
    `dev-deepseek-v4-pro-0813-2026-09-26` and the four test plans are still
    at the plan stage.
  - CI's three docs-mounted steps passed in the new test image: registration
    290 passed, pair report 2, second turn 2. The second-turn nodes accept
    the nine runs, whose prompts hold 2 messages in each resample and 4 in
    each bare and counterexample run. After e810150 the registration and
    pair steps passed again (290 and 2).
  - Against bff373c, none of the 12 prepare-hashed files changed. Apart
    from this file, every changed path is under `docs/results/` or
    `docs/decisions/evidence/repair-arms/`. The only existing files modified
    are this file and the locked page, where one line changed.
  - Not run: the other CI steps (format, lint, type checks, the full suite,
    the gates). No code changed.
- **Two deviations from the repair note's maintainer section.**
  - The work ran in the worktree `.worktrees/dev-repair-round`, not in the
    main checkout, which stays untouched while other work runs. `publish`
    read each run from the main checkout's ignored `artifacts/repair/` and
    wrote into the worktree's `docs/results/`.
  - `--code-revision` was fixed at bff373c, the code the runs were prepared,
    sent and scored with, not `$(git rev-parse --short HEAD)` of this
    docs-only branch. 431df73 played the same role for the dev bake-off
    passes, and 0623248 for the test baselines.
- **Compose override**, to recreate the setup. The override file holds
  these five lines:

  ```yaml
  services:
    lab:
      image: dfilterforge-lab:dev-repair-round
    test:
      image: dfilterforge-test:dev-repair-round
  ```

  Every container ran under its own compose project, from the worktree root
  in Git Bash:
  `MSYS_NO_PATHCONV=1 docker compose -p dfilterforge-devrepair -f compose.yaml -f <override> ...`.
  The lab used `--profile pilot run --rm lab`. The docs-mounted steps used
  `--profile dev run --rm --volume "$(pwd -W)/docs:/workspace/docs:ro" test`.
- **Next.** The frontier round, the dev pool and the test seeds wait for
  the re-run on NextBit, OD6 (a maintainer default; the owner confirmed it on
  2026-10-05). The owner's decision of 2026-10-04, recorded
  in the committed diagnostics, moves the frontier slot's repair arms from
  DeepInfra to NextBit, using the committed config
  `evidence/bakeoff/configs/deepseek-v4-pro-0813_nextbit_enabled-false.json`.
  By the default the maintainer took, the dev frontier round re-runs there
  under new run ids before the test round. The ruling and its tooling are not
  committed yet.

## Frontier arms moved to NextBit: 2026-10-04, branch dev-repair-round

The owner ruled on 2026-10-04 that the frontier slot's repair arms move from
DeepInfra to NextBit (OD5). Three commits on `dev-repair-round` register the
move and make the checks and the batch take it: 725bb5e, c57142a and 1d07612.
Each new or extended test failed before its change and passed after it, in the
test image built from the worktree. No model request was sent, no command set
the key variable, and none of the 12 prepare-hashed files changed against
bff373c.

- **The ruling.** The [repair note](decisions/repair-round.md) keeps the
  owner's decision apart from the maintainer's defaults, under "Owner
  decisions, 2026-10-04". A default stays one until the owner confirms it.
  - OD5, by the owner: deepseek/deepseek-v4-pro-0813's repair arm runs still
    to be sent, on test and on dev if dev is re-run (OD6), send the committed
    config `deepseek-v4-pro-0813_nextbit_enabled-false`. Every other slot is
    unchanged, and the counted first turns stay the answers DeepInfra served.
  - OD6, default taken: the dev frontier round is re-run on NextBit before the
    test round, as new runs with the tag `nb` after the arm tag. The owner's
    paid dev command is the confirmation.
  - OD7, default taken: on NextBit an arm run keeps the outage rule, one
    re-run from scratch, `-nb-r2` on dev and `-r2` on test. A second outage is
    not run, and no arm moves again.
  - OD8, default taken: the test frontier arms keep their registered ids,
    which no request has used.
- **Its evidence, recounted from the committed files.** The six DeepInfra
  runs were sent from bff373c. Each made 33 attempts (3 invocations of 11
  requests at `max_usd` 0.2), 198 in all, and every attempt was HTTP 429: 0
  answers and 0 charged, from 2026-10-04T02:23:26.403803Z to
  02:41:50.888604Z. The NextBit config's SHA-256 is
  `2942954e0c6896c29fe075f20cb9d0ce4a885d9ac72af8396022723b67de58ce`.
  Against the DeepInfra config it differs only in
  `settings.openrouter.provider_order` and in `prices.source`,
  `prices.usd_per_million_input` and `prices.usd_per_million_output`. The
  ruling record carries the test baseline's HTTP 429, 776 in all and 754
  before an item's last attempt, and the caps, 0.20 USD on dev and 0.50 on
  test.
- **The ids.** Each fits the call step's result-name pattern,
  `(dev|test)-[a-z0-9][a-z0-9.-]{0,31}-YYYY-MM-DD`, whose middle is at most 32
  characters.
  - New on dev: `dev-deepseek-v4-pro-0813-res-nb-2026-09-26`,
    `dev-deepseek-v4-pro-0813-bare-nb-2026-09-26` and
    `dev-deepseek-v4-pro-0813-cx-nb-2026-09-26` (middles 27, 28 and 26), and
    their `-nb-r2` re-runs (30, 31 and 29). The longest is
    `dev-deepseek-v4-pro-0813-bare-nb-r2-2026-09-26`, 46 characters.
  - Registered and unchanged on test: `test-deepseek-v4-pro-0813-res-2026-09-26`,
    `test-deepseek-v4-pro-0813-bare-2026-09-26` and
    `test-deepseek-v4-pro-0813-cx-2026-09-26`, and their `-r2` re-runs
    (middles 23 to 28).
  - No registry run id contains `-nb-`. The registry's four frontier rows are
    as they were: the pass `published`, and its `-fb`, `-r2` and `-fb-r2`
    rows `unused`.
  - The six DeepInfra runs are evidence only. They are never published or
    sent again, and they are no longer batch rows.
- **725bb5e: the registration.** It adds lines only, apart from one in
  `test-runs.json`:
  - a dated paragraph in the protocol's Repair section, with one-line
    pointers under Decoding and provenance and under Models;
  - the repair note's "Owner decisions, 2026-10-04" section, ten passages
    marked "Amended 2026-10-04", and an added list under Limits;
  - the bake-off note's section "Repair arms' provider: 2026-10-04";
  - a dated note in `test-runs.md` and an `amended` entry in
    `test-runs.json`, whose only removed line is `"rerun_tag": "r2"`, put back
    with a trailing comma. No registry row or status changes.
  - The record
    [`evidence/repair-arms/ruling-2026-10-04.json`](decisions/evidence/repair-arms/ruling-2026-10-04.json)
    (schema `repair-arms-ruling/1.0`) holds the four decisions, the moved ids
    and the evidence figures.
  - The four amended docs keep the code fence counts they had at bff373c,
    and the registered four-cell arm table (8 rows) is identical to
    bff373c's.
  - Test: `test_the_frontier_move_ruling_matches_its_evidence` in
    `tests/test_repair_arms.py` recounts the record's figures from the six
    committed runs, checks the config's digest and diff, derives each moved
    id from its registered one, and keeps the replaced runs out of
    `docs/results`. With the test alone it failed (FileNotFoundError, no
    record). After the commit it passed (1 passed).
- **c57142a: `repair --check` takes the moves.**
  - `repair_round.PROVIDER_MOVES` holds the two moves as constants, because
    the lab container sees only `docs/results`.
  - `arm_run_ids` gives the `-nb` names, and `registered_run_ids` keeps the
    protocol's, the only names the follow-up step builds under. So a moved
    run's `prepare.json` may name its arm's registered first id, and only a
    moved run's may; its manifest must still name its own directory.
  - A moved run's settings must be the pass's with the move's provider
    order, and its prices the move's. Its host, attempts and pacing must be
    the pass's. A base with no move is checked as before.
  - Tests in `tests/test_repair.py`: five new and one extended, 11 nodes.
    Before: 11 failed, each with an AttributeError (`repair_round` had no
    `ProviderMove`, `PROVIDER_MOVES` or `registered_run_ids`). After: 11
    passed.
- **1d07612: the batch sends the moves.**
  - `scripts/repair_arms.py` holds the same two moves with the committed
    NextBit config. A moved pass's rows send that config under the slot's cap
    (0.20 on dev, 0.50 on test), named by `arm_run_ids`.
  - `check_move` refuses a move config that is not a committed bake-off
    config or that names another host or model. It also refuses one that
    keeps the pass's provider order, or that differs from the pass's config
    in any other setting.
  - A moved run's prompt set is built under the arm's registered first id
    and installed under its own id.
  - Tests in `tests/test_repair_arms.py`: four new and three extended.
    Before: 7 failed, with an AttributeError (`repair_arms` had no
    `PROVIDER_MOVES` or `registered_run_ids`) or, in one, because the
    frontier row still took the DeepInfra config. After: 7 passed. On the
    host the file gave 73 passed and 7 failed before, and 80 passed after.
- **Mirrors.** Each ran in the test image built from the worktree at that
  commit. The compose `test` service has no network, and the compose project
  was `dfilterforge-devrepair`, with the override from "Dev repair rounds
  published" above.
  - At 725bb5e, `dfilterforge-test:dev-repair-round`
    `sha256:f32637e2aac725fd5315df8ac6e43f1610b8e84c02b69bebe4f010c4ce6dd835`:
    - pyink (96 files) and isort clean, pylint 10.00/10 with rc 0, pyright 0
      errors;
    - CI's docs-mounted steps: registration 291 passed, pair report 2,
      second turn 2.
    - The full suite and the gates did not run for this docs and test commit.
  - At c57142a,
    `sha256:51cb0f3b38d483f31cb5175beecc8cf21650cd1db59395ceb700e0f2bc00a992`:
    - pyink, isort, pylint (10.00/10, rc 0), pyright (0 errors) and
      lint-imports (5 contracts kept, 0 broken) pass;
    - pytest: 1,795 passed and 25 skipped, coverage 96.83 percent;
    - registration 291, pair report 2, second turn 2.
  - At 1d07612,
    `sha256:ab8d3b9259896fe284e29b58faddddadf2048a290018b99d52fe5c6a3f0e96d3`:
    - the same format, lint, type and import checks pass;
    - pytest: 1,799 passed and 25 skipped, coverage 96.85 percent;
    - registration 295 (the four new tests), pair report 2, second turn 2;
    - the benchmark gate (36 of 36 semantics), the adequacy gate (344
      mutants, 4 waived survivors, 0 unwaived), prepare (40 items) and recall
      pass.
- **Lab image and checks.** `dfilterforge-lab:dev-repair-round` was rebuilt
  from the worktree at c57142a:
  `sha256:03aa46ed3dc95d9ac52b65d2217d37207098a544f7e90ee75eeb3b04ba43fef4`.
  The rebuild at 1d07612 cached every step and gave the same ID: the image
  copies `src/` and the project files, none of which 1d07612 touches.
  - At both commits, `repair --check` checked the 8 committed plans with no
    difference. The three dev rounds at the summary stage kept their
    `summary.json` digests (`f69f0ded`, `d4bb1e5c`, `e95af163`). The frontier
    dev plan and the four test plans are still at the plan stage.
  - At both commits, CI's re-score loop checked 34 committed outputs with 0
    failures.
- **Keyless end to end at 1d07612.** The main checkout's ignored
  `artifacts/repair` was copied into the worktree's ignored
  `artifacts/repair` (`diff -rq`: identical). The batch ran from the
  worktree with the key variable unset.
  - `--dry-run` exited 0. It listed 12 arm runs of 4 passes: the nine done
    rows as done (complete), and the three frontier rows owed. Those are
    `dev-deepseek-v4-pro-0813-res-nb-2026-09-26`,
    `dev-deepseek-v4-pro-0813-bare-nb-2026-09-26` and
    `dev-deepseek-v4-pro-0813-cx-nb-2026-09-26`, each with config
    `deepseek-v4-pro-0813_nextbit_enabled-false`, 11 items and cap 0.20.
  - Worst request: 0.012053, 0.012645 and 0.013197 USD. Full-arm worst, at
    one attempt per item: 0.1299, 0.1368 and 0.1413.
  - The dry run printed each build as `follow-up ... --output-dir
    artifacts/repair/dev-deepseek-v4-pro-0813-<arm tag>-2026-09-26`,
    installed as the `-nb` directory.
  - Without `--dry-run`, the batch built the three prompt sets, and each
    keyless preflight stopped at `api_key_missing` (call exit 2). It printed
    "ABORTED: the keyless preflight passed and nothing was sent" and exited 3. The
    summary's total charged upper bound stayed 0.0459 USD (0.045822 exact).
  - Each built `prepare.json` names its arm's registered first id as its
    `prepare_id`: `dev-deepseek-v4-pro-0813-res-2026-09-26`,
    `dev-deepseek-v4-pro-0813-bare-2026-09-26` and
    `dev-deepseek-v4-pro-0813-cx-2026-09-26`.
  - Afterwards the copy differed from the main checkout's only by the three
    new `-nb` directories, and it was removed. The SHA-256 list of the main
    checkout's `artifacts/repair` and `artifacts/repair-arms` was the same
    before and after (`cmp` rc 0).
- **Host checks**, on Windows. pyink, isort and pyright passed at each
  commit.
  - Host pylint gave rc 2 at 725bb5e and 1d07612, from eight E1101 messages
    in `src/` on POSIX-only members (`os.O_NOFOLLOW`, `os.O_NONBLOCK`,
    `os.killpg`, `signal.SIGKILL`). In the test image pylint gave 10.00/10
    and rc 0.
  - At c57142a, `tests/test_repair.py` gave 136 passed, 2 skipped and 3
    failed on the host. The three failures are tests older than c57142a
    that create symlinks, which the host refused (WinError 1314). In the
    test image the full suite passed.
- **Paths and guard.** Against bff373c, `git diff --name-only` lists only:
  - `docs/results/` (the three rounds and the locked page);
  - `docs/decisions/evidence/repair-arms/` and
    `docs/decisions/evidence/test-runs.json`;
  - `docs/protocol.md`, the repair, bake-off and test-run notes, and this
    file;
  - `scripts/repair_arms.py`, `src/dfilterforge/repair_round.py`,
    `tests/test_repair.py` and `tests/test_repair_arms.py`.

  The prepare-hashed guard printed nothing.
- **This log.** With this section in place, CI's three docs-mounted steps
  passed in the 1d07612 test image: registration 295, pair report 2, second
  turn 2.
- **Not run.** No paid request was sent. The NextBit rows have stopped only
  at the keyless preflight, so NextBit has served no repair arm yet. CI's
  web and container jobs did not run, and nothing was pushed.

## Frontier move review fixes: 2026-10-04, branch dev-repair-round

A review of the move's registration (725bb5e to 30eb879) confirmed five
findings; five commits fix them, two with a test. No model request was sent,
no command set the key variable, and nothing was pushed.

- **What the 429 records show (169d2fb).** The protocol amendment and the
  ruling said all 198 dev frontier attempts were HTTP 429 "from the
  provider's shared pool (`engine_overloaded`,
  `upstream_provider_shared_pool`)". The records do not show that.
  - Recounted from the six committed evidence runs: 198 attempts, every one
    HTTP 429 with `provider` null and `provider_error_code` "429". No file
    under the six evidence directories contains `engine_overloaded` or
    `shared_pool`.
  - The client keeps only `error.code` from an error body
    (`_error_body_code` in `src/dfilterforge/model_client.py`). The
    shared-pool body comes from one request the owner sent after the round
    (diagnostics, section 2).
  - The protocol, the ruling's `why` and its rejected "waiting on DeepInfra"
    entry, and the note's shorthand of that entry now say this: no answer
    between 02:23 and 02:41 UTC on the DeepInfra-pinned route, and the
    shared-pool body from the owner's later request.
  - Not changed: the progress lines. They already said only "HTTP 429 from
    the DeepInfra-pinned route". 725bb5e's commit message keeps the old
    claim, since history is not rewritten. (Corrected on 2026-10-05: this
    was false when written. The Current slice said "The frontier arms got
    only HTTP 429 from DeepInfra", which credits the 429s to the provider;
    dabaf6c changed it to the DeepInfra-pinned route.)
- **The test baseline's 429 count (3b83b27).** The amendment set "754 HTTP
  429" beside the dev round's 198, which counts every attempt.
  - Recounted from
    `docs/results/test-deepseek-v4-pro-0813-2026-09-26/attempts/`: 1,202
    attempts, 776 HTTP 429 and 426 HTTP 200. Of the 429s, 754 came before an
    item's last attempt (C1 195, C2 199, C3 193, C4 167) and 22 on it (C1
    21, C4 1). All 776 have `provider` null.
  - The ruling now holds `test_baseline_http_429` 776,
    `test_baseline_http_429_before_last_attempt` 754 and
    `test_baseline_run`. The protocol, the repair note, the ruling's `why`
    and the progress line above give both figures.
  - `test_the_frontier_move_ruling_matches_its_evidence` recounts both from
    the baseline's committed attempts and ties the second to the locked
    page's sentence. Before the ruling changed it failed on
    `{'test_baseline_http_429': 754} != {'test_baseline_http_429': 776}`;
    after, it passed.
- **OD6, not OD5, replaces the six runs (adb2f8d).** The "Not run beyond the
  gate" amendment said OD5 replaced the six DeepInfra runs with the NextBit
  runs. The committed diagnostics say the owner did not answer whether dev
  re-runs; that is the default OD6.
  - The amendment now says the six are not run under the outage rule and
    are kept as evidence, and that OD5 is the provider move. It says their
    replacement is OD6, which the owner's paid dev command confirms before
    the round's summary.
  - OD5's text in the note and the ruling now covers the dev round only if
    it is re-run. So do the two progress lines that repeated the
    attribution: the OD5 bullet above and the bullet under Blocked or
    unverified.
- **The Order step (7586346).** The amended Order step put the NextBit
  re-run and the pool "before any correction". It now says "any further
  correction", and names OD5's move (725bb5e, c57142a, 1d07612) as the
  correction for the DeepInfra outage, as the protocol and Planned next
  already did.
- **The registry names the -r2 re-runs (2915a74).** The registry's
  amendment, in `test-runs.md` and in `test-runs.json`, named only the three
  first test frontier arm runs. Both now also name
  `test-deepseek-v4-pro-0813-{res,bare,cx}-r2-2026-09-26`, which the ruling,
  OD7 and the batch move too.
  - The ruling test now requires both texts to name exactly the ruling's
    six test move arm runs. Before the text changed it failed: the ruling
    had 3 more items, the first
    `test-deepseek-v4-pro-0813-cx-r2-2026-09-26`. After, it passed.
- **Checks.** They ran in `dfilterforge-test:dev-repair-round`, rebuilt from
  the worktree at 2915a74:
  `sha256:a7ca6d35053540567dcb97975bd0ce76053eaefd34aea42c438871caee3058e0`.
  The compose project was `dfilterforge-devrepair`, with the override above.
  - pyink (96 files) and isort are clean, and pyright reports 0 errors.
  - CI's three docs-mounted steps passed: registration 295, with no skip;
    pair report 2; second turn 2.
  - On the host, `tests/test_repair_arms.py`, `tests/test_hosted_test_runs.py`
    and `tests/test_test_passes.py` gave 155 passed.
  - Not run: the full suite, the gates and pylint. No `src/` or `scripts/`
    file changed, and the only code change is inside a docs-gated test.
  - The prepare-hashed guard printed nothing.
    `git diff --name-only 30eb879..HEAD` lists only `docs/protocol.md`, the
    repair and test-run notes, the ruling, `test-runs.json`,
    `tests/test_repair_arms.py` and this file.

## Dev repair round verified at 918bed9: 2026-10-04, branch dev-repair-round

The branch was checked whole at 918bed9 on 2026-10-04: CI's python job
mirrored, CI's lab loops run, and the owner's dev and test commands run
without the key. This section also gathers the dev round's figures, read
again from the committed files. No model request was sent, no command set
the key variable, and nothing was pushed.

- **The owner's dev batch**, from the committed runner summary
  [`summary-dev-2026-10-04.json`](decisions/evidence/repair-arms/summary-dev-2026-10-04.json),
  written at 2026-10-04T02:41:51Z from bff373c and marked final. The batch
  sent 277 requests: 79 in the nine done arm runs and 198 in the six
  frontier runs. Its total charged upper bound is 0.045822 USD, printed
  rounded up as 0.0459, all of it from the nine done runs.

  | Slot | Arm runs | Requests | Answers | HTTP 429 | Served by | Charged at most (USD) |
  | --- | --- | --- | --- | --- | --- | --- |
  | Anchor, `qwen/qwen3-32b` | 3, 10 items each, `done` | 30 | 30 | 0 | DeepInfra | 0.005259 |
  | 8B, `qwen/qwen3.5-9b` | 3, 7 items each, `done` | 25 | 21 | 4 | DeepInfra | 0.004868 |
  | 120B, `qwen/qwen3.5-122b-a10b` | 3, 8 items each, `done` | 24 | 24 | 0 | Novita | 0.035695 |
  | Frontier, `deepseek/deepseek-v4-pro-0813` | 3, 11 items each, `not_run` (outage on the `-r2` re-run) | 198 | 0 | 198 | none | 0.0 |

  - The 8B resample retried its 4 HTTP 429: 11 requests over 3
    invocations for 7 answers. Every other done run took one invocation.
  - The summary counts each frontier row by its `-r2` re-run (33 requests
    over 3 invocations, 0 answers, 0.0 charged) and gives its first run 0.0
    charged. The first runs' 99 requests are recounted from the committed
    evidence below.
- **The three repaired passes**, from each committed `repair/summary.json`:
  repair@1 with the bootstrap's 2.5 and 97.5 percentiles (1,000 resamples
  over 12 cases, seed 17), then the repaired items. These are dev numbers.

  | Pass | Triggered | Resample | Bare | Counterexample |
  | --- | --- | --- | --- | --- |
  | [`dev-qwen3-32b-2026-09-26`](results/dev-qwen3-32b-2026-09-26/repair/summary.md) | 10 items in 6 cases | 0.000 [0.000, 0.000], 0/10 | 0.200 [0.000, 0.417], 2/10 | 0.400 [0.143, 0.750], 4/10 |
  | [`dev-qwen3.5-9b-2026-09-26`](results/dev-qwen3.5-9b-2026-09-26/repair/summary.md) | 7 items in 6 cases | 0.000 [0.000, 0.000], 0/7 | 0.143 [0.000, 0.500], 1/7 | 0.429 [0.000, 0.818], 3/7 |
  | [`dev-qwen3.5-122b-a10b-2026-09-26`](results/dev-qwen3.5-122b-a10b-2026-09-26/repair/summary.md) | 8 items in 7 cases | 0.125 [0.000, 0.400], 1/8 | 0.250 [0.000, 0.600], 2/8 | 0.625 [0.250, 1.000], 5/8 |

  Every arm comparison is inconclusive. The most discordant cases in any
  pair is 6 (120B, counterexample against resample), and a conclusive
  comparison needs 10. No pass has an arm not run.
- **The frontier outage and the move.** The six DeepInfra runs,
  `dev-deepseek-v4-pro-0813-{res,bare,cx}-2026-09-26` and their `-r2`
  re-runs, made 33 attempts each, 198 in all. Every attempt was HTTP 429,
  none was answered, the attempt logs charge 0 micro-USD, and each
  manifest's bound is 0.0. Their evidence is committed (68556a4), and they
  are never published.
  - OD5, by the owner, in
    [`ruling-2026-10-04.json`](decisions/evidence/repair-arms/ruling-2026-10-04.json):
    the frontier slot's repair arms still to be sent move from DeepInfra to
    NextBit, with `deepseek-v4-pro-0813_nextbit_enabled-false` (SHA-256
    `2942954e0c6896c29fe075f20cb9d0ce4a885d9ac72af8396022723b67de58ce`), at
    the slot's caps, 0.20 USD on dev and 0.50 on test. The counted first
    turns stay the answers DeepInfra served.
  - OD6, a maintainer default: the dev frontier round is re-run on NextBit
    before the test round, under the new ids
    `dev-deepseek-v4-pro-0813-{res,bare,cx}-nb-2026-09-26`. OD7 (one outage
    re-run on NextBit, `-nb-r2` on dev) and OD8 (the test arms keep their
    registered ids) are maintainer defaults too. The owner confirmed all
    three on 2026-10-05.
- **The runner change** (c57142a and 1d07612; "Frontier arms moved to
  NextBit" above has the details). `scripts/repair_arms.py` sends the
  frontier rows with the NextBit config, under the `-nb` ids on dev and the
  registered ids on test. It builds a moved prompt set under the arm's
  registered first id and installs it under the moved id.
  `dfilterforge repair --check` accepts a moved run only for a registered
  move, sent with the move's provider order and prices.
- **CI's python job, mirrored at 918bed9**, from 13:26:27Z to 14:14:24Z. It
  ran in `dfilterforge-test:0.1.0`
  (`sha256:841791ecaaa12b00357895a526c0b628e4bd9e099a03adcdda22d4e0b4ccd90d`)
  with the worktree's `src`, `tests`, `scripts`, `pcap_lab`,
  `pyproject.toml` and `README.md` mounted read-only, no network, and the
  compose test service's limits. The package resolved to `/workspace/src`.
  - pyink (96 files unchanged), isort, pylint (10.00/10), pyright (0
    errors) and lint-imports (5 contracts kept, 0 broken) pass.
  - pytest: 1,799 passed and 25 skipped, coverage 96.85 percent.
  - The benchmark gate (36 of 36 semantics), the adequacy gate (344 mutants
    executed, 4 survived, 0 unwaived; dev 72, 0 and 0), prepare and recall
    pass.
  - `score --check` over 34 committed outputs and `repair --check` over 8
    plans report no difference. The three dev rounds check at the summary
    stage; the frontier dev plan and the four test plans at the plan stage.
    No pool is committed.
  - CI's three docs-mounted steps first exited 4. The mirror script wrote
    their commands with CRLF line ends, so each last pytest argument ended
    in a carriage return ("file or directory not found:
    tests/test_held_out.py"). Re-run with the carriage returns stripped and
    the same container flags: registration 295, pair report 2, second turn
    2, none skipped. The fault was in the mirror script, not the branch.
- **CI's lab loops at 918bed9**, as `ci.yml` writes them, from 14:15:15Z to
  14:39:45Z. The lab image was built from the worktree under its own tag,
  `dfilterforge-lab:verify-918bed9`
  (`sha256:5adc9c7dcd8b40aed51be89c4597bde0ef4c8375f66727a76d9156d1d372fbdc`),
  in the compose project `dfilterforge-verify918`, with the full HEAD
  revision as `--code-revision`. The 34 score checks and 8 repair checks
  exited 0 and reported no difference, and no pool was committed to check.
- **The owner's commands, keyless, at 918bed9.** They ran from the worktree
  against copies of the main checkout's ignored `artifacts/repair` and
  `artifacts/repair-arms`, with the key variable unset.
  - `--split dev --dry-run` exited 0. Rows 1 to 9 are done (complete). Rows
    10 to 12 are owed as the three `-nb` runs, with
    `deepseek-v4-pro-0813_nextbit_enabled-false`, 11 items each and cap
    0.20. Worst request: 0.012053, 0.012645 and 0.013197 USD; full-arm
    worst: 0.1299, 0.1368 and 0.1413. Each follow-up line builds under the
    registered first id, "installed as" the `-nb` directory.
  - `--split dev` exited 3. It built the three `-nb` prompt sets, each
    keyless preflight stopped at `api_key_missing`, and it printed
    "ABORTED: the keyless preflight passed and nothing was sent". The total
    charged upper bound stayed 0.0459 USD (0.045822 exact).
  - Each built `prepared/C4.json` equals (`cmp`) the DeepInfra first run's,
    and each `prepare.json` differs from it only in `created_at` and
    `source_revision`; both name the registered first id as `prepare_id`.
    So the NextBit arms are to send the prompts the DeepInfra arms sent.
  - `--split test --dry-run` and `--split test` exited 2, refused: "the test
    round needs its seed and admission commits first", naming the 12 test
    arm run directories. No test prompt set was built.
  - Run again after the sets were built, the dry run exited 0 and printed
    "equal to what follow-up builds now" for each `-nb` set, in place of
    "would build" and the follow-up lines. The keyless run printed the same
    output as before and exited 3. So a dry run after an aborted run shows
    the built sets, not the follow-up commands.
- **The main checkout** is on `main` at bff373c with a clean tree and 15
  run directories under `artifacts/repair`. Its `artifacts/repair-arms`
  files keep the modification time of the owner's batch.
- **The branch at 918bed9** is 16 commits and 291 files ahead of bff373c.
  None of the 12 prepare-hashed files changed, and the only code files
  changed are `scripts/repair_arms.py`, `src/dfilterforge/repair_round.py`,
  `tests/test_repair.py` and `tests/test_repair_arms.py`.
- **This log.** With this section in place, CI's three docs-mounted steps
  passed in `dfilterforge-test:dev-repair-round`
  (`sha256:a7ca6d35053540567dcb97975bd0ce76053eaefd34aea42c438871caee3058e0`,
  built at 2915a74, whose code 918bed9 keeps), compose project
  `dfilterforge-devrepair`: registration 295, pair report 2, second turn 2,
  none skipped.
- **Not run.** No paid request was sent, so NextBit has served no repair
  arm. CI's web and container jobs did not run, and nothing was pushed.
- **Next**, as Planned next 1 lists it, which this section leaves
  unchanged: `dev-repair-round` merges; the owner re-runs the frontier dev
  arms on NextBit with the unchanged dev command, which sends only rows 10
  to 12 (OD6); the maintainer publishes and scores each `done` `-nb` run,
  writes and checks the frontier round summary, then the dev pool; then the
  test seed and admission PR, with the frontier arms seeded under their
  registered ids and sent on NextBit (OD5, OD8); then the owner's test
  round.

## Owner confirmation and review fixes: 2026-10-05, branch dev-repair-round

On 2026-10-05 the owner confirmed the maintainer defaults OD6, OD7 and OD8.
Four commits on `dev-repair-round` record that and fix what the review of
918bed9 found: 39166f2, dabaf6c, 3c3ad82 and 53a55e9. No model request was
sent, no command set the key variable, nothing was pushed, and none of the
12 prepare-hashed files changed against bff373c.

- **The confirmation (39166f2).** OD5 stays the owner's ruling of
  2026-10-04. OD6 (the dev frontier arms re-run on NextBit under the `-nb`
  ids, the six DeepInfra runs reported not run and kept as evidence only),
  OD7 (one outage re-run on NextBit, `-nb-r2` on dev and `-r2` on test, and
  no third provider) and OD8 (the test frontier arms keep their registered
  ids and change only their config) are maintainer defaults the owner
  confirmed on 2026-10-05.
  - The protocol's amendment, the repair note's Owner decisions and its
    amendment labels, the bake-off note, the registry's amendment in
    `test-runs.md` and `test-runs.json`, the batch's docstring and the
    progress lines that called the OD6 re-run "ruled" now say so. Each
    repair-note label names the decisions its passage rests on; none whose
    passage states OD6, OD7 or OD8 content is labelled OD5 alone.
  - The ruling is now schema `repair-arms-ruling/1.1`. OD6 to OD8 have `by`
    `default_confirmed`, a `confirmation` record names the owner, 2026-10-05
    and OD6 to OD8, and each move's `decided_by` names every decision it
    rests on with who settled it and when.
  - The ruling test pins the attribution in each of the six files it
    reads. Served each file's previous text in turn, and the ruling's also
    with only its schema raised to 1.1, it failed in 7 of 7 cases, each on
    that file's assertion; with the committed texts it passed.
  - On OD6 to OD8, 39166f2 updated two sections above dated 2026-10-04:
    the "Next" bullet of "Dev repair rounds published" and the OD6 bullet
    of "Dev repair round verified at 918bed9" now say the owner confirmed
    them on 2026-10-05. The other sections dated 2026-10-04 keep their OD6
    to OD8 text as written: the OD6 bullet of "Frontier arms moved to
    NextBit" and the adb2f8d bullet of "Frontier move review fixes" still
    say the owner's paid dev command confirms OD6. Only OD6 was ever tied
    to that command. OD7 and OD8 were defaults awaiting the owner's
    confirmation, as every default is until the owner confirms it. The
    owner confirmed all three on 2026-10-05, before any paid dev command.
    (Corrected on 2026-10-05: this bullet first said that every section
    dated 2026-10-04 kept its text and that OD6 to OD8 all waited for the
    paid dev command; both were false.)
- **The progress facts (dabaf6c).** The Current slice no longer credits the
  frontier 429s to DeepInfra: recounted from the six runs' committed
  attempts, all 198 have HTTP status 429 and provider null, so they show
  429 on the DeepInfra-pinned route only. This disproves the 2026-10-04
  bullet "Not changed: the progress lines" under "What the 429 records
  show", which now carries a dated correction. The Blocked line that said
  `repair-arms` was not pushed now says PR #18 merged it as bff373c, and that
  no CI result for that PR is recorded here.
- **The moved runs' follow-up line (3c3ad82).** For each moved dev run the
  dry run printed `--output-dir artifacts/repair/<registered first id>`.
  - Before: in the worktree, beside the copies of the main checkout's
    DeepInfra run directories and with the `-nb` sets set aside, each of the
    three printed commands, run as printed, exited 2 with `output_exists`.
  - After: the line reads `--output-dir
    artifacts/repair-arms/build/<-nb run id>/<registered first id>`, still
    ending ", installed as artifacts/repair/<-nb run id>". Run as printed,
    each exited 0. (Corrected on 2026-10-05: "as printed" was false here and
    in the Before bullet. Each line was run without its ", installed as"
    tail and with a `python` that holds the project. As printed, `python`
    on this machine is the system Python, which has no `dfilterforge`
    (ModuleNotFoundError, exit 1), and the tail makes the revision end in a
    comma (exit 2). The line now starts `uv run --frozen python` and puts
    "installed as" on a comment line of its own.) `differences` found
    nothing between each built set and the `-nb` set the keyless batch
    installed at 918bed9. Their
    `prepared/C4.json` SHA-256 prefixes, `43b396f05b3e`, `b4fb01c575b7` and
    `2fb03e788c2d`, equal the replaced DeepInfra runs' sets'. A second dry
    run after those builds printed the same output.
  - `test_a_moved_runs_printed_follow_up_runs_where_the_replaced_run_is_kept`
    runs each printed line through the scripted follow-up step, which
    refuses an existing output. Before the change it failed on
    `(False, 'output_exists') == (True, None)`; after, it passed. The
    existing moved-pass test now pins the new line.
- **The dry run's expected lines (53a55e9).** The repair note's Commands and
  Planned next 1.1 say that step 1, the dry run, prints "would build" and an
  "installed as" follow-up line for each `-nb` set only until step 2 has
  built the sets, and "equal to what follow-up builds now" after that. Read
  from the worktree's dry run, both exiting 0: with the `-nb` sets absent,
  3 "would build" and 3 follow-up lines; with them in place, 3 "equal to
  what follow-up builds now" and no "installed as" line.
- **The ignored copies.** The verify of 918bed9 left copies in the
  worktree's `artifacts/repair` (3.6 MB) and `artifacts/repair-arms` (396
  KB), which git ignores. Both are deleted, with the `build/` directory the
  hand runs above made. The main checkout's `artifacts/` was not touched;
  its `artifacts/repair` still holds 15 run directories.
- **Checks at 53a55e9.**
  - In `dfilterforge-test:0.1.0`
    (`sha256:841791ecaaa12b00357895a526c0b628e4bd9e099a03adcdda22d4e0b4ccd90d`),
    with `src`, `tests`, `scripts`, `docs`, `pyproject.toml`, `README.md`
    and `pcap_lab` mounted read-only and no network:
    `tests/test_repair_arms.py`, `tests/test_repair.py`,
    `tests/test_hosted_test_runs.py` and `tests/test_test_passes.py` gave
    297 passed, none skipped.
  - On the host, with `uv run --frozen --offline --extra dev`: pyink (96
    files unchanged), isort, pylint on `scripts/repair_arms.py` (10.00/10,
    exit 0) and `pyright --pythonplatform Linux` (0 errors) pass. Host
    pytest of the same four files gave 292 passed, 2 skipped and 3 failed:
    three `tests/test_repair.py` tests that make symlinks, which Windows
    refuses here (WinError 1314); they pass in the container. Before the
    ignored copies were deleted, the host run also failed
    `test_the_real_follow_up_builds_every_committed_dev_arm`, which reads
    the worktree's `artifacts/repair`.
  - Not run: the full suite, the gates, lint-imports and CI's lab loops.
    The only code files changed are `scripts/repair_arms.py` and
    `tests/test_repair_arms.py`.
- **Not run.** No paid request was sent, so NextBit has served no repair
  arm. Planned next keeps its order; only its attribution and the dry run's
  expected lines changed.

## Review fixes at 03eca2e: 2026-10-05, branch dev-repair-round

A review of 03eca2e confirmed four minor findings, and four commits fix
them: 45b39ba, 716362b, 4d48a68 and b6ab13b. The last two change the batch
and add tests. OD5 stays the owner's ruling of 2026-10-04, and OD6 to OD8
stay maintainer defaults confirmed by the owner on 2026-10-05. No model
request was sent, no command set the key variable, nothing was pushed, and
none of the 12 prepare-hashed files changed against bff373c (`git diff`
printed nothing).

- **Which 2026-10-04 sections the confirmation changed (45b39ba).** The
  2026-10-05 section said every section dated 2026-10-04 kept what was true
  when written, and that OD6 to OD8 all waited for the owner's paid dev
  command. 39166f2 had rewritten the OD6 lines in two of those sections,
  and at f90674e only OD6 was tied to the paid dev command: in the ruling's
  OD6 text, in lines 101 and 723 of the repair note, and in four progress
  lines. The bullet now names the two sections 39166f2 updated and the two
  it left, says that only OD6 was tied to that command, and carries a dated
  correction.
- **The 429 bullet (716362b).** The 2026-10-04 bullet "Not changed: the
  progress lines" said they already read only "HTTP 429 from the
  DeepInfra-pinned route". At 918bed9, which added that bullet, the Current
  slice read "The frontier arms got only HTTP 429 from DeepInfra"
  (`git show 918bed9:docs/progress.md`). The bullet now carries a dated
  correction, and the dabaf6c bullet says it disproves it.
- **A follow-up refusal gives its reason (4d48a68).** For a refusal the
  protocol does not report, the batch used to tell the owner to run the
  printed follow-up line "to read why". That line builds in a fixed place,
  and follow-up refuses an existing output before any other check.
  - Before: the new test's two cases failed on the old hint. One named
    `artifacts/repair-arms/build/<-nb run id>/<registered first id>`, where
    the case had built the set by hand. The other named
    `artifacts/repair/dev-qwen3.5-122b-a10b-cx-2026-09-26`, where the
    keyless run had installed the set.
  - After: the in-process follow-up returns its message with its code, and
    the refusal quotes it.
    `test_a_follow_up_refusal_gives_its_reason_with_built_sets_in_place`
    passed for both cases. The test of the real follow-up step now pins
    its message, "A required file is missing".
  - A real dry run was made in the worktree, with copies of the main
    checkout's 15 run directories and the three moved sets built by hand
    under `artifacts/repair-arms/build/`. For that one dry run the frontier
    pass's `repair/plan.json` was rewritten with indent 2, then copied
    back; `git status` showed it unchanged. The dry run exited 2 with:
    "refused: dev-deepseek-v4-pro-0813-res-nb-2026-09-26: follow-up refused
    (plan_invalid) to build its prompt set from
    docs/results/dev-deepseek-v4-pro-0813-2026-09-26 and its plan: The
    repair plan is not in its canonical encoding".
- **The printed follow-up command runs as printed (b6ab13b).**
  - Before, at 4d48a68: the dev dry run (exit 0) printed `python
    scripts/model_run.py follow-up ... --source-revision 4d48a68, installed
    as artifacts/repair/<-nb run id>`. In Git Bash, `python` resolves to the
    system Python 3.12, which has no `dfilterforge`. Run literally in Git
    Bash and in Windows PowerShell 5.1, the first line exited 1 with
    `ModuleNotFoundError: No module named 'dfilterforge'`.
  - After: each moved set gets two lines,
    `uv run --frozen python scripts/model_run.py follow-up ...
    --source-revision <rev>` and `# installed as artifacts/repair/<-nb run
    id>`. Each pair was pasted whole and run as printed from the worktree
    root:
    - in Git Bash, each exited 0;
    - after those builds were moved aside, in Windows PowerShell
      5.1.26100.9444, each exited 0 again.
  - `differences` found nothing between each set built in either shell and
    the replaced DeepInfra run's set. The `prepared/C4.json` SHA-256
    prefixes were `43b396f05b3e`, `b4fb01c575b7` and `2fb03e788c2d`.
  - A dry run at b6ab13b printed the same output apart from the revision.
  - The tests:
    - The printed-line test now takes every word after the script through
      `scripts/model_run.py`'s own parser.
    - The moved-pass test pins the comment line.
    - A docs-mounted test ties `HOST_PYTHON` to the repair note's
      follow-up command.

    Against the code before the change all three failed; after, they
    passed. The repair note's Commands, Planned next 1.1 and the 3c3ad82
    bullet above, with a dated correction, describe the new lines.
- **The ignored copies.** The copies these checks put in the worktree's
  `artifacts/repair` and `artifacts/repair-arms`, built sets included, are
  deleted; only the tracked `artifacts/.gitkeep` remains. The main
  checkout's `artifacts/` was only read, and its `artifacts/repair` still
  holds 15 run directories.
- **Checks at b6ab13b.**
  - In `dfilterforge-test:0.1.0`
    (`sha256:841791ecaaa12b00357895a526c0b628e4bd9e099a03adcdda22d4e0b4ccd90d`),
    with `src`, `tests`, `scripts`, `docs`, `pyproject.toml`, `README.md`
    and `pcap_lab` mounted read-only and no network, the four test files
    `tests/test_repair_arms.py`, `tests/test_repair.py`,
    `tests/test_hosted_test_runs.py` and `tests/test_test_passes.py` gave
    300 passed, none skipped.
  - On the host, with `uv run --frozen --offline --extra dev`, these passed:
    - pyink, with 96 files unchanged;
    - isort;
    - pylint on `scripts/repair_arms.py`, at 10.00/10;
    - `pyright --pythonplatform Linux`, with 0 errors.
  - Host pytest of the same four files gave 295 passed, 2 skipped and 3
    failed. The failures are the three symlink tests above (WinError 1314).
  - Not run: the full suite, the gates, lint-imports and CI's lab loops.
    The only code files changed are `scripts/repair_arms.py` and
    `tests/test_repair_arms.py`.

## Branch verified at fb4110a: 2026-10-05, branch dev-repair-round

The branch was checked at fb4110a with no tracked edit. The times below are
UTC, 2026-10-04 17:11:51Z to 17:16:36Z (03:41 to 03:46 on 2026-10-05,
ACDT). OD5 stays the owner's ruling of 2026-10-04; OD6 to OD8 are
maintainer defaults confirmed by the owner on 2026-10-05. No model request
was sent, no command set the key variable, and nothing was pushed.

- **The branch.** fb4110a is 27 commits ahead of bff373c, its merge base
  with `origin/main`. `origin/main` is now df90b9b (PR #19, `web-data`), 53
  commits past that base. `git merge-tree` merges fb4110a and df90b9b with
  no conflict; `docs/progress.md` is the only file both sides changed.
  - None of the 12 prepare-hashed files is in `git diff --name-only`
    against `origin/main`, two-dot (336 files) or three-dot (291 files).
  - The log of `origin/main..HEAD` has no Co-Authored-By line and no
    non-ASCII character. The tree is clean, and the branch has no upstream.
- **CI's python job checks,** from 17:11:51Z to 17:16:36Z, in
  `dfilterforge-test:0.1.0`
  (`sha256:841791ecaaa12b00357895a526c0b628e4bd9e099a03adcdda22d4e0b4ccd90d`).
  Its `/workspace/uv.lock` equals the worktree's (SHA-256 prefix
  `2fac5eded2dc`). `src`, `tests`, `scripts`, `pyproject.toml`, `README.md`
  and `pcap_lab` were mounted read-only, with no network, a 128 MB `/tmp`
  and the compose test service's limits. The package resolved to
  `/workspace/src`.
  - pyink (96 files unchanged), isort, pylint on CI's list of `src` and
    nine scripts (10.00/10, exit 0), pyright (0 errors) and `lint-imports
    --no-cache` (5 contracts kept, 0 broken) pass.
  - pytest with coverage off over `tests/test_repair_arms.py`,
    `tests/test_repair.py`, `tests/test_hosted_test_runs.py`,
    `tests/test_test_passes.py` and `tests/test_model_run.py`: 429 passed
    and 17 skipped, each skip for the missing `docs/` tree.
  - CI's three docs-mounted steps, as `ci.yml` writes them, with `docs/`
    mounted read-only too: registration 299 passed, pair report 2, second
    turn 2, none skipped.
- **CI's repair loop,** from 17:12:30Z to 17:13:21Z. The lab image was
  built from the worktree as `dfilterforge-lab:verify-fb4110a`
  (`sha256:cffa2162f57b25caffd6294f835c9b4ad632edef469e81aa8e709e3fb192d43b`)
  in the compose project `dfilterforge-verifyfb4110a`, with the full HEAD
  revision as `--code-revision`.
  - All 8 `repair --check` runs exited 0 with no difference. The three
    published dev rounds checked at the summary stage; the frontier dev
    plan and the four test plans at the plan stage.
  - No repair pool is committed, and `git status` stayed clean.
- **The owner's commands, keyless,** from the worktree root in Git Bash,
  against fresh copies of the main checkout's `artifacts/repair` (15 run
  directories) and `artifacts/repair-arms`.
  - `--split dev --dry-run` exited 0. Rows 1 to 9 are `done (complete)`.
    Rows 10 to 12 are owed as `dev-deepseek-v4-pro-0813-{res,bare,cx}-nb-2026-09-26`
    with `deepseek-v4-pro-0813_nextbit_enabled-false`, 11 items each and
    cap 0.20. Worst request: 0.012053, 0.012645 and 0.013197 USD; full-arm
    worst: 0.1299, 0.1368 and 0.1413. Each of the three sets reads `would
    build`, with a `uv run --frozen python scripts/model_run.py follow-up`
    line and a `# installed as` comment.
  - `--split dev` exited 3. It built the three `-nb` sets, and each keyless
    preflight stopped at `api_key_missing`: 3 in the output, 3 new entries
    in the step log. It printed "ABORTED: the keyless preflight passed and
    nothing was sent". The total charged upper bound stayed 0.0459 USD
    (0.045822 exact).
  - The six printed lines, run as printed in Git Bash, each exited 0 and
    built under `artifacts/repair-arms/build/<-nb run id>/<registered first
    id>`. `differences` found nothing between each hand-built set, the
    `-nb` set the keyless run installed and the replaced DeepInfra run's
    set. The `prepared/C4.json` SHA-256 prefixes are `43b396f05b3e`,
    `b4fb01c575b7` and `2fb03e788c2d`.
  - A repeated dev dry run exited 0, with 3 "equal to what follow-up builds
    now" lines and no "would build" or "installed as" line.
  - `--split test --dry-run` and `--split test` each exited 2, refused:
    "the test round needs its seed and admission commits first", naming the
    12 test arm run directories. No prompt set was added.
  - The copies (3.6 MB and 396 KB) are deleted; only `artifacts/.gitkeep`
    remains. The main checkout is on `main` at bff373c with a clean tree.
    Its `artifacts/repair` and `artifacts/repair-arms` listings (names,
    sizes and modification times) did not change.
- **Not run.** The full suite with coverage, the benchmark and adequacy
  gates, prepare, recall, the `score --check` loop, and CI's web and
  container jobs. No paid request was sent, so NextBit has served no repair
  arm. Planned next is unchanged.

## Dev round, dev pool and test seeds: 2026-10-05, branch dev-pool-test-seeds

The owner re-ran the dev repair batch from the main checkout at 60d2421 on
2026-10-05. `dev-pool-test-seeds` branches from `origin/main` at 60d2421 (PR
#20 merged `dev-repair-round` there). On it, the frontier dev round is
published, scored and summarized, the dev pool is written, the defect the
pool showed is corrected (OD9), and the 12 test arm prompt sets are seeded
and admitted. The [repair note's](decisions/repair-round.md) After now holds
the dev numbers. No model request was sent from this branch, no command set
the key variable, and nothing was pushed.

- **The frontier runs,** `dev-deepseek-v4-pro-0813-{res,bare,cx}-nb-2026-09-26`,
  as committed:
  - Each is complete, with 11 of 11 items in one invocation, 11 attempts and
    no retry. Every attempt was HTTP 200, served by NextBit, with finish
    reason stop. Each was prepared at source revision 60d2421, with provider
    order `nextbit`.
  - They were sent from 2026-10-05T00:53:29Z to 00:55:55Z.
  - They charged at most 24,761, 26,496 and 27,363 micro-USD, the sums of
    their attempt logs, which equal each manifest's
    `charged_usd_upper_bound`.
  - With the nine runs of 2026-10-04, the 12 dev arm runs charged at most
    0.124442 USD. The runner summary in the main checkout's ignored
    `artifacts/repair-arms/summary-dev-2026-10-05.txt` gives the same exact
    total, and every one of its 12 rows reads `done (complete)`. That
    summary is not committed.
- **repair@1,** from the committed `repair/summary.json` and
  `repair-pool/dev.json`, with the bootstrap's 2.5 and 97.5 percentiles and
  the repaired items. These are dev numbers. The note's After has every
  model's row with the strata, transitions, `answer_unchanged`,
  `card_value_reuse` and spend.

  | Round | Triggered | Resample | Bare | Counterexample |
  | --- | --- | --- | --- | --- |
  | [`dev-deepseek-v4-pro-0813-2026-09-26`](results/dev-deepseek-v4-pro-0813-2026-09-26/repair/summary.md) | 11 items in 7 cases | 0.182 [0.000, 0.444], 2/11 | 0.091 [0.000, 0.333], 1/11 | 0.636 [0.333, 1.000], 7/11 |
  | [Pool of the four dev rounds](results/repair-pool/dev.md) | 36 items | 0.083 [0.000, 0.259], 3/36 | 0.167 [0.050, 0.370], 6/36 | 0.528 [0.257, 0.788], 19/36 |

  - The frontier comparisons have 5, 4 and 1 discordant cases
    (counterexample - bare, counterexample - resample, bare - resample).
  - The pooled ones, by case (OD9), have 8 (6 against 2), 7 (6 against 1)
    and 3 (3 against 0).
  - All are inconclusive. The four rounds' triggered items fall in 9
    distinct cases.
- **Commits,** in order:
  - d32efb3: the frontier round, its three arm runs with their `scored/`
    trees and the pass's `repair/summary.json` and `summary.md`.
  - e93c39f: the dev pool, `docs/results/repair-pool/dev.json` and
    `dev.md`.
  - 890a358: the correction the dev pool showed. `repair-pool` counted the
    pooled discordance on model-case cells; it now counts cases (OD9), and
    the pool is derived again.
  - be9f611: OD9 registered in `docs/protocol.md` and the repair note,
    pinned by a test.
  - e8f0ce9, 4ff9e99, fd9237e and b7a3e4e: the anchor, 8B, 120B and
    frontier test passes' seeds, each pass's three arm prompt sets in one
    commit.
  - d95483a: the 12 seeds' `prepare.json` digests admitted in
    `src/dfilterforge/held_out_freeze.json`.
  - The commit that adds this section: the repair note's After, its "Not
    measured yet" narrowed to the test round, and this file.
- **The test seeds,** checked against the committed plans:
  - Each seed's item ids equal its plan's, in order.
  - Each arm holds 28, 15, 20 and 12 prompts (anchor, 8B, 120B, frontier).
  - The plans' cards are 25 frames and 3 error, 11 and 4, 14 and 6, and 4
    and 8.
  - Each `prepared/C4.json` matches its prepare's digest. Each prepare is
    split test at source revision be9f611, under its own registered run id.
  - `admitted_prepares` holds 13 digests: the frozen test prepare first,
    unchanged (`206599bb67e1`), then the 12 seeds' in batch order.
- **Checks at d95483a and of this section's edits,** made after the
  container runs at d95483a that the next section lists. They ran on the
  host, with the worktree's venv: Python 3.12.10, and the locked dev extras
  installed offline with `uv sync --frozen --extra dev`, because by then the
  Docker daemon no longer answered.
  - `repair --check` over the 8 plans found no difference: the four dev
    passes at the summary stage, the four test passes at the prompts stage.
  - `repair-pool --check --split dev` found no difference, with
    `pool_sha256` `dcba4a24342b`.
  - The pytest nodes of CI's registration step, with `docs/` present: 300
    passed, none skipped, both at d95483a and with the repair note and this
    file edited. These are the frozen-prompt guard,
    `test_hosted_test_runs.py`, `test_dev_bakeoff.py`,
    `test_test_passes.py`, `test_repair_arms.py` and `test_held_out.py`.
    With the edits, `scripts/repair_arms.py` still reads the note's caps
    table (seven rows) and its empty raised caps table.
  - In the 12 dev arm runs, each bare and counterexample prompt holds 4
    messages and each resample prompt 2. Each run's `scored/outcomes.jsonl`
    has one row per prompt.
  - None of the 12 prepare-hashed files is in `git diff --name-only
    origin/main..HEAD`. The branch log has no Co-Authored-By line and no
    non-ASCII character.
  - Not run in this session: `score --check` over the three `-nb` runs (as
    d32efb3's message records, it ran in the lab image when the round was
    committed), CI's other steps, the full suite and the gates.

## Dev round review and branch check at 611afb4: 2026-10-05, branch dev-pool-test-seeds

This adds what the section above leaves out: the frontier round's outcomes
per arm, the dev pool before and after the OD9 correction, the defect review
behind that correction, the branch review and its fix, the container checks
each step ran, and the check of the whole branch at 611afb4. Figures come
from the committed files at 611afb4, from `git show e93c39f:` for the pool
before the correction, and from the logs of these checks. No model request
was sent, no command set the key variable, and nothing was pushed.

- **The frontier round on NextBit,**
  [`dev-deepseek-v4-pro-0813-2026-09-26`](results/dev-deepseek-v4-pro-0813-2026-09-26/repair/summary.json)
  (plan `c2e75d74b17a`). 11 triggered items in 7 cases, 9 silent-wrong and 2
  invalid at base; 9 frames cards and 2 error cards. No arm is recorded as
  not run, and no base outcome changed since the plan.

  | Arm run | Strong exact | Silent wrong | Invalid | repair@1 | Silent-wrong part | Answer unchanged | Card value reuse | Charged USD |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
  | `dev-deepseek-v4-pro-0813-res-nb-2026-09-26` | 2 | 7 | 2 | 0.182 [0.000, 0.444], 2/11 | 0.222 [0.000, 0.500] | 0 | - | 0.024761 |
  | `dev-deepseek-v4-pro-0813-bare-nb-2026-09-26` | 1 | 9 | 1 | 0.091 [0.000, 0.333], 1/11 | 0.111 [0.000, 0.400] | 2 | - | 0.026496 |
  | `dev-deepseek-v4-pro-0813-cx-nb-2026-09-26` | 7 | 3 | 1 | 0.636 [0.333, 1.000], 7/11 | 0.778 [0.500, 1.000] | 1 | 3 | 0.027363 |

  - No arm answer was a shortcut, malformed, abstained, false ready or a
    provider failure. The invalid part is 0.000 [0.000, 0.000] in each arm,
    on the 894 resamples that drew an invalid item.
  - Each run had one invocation at source revision 60d2421 with `max_usd`
    0.2 and 11 requests sent. All 11 attempts were first attempts, HTTP 200,
    served by NextBit, finish reason stop. No attempt carried reasoning (0
    reasoning tokens), which is what the `enabled-false` config asks; the
    owner's batch summary reads "reasoning honoured" for each row and rounds
    the charges up to 0.0248, 0.0265 and 0.0274 USD. The provider reported
    0.02475581, 0.0264887 and 0.02735779 USD.
  - Per-model comparisons, all inconclusive: counterexample - bare 0.545
    [0.250, 0.857], 5 against 0; counterexample - resample 0.455 [0.125,
    0.846], 4 against 0; bare - resample -0.091 [-0.273, 0.000], 0 against 1.
- **The dev pool,** [`repair-pool/dev.json`](results/repair-pool/dev.json)
  (schema `repair-pool/1.0`): 1,000 case-level resamples, seed 17, 12 cases,
  10 discordant cases needed for a reading.
  - Bases, as triggered items in cases and summary SHA-256 prefix: frontier
    11 in 7 (`aca5075b2293`), anchor 10 in 6 (`f69f0ded0f7f`), 120B 8 in 7
    (`d4bb1e5c9af4`), 8B 7 in 6 (`e95af1631f56`).
  - Arms over 36 triggered items: resample 3/36, 0.083 [0.000, 0.259]; bare
    6/36, 0.167 [0.050, 0.370]; counterexample 19/36, 0.528 [0.257, 0.788].
  - The comparisons before the correction (e93c39f, model-case cells) and
    after it (890a358 on, cases, OD9):

    | Pooled comparison | Difference | e93c39f: better, discordant, verdict | 890a358 on: better, discordant, verdict |
    | --- | ---: | --- | --- |
    | counterexample - bare | 0.361 [0.083, 0.632] | 13 against 2, 15 cells, conclusive | 6 against 2, 8 cases, inconclusive |
    | counterexample - resample | 0.444 [0.150, 0.741] | 15 against 1, 16 cells, conclusive | 6 against 1, 7 cases, inconclusive |
    | bare - resample | 0.083 [0.000, 0.178] | 4 against 1, 5 cells, inconclusive | 3 against 0, 3 cases, inconclusive |

  - Between the two `dev.json` files only the comparisons' `first_better`,
    `second_better`, `discordant`, `inconclusive` and `unit` fields differ;
    the bases, arms, differences and intervals are the same. The file's
    SHA-256 (the `pool_sha256` that `repair-pool --check` reports) is
    `706097e03dd8` at e93c39f and `dcba4a24342b` from 890a358 on.
- **Defect review of the dev round and pool,** before any test repair
  prompt (the note's Order, item 5.4). 1 candidate, 1 confirmed: the pooled
  discordance unit. `repair-pool` counted model-case cells, one per model
  and case; the protocol registers discordant cases. The cell count was
  written in 1c7df3c (2026-10-02) and merged with `repair-arms` in bff373c.
  - The owner ruled OD9 on 2026-10-05: count cases. 890a358 names the
    defect and OD9, changes `src/dfilterforge/repair_summary.py` (not
    prepare-hashed; `RepairComparisonV1.unit` now admits only `cases`) and
    derives `dev.json` and `dev.md` again. be9f611 registers OD9 in
    `docs/protocol.md` and the repair note, pinned by
    `test_the_pooled_unit_ruling_is_the_unit_the_pool_counts`.
  - Before the fix, the new and updated pool tests failed on the cell count
    (2 failed). A recount from the four committed summaries gave the same
    case counts as the corrected tool.
  - On dev only 9 of the 12 ready cases trigger in any model, so no pooled
    dev comparison can reach 10 discordant cases.
- **Main observations of the dev round,** none of them a finding, since
  every comparison is inconclusive (figures in the note's After):
  - The counterexample arm repaired the most items in each model: 4/10,
    3/7, 5/8 and 7/11 (anchor, 8B, 120B, frontier). Bare repaired more than
    resample in three models; the frontier's resample repaired 2 to bare's 1.
  - The frontier's resample, answered by NextBit while the counted first
    turn it repeats was answered by DeepInfra, repeated none of its 11
    answers.
    The other three resamples repeated 7 of 10, 2 of 7 and 5 of 8.
  - Of the 108 answers, 106 ended with finish reason stop. The other 2, the
    8B's bare `mei-0015` and counterexample `mei-0022`, stopped at the
    length limit and scored malformed. 3 more second-turn answers scored
    malformed with finish reason stop: the anchor's counterexample
    `mei-0017` and `mei-0018`, and the 120B's bare `mei-0013`.
  - No arm answer was a shortcut, a provider failure or false ready, no arm
    was recorded as not run, and no base outcome changed since its plan.
  - 11 of the counterexample arm's 19 strong-exact answers hold a value
    their card showed for that field (`card_value_reuse`, a diagnostic).
- **Branch review and its fix.** The review of the branch at d95483a
  confirmed one finding, F1: the repair note still read "After: not
  measured" and listed repair@1 and the arm comparisons as unmeasured,
  though the dev round and pool were committed. 611afb4 fills in the note's
  After for dev, narrows "Not measured yet" to the test round, and adds the
  section above. It changes only `docs/decisions/repair-round.md` and this
  file.
- **Seeds and admission.** e8f0ce9, 4ff9e99, fd9237e and b7a3e4e each hold
  6 files, one pass's three `prepare.json` and `prepared/C4.json`; d95483a
  changes only `src/dfilterforge/held_out_freeze.json`.
  - Each arm holds 28, 15, 20 and 12 prompts (anchor, 8B, 120B, frontier):
    2 messages in each resample prompt, 4 in each bare and counterexample
    prompt. Each prepare is split test at source revision be9f611.
  - `admitted_prepares` holds 13 of the record's 32: the frozen test prepare
    `206599bb67e1` first, then in batch order the anchor's `26c3b62d0727`,
    `f9ac09ef21a6` and `5cb96586fa04`, the 8B's `75428e115f7d`,
    `ad894c77906a` and `11c932b73807`, the 120B's `5c13a5d02dce`,
    `ea815b5f6413` and `af26c407dc2b`, and the frontier's `a64d811d31aa`,
    `c6a4ae6126aa` and `b21d0cddebd8` (resample, bare, counterexample).
  - Against copies of the main checkout's ignored artifacts, the test dry
    run exited 2 at be9f611 ("no committed seed"), 2 at b7a3e4e (the first
    seed's prepare "is not admitted") and 0 at d95483a.
- **Container checks of each step,** in lab and test images built under the
  step's own tags and compose project, never the `0.1.0` tags:
  - The frontier round and pool (images built from 60d2421): `score --check`
    of the three `-nb` runs, 11 items each, no difference; `repair --check`
    of the frontier pass at the summary stage, summary `aca5075b2293`;
    `repair-pool --check`, pool `706097e03dd8`. CI's steps at e93c39f: the
    re-score loop checked 37 with no difference, the repair loop 8 plans,
    registration 299 passed, pair 2, second turn 2, web exporter tests 180,
    and two web exports were identical (27,411,082 bytes, 1,935 files).
  - The OD9 correction at be9f611: the full suite 1,979 passed and 31
    skipped, coverage 97.09%; `tests/test_repair.py` and
    `tests/test_repair_arms.py` 227 passed; pyink (100 files unchanged),
    isort, pylint 10.00/10, pyright 0 errors, lint-imports 5 kept and 0
    broken; registration 300 passed, second turn 2, web exporter tests 180;
    the repair loop 8 plans and `repair-pool --check` (`dcba4a24342b`), no
    difference. That loop checked the four test passes at the plan stage,
    the last check that re-derives their cards: once a pass's seeds are
    committed, `repair --check` reads its committed plan at the prompts
    stage.
  - The seeds at d95483a: the full suite 1,979 passed and 31 skipped,
    coverage 97.09%; registration 300, pair 2, second turn 2; the repair
    loop 8 plans with 0 failures (dev at the summary stage, test at the
    prompts stage); `repair-pool --check` no difference; web exporter tests
    180; two identical web exports, whose `methodology.json` lists 13
    admitted prepares. Lint and the re-score loop were not run there: those
    commits change no source or scored file.
- **The branch at 611afb4,** checked from about 04:57Z to 05:40Z.
  - Docker Desktop's engine did not answer. Its host monitor log had no
    line after 04:07:19Z and its backend log none after 04:20:51Z.
    `docker version` timed out 3 times at 05:12:32Z; wait loops from 04:57Z
    to 05:12Z (40 tries) and from 05:14:31Z to 05:39:46Z (75 tries) got no
    answer. It still timed out at 05:46:48Z. Docker
    Desktop was not restarted: other sessions had commands waiting on it,
    and a restart is the owner's call.
  - Not run at 611afb4, for that reason: CI's python job in the test image
    (the `uv.lock` comparison, the full suite with coverage, the benchmark
    gate, adequacy, prepare and recall) and the `score --check` loop in the
    lab image.
  - On the host instead (Python 3.12.10, a venv synced with `uv sync
    --frozen --extra dev`): pyink (100 files unchanged), isort, lint-imports
    (5 kept, 0 broken) and pylint on the web data scripts pass. pylint on
    CI's main list (exit 2, 8 messages) and pyright (24 errors) fail on
    POSIX-only APIs Windows lacks and one Windows typeshed difference, all
    in `counterexample.py`, `live.py`, `runner.py`, `tests/test_live.py` and
    `tests/test_runner.py`, none of which the branch changes.
  - CI's docs-mounted steps on the host: registration 300 passed, pair 2,
    second turn 2; the web evidence check exit 0 (480 frames, 8 probes,
    `captures.json` `b3fe0d0bf728`); web exporter tests 173 passed, 5 failed
    and 2 skipped, the 5 failures differing from the expected text only by
    Windows `\` separators and the 2 skips needing symlink rights; two web
    exports identical (76 cases, 1,935 files, 1,854 receipts, 27,412,885
    bytes).
  - `repair --check` over the 8 plans, on the host: no difference. The dev
    passes checked at the summary stage with 11, 10, 8 and 7 items (frontier,
    anchor, 120B, 8B), the test passes at the prompts stage with 12, 28, 20
    and 15. `repair-pool --check --split dev`: no difference, pool
    `dcba4a24342b`.
  - The owner's test commands, keyless, in Git Bash at 611afb4 against fresh
    copies of the main checkout's `artifacts/repair` and
    `artifacts/repair-arms` (131 files). `--split test --dry-run` exited 0
    and wrote nothing: each of the 12 prompt sets reads "would copy the
    committed seed", and each row `owed (start (not_started))`. `--split
    test` exited 3 after 12 keyless preflights stopped at `api_key_missing`,
    with "ABORTED: the keyless preflight passed and nothing was sent". It
    added 13 step log lines (1 batch, 12 preflight), installed the 12 sets
    byte for byte equal to the seeds, created no `runs/` directory, and gave
    a total charged upper bound of 0.0000 USD. Its rows equal the dry run's:

    | Slot | Config | Items per arm | Worst request | Full-arm worst (resample, bare, counterexample) | Cap per arm |
    | --- | --- | ---: | ---: | --- | ---: |
    | anchor | `qwen3-32b_deepinfra_enabled-false` | 28 | 0.001033 to 0.001236 | 0.0279, 0.0305, 0.0318 | 0.05 |
    | 8B | `qwen3.5-9b_deepinfra_enabled-false` | 15 | 0.000853 to 0.001327 | 0.0125, 0.0148, 0.0155 | 0.05 |
    | 120B | `qwen3.5-122b-a10b_novita_enabled-false` | 20 | 0.008782 to 0.009620 | 0.1730, 0.1821, 0.1853 | 0.30 |
    | frontier | `deepseek-v4-pro-0813_nextbit_enabled-false` | 12 | 0.012246 to 0.013317 | 0.1442, 0.1520, 0.1546 | 0.50 |

    In all, 225 items, 2.70 USD of caps and 1.1242 USD of full-arm worst
    cases. The copies were deleted, and the main checkout's
    `artifacts/repair` and `artifacts/repair-arms` did not change.
  - HEAD 611afb4 has `origin/main` (60d2421) as an ancestor and no
    upstream: 10 commits and 145 files. None of the 12 prepare-hashed files
    changed; the commit messages have no Co-Authored-By line and no
    non-ASCII character. Both the worktree and the main checkout (on `main`)
    were clean.
- **Next.**
  1. The four gates of CI's python job (benchmark, adequacy, prepare and
     recall) and the `uv.lock` comparison have not run at any commit of this
     branch, and the `score --check` loop last ran at e93c39f. CI runs them
     on the pull request. The images `dfilterforge-{lab,test}:dev-pool-test-seeds`
     and `dfilterforge-{lab,test}:rv-docs-ci` are removed once the engine
     answers.
  2. The maintainer pushes `dev-pool-test-seeds`; on 2026-10-05 the owner
     asked for the push before item 1's checks, with the engine still down.
     The owner opens its pull request and pushes nothing.
  3. The owner merges it into `main`, then runs the test round from the
     main checkout with the Windows PowerShell 5.1 block "The test round,
     the same way" in the repair note's Commands: `--split test --dry-run`,
     then, with the key read in, `--split test`. The frontier rows send the
     NextBit config at the 0.50 cap under their registered ids.
  4. Then the maintainer's publish, score, `repair` and pool for test, as
     Planned next 1.5 and 1.6 say.

## Test repair round: 2026-10-06, branch test-repair-round

The owner sent the test round from the main checkout at 97531b6 on
2026-10-05, 10:29 to 10:58 UTC: 12 arm runs, 225 requests, all HTTP 200 on
the first attempt, at most 0.2139 USD against 2.70 USD of caps. NextBit
answered the frontier arms (OD5). The branch publishes, scores, summarizes
and pools the round and writes it up.

- Pooled repair@1 ([`repair-pool/test.json`](results/repair-pool/test.json)):
  counterexample 0.467 [0.347, 0.590], 35/75; bare 0.280 [0.161, 0.435],
  21/75; resample 0.053 [0.014, 0.113], 4/75. By case (OD9) all three pooled
  comparisons are conclusive: 12 against 4, 21 against 2 and 13 against 0.
- Per model (each pass's `repair/summary.json`): the primary,
  counterexample against bare, is conclusive only for the 120B, 9 against 2
  (0.350 [0.056, 0.636]). The anchor's two comparisons with resample are
  conclusive too; the other 9 of 12 are inconclusive.
- Commits: ef9de37, c40108c, 093143a and 4fc589f, one round each (anchor, 8B,
  120B, frontier); 9d10c9d, the pool. b65fd84 makes the exporter and the site
  read the round: the Reel's step 5 turn and the methodology page's Repair
  round section. 3556939 records that in `decisions/web-site.md` and
  `decisions/disproof-reel.md`. e0b1a65 writes the page's repair half and
  the README line, and 73ac90c the repair note's After, test and this entry.
  The review fixes that follow stop the export when the frontier slot's test
  pass has a round but the pick's pass has none, test that a repair cannot
  move the pick in either direction, and correct the wording of the results
  page, the README, the two web notes, the repair note and this entry.

## PR #22 merged: 2026-10-06

PR #22 merged `test-repair-round` into `main` as 1ec918c; the owner reports
hosted CI green on the PR and on `main`. It adds the test repair round and
its pool: counterexample repair@1 0.467 [0.347, 0.590], 35/75, against bare
0.280 (21/75) and resample 0.053 (4/75)
([`repair-pool/test.json`](results/repair-pool/test.json)); the repair half
of [`results/locked-test-v1.md`](results/locked-test-v1.md); and the
exporter's Reel step 5 turn and methodology repair line.

## PR #23 merged: 2026-10-06

PR #23 merged `site-reel` into `main` as 5dd672f. The Reel on `/` draws
the chosen prototype's ladder for each scored probe of the pick, with the
cursor's packet-list row and the predicate trace there. The new evidence is
`packets.json`, every curated frame's packet-list columns from the pinned
tshark (139,563 bytes, 8 probes, 480 frames), and the pick's trace (5,856
bytes). The Docker static export has 33 files in 5,514,918 bytes, and
Playwright ran 164 tests in 17.6 s
([web site note](decisions/web-site.md), Measured).

## PR #24 merged: 2026-10-06

PR #24 merged `train-data` into `main` as a686d29. It freezes training set
v1: 1,299 rows, 1,088 ready and 211 asking for clarification, kept from
2,400 sampled compositions of the dev and test gold's predicates, each
labelled by the pinned tshark on three train-only probes
([`data/train/v1/manifest.json`](../data/train/v1/manifest.json)).
`tests/test_train_split.py` asserts that no row shares a canonical key,
frame set or 8-word run with dev or test. `docs/protocol.md` records the
small model, Qwen/Qwen3-1.7B with thinking off, and the label rules.

## PR #25 merged: 2026-10-06

PR #25 merged `site-deploy` into `main` as 210e100. The `pages` job in
`ci.yml` builds and tests the site under `/DFilterForge` after every gate
passes on a push to `main`, and deploys it to GitHub Pages, which replaces
the Cloudflare Pages decision of 2026-10-01
([web site note](decisions/web-site.md), Deploy). The site is live at
https://weiguang-2099.github.io/DFilterForge/; on 2026-10-07 its
methodology page links its sources at 210e100. The branch also drops the
retired Go/No-Go gates from the pull request template and the docs.

## Planned next

The owner's rulings of 2026-10-06 fix three points of this order. The site
is live when item 2 is deployed: the Reel on `/`, `/board`, `/methodology`
and the README GIF; GPU spend waits until then. The small model is
Qwen/Qwen3-1.7B, the hybrid model with thinking off. The training data is
built on CPU alongside the site. The rest is the plan of record, except
where an item says it is the maintainer's order.

1. Done: the [repair round](decisions/repair-round.md), dev and test (PRs
   #20 to #22).
2. The hosted site: the Disproof Reel on `/`, chosen by the registered rule
   `reel-v1`, `/board`, `/methodology` and the README GIF, deployed to
   GitHub Pages by the `pages` job. The receipts and cases pages follow
   as site work once it is live, in the maintainer's order; they do not
   gate item 3.
3. Qwen/Qwen3-1.7B, the hybrid model with thinking off, through the same
   scorer, at most 3 USD, only after item 2 is live. GPU work runs on
   Modal (owner ruling).
4. Training data, built on CPU alongside item 2; then QLoRA-SFT,
   verifier-labelled DPO and a continued-SFT control, three seeds each; the
   GRPO gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed, and the
  standalone hash-validation phase was intentionally not run; the stopped local
  run reached 28 captures and 4,200 exact pairs without a difference, but
  partial measurements are not release evidence.
- Dev has 12 ready cases, so every dev comparison is inconclusive. The test
  repair round is measured, but 9 of its 12 per-model comparisons are
  inconclusive. SFT, DPO and GRPO are unmeasured.
- The A/A noise bound is measured on qwen/qwen3-32b only; the locked test
  page applies it to the other three models as a named extrapolation.
- Only the baseline half of `docs/results/locked-test-v1.md` was generated,
  by a local, uncommitted script whose guards now refuse the committed repair
  runs; the repair half is typed. No CI check ties either half to its files;
  CI checks the files themselves.
- `scripts/repair_arms.py` has sent paid calls three times: on the dev split,
  the owner's batch of 2026-10-04 ("Dev repair rounds published" above) and
  its re-run of 2026-10-05, whose committed runs are only the three frontier
  `-nb` runs; on the test split, the owner's batch of 2026-10-05 (225
  requests, "Test repair round" above). Apart from those batches, its
  sending path is tested only against a scripted call step,
  its keyless path against the real call step, and its invoker's key
  withholding against a stub child.
- The repair tooling records only gate stops as not run; no further round
  is planned, so the gap stays unfixed.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. The numbers of `results/locked-test-v1.md` tied to their files by a CI
   check.
2. New pages (the Reel, `/board`) render every number through the sourced
   components, so `consistency.spec.ts` checks them.

## Web data path: 2026-10-01, branch web-data

- The branch starts at 86cd624, on bakeoff-results, and has not been pushed.
  The [web site](decisions/web-site.md) note holds the data contract, a before
  and after table, and the measurements.
- `git diff --name-only 86cd624..HEAD` lists none of the 12 prepare-hashed
  files, and none of `runner.py`, `live.py` or `replay.py`.
- The commits:
  - 52c9a37 deletes the hand-written evaluation mock: `app/_data/recorded.ts`,
    `/evaluate`, its components and its test. It also removes the methodology
    page's claim that no language model had been evaluated.
  - 66297e0 makes the site a static export under `/DFilterForge`, served by
    `scripts/serve.mjs` and tested with bundled Chromium. The base path is read
    from `PAGES_BASE_PATH` in `apps/web/scripts/base_path.mjs` only; an empty
    value serves the site at the domain root. Its default, `/DFilterForge`,
    is also written in the Dockerfile's `ARG`, the composite action's
    `base-path` input and the CI loopback probe, which cannot import the
    module; `apps/web/tests/base-path.spec.ts` pins those three to it.
  - 9126742 commits `docs/decisions/evidence/web/captures.json`.
  - 3df8722 adds `scripts/export_web_data.py`.
  - 0dcd8df projects the Reel by rule `reel-v1`.
  - 7925340 builds the site inside Docker.
  - e1272c2 adds the sourced components and the digit lint.
  - fc0ee7e adds the consistency test.
  - 979397a and 5c043bd clean up formatting.
  - 07d91ca wires CI.
- `captures.json` has 8 probes, 480 frames and 51,073 bytes.
  `export_web_evidence.py check` regenerates it and passes. It matches every
  capture hash to the test-freeze gate receipt, the scored specifications and
  the held-out freeze digests.
- The export of the committed dev data has 676 files and 9,546,808 bytes: 651
  receipts and 20 cases.
  - It holds 52,934 sourced values, and an independent Python resolver
    re-derives every one from the raw files.
  - Two exports in the test image are byte-identical.
  - The Docker `data` stage's output equals the test-image export.
- Rule `reel-v1` picks `dev-qwen3-32b-2026-09-26` C4 `mei-0015` from 27 C4
  silent-wrong candidates. The headline counts are M = 284 and N = 65. These
  are dev counts: model selection, not an effect.
  - The rule is not registered yet. `docs/decisions/disproof-reel.md` and
    `docs/decisions/evidence/test-runs.json` must land before the first test
    request.
- The Docker-built static export has 29 files, 923,060 bytes and 3 routes.
  - The methodology page renders 138 sourced values: 40 linked numbers and 98
    strings.
  - The home page stays a digit-free placeholder until the Reel lands.
  - 57 Playwright tests pass on that build: 13 smoke, 11 formatter, 27
    lint-rule and 6 consistency.
  - A number typed into markup, in any script (fullwidth digits, Roman
    numerals) or as a list's `start`, fails the lint and the consistency
    sweep. A value that differs from its committed file fails the
    consistency test.
- CI, in 07d91ca:
  - The python job gains four steps after the re-score loop. The
    frozen-prompt guard and the pylint line are unchanged; lines 1 to 103 are
    byte-identical.
  - The web job builds `out/` through `apps/web/Dockerfile` with the
    composite action `.github/actions/web-site`. It then runs typecheck, lint
    and Playwright on that build, and serves the Compose `site` stage on
    loopback.
  - Neither job has run on GitHub. actionlint 1.7.7 reports no error, and
    every step ran locally under the Compose hardening.
- The CI python job mirror at 07d91ca, in the test image with the branch
  mounted, passed:
  - 1,289 tests passed and 7 skipped (no `docs/` tree in the image), with
    96.89 percent coverage;
  - pyink, isort, pylint, pyright (0 errors) and lint-imports (5 contracts
    kept);
  - the benchmark and adequacy gates, prepare and recall;
  - all 20 `score --check` outputs, with no difference.

  Run separately: CI's exact pylint line (rc 0), the frozen-prompt guard with
  `docs/` mounted (1 passed), and the four new steps. Their timings are pylint
  4 s, evidence check 2 s, 124 tests in 17 s and two exports in 16 s.
- Build and test timings:
  - A Docker build of `out/` takes 21.0 s with no layer cache and 1.8 s cached.
  - A host `pnpm web:build` takes 8.2 s.
  - The 57 Playwright tests take 10.5 s on the Docker build and 9.8 s on the
    host build.
  - Typecheck, lint, build and Playwright all pass on the host.
- Item 2 of "Next verification" now has a CI test for the methodology page.
  The board, case and receipt pages come in the next pull request.
- Still open:
  - hosting (GitHub Pages after a repository flip, or Cloudflare Pages);
  - the two registration commits;
  - the board, case and receipt pages and the Reel;
  - predicate traces for the Reel pool;
  - pinning base images by digest;
  - a first CI run on GitHub.

## Web data path review fixes: 2026-10-01, branch web-data

- A review of 07c0cbf confirmed eight minor findings. Each is fixed in its
  own commit, still unpushed. Each commit's new test fails on the old code,
  except the CI step, which was proven with a local server.
- The commits:
  - 113396f: the CI compose smoke probe now uses `--retry-all-errors` and
    stops the service from an `EXIT` trap.
    - On a Linux runner, docker-proxy accepts and drops connections until
      node listens. curl then exits 52 or 56, and `--retry-connrefused`
      never retries those.
    - A local server that drops the first three connections fails the old
      flags at once (exit 56) and passes the new ones.
    - The step ran locally: a 200 in 4.8 s. With a wrong prefix it exits 22
      after its retries, and the trap removes the container.
  - 0e4c78a: `react/no-danger` now applies to every component
    (`customComponentNames: ['*']`). A syntax rule also bans the prop's
    name as an identifier, a string or a template key. Eight fixtures, each
    linted as a page and as a test, cover:
    - a DOM element;
    - a wrapper component;
    - a spread object;
    - `createElement` props;
    - a string key, a computed member, a template key and a member.
  - 9d8929e: `visible()` now marks every format, default-ignorable and
    private-use code point as `[U+XXXX]`. That covers tag characters,
    invisible operators, variation selectors and Hangul fillers.
    - Unassigned code points are left alone. A browser draws them as a box,
      and their set changes with each Unicode version.
    - Node 20.20.2 and 24.21.0 both carry Unicode 17.0, and both mark
      141,674 code points.
  - 9c30d68: the exporter, the TypeScript resolver and the Python test
    resolver now refuse a symbolic link at any path component. That
    includes a directory link that stays inside the repository.
    - A pytest case plants such a link, and so does a resolver spec, which
      uses a junction on Windows.
  - 28efe20: the cut of model text comes from the contract, never from the
    page's `data-cap`. It is exactly 4,096 bytes, it applies to a
    completion's `response_text` only, and it is required there.
    - This holds in the consistency test, `lib/data.ts` and the Python
      source check.
    - The new tests plant a 64-byte cut, a 1-byte cut, a missing cap and a
      cap on a label. Each fails.
  - 3d3342c: the lint and the sweep now match any Unicode number character
    (`\p{N}`), and both treat `start` as a shown attribute.
    - Seven new lint fixtures fail on the old rules, and so does a planted
      page for the sweep.
  - 5048d0e: each route is also checked in a browser context with
    JavaScript disabled, with the same value, number and data-free checks.
    - A planted page removes its typed number once scripts run. It passes
      the hydrated sweep and fails the server-rendered one.
  - a9f12d9: `base_path.mjs` exports `DEFAULT_BASE_PATH`.
    `tests/base-path.spec.ts` pins the other three copies of the default to
    it: the Dockerfile `ARG`, the action input and the CI probe URL. With
    the default renamed, all three tests fail.
- `git diff --name-only 86cd624..HEAD` still lists none of the 12
  prepare-hashed files, and none of `runner.py`, `live.py` or `replay.py`.
- Verification at a9f12d9:
  - Host: `pnpm web:typecheck`, `pnpm web:lint` and `pnpm web:build` pass.
    actionlint 1.7.7 reports no error.
  - The Docker `--target out` build takes 12.2 s with a warm cache. It
    gives the same 29 files and 923,060 bytes as before, with 4
    `index.html` routes.
  - 82 Playwright tests pass on that build in 10.9 s on two workers:
    - 13 smoke and 13 formatter;
    - 41 lint-rule and 9 consistency;
    - 3 resolver and 3 base-path.
  - In the test image with `docs/` mounted:
    - The exporter and evidence tests pass: 126 tests.
    - The frozen-prompt guard passes: 1 test.
    - pylint on the two web scripts exits 0.
    - `export_web_evidence.py check` passes.
    - Two exports are identical under `diff -r`: 676 files, 651 receipts.
  - The CI python job mirror passes in 33 min 56 s:
    - pyink, isort, pylint, pyright (0 errors) and lint-imports (5
      contracts kept);
    - 1,291 tests passed and 7 skipped, with 96.89 percent coverage;
    - the benchmark and adequacy gates, prepare and recall;
    - all 20 `score --check` outputs, with no difference.
- Still open:
  - The `lib/data.ts` cap guard has no unit test. The module imports
    `server-only`, so the Playwright runner cannot load it. The consistency
    test and the Python check cover the same rule.
  - The sweep does not see the markers that CSS numbers for a list without
    a `start`.
  - Neither CI job has run on GitHub.

## Web data path final check: 2026-10-02, branch web-data

- Every check was re-run at bef74e9, the head after the review fixes. The
  counts equal those at a9f12d9; bef74e9 only rewrites test fixture
  characters as escapes.
- `git diff --name-only 86cd624..bef74e9` lists none of the 12
  prepare-hashed files, and none of `runner.py`, `live.py` or `replay.py`.
- The CI python job mirror passes in 35 min 17 s:
  - pyink, isort, pylint, pyright (0 errors) and lint-imports (5 contracts
    kept);
  - 1,291 tests passed and 7 skipped, with 96.89 percent coverage;
  - the benchmark and adequacy gates, prepare and recall;
  - all 20 `score --check` outputs, with no difference.
- The CI steps the mirror leaves out ran in the test image under the
  Compose test-service hardening, with `docs/` mounted read-only:
  - CI's exact pylint line and pylint on the two web scripts each rate
    10.00/10;
  - `export_web_evidence.py check` passes: 8 probes, 480 frames;
  - the exporter and evidence tests pass: 126 tests;
  - two exports are identical under `diff -r`: 676 files, 651 receipts;
  - the frozen-prompt guard passes: 1 test.
- On the host, `pnpm web:typecheck`, `pnpm web:lint` and `pnpm web:build`
  pass. The host build has 29 files and 922,854 bytes, and 82 Playwright
  tests pass on it.
- The Docker `--target out` build has 29 files, 923,060 bytes and 4
  `index.html` routes. 82 Playwright tests pass on it in 10.1 s. The
  methodology page renders 138 sourced values (40 linked numbers and 98
  strings) and 4 terms.
- With `PAGES_BASE_PATH` empty, as a host at the domain root needs, the
  host build links from `/`. 81 tests pass; the one that checks nothing is
  served outside the base path skips, since there is no outside.
- The `site` stage, run with the Compose hardening on a private loopback
  port, answers 200 at `/DFilterForge/` and `/DFilterForge/methodology/`,
  404 for an unknown page and for the bare root, and runs as uid 10001.
  The image is 201 MB.
- The design asked to rewrite two older Web lines in this file. They stay
  as written, because this file only gains appended sections, which limits
  the known merge conflict with `repair-multiturn`. The first is in the
  2026-09-15 to 2026-09-21 section and was true at that date. The second,
  under the limits, still holds: the site is recorded-only.
- Still open: the same items as after the review fixes, plus hosting
  (decision D1) and the two registration commits (decision D2).

## Web data on the registered test runs: 2026-10-04, branch web-data

- `web-data` now builds the site on main's registered, scored test runs.
  The branch is still local: nothing is pushed and no pull request is open.
  Every check below ran at 69d237e; the two commits after it, dffcc8c (the
  [web site](decisions/web-site.md) note) and this entry, change only docs.
- `git diff --name-only bff373c..69d237e` lists 46 files: none of the 12
  prepare-hashed files, and none of `runner.py`, `live.py` or `replay.py`.
- 10dae61 merges main (bff373c) into `web-data` (a79d548) with a merge
  commit whose parents are a79d548, then bff373c.
  - The only conflict was `.github/workflows/ci.yml`. The resolution keeps
    main's text with its two repair checks first, then `web-data`'s four
    web steps, and `web-data`'s web job. Its blob is
    ea0100ba08271dd31015a20537d3b09ffd4be1c4, unchanged since.
  - At the merge, the two committed-tree exporter tests failed with
    `role_invalid` on main's registry roles, as expected, until def05f4.
- The commits after the merge:
  - b4bde9d checks the registry's rows against the Runs table of
    `docs/decisions/test-runs.md`, numbered from 1 and in order. The
    exporter no longer reads `model-bakeoff.md`.
  - 0bbf3fd takes the winners' dev passes from the ruling the registry
    names (`slots.<slot>.winner.run_id`) and hashes the ruling into the
    Reel's inputs.
  - def05f4 reads the registered roles and statuses, and the test-phase
    rule of `disproof-reel.md`.
  - 628e1ba makes pass B the board's `rerun`, never a board row.
  - 61030fc repeats the registered dev Reel check on a copy of the
    committed tree.
  - 114171d mirrors the registry reading, the Reel pool and the pick in
    the TypeScript resolver.
  - Review fixes, one commit per finding, except the TypeScript refusals,
    which took two (97bb621 and 56b8c96):
    - e073ab1, d7b31d3 and d9d5a74 add exporter cases for an unknown
      trigger, a row that names itself, a note numbered from 0, a note
      with an extra row, an empty `not_run` reason and a run manifest
      under a `registered` row. Each fails with DID NOT RAISE against the
      mutant it targets.
    - 93db036 pins `board.json`'s `not_run` list to role order.
    - d586d65, 1b2cbf7 and c88c985 add TypeScript cases: fewest frames
      before pool position, an unscored published row, an empty test pool,
      and the registry refusals of the exporter's broken-registration test.
    - 97bb621 and 56b8c96 make the TypeScript resolver refuse what the
      exporter refuses: the registry's schema, note, Runs table and run
      ids, and the ruling in both phases.
    - 787fded stops the export with `repair_unread` once scored repair
      results exist for the Reel's pool, until Reel step 5 is built. The
      TypeScript resolver refuses the same files.
    - 69d237e shows a summary's `not_measured` status `not_run` as "not
      measured yet" through a new fmt kind, `unmeasured`, and the
      `<Unmeasured>` component. The consistency test fails such a value
      shown with any other kind. The dev anchor's own
      `repair/summary.json` stops the export too, in either phase. d3ff716
      keeps that stop for the dev phase only (next section).
- The exporter's reading of `docs/decisions/evidence/test-runs.json`:
  - Schema `test-runs/1.0`, else `schema_invalid`, exit 2. `note` must be
    `docs/decisions/test-runs.md`, else `note_mismatch`.
  - For each row: one of the eight roles (`role_invalid`); a run id that
    fits the result-name pattern (`run_id_invalid`), starts with `test-`
    (`split_mismatch`) and is unique (`run_repeated`); one of the four
    statuses (`status_invalid`); a reason on each `not_run` row
    (`not_run_invalid`).
  - Then conditions as the frozen-prompt guard reads them
    (`condition_invalid`), the five planned rows in order
    (`role_missing`), no run manifest or scored summary under a row that
    is not published (`not_run_scored`), and at most one published row
    per slot (`role_invalid`).
  - Then the Runs table (`run_unregistered`) and the ruling: schema
    `bakeoff-ruling/1.0` with a winner run id per slot (`schema_invalid`,
    exit 2), a `dev-` prefix (`split_mismatch`), and a winner the ranking
    shows (`pool_unshown`).
  - The test phase is on once no row is `registered`, every published
    row's run is scored and every other row is final. A published but
    unscored row keeps it off, with no error.
  - The shown test runs are the published rows in role order. The Reel's
    test pool is pass A, then each slot's published winner, else its
    published fallback. Pass B is only the board's `rerun`. The board's
    `not_run` lists the `not_run` rows with sourced reasons.
- On the committed tree the test phase is on. Of the registry's 16 rows,
  rows 1 to 5 are published, each with `scored/summary.json`, and the other
  11 are unused. 15 runs are shown: the ten dev passes, then the five test
  passes in role order.
- The export at 69d237e:
  - 1,935 files and 27,410,976 bytes, with 1,854 receipts and 76 cases.
    The resolver in `tests/test_export_web_data.py` re-derives all 150,084
    sourced values (100,433 strings and 49,651 numbers, booleans or integer
    arrays) with no mismatch.
  - On the host, with Python 3.12.10, two exports take 5.736 s and 5.544 s
    and are byte-identical.
  - In the test image, CI's export-twice step takes 68.629 s, and the two
    exports are identical under `diff -r`.
  - `/tmp`, a 128 MB tmpfs in the test service, ends the export-twice step
    at 59,548 KB of 131,072 KB (46 percent). The exporter and evidence
    tests peak at 20,460 KB in samples taken every 0.2 s, which can miss a
    shorter spike.
- Rule `reel-v1` on the test phase picks `test-qwen3-32b-2026-09-26` C4
  `mei-1038`:
  - The pool is pass A and the three slot winners' test runs, with 54 C4
    silent-wrong candidates. Only the pick has 3 disagreeing frames; the
    next fewest is 4.
  - The answer `(tcp.srcport == 443 && tcp.completeness.fin == true)`
    misses frames 59, 60 and 66 on semantic-31, -37 and -43. The highlight
    is semantic-37, frame 60, `server-fin-ack`.
  - Headline over the test pool: M is 971 and N is 165.
- The 2026-10-01 dev check still holds. On a copy of the committed dev
  inputs with rows 1 to 5 set back to `registered`, the exporter picks
  `dev-qwen3-32b-2026-09-26` C4 `mei-0015` from 27 candidates, with M 284
  and N 65. The `registered` edit is not what keeps that copy in the dev
  phase: the copy holds no test run. With the five test runs copied in and
  the edit dropped, the phase moves to test and the test fails.
- Tests and checks at 69d237e:
  - Host: `tests/test_export_web_data.py` has 148 passed and 2 skipped in
    149.79 s; the skips are the symbolic-link tests, which need privileges
    on Windows. `tests/test_export_web_evidence.py` fails only its 5 known
    Windows path-separator cases.
  - Host static checks: pyink, isort, pylint on the two web scripts
    (10.00/10) and lint-imports (5 contracts kept) pass. pyright reports 0
    errors with `--pythonplatform Linux` and in the test image.
  - CI's four web steps, run as written in the test image under
    `-p dfilterforge-webcheck` with read-only mounts, pass: pylint
    10.00/10, the evidence check (8 probes, 480 frames), 174 exporter and
    evidence tests in 125.93 s, and two identical exports.
  - Playwright: 142 tests pass in 15.7 s on two workers against the
    Docker-built `out/`: 56 registry, 41 lint-rule, 14 formatter, 13
    smoke, 11 consistency, 4 resolver and 3 base-path.
    `pnpm web:typecheck` and `pnpm web:lint` pass. Host Node is 24.21.0;
    CI pins 20.20.2.
- Docker builds at 69d237e:
  - `--target out` gives 29 files and 923,059 bytes. It takes 19.515 s
    with the export and build stages rebuilt (export 4.1 s, `next build`
    8.1 s) and 3.416 s cached. The cached and rebuilt trees differ only in
    the Next build id.
  - `--target data` gives 1,935 files and 27,410,976 bytes. It takes
    15.434 s with the export rebuilt and 6.672 s cached. `diff -r` against
    the test-image export and against the host export is empty.
  - The Compose `web` service, built and started under
    `-p dfilterforge-webcheck`, answers 200 at
    `http://127.0.0.1:3000/DFilterForge/`.
- The CI python job mirror at 69d237e passes all 58 steps in 3,400 s. It
  runs in the test image with the branch's code mounted read-only and a
  128 MB `/tmp`:
  - pyink, isort, pylint, pyright (0 errors) and lint-imports (5 contracts
    kept);
  - 1,955 tests passed and 28 skipped in 1,187.49 s, with 97.10 percent
    coverage;
  - with `docs/` mounted, 5 test nodes and 7 test files give 468 passes
    and no skip, the frozen-prompt guard and 150 exporter tests included;
  - the benchmark and adequacy gates, prepare and recall;
  - `score --check` over 25 directories (17 scored, 4 control-reference and
    4 control-mutation) with no difference, `repair --check` over 8 plans,
    and `repair-pool --check` over 0 pools, since none is committed.

  The mirror runs the score and repair checks in the test image, not CI's
  lab image, and without the Compose hardening.
- actionlint 1.7.7 reports no finding, and `ci.yml` holds exactly one
  `127.0.0.1:3000` probe.
- Closed: the "two registration commits" (decision D2) that both web
  sections above list as open. `disproof-reel.md` landed in 6f2beb9, and
  `test-runs.json` with `test-runs.md` in 6819a52. Both are ancestors of
  7aaade8, the source revision pass A's first invocation recorded at
  2026-10-01T18:45:12Z, so rule `reel-v1` and the registry predate every
  test answer.
- Still open:
  - the A/A reading and the confound notes: `board.json` keeps `aa` null,
    and the pages must show the pair report's reading, the comparisons
    `results/locked-test-v1.md` marks confounded, and the HTTP 429 losses;
  - Reel step 5: no test `-cx` arm run is scored and `reel.json` keeps
    `repair` null. Once main holds a scored repair result for a Reel pool
    run (its `repair/summary.json`, its scored `-cx` arm or that arm's
    `-r2` re-run) or the pool split's `repair-pool` file, merging main
    stops the export and CI's export steps with `repair_unread`. In the
    test phase the pool is pass A and the slot winners' test runs, so the
    dev repair round on branch `dev-repair-round` stops nothing (next
    section). Building step 5 lifts the Reel's stop. The first pool run's
    `repair/summary.json`, pass A's, also stops the methodology page,
    which must first read the round's summary;
  - the methodology page's bootstrap block, still taken from the dev
    anchor's summary;
  - the board, case, receipt and Reel pages, with the rules the web site
    note now lists for them;
  - predicate traces for the Reel pool, now the four test passes, and
    pinning base images by digest;
  - hosting (decision D1);
  - a first CI run on GitHub;
  - this file's header, Current slice and Planned next. They are main's
    lines, so they are updated at the last merge before the push.

## Web data: the methodology's repair status follows the phase, 2026-10-04, branch web-data

- Why: at df04ade the methodology page took its `not_measured` status from
  the dev anchor's summary in both phases, and the export stopped with
  `repair_unread` whenever the anchor's `repair/summary.json` existed. The
  local branch `dev-repair-round` (1d07612, read only) commits that file,
  and those of `dev-qwen3.5-9b-2026-09-26` and
  `dev-qwen3.5-122b-a10b-2026-09-26`, for the dev repair round. The df04ade
  exporter on a `git archive` of that branch's `docs/` and
  `held_out_freeze.json`, plus `web-data`'s `captures.json`, exits 1 with
  `repair_unread` on the anchor's file. Merging that round would have
  turned the export and CI red, although the test-phase site never shows
  the dev round.
- d3ff716 takes the page's `not_measured` statuses from the run whose
  repair round the site reports. In the test phase that is the first test
  pool run: pass A whenever it is published, else the published winner or
  fallback of the first slot that has one, and no run, with no status
  listed, when the pool is empty. In the dev phase it is the dev anchor.
  Only that run's `repair/summary.json` stops the methodology
  (`repair_unread`); the Reel's pool guard from 787fded is unchanged. The
  page's other run values, the prompt conditions, `top_k`, the bootstrap
  block and the scoring environment, stay with the dev anchor in both
  phases; its probes, mutant counts, shortcut audit and admitted prepares
  come from no run and were not touched. The page's wording names no
  source run for its "Not measured yet" section, so it was not changed.
- The TypeScript resolver mirrors the rule in the same commit:
  `repairStatusSummary()` names the cited summary and refuses that one
  file. `tests/registry.spec.ts` covers it in both phases, and
  `tests/consistency.spec.ts` checks that the built methodology page takes
  its statuses from that summary and pins pass A's for the committed tree.
- Proof, on scratch copies only:
  - Exporter: of the new cases, the three test-phase citing cases (pass A;
    the small winner without pass A; no run with only pass B published,
    each with the anchor's `repair/summary.json` present), the test-phase
    stop on pass A's file, and the outside-the-pool case with the anchor's
    file added fail on df04ade's exporter. The dev-phase stop on the
    anchor's file passes there, as it should: that behaviour is kept.
  - Exporter mutants, each failing its named cases: the anchor in both
    phases (the three citing cases, the test-phase stop and the
    outside-the-pool case); the methodology's own check removed (both
    stop cases, with DID NOT RAISE); only a published `aa_pass_a` counted
    (the small-winner case); an empty test pool falling back to the
    anchor (the empty-pool case).
  - Resolver: all 5 new `registry.spec.ts` cases fail on df04ade's
    resolver, which has no such method. The same four mutants fail their
    matching cases.
  - The new consistency check fails on the `out/` left from the 69d237e
    checks, whose methodology page cites the dev anchor's summary, and
    passes after a Docker rebuild at d3ff716.
  - On the `dev-repair-round` tree above, d3ff716's exporter exits 0 with
    1,935 files; `methodology.json` cites
    `test-qwen3-32b-2026-09-26`'s summary and its bootstrap still the dev
    anchor's. The three committed-tree tests pass there with d3ff716's
    exporter and tests; with df04ade's, two of them fail.
- Checks at d3ff716, on the host:
  - `tests/test_export_web_data.py`: 152 passed and 2 skipped (the
    symbolic-link tests) in 66.43 s, committed-tree tests included.
  - pyink and isort pass on the two web scripts and the test. pylint on
    the two web scripts rates 10.00/10 and exits 0. pylint on the test
    exits 24, as it does at df04ade, with the same message kinds and one
    more missing function docstring, for the one test function added net.
    pyright with `--pythonplatform Linux` reports 0 errors.
  - `pnpm web:typecheck` and `pnpm web:lint` exit 0.
  - Two host exports are byte-identical: 1,935 files and 27,410,977 bytes,
    1 byte more than at 69d237e, from `methodology.json` (16,213 bytes).
  - Docker `--target out` gives 29 files and 923,064 bytes. Playwright on
    it: 148 passed in 11.4 s on two workers (61 registry, 41 lint-rule, 14
    formatter, 13 smoke, 12 consistency, 4 resolver, 3 base-path).
  - Not run at d3ff716: the CI python job mirror, the test-image steps,
    Docker `--target data` and the Compose `web` service.
- Still open: the items of the section above, with the Reel step 5 item as
  corrected there.

## Web data: methodology source wording, 2026-10-04, branch web-data

- Why: a review of d3ff716 and 70a8c9c found two false sentences, each
  confirmed against the code at 70a8c9c.
  - Four places said `methodology.json` takes everything from the dev
    anchor but its `not_measured` statuses: the exporter's module
    docstring, `build_methodology`'s docstring, web-site.md's Outputs list
    and this file's d3ff716 entry. `build_methodology` takes only the
    prompt conditions, `top_k`, the bootstrap block and the scoring
    environment from the anchor run. Six of its eleven keys come from no
    run: probes and witnesses from `captures.json`, mutant counts and
    categories from the test-freeze gate receipt, the shortcut audit from
    ablation 006's evidence and the admitted prepares from
    `held_out_freeze.json`. 49f458b names each source in all four places.
  - web-site.md's What-fails item said `resolve.ts` refuses "exactly that
    one file" right after a sentence naming the dev anchor's
    `repair/summary.json`, which `repairStatusSummary()` does not refuse in
    the test phase. 6f1290e names the cited run's file and the phase rule.
- Neither commit changes code or the export. Checks at 49f458b, on the
  host: pyink and isort pass on the exporter, pylint on the two web scripts
  rates 10.00/10 and exits 0, and `tests/test_export_web_data.py` gives 152
  passed and 2 skipped in 83.37 s. The web gates, Playwright and the Docker
  export were not rerun, since no TypeScript, page or exported byte
  changed.
- Not applied: labelling the methodology's repair line "Test repair round"
  in the test phase. Once `dev-repair-round` merges, the page's plain
  "Repair round: not measured yet" cites pass A's summary only through
  `data-src`, beside three sections that say they come from the anchor
  pass. The decided fix allows a wording change only where the page claims
  the line comes from the anchor, and it does not; `docs/protocol.md`
  never reports the dev round as an effect. The label is left to the
  maintainer.
- Still open: the items of the two sections above.

## Web data: the methodology's repair line names its round, 2026-10-04, branch web-data

- Why: the maintainer decided review finding B1, which the section above
  left open. The methodology page's repair line must say which round it
  describes, so that once `dev-repair-round` merges the page cannot read as
  if no repair round had been measured. The label follows the split of the
  run the line cites: "Test repair round" for a test run (test phase),
  "Dev repair round" for the dev anchor (dev phase). With an empty test
  pool the page lists no status and no label, as before.
- dfeaf11 makes the change in one commit:
  - Exporter: each `not_measured` entry of `methodology.json` gains
    `split`, a sourced string `["ptr", <cited summary>, "/split"]`. `Run`
    already refuses a summary whose split is not its run id's
    (`split_mismatch`).
  - Page: `lib/fmt.ts` gains the kind `split`, which shows `dev` as "Dev"
    and `test` as "Test" and throws on anything else. `lib/sourced.tsx`
    gains `<Split>`, `lib/data.ts` requires `split` on every entry, and the
    page's label is `<Split>` followed by "repair round". No digit or
    typed split is in the markup.
  - Resolver: `repairStatusSplit()` reads the cited summary's split and
    refuses one that differs from the cited run id's.
  - Tests: the Python `_statuses` helper and a new test, run in both
    phases; two new `registry.spec.ts` cases and a split check in the
    three citing cases; a `fmt.spec.ts` case and the kinds list; a new
    `consistency.spec.ts` test that checks each "Not measured yet" label's
    text and that its `<Split>` points at the summary
    `repairStatusSummary()` names, and a `test` pin for the committed tree.
- Proof, on scratch copies only:
  - Exporter, 9 selected methodology cases: f66b1e4's exporter fails 6
    (the two citing cases with a run, both stop cases and both new cases).
    A split from the dev anchor in both phases fails 4, the test-phase
    ones; a split from the first probe capture fails 6. The committed-tree
    export test fails with f66b1e4's exporter and passes with dfeaf11's,
    on a copy of the tracked files.
  - Resolver, 7 methodology cases: f66b1e4's resolver fails 5
    (`repairStatusSplit is not a function`); reading the anchor's summary
    in both phases fails 3; taking the split from the run id without
    reading the summary fails 2; dropping the split check fails 2.
  - Site: six Docker `--target out` builds of scratch copies, each checked
    with the copy's `consistency.spec.ts`. The unmutated copy passes all 13.
    f66b1e4's exporter, page, `data.ts` and `sourced.tsx` (with the new
    `fmt.ts`, since `next build` typechecks the specs) shows "Repair round"
    and fails only the new label test. So do four mutants: the exporter
    taking the dev anchor's split ("Dev repair round"), the page taking the
    first probe capture's split ("Dev repair round"), the page showing the
    split through `<Str>` ("test repair round"), and the page typing "Test
    repair round". The `/methodology/` route's value checks pass on all
    five, which is why the label test is needed.
  - The new consistency spec on the `out/` built at d3ff716 also fails
    only the label test.
- On `dev-repair-round` at 30eb879 (a `git archive` of its `docs/` inputs
  and `held_out_freeze.json`, plus web-data's `evidence/web/`), dfeaf11's
  exporter exits 0 with 1,935 files. The label's split is `test`, from
  pass A's summary, and the bootstrap block is still the dev anchor's.
- Checks at dfeaf11:
  - Host `tests/test_export_web_data.py`: 154 passed and 2 skipped (the
    symbolic-link tests) in 87.51 s.
  - pyink and isort pass on `src`, `tests` and `scripts`. pylint on the two
    web scripts rates 10.00/10 and exits 0. pyright with
    `--pythonplatform Linux` reports 0 errors.
  - `pnpm web:typecheck` and `pnpm web:lint` exit 0.
  - Two host exports are byte-identical: 1,935 files and 27,411,082 bytes.
    `methodology.json` is 16,318 bytes, 105 more than at f66b1e4, and is
    the only file that differs from f66b1e4's export.
  - Docker `--target out` (14 s) gives 29 files and 924,010 bytes;
    `methodology/index.html` is 108,305 bytes with 139 sourced values.
    Playwright on it: 152 passed in 13.5 s on two workers (63 registry, 41
    lint-rule, 15 formatter, 13 smoke, 13 consistency, 4 resolver, 3
    base-path).
  - The CI python job's four web steps, run in `dfilterforge-test:0.1.0`
    (created 2026-09-26, not rebuilt) with the worktree's code mounted
    read-only, under Compose project `dfilterforge-webcheck`: pylint
    10.00/10 (5 s); the evidence check exits 0 with 480 frames and 8
    probes (3 s); the exporter and evidence tests give 180 passed (80 s);
    two exports compare equal with `diff -r` (36 s). Docker was down for
    the f66b1e4 verification, so these steps had not run since 69d237e.
  - Not run: the Compose `web` service, Docker `--target data` and the
    rest of the CI python job.
- Still open: the items of the sections above. B1 is now applied.

## Web data: `<Num>` refuses the split kind, 2026-10-04, branch web-data

- Why: a review of dfeaf11 found that it added the string-only kind
  `split` to `FMT_KINDS` without adding it to the exclusion on `<Num>`'s
  `kind` prop, which 69d237e had widened for `unmeasured`. `<Num>` takes a
  `NumNode`, whose value is a number, a boolean or a list of integers, and
  fmt's split kind throws on every one of those. So `<Num kind="split">`
  passed `pnpm web:typecheck` and `pnpm web:lint` and would have failed
  only in `next build`. No page used it: the only kind passed to `<Num>` on
  a page is `int`. Three reviewers confirmed it with their own tsc probes.
- 19dff88 makes the change in one commit:
  - `lib/sourced.tsx`: the exclusion is now `text`, `unmeasured` and
    `split`.
  - `tests/fmt.spec.ts`: `NUM_KIND_SAMPLES` holds one `NumNode` value per
    kind `<Num>` accepts, typed as a record over that kind type, which the
    compiler checks both ways. A kind added to `FMT_KINDS` fails typecheck
    there until it is listed or excluded on `<Num>`. A new test checks the
    runtime half: each listed kind formats its sample, and fmt refuses
    every sample under `text`, `unmeasured` and `split`.
- Proof:
  - The new spec before the fix: `pnpm web:typecheck` exits 2 with TS2741,
    `split` missing from the record.
  - The reviewers' probe after the fix: `<Num kind="split">` fails with
    TS2322, not assignable to `"int" | "num" | "bool" | "ints"`. The
    control, with `@ts-expect-error` on both `split` and `unmeasured`,
    exits 0.
  - Mutants, each applied to the worktree's files and restored byte for
    byte, run with tsc and the formatter spec:
    - The exclusion reverted: typecheck fails (TS2741). All 16 formatter
      tests pass, since the runtime cannot see types, which is why the
      record is typed.
    - A numeric kind `count` added to fmt and left out of the record:
      typecheck fails (TS2741). Two tests fail, the kinds list and the new
      test.
    - A string-only kind `role` added and not excluded: typecheck fails
      (TS2741). The same two tests fail.
    - `role` listed in the record with a number sample: typecheck passes,
      and the same two tests fail.
    - `num` excluded on `<Num>` and its sample removed: typecheck passes,
      and the new test fails.
    - `num` excluded with its sample kept: typecheck fails (TS2353, excess
      property).
- Checks at 19dff88:
  - `pnpm web:typecheck` and `pnpm web:lint` exit 0.
  - Docker `--target out`: 29 files and 924,010 bytes, the same sizes as
    at dfeaf11. `methodology/index.html` is 108,305 bytes with 139 sourced
    values. `next build`'s TypeScript step, which checks the specs, passes.
  - Playwright on that build: 153 passed in 11.4 s on two workers (16
    formatter, the rest unchanged).
  - The CI python job's four web steps, run in `dfilterforge-test:0.1.0`
    (created 2026-09-26, not rebuilt) with the worktree's code mounted
    read-only, under Compose project `dfilterforge-webcheck`:
    - pylint rates 10.00/10 (4 s).
    - The evidence check exits 0 with 480 frames and 8 probes (3 s).
    - The exporter and evidence tests give 180 passed (80 s).
    - Two exports compare equal with `diff -r`: 1,935 files and
      27,411,082 bytes (38 s).
  - Not run: host pytest and the Python static checks (no Python changed),
    the Compose `web` service and Docker `--target data`.
- Docker's local exporter does not clear its destination. A first build
  into the worktree's existing `apps/web/out` left three manifest files
  from the dfeaf11 build's old build id, 32 files in all. The sizes above
  come from a build into an emptied `apps/web/out`, as on a fresh CI
  checkout.
- Still open: the items of the sections above.
