# Implementation Progress

Last updated: 2026-10-01

## Current slice

The test split is frozen, the slot winners are fixed, every hosted test run is
registered, and the repair round and the Disproof Reel's selection rule are
pre-registered; the paid test passes follow once the registration merges, sent
by the owner with one command, `scripts/test_passes.py`.
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

## Two-turn smoke and slot winners: 2026-10-01

- The owner sent the nine smokes from `repair-multiturn` at 281b2ce (prepared
  at 2d305e0 from the committed runner summary, same SHA-256) between 11:50
  and 12:06 UTC, charged at most 0.0115 USD. The anchor's (informational) and
  eight candidates' passed: both replies completed with finish_reason stop,
  parsed under C4 and reported 0 reasoning tokens; every served provider and
  model was the pinned one.
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
  9.00 USD, and the committed runs so far record at most 0.940 USD.
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
  0.940 USD recorded so far and the registry's runs 1 to 5 at their caps,
  OpenRouter spend stays within 7.19 USD of the plan's 12 USD.
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
  reads `evidence/test-runs.json` and sends pass A, pass B only after a
  complete pass A and within 24 hours of its first invocation, then the small,
  mid and frontier winners. Each run is one `scripts/model_run.py call`
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

## Planned next

1. The [registered test runs](decisions/test-runs.md), sent with
   `scripts/test_passes.py`: qwen/qwen3-32b passes A and B, then the slot
   winners; the 12 hashed files stay unchanged until the last one, and no test
   run is scored before the `repair-cards` branch merges.
2. The [repair round](decisions/repair-round.md) as registered: the
   `repair-cards` branch (card code, dev plans), then `repair-arms` with the
   dev round, then, after the last baseline request, the test round and the
   locked test result. Then the hosted static page generated from receipts,
   its Disproof Reel chosen by the registered rule `reel-v1`.
3. Qwen3-1.7B base, QLoRA-SFT, verifier-labelled DPO and continued-SFT
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
