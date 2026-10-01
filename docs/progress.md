# Implementation Progress

Last updated: 2026-09-27

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
