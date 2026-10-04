import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';

import {expect, test} from '@playwright/test';

import {Resolver} from './support/resolve';

// The resolver reads the test-run registry (test-runs/1.0) the way the
// exporter does, from docs/decisions/disproof-reel.md and
// docs/decisions/test-runs.md: which test runs are shown, when the test
// phase starts and which runs the Reel pools. Each case builds a scratch
// tree with a bake-off ranking, the ruling and a registry; the exporter's
// fixture tests in tests/test_export_web_data.py cover the same cases.

const DATE = '2026-09-26';
const ANCHOR = `dev-anchor-${DATE}`;
// The ranking's provisional small winner, and the ruling's.
const SMALL_PROVISIONAL = `dev-small-a-${DATE}`;
const SMALL_RULED = `dev-small-b-${DATE}`;
const DEV_MID = `dev-mid-${DATE}`;
const DEV_FRONTIER = `dev-frontier-${DATE}`;
const DEV_RUNS = [ANCHOR, SMALL_PROVISIONAL, SMALL_RULED, DEV_MID, DEV_FRONTIER];

const PASS_A = `test-pass-a-${DATE}`;
const PASS_B = `test-pass-b-${DATE}`;
const SMALL = `test-small-${DATE}`;
const MID = `test-mid-${DATE}`;
const FRONTIER = `test-frontier-${DATE}`;
// Runs 1 to 5 of test-runs.md, in registry order.
const PLANNED: readonly (readonly [string, string])[] = [
  ['aa_pass_a', PASS_A],
  ['aa_pass_b', PASS_B],
  ['winner_small', SMALL],
  ['winner_mid', MID],
  ['winner_frontier', FRONTIER],
];

const BAKEOFF = 'docs/decisions/evidence/bakeoff';
const RULING = `${BAKEOFF}/ruling-2026-10-01.json`;
const TEST_RUNS = 'docs/decisions/evidence/test-runs.json';

/** One registry row, with the fields the resolver reads. */
interface Row {
  role: string;
  run_id: string;
  status: string;
  trigger: string | null;
  conditional_on: string | null;
  reason: string | null;
}

interface Registry {
  readonly schema: string;
  readonly note: string;
  readonly ruling: string;
  readonly runs: Row[];
}

/** Names a fallback (fb) or an outage re-run (r2) as test-runs.md does. */
function tag(runId: string, name: string): string {
  return runId.replace(`-${DATE}`, `-${name}-${DATE}`);
}

function row(
  role: string,
  runId: string,
  status: string,
  trigger: string | null = null,
  conditionalOn: string | null = null,
): Row {
  return {role, run_id: runId, status, trigger, conditional_on: conditionalOn, reason: null};
}

/**
 * A registry in the committed shape, 16 rows: the five planned rows
 * published, each winner's fallback an unused gate_stop row, and an unused
 * outage re-run of every planned and fallback row. Every unused row names a
 * published or unused run, so the registry is final once the five planned
 * runs are scored.
 */
function registry(): Registry {
  const planned = PLANNED.map(([role, runId]) => row(role, runId, 'published'));
  const fallbacks = PLANNED.slice(2).map(([role, runId]) =>
    row(role.replace('winner_', 'fallback_'), tag(runId, 'fb'), 'unused', 'gate_stop', runId),
  );
  const reruns = [...planned, ...fallbacks].map((entry) =>
    row(entry.role, tag(entry.run_id, 'r2'), 'unused', 'outage', entry.run_id),
  );
  return {
    schema: 'test-runs/1.0',
    note: 'docs/decisions/test-runs.md',
    ruling: RULING,
    runs: [...planned, ...fallbacks, ...reruns],
  };
}

/** The one row of a run. */
function at(runs: Registry, runId: string): Row {
  const found = runs.runs.find((entry) => entry.run_id === runId);
  if (found === undefined) {
    throw new Error(`no row for ${runId}`);
  }
  return found;
}

/**
 * Rules a run not_run with a reason, as the owner records a stop. Every
 * unused row that names it gets a reason too, or the test phase would wait
 * for that row.
 */
function stop(runs: Registry, runId: string, reason: string): void {
  for (const entry of runs.runs) {
    if (entry.run_id === runId) {
      Object.assign(entry, {status: 'not_run', reason});
    } else if (entry.conditional_on === runId && entry.status === 'unused') {
      entry.reason = `${runId} ended by ${reason}; not sent`;
    }
  }
}

function publish(runs: Registry, runId: string): void {
  Object.assign(at(runs, runId), {status: 'published', reason: null});
}

let root: string;

function write(file: string, text: string): void {
  const location = path.join(root, ...file.split('/'));
  mkdirSync(path.dirname(location), {recursive: true});
  writeFileSync(location, text);
}

function put(file: string, value: unknown): void {
  write(file, `${JSON.stringify(value)}\n`);
}

/** Commits the registry and a scored summary for each published run. */
function commit(runs: Registry): void {
  put(TEST_RUNS, runs);
  for (const entry of runs.runs.filter((each) => each.status === 'published')) {
    put(`docs/results/${entry.run_id}/scored/summary.json`, {run: entry.run_id});
  }
}

/** One outcome row: condition, item, gold status, outcome, and frames. */
type Answer = readonly [string, string, string, string, number];

/**
 * Commits a run's outcome rows and, for each silent-wrong answer, a receipt
 * whose probes disagree on the given number of frames: the first half in
 * candidate_only of the first probe, the rest in reference_only of the
 * second, and none on the third.
 */
function answers(runId: string, rows: readonly Answer[]): void {
  write(
    `docs/results/${runId}/scored/outcomes.jsonl`,
    rows
      .map(([cond, item, gold, outcome]) =>
        JSON.stringify({condition: cond, item_id: item, gold_status: gold, outcome}),
      )
      .join('\n') + '\n',
  );
  for (const [cond, item, , outcome, frames] of rows) {
    if (outcome === 'silent_wrong') {
      const numbered = Array.from({length: frames}, (_, index) => index + 1);
      const half = Math.floor(frames / 2);
      put(`docs/results/${runId}/scored/receipts/${cond}/${item}.json`, {
        probes: [
          {candidate_only: numbered.slice(0, half), reference_only: []},
          {candidate_only: [], reference_only: numbered.slice(half)},
          {candidate_only: [], reference_only: []},
        ],
      });
    }
  }
}

test.beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'registry-'));
  put(`${BAKEOFF}/ranking-2026-09-26.json`, {
    anchor: {run_id: ANCHOR},
    slots: {
      small: {
        candidates: [
          {rank: 2, run_id: SMALL_RULED},
          {rank: 1, run_id: SMALL_PROVISIONAL},
        ],
        provisional_winner: SMALL_PROVISIONAL,
      },
      mid: {candidates: [{rank: 1, run_id: DEV_MID}], provisional_winner: DEV_MID},
      frontier: {candidates: [{rank: 1, run_id: DEV_FRONTIER}], provisional_winner: DEV_FRONTIER},
    },
  });
  put(RULING, {
    schema: 'bakeoff-ruling/1.0',
    anchor: {run_id: ANCHOR},
    slots: {
      small: {winner: {run_id: SMALL_RULED}},
      mid: {winner: {run_id: DEV_MID}},
      frontier: {winner: {run_id: DEV_FRONTIER}},
    },
    // Model ids, which the resolver never reads.
    winners: {small: 'm/small-b', mid: 'm/mid', frontier: 'm/frontier'},
  });
});

test.afterEach(() => {
  rmSync(root, {recursive: true, force: true});
});

test('unused conditional rows that name published runs leave the five planned runs shown', () => {
  commit(registry());
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual([...DEV_RUNS, PASS_A, PASS_B, SMALL, MID, FRONTIER]);
  expect(resolver.reelPool()).toEqual([PASS_A, SMALL, MID, FRONTIER]);
});

test("a registered row shows no test run and pools the ruling's dev winners", () => {
  const runs = registry();
  at(runs, FRONTIER).status = 'registered';
  commit(runs);
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual(DEV_RUNS);
  // The ranking's provisional small winner differs from the ruling's; the
  // ruling the registry names is taken.
  expect(resolver.reelPool()).toEqual([ANCHOR, SMALL_RULED, DEV_MID, DEV_FRONTIER]);
});

test('a not_run winner waits for reasons on its fallback and its re-run', () => {
  const runs = registry();
  Object.assign(at(runs, FRONTIER), {status: 'not_run', reason: 'outage'});
  commit(runs);

  expect(new Resolver(root).shownRuns()).toEqual(DEV_RUNS);

  at(runs, tag(FRONTIER, 'fb')).reason = 'an outage is no gate stop';
  commit(runs);

  // The re-run still names a not_run run and gives no reason.
  expect(new Resolver(root).shownRuns()).toEqual(DEV_RUNS);

  at(runs, tag(FRONTIER, 'r2')).reason = 'the owner ruled the re-run not sent';
  commit(runs);
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual([...DEV_RUNS, PASS_A, PASS_B, SMALL, MID]);
  expect(resolver.reelPool()).toEqual([PASS_A, SMALL, MID]);
});

test("a published fallback takes its winner's place in the pool", () => {
  const fallback = tag(SMALL, 'fb');
  const runs = registry();
  stop(runs, SMALL, 'gate stop');
  publish(runs, fallback);
  commit(runs);
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual([...DEV_RUNS, PASS_A, PASS_B, fallback, MID, FRONTIER]);
  expect(resolver.reelPool()).toEqual([PASS_A, fallback, MID, FRONTIER]);
});

test('a published re-run of a not_run run is shown and pooled under the shared role', () => {
  const rerun = tag(MID, 'r2');
  const runs = registry();
  stop(runs, MID, 'outage');
  publish(runs, rerun);
  commit(runs);
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual([...DEV_RUNS, PASS_A, PASS_B, SMALL, rerun, FRONTIER]);
  expect(resolver.reelPool()).toEqual([PASS_A, SMALL, rerun, FRONTIER]);
});

test('a not_run row whose run holds a scored summary is refused', () => {
  const runs = registry();
  stop(runs, MID, 'outage');
  commit(runs);
  put(`docs/results/${MID}/scored/summary.json`, {run: MID});

  expect(() => new Resolver(root).shownRuns()).toThrow(
    `docs/results/${MID} holds scored/summary.json, but its row is not_run`,
  );
});

test('two published rows in one slot are refused', () => {
  const runs = registry();
  stop(runs, MID, 'outage');
  publish(runs, tag(MID, 'r2'));
  publish(runs, tag(MID, 'fb'));
  commit(runs);

  expect(() => new Resolver(root).shownRuns()).toThrow(
    `publishes ${tag(MID, 'fb')} and ${tag(MID, 'r2')} for the mid slot`,
  );
});

test('a conditional row not_run while its named run is published is refused', () => {
  const runs = registry();
  Object.assign(at(runs, tag(SMALL, 'fb')), {status: 'not_run', reason: 'outage'});
  commit(runs);

  expect(() => new Resolver(root).shownRuns()).toThrow(
    `${tag(SMALL, 'fb')} is not_run while ${SMALL} is published`,
  );
});

test('the Reel picks the fewest frames, then the earlier pool run and lower item, C4 first', () => {
  // With no registry the pool is the anchor and the ranking's provisional
  // winners, so the ruled small winner's 0-frame answer is never a candidate.
  answers(ANCHOR, [
    ['C4', 'mei-0003', 'ready', 'silent_wrong', 2],
    ['C4', 'mei-0002', 'ready', 'silent_wrong', 2],
    ['C4', 'mei-0001', 'needs_clarification', 'silent_wrong', 1],
    ['C3', 'mei-0001', 'ready', 'silent_wrong', 1],
  ]);
  answers(SMALL_PROVISIONAL, [
    ['C4', 'mei-0001', 'ready', 'silent_wrong', 2],
    ['C4', 'mei-0004', 'ready', 'strong_exact', 0],
  ]);
  answers(SMALL_RULED, [['C4', 'mei-0001', 'ready', 'silent_wrong', 0]]);
  answers(DEV_MID, [['C4', 'mei-0005', 'ready', 'silent_wrong', 5]]);
  answers(DEV_FRONTIER, [['C4', 'mei-0006', 'ready', 'shortcut', 0]]);
  const resolver = new Resolver(root);

  expect(resolver.reelPool()).toEqual([ANCHOR, SMALL_PROVISIONAL, DEV_MID, DEV_FRONTIER]);
  expect(resolver.reelPick()).toEqual({run: ANCHOR, cond: 'C4', item: 'mei-0002', candidates: 4});

  // No C4 or C3 answer is silent-wrong: the pick comes from C2.
  for (const runId of [ANCHOR, SMALL_PROVISIONAL, DEV_MID]) {
    answers(runId, [['C4', 'mei-0001', 'ready', 'strong_exact', 0]]);
  }
  answers(DEV_FRONTIER, [
    ['C3', 'mei-0006', 'ready', 'shortcut', 0],
    ['C2', 'mei-0006', 'ready', 'silent_wrong', 4],
  ]);

  expect(new Resolver(root).reelPick()).toEqual({
    run: DEV_FRONTIER,
    cond: 'C2',
    item: 'mei-0006',
    candidates: 1,
  });

  answers(DEV_FRONTIER, [['C2', 'mei-0006', 'ready', 'invalid', 0]]);

  expect(new Resolver(root).reelPick()).toBeNull();
});
