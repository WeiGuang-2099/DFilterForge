# Disproof Reel: which trajectory the site shows

The site's home page plays one model answer and the packet that disproves it.
The trajectory is chosen by rule `reel-v1`, run by `scripts/export_web_data.py`
over committed files only, and fixed here before any test or repair answer
exists.

## Rule reel-v1

1. Pool. If every test run named in `docs/decisions/evidence/test-runs.json`
   has a scored summary or is listed there as not run: the pass A run, then
   the small, mid and frontier slot winners' test runs, in that order, skipping
   runs not run. Otherwise: the dev anchor `dev-qwen3-32b-2026-09-26`, then the
   three slot winners' dev passes in slot order (from `test-runs.json` when it
   exists, else the latest bake-off ranking's provisional winners). Pass B,
   unregistered or partial runs and two-turn smoke runs are never in the pool.
2. Candidates. Items of pool runs in condition C4 with ready gold and outcome
   `silent_wrong`; if there are none, C3, then C2, then C1. With none at all,
   the Reel says that no answer in the pool is silent-wrong.
3. Pick. The candidate with the fewest disagreeing frames summed over its
   three scored probes (frames in `candidate_only` plus `reference_only`);
   ties go to the earlier run in the pool, then to the lower item id.
4. Highlight. The second scored probe in the receipt's order if it disagrees,
   else the first, else the third; on it, the lowest disagreeing frame.
5. Repair. No repair outcome, feedback-probe result or predicate trace is an
   input to steps 1 to 4. Once repair runs are scored, the Reel shows the
   structured-counterexample arm's second turn for the picked item whatever it
   scored, including not repaired, invalid or no reply; if the pick is not C4,
   or has no repair row, it says so.

Headline. "Of M filters that compiled and ran, N were silent-wrong" counts,
over the pool runs and conditions C1 to C4, ready items with outcome
`strong_exact`, `shortcut` or `silent_wrong` (M) and those with `silent_wrong`
(N). Pass A and pass B are never pooled.

Dev display. Bake-off passes are shown as model selection: per-pass counts
over C1 to C4 in the ranking's order, with no interval and no comparison
(model bake-off note, "Not an effect"). Intervals and comparisons are shown
only for test runs, copied from their `summary.json`.

## Repair trajectory

The repair round's registration (the protocol's Repair section and the
[repair note](repair-round.md)) fixes one more sentence for the web track,
before any test repair result is read:

> The Reel's repair trajectory is the first item in base prepare order of the
> frontier slot's test plan whose card kind is `frames`, shown with its
> counterexample-arm outcome whatever it is.

Step 5 already shows the pick's own counterexample turn, so the two sentences
are read together.
- **The pick has a repair row.** The Reel shows step 5's repair turn for the
  pick.
- **The pick has no repair row.** This happens when the pick is not C4, or
  its pass's round was not run. The Reel says so and shows this trajectory
  instead. The item comes from `repair/plan.json` of the frontier slot's
  counted test pass, and its turn from that pass's `-cx` arm run.
- **Neither exists.** The frontier slot may have no such item, or no scored
  `-cx` run. The Reel then says that no repair trajectory is shown.

Repair numbers on the page come only from `repair/summary.json` and
`repair-pool/test.json`, checked by the Playwright consistency test.

## Reading the rule against the registry

The rule was written before the registry took its committed shape:
[`evidence/test-runs.json`](evidence/test-runs.json), schema `test-runs/1.0`,
described in the [test-run registry](test-runs.md). The rule reads it as
follows. No choice the rule makes today changes.

- **When the test phase starts.** Step 1's condition, "has a scored summary
  or is listed there as not run", holds when all three of these are true:
  - no row is `registered`;
  - every `published` row's run has `scored/summary.json`;
  - every other row is either `not_run`, or an `unused` conditional run that
    gives a reason or whose named run is not `not_run`.

  These are the rows the frozen-prompt guard treats as final (the
  registry's Status section). So the Reel never waits for a fallback or
  re-run whose condition never occurred. OD4 also holds back scoring of any
  test run until the `repair-cards` branch merges, so the test phase cannot
  start before then.
- **"The pass A run".** This is the run of the `published` row with role
  `aa_pass_a`.
- **"A slot winner's test run".** This is the run of the slot's `published`
  `winner_<slot>` row, else of its `published` `fallback_<slot>` row; an
  outage re-run counts. A role with no published row is skipped.
- **"The three slot winners' dev passes ... from `test-runs.json`".** These
  are the winners' dev passes in
  [`evidence/bakeoff/ruling-2026-10-01.json`](evidence/bakeoff/ruling-2026-10-01.json),
  the ruling `test-runs.json` names. Today they are
  `dev-qwen3.5-9b-2026-09-26`, `dev-qwen3.5-122b-a10b-2026-09-26` and
  `dev-deepseek-v4-pro-0813-2026-09-26`. These are also the ranking's
  provisional winners.
- **Repair arm runs.** The `-res`, `-bare` and `-cx` runs are not rows of
  `test-runs.json` and never enter the pool. The "structured-counterexample
  arm" of step 5 is the `-cx` arm run of the pick's pass.

## Checked on today's data

On the committed dev data at the time of writing, the rule picks
[`dev-qwen3-32b-2026-09-26` C4 `mei-0015`](../results/dev-qwen3-32b-2026-09-26/scored/receipts/C4/mei-0015.json).

This was checked on 2026-10-01 by applying steps 1 to 4 and the headline to
the committed files. The script read only `test-runs.json`, the bake-off
ruling, each pool run's `scored/outcomes.jsonl` and its
`scored/receipts/C4/*.json`. It is not committed; the exporter's tests are to
repeat the check.

- **Pool.** The test phase is off, because five registry rows are
  `registered`. The pool is therefore the dev anchor
  `dev-qwen3-32b-2026-09-26`, then `dev-qwen3.5-9b-2026-09-26`,
  `dev-qwen3.5-122b-a10b-2026-09-26` and
  `dev-deepseek-v4-pro-0813-2026-09-26`.
- **Candidates.** The pool has 27 C4 items with ready gold and outcome
  `silent_wrong`, each with a receipt.
- **Pick.** Three candidates tie at 3 disagreeing frames: the anchor's
  `mei-0015`, and deepseek-v4-pro-0813's `mei-0009` and `mei-0015`. Pool order
  picks the anchor's.
- **What the receipt shows.**
  - The request is "Show DNS AAAA questions or DNS NXDOMAIN messages."
  - The answer compiles to `(dns.aaaa || dns.flags.rcode == 3)`. The
    reference is `dns.qry.type == 28 || dns.flags.rcode == 3`.
  - On every scored probe the filter misses one labelled frame and selects no
    extra one: `reference_only` is [17] on semantic-11, [3] on semantic-17
    and [9] on semantic-23. The tshark runtimes are 67.48, 67.76 and 68.53
    ms.
- **Highlight.** The highlight is semantic-17, the second probe, at frame 3.
- **Headline.** Over the dev pool, M is 284 and N is 65.

## Reading step 5 (2026-10-06)

This reading was written after the test repair round was scored, when step 5
got code. It leaves the rule and "Repair trajectory" as registered.
- **A repair row.** The picked item is in the `items` of its pass's
  `repair/summary.json`, and the round's `arms` list the counterexample arm,
  which `arms_not_run` does not stop. The arm run id is the one that arm
  names in the summary, so an `-r2` or `-nb` re-run needs no name rule.
- **The turn.** The card comes from the pass's `repair/plan.json`. From the
  arm run come its completion, its outcome row and, for an executed answer,
  its receipt's filter and frame strips; never its `scored/summary.json`.
- **The fallback trajectory is not built.** Wherever "Repair trajectory"
  would show it, the export stops (`repair_fallback_unbuilt`) rather than
  drop it. That is when the pick's pass has a scored round but the pick is
  not C4 or has no repair row, and when the pick's pass has no scored round
  but, in the test phase, the frontier slot's counted test pass (its
  `winner_frontier` run, else its `fallback_frontier` run) has one. With
  neither round the Reel says no round is scored. The dev phase reads no
  frontier round, since the fallback names the frontier slot's test plan.
  No committed data needs the fallback: all four test pool passes have
  rounds.
- **Today's pick.** Steps 1 to 4, which read no repair result, pick pass A's
  C4 `mei-1038`. Its row is item 15 of pass A's
  [`repair/plan.json`](../results/test-qwen3-32b-2026-09-26/repair/plan.json),
  committed in b3a7d40 on 2026-10-02, before the first test repair request
  on 2026-10-05.

## Limits

- **The rule has no code yet.** `scripts/export_web_data.py` does not exist
  yet; the web track's exporter implements the rule and tests it on fixtures.
  Amended 2026-10-06: steps 1 to 5 have code, `build_reel` and
  `reel_repair` in `scripts/export_web_data.py`, derived again in
  `apps/web/tests/support/resolve.ts`; the fallback repair trajectory has
  none (Reading step 5).
- **The pick depends on gold.** A gold correction that re-scores the pool
  runs can change it, and the rule then picks again by the same steps.
- **The pool changes at the test phase.** Once every registered test run is
  final, the pool moves from dev to test, and the dev pick above is no longer
  shown.
