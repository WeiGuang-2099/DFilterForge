# Implementation Progress

Last updated: 2026-10-02

## Current slice

The test split is frozen and the bake-off dev passes are scored; the two-turn
smoke is next. Reports under the ignored `artifacts/` are not project evidence.

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

## Planned next

1. The two-turn smoke, built on the branch `repair-multiturn`, sent by the
   owner as a second command; a candidate that fails it gives way by rule 5.
2. Register every hosted test run (run id, model id, provider, settings) before
   the first test request, pass A as `test-qwen3-32b-2026-09-26`, and say what
   releases the CI frozen-prompt guard if pass A never publishes there; then
   qwen/qwen3-32b passes A and B and the slot winners on test; the 12 hashed
   files stay unchanged until the last one.
3. Counterexample repair with three feedback arms, the feedback sent as a
   second conversational turn; hosted static page generated from receipts.
4. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
   control, three seeds each; GRPO variance gate measured.

## Blocked or unverified

- The complete 50-capture by 150-filter stability gate has not passed, and the
  standalone hash-validation phase was intentionally not run; the stopped local
  run reached 28 captures and 4,200 exact pairs without a difference, but
  partial measurements are not release evidence.
- Dev has 12 ready cases, so every dev comparison is inconclusive. Test-split
  baselines, SFT, DPO, GRPO and the Pilot Go/No-Go decision are unmeasured.
- The Web remains recorded-only; Linux CI teardown and the production
  container were not re-verified, so no live Web job boundary is enabled.
- Container limits and process controls do not constitute an exhaustive
  host/network escape audit.

## Next verification

1. Locked-test run replayed offline from a clean checkout without an API key.
2. Web numbers checked against the scored summary by a CI test.
