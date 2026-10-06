# Web site: a static export from committed files

The site shows recorded results only and never calls a model. This note
records how a value gets from a committed file onto a page, what fails when
that path is bypassed, and the sizes and timings measured on the committed
data: first on the dev passes alone, now in the test phase.

## Question

How can a reader trace every number on a page to a committed receipt, and how
can CI make a hand-typed or stale number fail?

## Decision

Data moves one way, through three layers:

1. **Committed results.** The scored runs under `docs/results/`, the bake-off
   ranking, the test-run registry
   [`evidence/test-runs.json`](evidence/test-runs.json) and the bake-off
   ruling it names, the test-freeze gate receipt, the shortcut-policy
   evidence of ablation 006 and `src/dfilterforge/held_out_freeze.json`. The
   registry's note, [`test-runs.md`](test-runs.md), is read only to check
   that its Runs table lists the same rows.
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
   tshark or shipping packet bytes.

   Beside it, [`packets.json`](evidence/web/packets.json)
   (`capture-packets/1.0`) holds each frame's packet-list columns as the
   pinned tshark 4.6.8 prints them with name resolution off: number,
   relative time, Source, Destination, Protocol, length and Info. It also
   holds each probe's client address, the address seen in most frames
   (ties to the lowest), and each frame's direction to it: `out`, `in` or
   `other`. `export_web_evidence.py packets --write` runs tshark on the
   same regenerated captures through `dfilterforge.packet_list`. Under
   [`traces/`](evidence/web/traces/) sits the predicate trace of the Reel's
   pick, `web-trace/1.0`. `export_web_evidence.py trace` writes it by
   replaying the committed answer with the scorer's `replay_live`. It
   records the receipt's path and SHA-256, and for each scored probe the
   frames where the answer and the labels disagree, with each leaf of
   both filters and the frames among those that tshark matched it on.
   `check` rebuilds both files and compares them byte for byte, so it runs
   in the test image, which has tshark and the frozen catalog.
3. **`scripts/export_web_data.py`.** It uses the standard library only, starts
   no process, opens no socket and reads no clock, environment variable or git
   state. Its output in `apps/web/data/` is ignored by git and rebuilt for
   every build.

The site is a Next static export (`output: 'export'`, `trailingSlash`). Its
URL prefix is resolved in one place, `apps/web/scripts/base_path.mjs`: it
reads `PAGES_BASE_PATH` and defaults to `/DFilterForge`, the path of a GitHub
project page. The build, `scripts/serve.mjs` and the Playwright config all
import it. An empty value builds and serves the site at the domain root, with
no code change.

The host is GitHub Pages, at https://weiguang-2099.github.io/DFilterForge/.
CI deploys it with `actions/deploy-pages` on each push to `main`. The owner
decided this on 2026-10-06, with the ruling that the repository goes public;
it replaces the Cloudflare Pages decision of 2026-10-01. GitHub Pages is
free for a public repository and needs no secret. It serves the site under
`/DFilterForge`, the default prefix that local Compose, the CI loopback
probe and the tests already use, so the deployed build is the one CI tests.
Its 1 GB site limit and lack of a file-count cap leave room for the receipt
pages that come later. The Deploy section below has the job and the owner's
setup.

The default itself is written in four places, because three files cannot
import the module:
- `DEFAULT_BASE_PATH` in `apps/web/scripts/base_path.mjs`;
- `ARG PAGES_BASE_PATH` in `apps/web/Dockerfile`. A Docker build always sets
  the variable from it, so the module's own default never applies there;
- the `base-path` input default of `.github/actions/web-site/action.yml`,
  which the build and the Playwright step both receive;
- the loopback probe URL of the compose smoke in `.github/workflows/ci.yml`.

`apps/web/tests/base-path.spec.ts` fails when any of the last three differs
from the module's default, so a rename cannot leave CI green on the old
prefix. The `pages` job's guard and live probe write the prefix again, as
the path GitHub Pages serves this repository under, so a renamed default
fails that guard on the push to `main`.

The site is built in Docker. `apps/web/Dockerfile` has six stages: `export`,
`data`, `deps`, `build`, `out` and `site`. The exporter and `next build` each
run under `RUN --network=none`. CI's web job builds through the composite
action `.github/actions/web-site`, and the `pages` job reuses it.
The Compose `web` service serves the `site` stage on 127.0.0.1 only.

### Inputs

The exporter reads only these paths:
- under `docs/results/`, `docs/decisions/evidence/` and
  `docs/ablations/evidence/`;
- exactly `src/dfilterforge/held_out_freeze.json`;
- exactly `docs/decisions/test-runs.md`, the note the registry's `note`
  field names. It is read only to check that the rows of its Runs table are
  the registry's rows, numbered from 1, in order. A run id named only in the
  note's prose registers nothing. No source op can point into the note:
  the exporter and both test resolvers refuse its path as a source like any
  other path outside the roots.

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
- **Test.** The `published` rows of
  [`evidence/test-runs.json`](evidence/test-runs.json) (schema
  `test-runs/1.0`), in role order: `aa_pass_a`, `aa_pass_b`, `winner_small`,
  `fallback_small`, `winner_mid`, `fallback_mid`, `winner_frontier`,
  `fallback_frontier`. These are the registry's eight roles, kept verbatim.
  An outage re-run (`-r2`) keeps the role of the run it replaces, so a role
  may repeat, but at most one published row fills a slot. The rows are shown
  only once every row is final, which is how
  [`disproof-reel.md`](disproof-reel.md) ("Reading the rule against the
  registry") reads step 1 of rule `reel-v1`. All three conditions must hold:
  - no row is `registered`;
  - every `published` row's run has `scored/summary.json`;
  - every other row is `not_run`, or an `unused` conditional row that gives
    a reason or whose named run is not `not_run`.

  A published run with no summary yet keeps the phase off; that is not an
  error.
- **The Reel pool.** In the test phase it is the published `aa_pass_a` run,
  then for the small, mid and frontier slots the published `winner_<slot>`
  run, else the published `fallback_<slot>` run, an outage re-run included.
  A slot with neither is skipped, so the pool may be empty, and then there
  is no pick. Pass B is never pooled. In the dev phase it is the ranking's
  anchor, then each slot's `slots.<slot>.winner.run_id` from
  [`ruling-2026-10-01.json`](evidence/bakeoff/ruling-2026-10-01.json), the
  ruling the registry's `ruling` field names. The ruling's top-level
  `winners` holds model ids and is not read. Only with no `test-runs.json`
  does the dev pool fall back to the ranking's provisional winners.
- **Today.** The test phase has been on since the five baselines were
  published and scored ([`locked-test-v1.md`](../results/locked-test-v1.md)).
  Of the registry's 16 rows, rows 1 to 5 are `published` and each run has
  `scored/summary.json`; the other 11 are `unused`. So 15 runs are shown:
  the ten dev passes, then the five test passes in role order.

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
| `["json", path, pointer, inner]` | the JSON text of the string at the pointer, parsed, then the pointer `inner` into it |

The exporter gets each value by resolving its own `src`, so a value cannot
drift from its source. The site never divides. Dev runs get counts only, per
pass and summed over C1 to C4, with no interval and no comparison: the
model bake-off note's "Not an effect" rule. Every other number has one
allowed source:
- a test rate, interval or comparison: a `ptr` pointer into the test run's
  `scored/summary.json`;
- the A/A reading: the pair report
  [`evidence/aa-test-qwen3-32b-2026-09-26.json`](evidence/aa-test-qwen3-32b-2026-09-26.json);
- a repair number: a pass's `repair/summary.json` or
  `docs/results/repair-pool/test.json`, the two sources
  [`disproof-reel.md`](disproof-reel.md) ("Repair trajectory") allows;
- never an arm run's (`-res`, `-bare` or `-cx`) `scored/summary.json`. The
  [repair note](repair-round.md) calls that file a scoring record, never a
  reported number. The Reel's repair turn reads the pass's
  `repair/plan.json` and `repair/summary.json`, and of the `-cx` arm run only
  its completion, outcome row, receipt and specification.

### Outputs

The output files use the schema family `web-*/1.0`. Each is written with
sorted keys, compact separators, `ensure_ascii=False` and one trailing LF:
- `site.json`: the source commit, every input with its SHA-256, the phase
  flags and the run slugs. `phase.repair` is true when `board.json` holds
  the test repair round.
- `routes.json`: the parameters of every dynamic route.
- `board.json`: the dev selection rows, `test_registered`, and a `test`
  block. The block is null until the test phase, and it is set now:
  - `rows` are the Reel's test pool, in pool order;
  - `rerun` is pass B's row, null when pass B is not published. Pass B
    serves only as pass A's rerun
    ([`locked-test-v1.md`](../results/locked-test-v1.md)), so it is never a
    row; it stays a shown run with receipts and cases;
  - `not_run` lists every `not_run` row in role order, as its role with
    sourced `run_id` and `reason` pointers into the registry's
    `/runs/<i>`. An `unused` row is left out, because its condition never
    occurred. Today the list is empty;
  - `repair` is null until `docs/results/repair-pool/test.json` exists.
    Then it holds the pool's arms (repair@1 with its interval, repaired
    and triggered answers), its bootstrap settings and its three
    comparisons by case, then each pool pass's arms, comparisons and any
    arm the gate stopped, from its `repair/summary.json`, in pool order. A
    pool file whose split is not `test` or that pools other passes than
    the test pool, or a pool pass without a scored round, stops the export
    (`repair_inconsistent`). The dev round is never read: it was a
    pipeline check (protocol, Repair);
  - `aa` stays null (Limits).
- `methodology.json`: the prompt conditions, `top_k`, the bootstrap block
  and the scoring environment from the dev anchor, in both phases; the
  probes and witnesses from `captures.json`, the mutant counts and
  categories from the test-freeze gate receipt, the shortcut audit from
  ablation 006's evidence and the admitted prepares and their count (a
  `len` op) from `held_out_freeze.json`, none of them a run; and the `not_measured`
  statuses from the run its repair line cites (What fails), each with a
  `split` node that points at that run's summary `/split` and labels the
  line. Once that run's `repair/summary.json` exists, `repair_at_1` is left
  out of `not_measured`, and `repair` holds the round's line: split, model,
  triggered items, each arm's repaired count and any arm the gate stopped,
  all pointers into that summary. Before, `repair` is null.
- `reel.json`: the Disproof Reel projected by rule `reel-v1`, step 5
  included. `repair` is null with no pick. Before the pick's pass has a
  scored round it has `reason` `no_round` and a null `turn`; after, a null
  `reason` and the pick's counterexample turn: the card from the pass's
  plan, and for a frames card `card_frames`, each field's value a `json`
  op into the card's text, one node per string of a list such as
  `tcp.flags`; then the arm run named by the round, and that run's
  outcome, filter, capped raw answer and frame strips. Each of the pick's own strips also
  lists every frame of its capture, which the home page's ladder and
  cursor read: number, kind and name from `captures.json`, and time,
  source, destination, protocol, length, Info and direction from
  `packets.json`, with the probe's client address. Receipts and cases list
  only the frames that disagree. `trace` holds, per probe, the traced
  frames and each filter and request leaf with the frames it matched, all
  pointers into the committed trace; `pick.joins` holds the root operator
  of each side's IR.
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
- a test-run registry that breaks its contract, checked in this order:
  - `note_mismatch`: a `note` other than `docs/decisions/test-runs.md`;
  - for each row in turn: a role outside the eight (`role_invalid`), a
    malformed run id (`run_id_invalid`), a run id without the `test-`
    prefix (`split_mismatch`), a repeated run id (`run_repeated`), a status
    other than `registered`, `unused`, `published` or `not_run`
    (`status_invalid`), or a `not_run` row with no reason
    (`not_run_invalid`);
  - `condition_invalid`: a trigger without a named run or the reverse, a
    trigger other than `gate_stop` or `outage`, a named run that is not
    another row, a planned row marked `unused`, or a conditional row that
    is not `unused` while the run it names is not `not_run`;
  - `role_missing`: planned rows other than `aa_pass_a`, `aa_pass_b`,
    `winner_small`, `winner_mid` and `winner_frontier`, in that order;
  - `not_run_scored`: a row that is not `published` whose
    `docs/results/<run id>/` holds `run_manifest.json` or
    `scored/summary.json`;
  - `role_invalid`: two `published` rows that fill one slot;
  - `run_unregistered`: a Runs table in `test-runs.md` whose rows are not
    the registry's rows, numbered from 1, in order;
  - a ruling winner that is no dev run (`split_mismatch`) or that the
    ranking does not show (`pool_unshown`).

  The trigger's role rules (a gate stop sends the named winner's fallback,
  an outage re-run keeps the named run's role) are left to CI's registry
  tests. `tests/support/resolve.ts` refuses the same registry, note and
  ruling shapes, and `tests/registry.spec.ts` checks those refusals against
  it case by case;
- a scored repair round that names another pass (`repair_inconsistent`):
  a `repair/summary.json` whose `base_run` or `split` is not that of the
  pass whose directory holds it, or a shown turn whose item the pass's
  `repair/plan.json` or the arm run's completions lack. The rounds read are
  the Reel pick's pass's, for step 5, the frontier slot's test pass's when
  the pick's pass has none (below), and that of the run the methodology
  page cites. The page's repair line describes the repair round the site
  reports, so the cited run depends on the phase:
  - in the test phase, the first test pool run: pass A whenever pass A is
    published, else the published winner or fallback of the first of the
    small, mid and frontier slots that has one, and no run when the pool is
    empty, in which case the page lists no status and no round;
  - in the dev phase, with no registry or before every registry row is
    final, the dev anchor.

  So in the test phase the dev anchor's `repair/summary.json`, the dev
  repair round, is not read. `tests/support/resolve.ts` refuses the same
  summaries in `repairRound()`; `repairStatusSummary()` names the cited
  run's summary and `methodologyRound()` its round, and the consistency
  test checks that the built methodology page takes its statuses and its
  repair line from those files;
- a `packets.json` row that names another capture than `captures.json`,
  lists other frames or gives a direction outside `out`, `in` and `other`
  (`packets_stale`);
- a trace that names other receipt bytes, or whose probes or traced frames
  are not the receipt's probes and disagreeing frames (`trace_stale`);
- a pick without a counterexample turn in its pass's scored round
  (`repair_fallback_unbuilt`): the round exists, but the pick is not C4, is
  not one of the round's `items`, or its counterexample arm is missing from
  `arms` or listed in `arms_not_run`. The same code stops a pick whose pass
  has no scored round while, in the test phase, the frontier slot's test
  pass (the pool's `winner_frontier` run, else its `fallback_frontier` run)
  has one. With neither round, `repair` is `no_round`; the dev phase reads
  no frontier round. In both stopped cases `disproof-reel.md` shows the
  frontier slot's repair trajectory instead. That fallback is not built and
  no committed data needs it, so the export stops rather than drop the
  trajectory. `reelRepair()` in `tests/support/resolve.ts` refuses the same
  picks.

It exits 2 when an input cannot be read, a flag is invalid or the output
directory is not empty. That includes a registry whose schema tag is not
`test-runs/1.0`, and a ruling whose schema tag is not `bakeoff-ruling/1.0`
or that has a slot without a winner run id (`schema_invalid`), and a
ruling path outside the allowed roots (`path_refused`).

On the web side, `lib/data.ts` checks every document's schema id, closed key
sets and source ops before a page renders.
- **Sourced components.** `<Num>` renders a number as a link to the GitHub
  blob of its source file at the source commit, with `data-src`, `data-v` and
  `data-fmt`. It accepts only the kinds that format a number, a boolean or
  a list of integers (`int`, `num`, `bool`, `ints`, `rate`, `runtime`,
  `verdict`); the string-only kinds `text`, `unmeasured`, `split`,
  `outcome`, `frame_kind`, `join` and `digest` are excluded from its `kind`
  prop, and
  `tests/fmt.spec.ts` fails typecheck
  when a kind added to `lib/fmt.ts` is neither excluded there nor listed
  with a sample value in the spec. `rate` shows three decimals and
  `runtime` one; both round the committed decimal digits by string
  arithmetic, a value exactly halfway away from zero, as
  [`locked-test-v1.md`](../results/locked-test-v1.md) rounds, so 0.6375
  shows as 0.638 where the binary float would give 0.637.
  `<Str>` renders a string the same way, without the link.
  `<Digest>` renders a SHA-256 digest in hex as its first twelve digits
  (`data-fmt="digest"`), as a short git revision is shown, linked to its
  file, with the whole digest in `data-v` and in the `title`. Every page
  shows every digest this way; a replay command keeps its revision
  exact.
  `<Outcome>` renders a scored outcome code as the protocol's words, with
  `data-fmt="outcome"`: `silent_wrong` reads "silent-wrong", and a code the
  table does not list fails the build. `<Word>` does the same for two more
  codes: a frame's kind in `captures.json` (`frame_kind`: "recipe" or
  "witness") and an IR's root operator (`join`: `all` reads "every
  leaf"). `<Num link={false}>` leaves out the link where numbers stand
  close, as on the ladder's axis.
  `<Term>` renders a reviewed name that holds a digit; the list in
  `lib/terms.ts` is `IPv4`, `SHA-256` and `repair@1`. `verdict` shows a
  comparison's `inconclusive` flag as "inconclusive" or "conclusive", the
  words of `locked-test-v1.md`; the consistency test fails the flag shown
  any other way and the verdict words on any other value. `<Split>`
  renders a run's split as the word that names its round, with
  `data-fmt="split"`: `test` reads "Test" and `dev` reads "Dev", and any
  other split fails the build.
- **Not measured yet.** A scored summary's `not_measured` status, such as
  `repair_at_1`, is never shown as written. The scorer writes `not_run` for
  a measurement no round has made, and `docs/protocol.md` keeps "not run"
  for a run ruled not run. `<Unmeasured>` shows it as fixed words with
  `data-fmt="unmeasured"`: `not_run` reads "not measured yet", the heading
  the [repair note](repair-round.md) gives what no round has measured, and
  any other status fails the build.
  The consistency test fails a `not_measured` value shown with any other
  kind, and the unmeasured kind on any other value. The methodology page
  uses it now; a page in the next pull requests that shows the Reel's
  `receipt_panel.repair` must use it too. The methodology page labels each
  status with `<Split>` over the cited summary's `/split`, "Test repair
  round" or "Dev repair round", so that once the dev round is merged
  beside the test round the line still says which round it describes. With
  an empty test pool it lists no status and no label. Once the cited run's
  round is scored the page drops the "Not measured yet" section, which has
  no other status today, and shows a "Repair round" section: the round's
  split through `<Split>`, its model, its triggered items and each arm's
  repaired count, all from that round's `repair/summary.json`.
- **The digit lint.** ESLint fails on a digit in JSX text, as a literal JSX
  child or in a text-bearing attribute, and in a page title or description.
  A digit here is any Unicode number character (`\p{N}`): ASCII, fullwidth
  or Arabic-Indic digits, superscripts and Roman numerals. A list's `start`
  is a text-bearing attribute, since the list shows it as its first marker.
  It also fails on `toFixed`, `toPrecision`, `toExponential`, the
  `toLocale*` methods and `Intl` outside `lib/fmt.ts`.
  `tests/lint-rules.spec.ts` proves each of these selectors fires.
- **The consistency test.** `tests/consistency.spec.ts` visits every built
  page. A TypeScript resolver written apart from the exporter re-derives every
  `[data-src]` value from the raw committed files, never from
  `apps/web/data`. The test fails on any of these:
  - a value or its formatted text that differs;
  - a `not_measured` status shown as anything but fixed words;
  - a SHA-256 digest shown other than as a digest, or a digest whose text
    is not the first twelve digits of the committed value or whose `title`
    does not hold the whole of it, and the digest kind on any other value;
  - a Unicode number character outside a sourced value, a script, a style
    or a `<Term>`, in the text, a swept attribute (`start` included) or
    `document.title`;
  - a page without values that is not on the closed data-free list;
  - a server-rendered HTML file whose `data-src` set differs from the
    hydrated page's.

  The first four checks run twice per route: on the hydrated page, and in
  a browser context with JavaScript disabled, which sees the HTML as the
  server rendered it. A number that only the server HTML shows, and that
  hydration removes, reaches every visitor without JavaScript, every crawler
  and every first paint; a planted page proves the second pass catches it.
  Playwright 1.62.1 evaluates in a context with JavaScript disabled.
  On `/` it also re-derives, for every frame of every probe, what the
  Reel says in fixed words or draws, which no value check sees: each
  ladder row's direction from `packets.json`; the readout's request and
  filter words and its agree or disagree from the pick's receipt; and each
  leaf's true, false or dash from the committed trace.
  Separately, the test fails when the receipt and case routes differ from
  the resolver's executed rows, and when the resolver's own reading of the
  registry and of rule `reel-v1` gives other shown runs, another Reel pool,
  another pick or another step 5 choice than the ones it pins for the
  committed tree, and when the built methodology page takes its
  `not_measured` statuses from another summary than the one
  `repairStatusSummary()` names, shows one once `methodologyRound()` names
  a scored round, or reads any `repair/summary.json` value from another
  round. The value checks alone cannot tell: every summary still says
  `not_run` after a round. It
  also fails when a "Not measured yet" label is not the split's word and
  "repair round", or when its `<Split>` does not point at that summary's
  `/split`: a split from another run's summary or from a probe capture,
  or a typed label, passes the value checks. `repairStatusSplit()` reads
  that split and refuses one that differs from the cited run id's, as the
  exporter does (`split_mismatch`); the test pins `test` for the committed
  tree.
- **The Python side.** `tests/test_export_web_data.py` holds a second
  independent resolver and an AST allowlist that keeps the exporter on the
  standard library. Its committed-tree tests export the committed files and
  pin the test-phase Reel pick, its step 5 turn and the methodology's
  repair line, and
  `test_the_committed_dev_pool_picks_the_registered_dev_reel` repeats the
  dev check that `disproof-reel.md` recorded (Measured).

### CI

The python job runs four steps after the re-score loop and the repair plan
and pool checks, which leaves the frozen-prompt guard and the pylint line
untouched:
1. pylint on the two web scripts;
2. `export_web_evidence.py check`, with `docs/` mounted read-only. It
   regenerates `captures.json` in pure Python, and `packets.json` and
   every committed trace with the image's tshark;
3. the two scripts' tests, with `docs/` mounted, so the committed-tree cases
   run instead of skipping;
4. two exports of the committed tree, compared with `diff -r`.

Each step that needs `docs/` starts with `test -d`, so a missing mount fails
the step.

The web job runs the composite action. It builds `out/` through the
Dockerfile, then runs typecheck, lint and the Playwright suite on the runner
against that build. Last, it starts the Compose `site` service and expects a
200 on loopback.

### Deploy

The `pages` job in `ci.yml` runs only on a push to `main` of this
repository, `WeiGuang-2099/DFilterForge`, after the python, web and
containers jobs pass; a fork's push to its own `main` skips it. It holds
`pages: write` and `id-token: write`, deploys to the `github-pages`
environment, whose URL is the deploy step's `page_url`, and runs in the
concurrency group `pages`, which keeps two deploys from overlapping and
cancels none; a newer push to `main` still cancels the whole older run
through the workflow's group:
1. It runs the composite action with the default base path: it builds
   `out/` under `/DFilterForge` and runs typecheck, lint and the Playwright
   suite against that build, the bytes it then ships.
2. It refuses an `out/index.html` that does not load
   `/DFilterForge/_next/static/`, so a build for another prefix cannot ship.
3. `actions/configure-pages@v6`, `actions/upload-pages-artifact@v5` (path
   `apps/web/out`) and `actions/deploy-pages@v5` publish it. The upload
   leaves out dotfiles; the export has none.
4. It fetches `https://weiguang-2099.github.io/DFilterForge/methodology/`
   until the page links its sources at the pushed commit, for up to ten
   minutes, longer than the `max-age=600` GitHub Pages sends. Then it
   fetches one of the page's `/DFilterForge/_next/static/` assets.

On a87f777 the build has 29 files and 962,772 bytes. The step 2 guard
passes on it and fails on a build for the domain root. The upload's `tar`
command keeps all 29 files. Served by `scripts/serve.mjs`, the step 4 probe
passes when it expects a87f777 and, run with 1-second sleeps, fails after
its 20 attempts when it expects 1ec918c.

The owner sets up, once, before the merge that adds the job:
- a public repository: on the Free plan GitHub Pages serves only a public
  repository, and the site's source links point into it;
- Settings > Pages > Build and deployment > Source: GitHub Actions; without
  it `configure-pages` fails;
- after the first deploy, the repository's About > Website.

## Before and after

Before is 86cd624, the base of this branch. After is 07d91ca, the commit
that wired CI.

| Case | Before | After |
| --- | --- | --- |
| Where page values come from | `app/_data/recorded.ts`, which says it is hand-written illustrative data | `apps/web/data`, exported from committed files, every value with its source op |
| Methodology page | Typed prose: "36-specification" and "No language model has been evaluated", false since the ten dev passes | 138 sourced values (40 linked numbers, 98 strings) and a link to `docs/protocol.md` at the source commit |
| A number typed into page markup, in any script or as a list's `start` | Builds and ships | Fails `pnpm web:lint`; the same number through a constant fails the consistency sweep |
| A rendered value that differs from the committed file | Not checked | Fails the consistency test |
| Routes | `/` redirects to `/evaluate` (the mock); `/methodology` | `/` (a placeholder until the Reel), `/methodology/`, a digit-free 404 |
| Build | `output: 'standalone'` built on the runner; the Docker image ran the Next server | Static export built in Docker from the exported data; `serve.mjs` serves it under the base path |
| Compose `web` port | `3000:3000`, every interface | `127.0.0.1:3000:3000` |
| Web end-to-end tests | 2 | 57 (13 smoke, 11 formatter, 27 lint-rule, 6 consistency); 82 after the review fixes at a9f12d9 (13 smoke, 13 formatter, 41 lint-rule, 9 consistency, 3 resolver, 3 base-path); 142 at 69d237e, on the registered test runs (56 registry, 41 lint-rule, 14 formatter, 13 smoke, 11 consistency, 4 resolver, 3 base-path); 148 at d3ff716 (61 registry, 12 consistency, the rest unchanged); 152 at dfeaf11 (63 registry, 15 formatter, 13 consistency, the rest unchanged); 153 at 19dff88 (16 formatter, the rest unchanged); 160 at 7f4eb33 (61 registry, 41 lint-rule, 19 formatter, 15 consistency, 13 smoke, 4 Reel, 4 resolver, 3 base-path), 18.2 s on the Docker build; 164 at 54c056f (20 formatter, 7 Reel, the rest unchanged), 17.6 s on the Docker build (on `site-reel`); 168 at 0a1617c, with the board (61 registry, 41 lint-rule, 20 formatter, 19 consistency, 16 smoke, 4 Reel, 4 resolver, 3 base-path), 18.0 s on the Docker build (on `site-board`); 173 at 645e658, after `main` was merged in (61 registry, 41 lint-rule, 21 formatter, 19 consistency, 16 smoke, 8 Reel, 4 resolver, 3 base-path), 21.8 s on a host `next build`, with Docker Desktop not running |
| CI checks of web data | None | The four python steps above and the Docker-built site under test |

## Measured

Two exports are measured. The dev data was exported at 07d91ca, before this
branch had a test-run registry. The test phase is exported at 69d237e, the
code these figures describe. Of the commits after it, three change the
export or the site:
- At d3ff716 `methodology.json` takes its `not_measured` status from pass
  A's summary instead of the dev anchor's, which adds 1 byte. The export
  has the same 1,935 files in 27,410,977 bytes, `methodology.json` is
  16,213 bytes, and two host exports are byte-identical. The Docker static
  export has 29 files in 923,064 bytes, `methodology/index.html` 107,899 of
  them.
- At dfeaf11 each status also carries its run's `split` node, which adds
  105 bytes. The export has 1,935 files in 27,411,082 bytes,
  `methodology.json` is 16,318 bytes, two host exports are byte-identical,
  and only `methodology.json` differs from f66b1e4's export. The Docker
  static export has 29 files in 924,010 bytes, `methodology/index.html`
  108,305 of them, and the page renders 139 sourced values: the 138 listed
  below and the split.
- At b65fd84 on `test-repair-round` (2026-10-06), over the committed test
  repair rounds, `reel.json` gains step 5's turn and `methodology.json` the
  repair line. A host export with `--source-commit abc1234` has 1,935 files
  in 27,420,742 bytes; `reel.json` is 24,885 bytes and `methodology.json`
  18,933. The Docker static export has 29 files in 962,772 bytes,
  `methodology/index.html` 123,439 of them, and the page renders 158
  sourced values: 44 integers, 113 strings and 1 split, and no status
  shown as "not measured yet". Of the 19 values added since dfeaf11, 12 are
  the 12 test prepares d95483a admitted in `held_out_freeze.json`, and 7
  are the repair line: its 8 values beside its split, less the status it
  replaces.
- At 7f4eb33 on `site-reel` (2026-10-06), the pick's strips list every
  frame and the home page renders the Reel. Two exports in the test image
  are identical: 1,935 files in 27,479,337 bytes, `reel.json` 83,486 of
  them. The Docker static export has 33 files in 2,286,305 bytes (5 HTML,
  12 JS, 12 TXT, 2 CSS and the 2 committed fonts); `index.html` is 477,885
  bytes, 29,908 gzipped, and renders 487 sourced values: 397 strings, 82
  integers, 3 runtimes, 3 booleans and 2 outcomes. Most of them are the
  readout: every frame of the three probes, with its kind and name. The
  Docker `--target out` build took 16.3 s, export 2.8 s and `next build`
  5.4 s; the test image ran the 185 exporter and evidence tests in
  215.8 s.
- At 54c056f on `site-reel` (2026-10-06), the Reel draws the ladder. The
  new evidence is `packets.json`, 139,563 bytes for 8 probes and 480
  frames, and the pick's trace, 5,856 bytes. In the test image, `check`
  rebuilds them and `captures.json` in 7 s, and the 194 exporter,
  evidence and packet-list tests pass in 83.6 s. An export with a 40-hex
  source commit has 1,935 files in 27,623,230 bytes, `reel.json` 221,237
  of them, and two exports in the test image are identical. The Docker
  static export has 33 files in 5,514,918 bytes; `index.html` is
  1,762,572 bytes, 86,365 after `gzip -9`, and renders 2,138 sourced
  values: 1,243 strings, 693 integers, 185 frame kinds, 6 joins, 3
  runtimes, 3 integer lists, 3 booleans and 2 outcomes. Most are the
  readout's: each frame of the three probes has its number, kind, name
  and packet-list row in the HTML. The Docker `--target out` build took
  about 18 s, export 2.9 s and `next build` 6.7 s.

The other figures below were not measured again.

| Export | Files | Bytes | Receipts | Cases | Sourced values |
| --- | ---: | ---: | ---: | ---: | --- |
| Dev data at 07d91ca | 676 | 9,546,808 | 651 | 20 | 52,934: 35,570 strings and 17,364 numbers, booleans or integer arrays |
| Test phase at 69d237e | 1,935 | 27,410,976 | 1,854 | 76 | 150,084: 100,433 strings and 49,651 numbers, booleans or integer arrays |

The test resolver re-derives every sourced value of both exports on the
committed tree. At 69d237e, two host exports are byte-identical, and so are
two exports in the test image; the Docker `data` stage's output equals both.

| Output | Design estimate | Dev data at 07d91ca | Test phase at 69d237e |
| --- | --- | --- | --- |
| `site.json` | about 200 KB | 208,972 bytes (1,280 inputs) | 563,950 bytes (3,435 inputs) |
| `routes.json` | about 40 KB | 46,425 bytes | 134,211 bytes |
| `board.json` | 20-40 KB | 26,979 bytes | 143,673 bytes |
| `methodology.json` | 10-20 KB | 16,212 bytes | 16,212 bytes |
| `reel.json` | under 25 KB | 18,263 bytes | 18,725 bytes |
| `cases/` | 15-20 KB each | 20 files, 33,345 to 64,266 bytes, median 41,809; 940,095 in all | 76 files, 18,985 to 64,266 bytes, median 30,083; 2,524,372 in all |
| `receipts/` | 3-5 KB each | 651 files, 9,582 to 74,320 bytes, median 10,738; 8,289,862 in all | 1,854 files, 9,582 to 79,301 bytes, median 11,015.5; 24,009,833 in all |

`board.json` grows by its test block: the four pool rows and pass B's
rerun, each with pointers into its run's summary.

At 07d91ca, case and receipt files were about two to three times the
estimate, mostly because each sourced node carries its whole source op, path
included. Those ops, with their `"src":` keys, were 61.6 percent of the
receipt bytes (5,106,294) and 63.9 percent of the case bytes (600,363).
These shares were not measured again at 69d237e.

`captures.json`: 8 probes, 480 frames, 51,073 bytes, the same at 69d237e.

The static export at 69d237e, from the Docker (Linux) build:
- 29 files, 923,059 bytes: 5 HTML, 11 JS, 12 TXT and 1 CSS. At 07d91ca it
  had 29 files and 923,060 bytes.
- 3 routes: `/`, `/methodology/` and `/_not-found`. The 5 HTML files are
  `index.html`, `methodology/index.html` (107,897 bytes; 107,895 at
  07d91ca), `404.html`, `404/index.html` and `_not-found/index.html`.
- The methodology page renders 138 sourced values: 40 integers, 97 strings
  and 1 status shown as "not measured yet" (`data-fmt` `int`, `text` and
  `unmeasured`). At 07d91ca the same 138 were 40 linked numbers and 98
  strings.
- The 1,854 receipt and 76 case documents are exported but not rendered
  yet; those pages come next.

Timings are wall-clock on the Windows 11 host. At 07d91ca, Docker Desktop was
29.7.2 and other sessions used Docker at the same time:

| Step | Time |
| --- | --- |
| Docker `--target out`, no layer cache | 21.0 s: export 1.1 s, `pnpm install` 12.1 s, `next build` 4.8 s |
| Docker `--target out`, cached | 1.8 s |
| Host `pnpm web:build` | 8.2 s: compile 1.8 s, static generation 0.5 s |
| Host `pnpm web:typecheck` / `pnpm web:lint` | 2.4 s / 5.0 s |
| Playwright, 57 tests on two workers | 10.5 s on the Docker build, 9.8 s on the host build; about 0.7 to 0.9 s per route for the consistency test |
| Playwright, 82 tests on two workers, at a9f12d9 | 10.9 s on the Docker build; each consistency route now loads twice, with and without JavaScript, in 0.9 to 1.6 s per route on the host build |
| CI pylint step for the two scripts | 4.2 s |
| CI evidence check | 2.2 s |
| CI exporter and evidence tests, 124 with `docs/` | 18.3 s (pytest 17.3 s) |
| CI export twice and `diff -r` | 16.0 s; peak `/tmp` 21 MB of the 128 MB tmpfs |
| Full CI python mirror at 07d91ca | 32 min 46 s (pytest 822 s) |

The `site` image is 201 MB.

At 69d237e, on the same host with Python 3.12.10 and Node 24.21.0 (CI pins
Node 20.20.2):

| Step | Time |
| --- | --- |
| Host export, two runs | 5.736 s and 5.544 s |
| Host exporter tests, 148 passed and 2 skipped | 149.79 s |
| Docker `--target out`, export and build stages rebuilt, dependency layers cached | 19.515 s: export 4.1 s, `next build` 8.1 s |
| Docker `--target out`, cached | 3.416 s |
| Docker `--target data`, export rebuilt / cached | 15.434 s / 6.672 s |
| Host `pnpm web:typecheck` / `pnpm web:lint` | 3.093 s / 9.355 s |
| Playwright, 142 tests on two workers, on the Docker build | 15.7 s |
| CI pylint step for the two scripts | 5.354 s |
| CI evidence check | 2.754 s |
| CI exporter and evidence tests, 174 with `docs/` | 127.154 s (pytest 125.93 s) |
| CI export twice and `diff -r` | 68.629 s |
| Full CI python mirror | 3,400 s (pytest 1,187.49 s) |

The two host skips are the symbolic-link tests, which need privileges on
Windows; in the test image all 150 exporter tests pass. Under the test
service's 128 MB `/tmp` tmpfs, the export-twice step ends with 59,548 KB in
`/tmp`, 46 percent of the 131,072 KB. The exporter tests peak at 20,460 KB
in samples taken every 0.2 s, which can miss a shorter spike.

### The Disproof Reel

In the test phase, rule `reel-v1` picks
[`test-qwen3-32b-2026-09-26` C4 `mei-1038`](../results/test-qwen3-32b-2026-09-26/scored/receipts/C4/mei-1038.json):
- the pool is pass A, `test-qwen3-32b-2026-09-26`, then the slot winners'
  test runs `test-qwen3.5-9b-2026-09-26`,
  `test-qwen3.5-122b-a10b-2026-09-26` and
  `test-deepseek-v4-pro-0813-2026-09-26`;
- 54 C4 silent-wrong candidates in the pool; only the pick has 3
  disagreeing frames, and the next fewest is 4;
- the request is "I want every TCP segment with FIN set whose source port
  is 443, whether or not ACK is also set. Judge by the port alone; a FIN
  sent to destination port 443 from some other source port doesn't
  belong.";
- the answer `(tcp.srcport == 443 && tcp.completeness.fin == true)` misses
  one frame that the reference `tcp.flags.fin == 1 && tcp.srcport == 443`
  selects on each scored probe: frames 59, 60 and 66 are reference-only on
  semantic-31, -37 and -43, each the `server-fin-ack` witness frame;
- the highlight is semantic-37, frame 60, `server-fin-ack`;
- the headline counts M = 971 and N = 165.

Step 5 shows the pick's turn in pass A's counterexample arm run,
`test-qwen3-32b-cx-2026-09-26`, which pass A's
[`repair/summary.json`](../results/test-qwen3-32b-2026-09-26/repair/summary.json)
names at `/arms/2/run`:
- the card is `/items/15` of pass A's `repair/plan.json`, kind `frames`: frame
  63 of the feedback probe semantic-35, a FIN+ACK from source port 443 that
  the request selects and the first answer missed;
- the second answer `(tcp.srcport == 443 && tcp.flags.fin == true)` scored
  `strong_exact`, and its receipt agrees with the reference on every frame
  of the three scored probes.

The receipt panel's `repair` field is null now that pass A's round is
scored.

The pick's predicate trace is committed at
[`traces/test-qwen3-32b-2026-09-26/C4/mei-1038.json`](evidence/web/traces/test-qwen3-32b-2026-09-26/C4/mei-1038.json).
Steps 1 to 4 of `reel-v1` read no trace, so it was made after the pick
and cannot move it. On semantic-37's frame 60, the filter's leaf
`tcp.srcport == 443` is true and `tcp.completeness.fin == true` is false,
so the filter does not select the frame. The request's leaves,
`tcp.flags.fin == true` and `tcp.srcport == 443`, are both true. The
other two probes trace alike at frames 59 and 66. The replay gave the
receipt's frames exactly.

On the committed dev data, before the test phase, the rule picked
[`dev-qwen3-32b-2026-09-26` C4 `mei-0015`](../results/dev-qwen3-32b-2026-09-26/scored/receipts/C4/mei-0015.json):
- the request is "Show DNS AAAA questions or DNS NXDOMAIN messages.";
- 27 C4 silent-wrong candidates in the pool; three tie at 3 disagreeing
  frames, and pool order picks the anchor's;
- frames 17, 3 and 9 are reference-only on semantic-11, -17 and -23;
- the highlight is semantic-17, frame 3, `udp-aaaa`;
- the headline counts M = 284 and N = 65.

[`disproof-reel.md`](disproof-reel.md) recorded that pick on 2026-10-01,
when five registry rows were `registered`.
`test_the_committed_dev_pool_picks_the_registered_dev_reel` repeats the
check on a copy of the committed dev inputs with rows 1 to 5 set back to
`registered`. Its pool is the anchor, then the three winners' dev passes
from the ruling. The copy holds no test-run directory, so the published
rows have no summary and the phase stays dev even without that edit; with
the five test runs copied in and the edit dropped, the phase moves to test
and the test fails. `test_the_committed_tree_picks_the_registered_reel`
pins the test-phase pick, and `tests/consistency.spec.ts` derives it again
in TypeScript, with its step 5 choice. `disproof-reel.md` registered that
the rule had no code. Its registered text is left as it is; a dated line in
its Limits now says steps 1 to 5 have code, and its "Reading step 5" section
says how step 5 is read.

### The board

`/board/` opens with the test repair round's strongest number: after one
structured counterexample, 35 of the 75 failed answers were repaired,
against 21 after a bare turn and 4 on a resample. Then it shows:
- the three pooled arms as bars, each with repair@1, its interval and the
  pool's bootstrap settings;
- the counted test passes in pool order, each with its C4 outcome bar and
  its C4 strong-exact rate and interval;
- the three pooled comparisons, labelled secondary;
- each pool pass's arms and comparisons, with counterexample - bare
  labelled primary.

Each comparison shows its discordant cases and its verdict. A bar grows
by counts: an outcome bar's segments by flex-grow, and a repair bar is a
grid of one column per triggered answer whose fill spans the repaired
ones. An interval is placed by its committed bounds.

The board leaves out the comparisons between conditions and the A/A pair;
it links `locked-test-v1.md` for them (Limits). It shows no dev bake-off
count and no dev repair number. `tests/consistency.spec.ts` checks three
things that the value checks cannot see:
- its rows and its repair rounds are the Reel's pool in pool order;
- its repair numbers come only from the pool file and the pool passes'
  rounds;
- only the per-model counterexample - bare comparison is labelled
  primary.

Measured at 0a1617c on `site-board` (2026-10-06):
- Two exports in the test image are identical: 1,935 files in 27,510,508
  bytes. `board.json` grows from 143,673 to 174,259 bytes, and only it and
  `site.json` differ from 6434424's export.
- The Docker static export has 39 files in 3,043,537 bytes: 6 HTML, 12 JS,
  16 TXT, 3 CSS and the 2 committed fonts. `board/index.html` is 297,752
  bytes, 18,515 gzipped, and renders 280 sourced values: 107 integers, 102
  rates, 56 strings and 15 verdicts.
- The Docker `--target out` build took 16 s with cached dependency layers.
- The test image ran the 189 exporter and evidence tests in 92.9 s.
- Playwright ran 168 tests on the Docker build in 18.0 s.

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

- The methodology page, the Reel on `/` and the board render values today.
  The case and receipt pages come next.
- The Reel draws the chosen prototype's figure: one ladder diagram per
  scored probe of the pick, with an arrow and the Info column per frame
  and each run of agreeing witness frames collapsed into one break row,
  the probe bars over it,
  the draggable cursor, the packet-list row of the cursor's frame and the
  predicate trace there. The branch's first Reel, 9343e3a, drew request
  and filter lanes instead, for want of per-frame columns, which
  `packets.json` now holds; the owner ruled on 2026-10-06 to restore the
  ladder. The prototype's RFC header box is left out. The GIF is not encoded yet:
  `apps/web/scripts/record_reel.mjs` records its frames, and two
  recordings of one build are identical, but ffmpeg is not installed on
  the development host.
- The trace evaluates leaves only at the frames where the answer and the
  labels disagree, as `dfilterforge.live` traces a counterexample, so on
  every other frame the readout shows a leaf as a dash. Only the Reel's
  pick is traced.
- Rule `reel-v1` and the registry were committed before the first test
  request, so the test-phase pick predates the test data:
  `disproof-reel.md` in 6f2beb9, and `test-runs.json` with `test-runs.md`
  in 6819a52. Both are ancestors of 7aaade8, as
  `git merge-base --is-ancestor` confirms; 7aaade8 is the source revision
  that pass A's first invocation recorded, at 2026-10-01T18:45:12Z.
- `methodology.json` still takes its bootstrap block from the dev anchor's
  summary, in the test phase too. The methodology page says its intervals
  come from bootstrap resamples "as the anchor pass's summary records
  them", so it stays true. The board states the bootstrap of its own
  intervals beside them, from the repair pool file, so the methodology
  page keeps the dev anchor's block. Only the page's
  `not_measured` statuses and its repair line follow the phase (What
  fails). Neither names its source run, but each label names the split of
  the run it cites: "Test repair round" in the test phase, "Dev repair
  round" in the dev phase.
- Step 5 shows only the pick's own counterexample turn. The fallback repair
  trajectory `disproof-reel.md` registers for a pick without a repair row
  is not built: no committed data needs it, and the export stops
  (`repair_fallback_unbuilt`) rather than drop it. The consistency test
  re-derives every value the home page shows from the committed files, the
  turn's included.
- The methodology page's repair line shows counts for the cited run's round
  only, pass A's in the test phase; the board shows repair@1, its
  intervals and every pool pass's round.
- The A/A pair is not wired in: `board.json` keeps `aa` null, and no
  committed file holds the confound notes `locked-test-v1.md` attaches to
  the comparisons between conditions. So the board leaves those
  comparisons out and links that page for them.
- Base images are pinned by tag, not by digest.
- `RUN --network=none` was verified only on Docker Desktop 29.7.2: the step
  saw only `lo`, and a connect failed with `ENETUNREACH`. The CI workflow and
  the composite action run on every pull request and every push to `main`;
  the owner reports hosted CI green on `main` at 1ec918c. The `pages` job
  first runs on the push that merges it.
- The consistency test does not sweep CSS `content:`, `<head>` meta, or the
  markers CSS numbers for a list without a `start`.
- Next 16.3.4 on Windows writes nested segment-prefetch files into
  subdirectories, where a Linux build writes flat names. The smoke test
  exempts exactly that case, so CI and Pages use the Linux build.

## What the next pages must do

The case and receipt pages come in the next pull requests. These rules
bind them, as they bind the Reel and the board. The first and the rounding
are enforced by tests today:
- **Not measured yet.** Until the pick's pass has a scored round,
  `reel.json`'s `receipt_panel.repair` holds the summary's status key,
  `not_run`; after, it is null. A page shows it through `<Unmeasured>` as
  "not measured yet", the words of the [repair note](repair-round.md), and
  never renders the raw node: the protocol keeps "not run" for a run that
  ended without a result. The consistency test fails a `not_measured`
  value shown with any other kind. A page shows `repair.reason` as fixed
  words too, never the code.
- **The A/A reading and the confounds.** A page that shows a test
  comparison also shows its A/A reading from the pair report, and the
  notes `locked-test-v1.md` attaches to it: the comparisons it marks
  confounded by rate limiting, and the items each pass lost to HTTP 429.
  The board shows only the repair arms' comparisons, which no A/A bound
  reads (`locked-test-v1.md`, Limits); its Limits section says so and
  carries the round's own notes.
- **Rounding.** A rate or difference is shown with `lib/fmt.ts`'s `rate`
  kind, which rounds a value exactly halfway away from zero, as
  `locked-test-v1.md` does, so a shown rate matches its count.
- **No ranking.** Test rows keep pool order. No page orders the models by a
  rate or presents the rows as a ranking: `locked-test-v1.md` reports the
  rates as descriptive, and no comparison between models was
  pre-registered.
- **Role labels.** `reel.json`'s pool, `site.json`'s runs and the board rows
  carry the registry's roles verbatim, with no slot field. Pages map a role
  to its label with `lib/roles.ts`, the one table, which fails the build on
  a role it does not know.
