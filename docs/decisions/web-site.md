# Web site: a static export from committed files

The site shows recorded results only and never calls a model. This note
records how a value gets from a committed file onto a page, what fails when
that path is bypassed, and the sizes and timings measured on the dev data. The
web track only consumes the runner, catalog, oracle, trace and replay code, so
under AGENTS.md it gets a decision note with a measured before and after, not
a Full-versus-Simplified ablation.

## Question

How can a reader trace every number on a page to a committed receipt, and how
can CI make a hand-typed or stale number fail?

## Decision

Data moves one way, through three layers:

1. **Committed results.** The scored runs under `docs/results/`, the bake-off
   ranking, the test-freeze gate receipt, the shortcut-policy evidence of
   ablation 006 and `src/dfilterforge/held_out_freeze.json`.
2. **New committed evidence**, regenerated and compared byte for byte in CI.
   Today that is [`captures.json`](evidence/web/captures.json)
   (`capture-frames/1.0`). It holds the frame tables of the eight curated
   captures: dev semantic-11, -17 and -23 with feedback semantic-29, and
   test semantic-31, -37 and -43 with feedback semantic-35. For each frame it
   records the number, whether it is a recipe or a witness frame, and the
   name. `scripts/export_web_evidence.py captures --write` regenerates the
   captures in pure Python through the split and feedback generators. It
   writes the file only when every capture hash matches three committed
   anchors: the test-freeze gate receipt, the scored specifications and the
   held-out freeze digests. The site therefore names frames without running
   tshark or shipping packet bytes. Predicate traces for the Reel pool come
   later, in the same directory.
3. **`scripts/export_web_data.py`.** It uses the standard library only, starts
   no process, opens no socket and reads no clock, environment variable or git
   state. Its output in `apps/web/data/` is ignored by git and rebuilt for
   every build.

The site is a Next static export (`output: 'export'`, `trailingSlash`). Its
URL prefix is resolved in one place, `apps/web/scripts/base_path.mjs`: it
reads `PAGES_BASE_PATH` and defaults to `/DFilterForge`, the path of a GitHub
project page. The build, `scripts/serve.mjs` and the Playwright config all
import it. An empty value builds and serves the site at the domain root, as a
host such as Cloudflare Pages needs, with no code change. Hosting is still
undecided.

The site is built in Docker. `apps/web/Dockerfile` has six stages: `export`,
`data`, `deps`, `build`, `out` and `site`. The exporter and `next build` each
run under `RUN --network=none`. CI's web job builds through the composite
action `.github/actions/web-site`, which the Pages workflow is meant to reuse.
The Compose `web` service serves the `site` stage on 127.0.0.1 only.

### Inputs

The exporter reads only these paths:
- under `docs/results/`, `docs/decisions/evidence/` and
  `docs/ablations/evidence/`;
- exactly `src/dfilterforge/held_out_freeze.json`;
- `docs/decisions/model-bakeoff.md`, only to check that every registered test
  run is named in it.

Any other path is refused, and so is a path with a dot segment, a file that
is not regular, or a symbolic link at any component, even a directory link
that stays inside the repository: such a link would publish another
folder's bytes under an allowed path. Both test resolvers apply the same
roots and the same link rule to every source path. Every read uses UTF-8 and is capped at
32 MiB, the run store's ceiling. NaN, Infinity and duplicate keys are refused.

The shown runs come from files, never from a hand list:
- **Dev.** The runs of the lexicographically last
  `docs/decisions/evidence/bakeoff/ranking-*.json`, in this order: the anchor,
  then the small, mid and frontier slots, then rank 1 to 3 within a slot.
  Today that is ten passes.
- **Test.** The runs that `docs/decisions/evidence/test-runs.json` registers.
  They are shown only once every one of them has a scored `summary.json` or is
  listed in that file as not run. That file does not exist yet, so the test
  phase is off.

### Sourced values

Every value a page renders arrives as `{"t": text, "src": op}` for a string,
or `{"v": value, "src": op}` for a number, a boolean or an array of integers.
`op` names committed bytes and the reading that yields the value:

| Op | Value |
| --- | --- |
| `["ptr", path, pointer]` | an RFC 6901 pointer into a JSON file |
| `["row", path, {key: text}, pointer]` | the one JSONL row whose keys equal the given strings, then a pointer into it |
| `["count", path, pointer or null, {key: [text]}]` | the JSONL rows, or the array items at the pointer, whose every key holds one of the listed strings |
| `["len", path, pointer]` | the length of the array at the pointer |
| `["sum", [op]]` | the sum of integer operands |
| `["sha256", path]` | the SHA-256 of the file's bytes |
| `["input", path, item_id, pointer]` | the `INPUT_JSON` object of a prepared prompt's user message, then a pointer into it |

The exporter gets each value by resolving its own `src`, so a value cannot
drift from its source. The site never divides. Dev runs get counts only, per
pass and summed over C1 to C4, with no interval and no comparison: the
model bake-off note's "Not an effect" rule. Rates, intervals and comparisons
can only appear as `ptr` pointers into a test run's `summary.json`.

### Outputs

The output files use the schema family `web-*/1.0`. Each is written with
sorted keys, compact separators, `ensure_ascii=False` and one trailing LF:
- `site.json`: the source commit, every input with its SHA-256, the phase
  flags and the run slugs.
- `routes.json`: the parameters of every dynamic route.
- `board.json`: the dev selection rows and a `test` block, which is null until
  the test phase.
- `methodology.json`.
- `reel.json`: the Disproof Reel projected by rule `reel-v1`.
- `cases/<case_id>.json`.
- `receipts/<run_slug>/<condition>/<item_id>.json`, one per executed answer.

The run slug is the run id with each dot replaced by an underscore. Run ids
cannot contain an underscore, so the mapping is injective, and no route
segment ends in a dotted name that Next would treat as a file.

Model output is untrusted. Raw text is capped at 4 KiB on a character
boundary and rendered only as a React text node. The cap is the contract's,
never the page's: `lib/data.ts`, the consistency test and the Python source
check accept `cap` only as 4,096 and only on a completion's `response_text`,
and require it there. `lib/fmt.ts` passes every
string through `lib/visible.ts`, which shows C0 and C1 controls, bidi and
zero-width characters, and every other format, default-ignorable or
private-use code point (Unicode tag characters, invisible operators,
variation selectors) as visible marks. Unassigned code points are left as
they are: a browser draws them as a missing-glyph box. Node 20.20.2 and
Node 24.21.0 both carry Unicode 17.0 and mark the same 141,674 code points.
`react/no-danger` is an error on every
component, not only DOM elements, and a `no-restricted-syntax` rule bans the
prop's name wherever else it could reach React: a spread object,
`createElement` props, a member or a string key. Both apply everywhere, tests
included, and `tests/lint-rules.spec.ts` proves each form fails.

### What fails

The exporter exits 1 when the committed files break the contract. The cases
are:
- an executed outcome row without exactly one receipt, or a receipt without a
  row;
- a typed ready answer without an intent file, or the reverse;
- a case without exactly two items;
- ready segment counts that do not add up;
- a strong-exact count that differs from the ranking's `strong_exact_ready`;
- a ready count over the ready items that differs from the summary's case
  mean by more than 5e-7;
- a bad run id, or a slug collision;
- receipt frame sets that disagree with their specification, or
  specifications that differ between runs;
- a registered test run that `model-bakeoff.md` does not name.

It exits 2 when an input cannot be read, a flag is invalid or the output
directory is not empty.

On the web side, `lib/data.ts` checks every document's schema id, closed key
sets and source ops before a page renders.
- **Sourced components.** `<Num>` renders a number as a link to the GitHub
  blob of its source file at the source commit, with `data-src`, `data-v` and
  `data-fmt`. `<Str>` renders a string the same way, without the link.
  `<Term>` renders a reviewed name that holds a digit; the list in
  `lib/terms.ts` is `IPv4` and `SHA-256`.
- **The digit lint.** ESLint fails on a digit in JSX text, as a literal JSX
  child or in a text-bearing attribute, and in a page title or description.
  It also fails on `toFixed`, `toPrecision`, `toExponential`, the
  `toLocale*` methods and `Intl` outside `lib/fmt.ts`.
  `tests/lint-rules.spec.ts` proves each of these selectors fires.
- **The consistency test.** `tests/consistency.spec.ts` visits every built
  page. A TypeScript resolver written apart from the exporter re-derives every
  `[data-src]` value from the raw committed files, never from
  `apps/web/data`. The test fails on any of these:
  - a value or its formatted text that differs;
  - a digit outside a sourced value, a script, a style or a `<Term>`, in the
    text, a swept attribute or `document.title`;
  - a page without values that is not on the closed data-free list;
  - a server-rendered HTML file whose `data-src` set differs from the
    hydrated page's;
  - receipt and case routes that differ from the resolver's executed rows.
- **The Python side.** `tests/test_export_web_data.py` holds a second
  independent resolver and an AST allowlist that keeps the exporter on the
  standard library.

### CI

The python job runs four steps after the re-score loop, which leaves the
frozen-prompt guard and the pylint line untouched:
1. pylint on the two web scripts;
2. `export_web_evidence.py check`, with `docs/` mounted read-only;
3. the two scripts' tests, with `docs/` mounted, so the committed-tree cases
   run instead of skipping;
4. two exports of the committed tree, compared with `diff -r`.

Each step that needs `docs/` starts with `test -d`, so a missing mount fails
the step.

The web job runs the composite action. It builds `out/` through the
Dockerfile, then runs typecheck, lint and the Playwright suite on the runner
against that build. Last, it starts the Compose `site` service and expects a
200 on loopback.

## Before and after

Before is 86cd624, the base of this branch. After is 07d91ca, the commit
that wired CI.

| Case | Before | After |
| --- | --- | --- |
| Where page values come from | `app/_data/recorded.ts`, which says it is hand-written illustrative data | `apps/web/data`, exported from committed files, every value with its source op |
| Methodology page | Typed prose: "36-specification" and "No language model has been evaluated", false since the ten dev passes | 138 sourced values (40 linked numbers, 98 strings) and a link to `docs/protocol.md` at the source commit |
| A digit typed into page markup | Builds and ships | Fails `pnpm web:lint`; the same number through a constant fails the consistency sweep |
| A rendered value that differs from the committed file | Not checked | Fails the consistency test |
| Routes | `/` redirects to `/evaluate` (the mock); `/methodology` | `/` (a placeholder until the Reel), `/methodology/`, a digit-free 404 |
| Build | `output: 'standalone'` built on the runner; the Docker image ran the Next server | Static export built in Docker from the exported data; `serve.mjs` serves it under the base path |
| Compose `web` port | `3000:3000`, every interface | `127.0.0.1:3000:3000` |
| Web end-to-end tests | 2 | 57 (13 smoke, 11 formatter, 27 lint-rule, 6 consistency) |
| CI checks of web data | None | The four python steps above and the Docker-built site under test |

## Measured

The dev data is exported at 07d91ca: 676 files, 9,546,808 bytes, with 52,934
sourced values (35,570 strings, 17,364 numbers, booleans or integer arrays).
The test resolver re-derives every one of them on the committed tree.

| Output | Design estimate | Measured |
| --- | --- | --- |
| `site.json` | about 200 KB | 208,972 bytes (1,280 inputs) |
| `routes.json` | about 40 KB | 46,425 bytes |
| `board.json` | 20-40 KB | 26,979 bytes |
| `methodology.json` | 10-20 KB | 16,212 bytes |
| `reel.json` | under 25 KB | 18,263 bytes |
| `cases/`, 20 files | 15-20 KB each | 33,345 to 64,266 bytes, median 41,809; 940,095 in all |
| `receipts/`, 651 files | 3-5 KB each | 9,582 to 74,320 bytes, median 10,738; 8,289,862 in all |

Case and receipt files are about two to three times the estimate, mostly
because each sourced node carries its whole source op, path included. Those
ops, with their `"src":` keys, are 61.6 percent of the receipt bytes
(5,106,294) and 63.9 percent of the case bytes (600,363).

`captures.json`: 8 probes, 480 frames, 51,073 bytes.

The static export today:
- 29 files, 923,060 bytes, from the Docker (Linux) build: 5 HTML, 11 JS, 12
  TXT and 1 CSS.
- 3 routes: `/`, `/methodology/` and `/_not-found`. The 5 HTML files are
  `index.html`, `methodology/index.html` (107,895 bytes), `404.html`,
  `404/index.html` and `_not-found/index.html`.
- The 651 receipt and 20 case documents are exported but not rendered yet;
  those pages come next.

Timings are wall-clock on the Windows 11 host with Docker Desktop 29.7.2,
with other sessions using Docker at the same time:

| Step | Time |
| --- | --- |
| Docker `--target out`, no layer cache | 21.0 s: export 1.1 s, `pnpm install` 12.1 s, `next build` 4.8 s |
| Docker `--target out`, cached | 1.8 s |
| Host `pnpm web:build` | 8.2 s: compile 1.8 s, static generation 0.5 s |
| Host `pnpm web:typecheck` / `pnpm web:lint` | 2.4 s / 5.0 s |
| Playwright, 57 tests on two workers | 10.5 s on the Docker build, 9.8 s on the host build; about 0.7 to 0.9 s per route for the consistency test |
| CI pylint step for the two scripts | 4.2 s |
| CI evidence check | 2.2 s |
| CI exporter and evidence tests, 124 with `docs/` | 18.3 s (pytest 17.3 s) |
| CI export twice and `diff -r` | 16.0 s; peak `/tmp` 21 MB of the 128 MB tmpfs |
| Full CI python mirror at 07d91ca | 32 min 46 s (pytest 822 s) |

The `site` image is 201 MB.

On the committed dev data, rule `reel-v1` picks
[`dev-qwen3-32b-2026-09-26` C4 `mei-0015`](../results/dev-qwen3-32b-2026-09-26/scored/receipts/C4/mei-0015.json):
- the request is "Show DNS AAAA questions or DNS NXDOMAIN messages.";
- 27 C4 silent-wrong candidates in the pool;
- frames 17, 3 and 9 are reference-only on semantic-11, -17 and -23;
- the highlight is semantic-17, frame 3, `udp-aaaa`;
- the headline counts M = 284 and N = 65.

The pool is the anchor plus the ranking's provisional winners, because
`test-runs.json` does not exist yet.

## Commands

From the repository root in Git Bash. `MSYS_NO_PATHCONV=1` keeps Docker's
paths as written. Set it per command: exported, it broke the `pnpm` shim on
the development host.

```text
export SOURCE_COMMIT=$(git rev-parse HEAD)
MSYS_NO_PATHCONV=1 docker build -f apps/web/Dockerfile --target out --build-arg SOURCE_COMMIT=$SOURCE_COMMIT --output type=local,dest=apps/web/out .
MSYS_NO_PATHCONV=1 docker build -f apps/web/Dockerfile --target data --build-arg SOURCE_COMMIT=$SOURCE_COMMIT --output type=local,dest=apps/web/data .
docker compose --profile web-local up --build
pnpm --filter @dfilterforge/web test:e2e
```

- The first command builds the site. The second exports the data only, which
  `next dev` and a host `pnpm web:build` need.
- Compose serves the site at `http://127.0.0.1:3000/DFilterForge/`.
- The Playwright suite runs against `apps/web/out`.
- `--build-arg PAGES_BASE_PATH=` with an empty value builds for the domain
  root. In Git Bash, exempt the variable from path conversion
  (`MSYS2_ENV_CONV_EXCL=PAGES_BASE_PATH`) before the host tests read it.

## Limits

- Only the methodology page renders values today. The board, case and receipt
  pages and the Reel are the next two pull requests, and the home page is a
  digit-free placeholder until the Reel lands.
- Rule `reel-v1` is applied but not yet registered.
  `docs/decisions/disproof-reel.md` and `test-runs.json` must be committed
  before the first test request, or the test-phase pick cannot be shown to
  predate the data.
- No predicate trace is committed yet. The Reel says "not traced" until the
  Reel pool's C4 silent-wrong answers are traced offline.
- Base images are pinned by tag, not by digest.
- `RUN --network=none` was verified only on Docker Desktop 29.7.2: the step
  saw only `lo`, and a connect failed with `ENETUNREACH`. The CI workflow and
  the composite action have not run on GitHub yet; they pass actionlint
  1.7.7, and each step was run locally.
- The consistency test does not sweep CSS `content:` or `<head>` meta.
- Next 16.3.4 on Windows writes nested segment-prefetch files into
  subdirectories, where a Linux build writes flat names. The smoke test
  exempts exactly that case, so CI and Pages use the Linux build.
