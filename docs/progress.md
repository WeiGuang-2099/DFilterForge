# Implementation Progress

Last updated: 2026-10-02

## Current slice

The baseline test passes are sent, published and scored, and every hosted
test-run registry row is final. On `repair-arms` the four dev and four test
repair plans are committed, and `scripts/repair_arms.py` gives the owner one
command per split for the arm runs. The branch's PR check at eb7ebcd passed
locally. The dev repair round is next, from main once `repair-arms` merges;
the test round follows any correction the dev round names, after its seeds and
their admission are committed.
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

## Planned next

1. The [repair round](decisions/repair-round.md) as registered, in this
   order; its "Commands" section gives each command. `repair-arms` merges
   first, with a merge commit.
   1. **Owner: the dev round.** From the main checkout on `main`, in Windows
      PowerShell 5.1 or Git Bash, with the key only in that shell:
      `uv run --frozen python scripts/repair_arms.py --split dev`, after its
      `--dry-run`.
   2. **Maintainer: dev publish, score and check.** Publish and score each
      `done` arm run, keep the evidence of each run not run, write each
      pass's round summary with `dfilterforge repair` and check it with
      `repair --check`, then the dev pool with `repair-pool` and its check.
      Each round is committed whole.
   3. **A correction for any defect the dev round shows,** in a commit that
      names it, before any test repair prompt is prepared.
   4. **Test seed and admission PR.** The 12 test arm prompt sets seeded in
      `docs/results/<arm run id>/`, a pass's three in one commit, then their
      `prepare.json` digests admitted in
      `src/dfilterforge/held_out_freeze.json` in a commit of its own (13 of
      the record's 32 admitted prepares).
   5. **Owner: the test round,** once that PR is on `main`:
      `repair_arms.py --split test`, the same way. Then the maintainer's
      publish, score, `repair` and pool for test.
   6. **The repair half of
      [`results/locked-test-v1.md`](results/locked-test-v1.md).**
2. The hosted static page generated from receipts, with its Disproof Reel
   chosen by the registered rule `reel-v1`.
3. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed, and the
  standalone hash-validation phase was intentionally not run; the stopped local
  run reached 28 captures and 4,200 exact pairs without a difference, but
  partial measurements are not release evidence.
- Dev has 12 ready cases, so every dev comparison is inconclusive. Test-split
  repair, SFT, DPO, GRPO and the Pilot Go/No-Go decision are unmeasured.
- The A/A noise bound is measured on qwen/qwen3-32b only; the locked test
  page applies it to the other three models as a named extrapolation.
- `docs/results/locked-test-v1.md` is generated by a local, uncommitted
  script, so no CI check ties the page to its files yet. PR #17 merged the
  `score-test-baselines` branch into main (7a8ec03).
- CI has not run on `repair-arms`, which is not pushed; only the local
  mirrors above have.
- `scripts/repair_arms.py` has sent no paid call. Its sending path is tested
  only against a scripted call step, its keyless path against the real call
  step, and its invoker's key withholding against a stub child.
- The repair tooling records only gate stops as an arm not run
  (`repair --not-run`, at most two arms). An arm not run after an outage on
  its re-run or a refusal, or a round with no arm run, has no record yet; the
  owner would rule on it before that round's summary.
- The Web remains recorded-only; Linux CI teardown and the production
  container were not re-verified, so no live Web job boundary is enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Locked-test run replayed offline from a clean checkout without an API key.
2. Web numbers checked against the scored summary by a CI test.

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
