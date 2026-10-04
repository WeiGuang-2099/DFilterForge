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
const NOTE = 'docs/decisions/test-runs.md';

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
  schema: string;
  note: string;
  ruling: string;
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

/**
 * Renders test-runs.md: prose, the Runs table of the given rows numbered
 * from start, in the committed note's column order, then a table that is
 * not the Runs table.
 */
function note(rows: readonly Row[], start = 1, prose = ''): string {
  return [
    '# Hosted test runs',
    '',
    prose,
    '',
    '| # | Role | Run id | Model id | Runs |',
    '| --- | --- | --- | --- | --- |',
    ...rows.map(
      (entry, index) =>
        `| ${index + start} | \`${entry.role}\` | \`${entry.run_id}\` | \`m/m\` | always |`,
    ),
    '',
    '| Exit | Meaning |',
    '| --- | --- |',
    '| 0 | Every row has a final state: `done`. |',
    '',
  ].join('\n');
}

/**
 * Commits the registry, its note's Runs table and a scored summary for
 * each published run.
 */
function commit(runs: Registry): void {
  put(TEST_RUNS, runs);
  write(NOTE, note(runs.runs));
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

/** A bake-off ruling, with the fields the resolver reads and the model ids. */
interface Ruling {
  schema: string;
  readonly anchor: {readonly run_id: string};
  readonly slots: Record<string, {winner?: {run_id: string}}>;
  readonly winners: Readonly<Record<string, string>>;
}

/**
 * A bakeoff-ruling/1.0 document whose small winner is the ranking's
 * second-ranked run, not its provisional winner, so a pool that holds it
 * took its winners from the ruling.
 */
function ruling(): Ruling {
  return {
    schema: 'bakeoff-ruling/1.0',
    anchor: {run_id: ANCHOR},
    slots: {
      small: {winner: {run_id: SMALL_RULED}},
      mid: {winner: {run_id: DEV_MID}},
      frontier: {winner: {run_id: DEV_FRONTIER}},
    },
    // Model ids, which the resolver never reads.
    winners: {small: 'm/small-b', mid: 'm/mid', frontier: 'm/frontier'},
  };
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
  put(RULING, ruling());
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

test('a published run without a scored summary keeps the test phase off', () => {
  // Published but not scored yet, as test-runs.md allows: the phase waits,
  // and nothing is wrong.
  commit(registry());
  rmSync(path.join(root, 'docs', 'results', MID, 'scored'), {recursive: true});
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual(DEV_RUNS);
  expect(resolver.reelPool()).toEqual([ANCHOR, SMALL_RULED, DEV_MID, DEV_FRONTIER]);
});

test('a test pool with every pooled run stopped is empty and has no pick', () => {
  const runs = registry();
  for (const runId of [PASS_A, SMALL, MID, FRONTIER]) {
    stop(runs, runId, 'outage');
  }
  commit(runs);
  // Only pass B is published, and its answer is silent-wrong, as are the
  // dev anchor's: neither may be pooled.
  answers(PASS_B, [['C4', 'mei-1001', 'ready', 'silent_wrong', 1]]);
  answers(ANCHOR, [['C4', 'mei-0001', 'ready', 'silent_wrong', 1]]);
  const resolver = new Resolver(root);

  expect(resolver.shownRuns()).toEqual([...DEV_RUNS, PASS_B]);
  expect(resolver.reelPool()).toEqual([]);
  expect(resolver.reelPick()).toBeNull();
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

/** One registry the exporter refuses, and the refusal the resolver gives. */
interface Broken {
  readonly name: string;
  readonly edit: (runs: Registry) => void;
  /** Files committed beside the registry, as a run directory holds them. */
  readonly files?: readonly string[];
  readonly message: string;
}

const MID_FALLBACK = tag(MID, 'fb');

// The cases of test_a_broken_registration_fails and
// test_a_registry_of_another_schema_exits_two in
// tests/test_export_web_data.py for each refusal the resolver makes beyond
// the three tests above, so deleting any one of them fails a test.
const BROKEN: readonly Broken[] = [
  {
    name: 'another schema',
    edit: (runs) => {
      runs.schema = 'test-runs/0.9';
    },
    message: `${TEST_RUNS} is not test-runs/1.0`,
  },
  {
    name: 'another note',
    edit: (runs) => {
      runs.note = 'docs/decisions/model-bakeoff.md';
    },
    message: `${TEST_RUNS} note is not ${NOTE}`,
  },
  {
    name: 'an unknown role',
    edit: (runs) => {
      at(runs, MID).role = 'winner_huge';
    },
    message: 'row 4 has the role "winner_huge"',
  },
  {
    name: 'a malformed run id',
    edit: (runs) => {
      at(runs, PASS_A).run_id = `test-Bad_X-${DATE}`;
    },
    message: `row 1 run_id "test-Bad_X-${DATE}" is not a run id`,
  },
  {
    name: 'a run id that leaves its directory',
    edit: (runs) => {
      at(runs, tag(MID, 'r2')).run_id = `test-x/../${MID}`;
    },
    message: `run_id "test-x/../${MID}" is not a run id`,
  },
  {
    name: 'a dev run id',
    edit: (runs) => {
      at(runs, PASS_A).run_id = ANCHOR;
    },
    message: `row 1 ${ANCHOR} is no test run`,
  },
  {
    name: 'a repeated run id',
    edit: (runs) => {
      at(runs, FRONTIER).run_id = MID;
    },
    message: `row 5 repeats ${MID}`,
  },
  {
    name: 'an unknown status',
    edit: (runs) => {
      at(runs, MID).status = 'done';
    },
    message: 'row 4 has the status "done"',
  },
  {
    name: 'a not_run row without a reason',
    edit: (runs) => {
      at(runs, MID).status = 'not_run';
    },
    message: `${MID} is not_run with no reason`,
  },
  {
    name: 'a not_run row with an empty reason',
    edit: (runs) => {
      Object.assign(at(runs, MID), {status: 'not_run', reason: ''});
    },
    message: `${MID} is not_run with no reason`,
  },
  {
    name: 'no mid winner',
    edit: (runs) => {
      // Drops winner_mid and every row its condition chain reaches, so only
      // the planned roles are wrong.
      const dropped = new Set([MID]);
      for (const entry of runs.runs) {
        if (entry.conditional_on !== null && dropped.has(entry.conditional_on)) {
          dropped.add(entry.run_id);
        }
      }
      const kept = runs.runs.filter((each) => !dropped.has(each.run_id));
      runs.runs.splice(0, runs.runs.length, ...kept);
    },
    message: 'plans aa_pass_a, aa_pass_b, winner_small, winner_frontier, not',
  },
  {
    name: 'planned rows out of order',
    edit: (runs) => {
      const [small, mid] = runs.runs.slice(2, 4);
      if (small === undefined || mid === undefined) {
        throw new Error('the registry has no planned small and mid rows');
      }
      runs.runs.splice(2, 2, mid, small);
    },
    message: 'plans aa_pass_a, aa_pass_b, winner_mid, winner_small, winner_frontier, not',
  },
  {
    name: 'a planned row marked unused',
    edit: (runs) => {
      at(runs, MID).status = 'unused';
    },
    message: `${MID} is a planned row marked unused`,
  },
  {
    name: 'an unknown trigger',
    edit: (runs) => {
      at(runs, MID_FALLBACK).trigger = 'owner_wish';
    },
    message: `${MID_FALLBACK} has the trigger "owner_wish"`,
  },
  {
    name: 'a row that names itself',
    edit: (runs) => {
      at(runs, MID_FALLBACK).conditional_on = MID_FALLBACK;
    },
    message: `names ${MID_FALLBACK}, which is no other row`,
  },
  {
    name: 'a dangling named run',
    edit: (runs) => {
      at(runs, MID_FALLBACK).conditional_on = `test-x-${DATE}`;
    },
    message: `names test-x-${DATE}, which is no other row`,
  },
  {
    name: 'a trigger without a named run',
    edit: (runs) => {
      at(runs, MID_FALLBACK).conditional_on = null;
    },
    message: `${MID_FALLBACK} has a trigger or a named run without the other`,
  },
  {
    name: 'an unused row whose run holds a manifest',
    edit: () => undefined,
    files: [`docs/results/${MID_FALLBACK}/run_manifest.json`],
    message: `docs/results/${MID_FALLBACK} holds run_manifest.json, but its row is unused`,
  },
  {
    name: 'a registered row whose run holds a manifest',
    edit: (runs) => {
      at(runs, MID).status = 'registered';
    },
    files: [`docs/results/${MID}/run_manifest.json`],
    message: `docs/results/${MID} holds run_manifest.json, but its row is registered`,
  },
];

for (const broken of BROKEN) {
  test(`a registry with ${broken.name} is refused`, () => {
    const runs = registry();
    broken.edit(runs);
    commit(runs);
    for (const file of broken.files ?? []) {
      put(file, {run_id: file.split('/')[2]});
    }

    expect(() => new Resolver(root).shownRuns()).toThrow(broken.message);
  });
}

/** A Runs table that differs from the registry, and the first row that does. */
interface Noted {
  readonly name: string;
  readonly note: (rows: readonly Row[]) => string;
  readonly row: number;
}

/** The rows with the third and fourth exchanged. */
function swapped(rows: readonly Row[]): Row[] {
  return rows.map((entry, index) => {
    if (index === 2 || index === 3) {
      return rows[5 - index] ?? entry;
    }
    return entry;
  });
}

// The cases of test_a_note_that_differs_from_the_registry_fails.
const NOTED: readonly Noted[] = [
  {name: 'without a row', note: (rows) => note([...rows.slice(0, 3), ...rows.slice(4)]), row: 4},
  {name: 'with two rows swapped', note: (rows) => note(swapped(rows)), row: 3},
  {
    name: 'with another role',
    note: (rows) =>
      note(rows.map((entry, index) => (index === 3 ? {...entry, role: 'small'} : entry))),
    row: 4,
  },
  {
    name: "with pass A's run id only in prose",
    note: (rows) => note(rows.slice(1), 1, `Pass A's run id is \`${PASS_A}\`.`),
    row: 1,
  },
  {name: 'numbered from 0', note: (rows) => note(rows, 0), row: 1},
  {
    name: 'with an extra row',
    note: (rows) => note([...rows, row('fallback_frontier', `test-extra-${DATE}`, 'unused')]),
    row: 17,
  },
];

/** A ruling the exporter refuses, and the refusal the resolver gives. */
interface BrokenRuling {
  readonly name: string;
  readonly edit: (value: Ruling, runs: Registry) => void;
  readonly message: string;
}

// The cases of test_a_broken_ruling_fails, and a winner that is no run id.
const BROKEN_RULINGS: readonly BrokenRuling[] = [
  {
    name: 'another schema',
    edit: (value) => {
      value.schema = 'bakeoff-ruling/0.9';
    },
    message: `${RULING} is not bakeoff-ruling/1.0`,
  },
  {
    name: 'a slot without a winner',
    edit: (value) => {
      delete value.slots['mid']?.winner;
    },
    message: `${RULING} mid winner is not an object`,
  },
  {
    name: 'a winner that is no run id',
    edit: (value) => {
      value.slots['small'] = {winner: {run_id: `dev-Bad_X-${DATE}`}};
    },
    message: `${RULING} small winner "dev-Bad_X-${DATE}" is not a run id`,
  },
  {
    name: 'a test run as a winner',
    edit: (value) => {
      value.slots['small'] = {winner: {run_id: SMALL}};
    },
    message: `${RULING} small winner ${SMALL} is no dev run`,
  },
  {
    name: 'a winner the ranking does not show',
    edit: (value) => {
      value.slots['small'] = {winner: {run_id: `dev-x-${DATE}`}};
    },
    message: `${RULING} small winner dev-x-${DATE} is not shown`,
  },
  {
    name: 'a path outside the allowed roots',
    edit: (_, runs) => {
      runs.ruling = 'docs/decisions/model-bakeoff.md';
    },
    message: '"docs/decisions/model-bakeoff.md" is outside the allowed roots',
  },
];

// The exporter reads the ruling whenever the registry exists, so a broken
// one is refused in the test phase too, where the pool never uses it.
for (const phase of ['dev', 'test']) {
  for (const broken of BROKEN_RULINGS) {
    test(`a ${phase}-phase registry naming a ruling with ${broken.name} is refused`, () => {
      const runs = registry();
      if (phase === 'dev') {
        at(runs, FRONTIER).status = 'registered';
      }
      const value = ruling();
      broken.edit(value, runs);
      put(RULING, value);
      commit(runs);
      const resolver = new Resolver(root);

      expect(() => resolver.shownRuns()).toThrow(broken.message);
      expect(() => resolver.reelPool()).toThrow(broken.message);
    });
  }
}

for (const noted of NOTED) {
  test(`a registry note ${noted.name} is refused`, () => {
    const runs = registry();
    commit(runs);
    write(NOTE, noted.note(runs.runs));

    expect(() => new Resolver(root).shownRuns()).toThrow(`${NOTE} Runs row ${noted.row} is`);
  });
}

// reel-v1 step 5 is not built, so scored repair results for the pool stop
// the Reel, as they stop the exporter: a pool run's round summary, its
// scored counterexample arm or that arm's re-run, or the split's pool file.
const REPAIRED: readonly {readonly phase: string; readonly file: string}[] = [
  {phase: 'test', file: `docs/results/${PASS_A}/repair/summary.json`},
  {phase: 'test', file: `docs/results/test-pass-a-cx-${DATE}/scored/summary.json`},
  {phase: 'test', file: `docs/results/test-frontier-cx-r2-${DATE}/scored/summary.json`},
  {phase: 'test', file: 'docs/results/repair-pool/test.json'},
  {phase: 'dev', file: `docs/results/${ANCHOR}/repair/summary.json`},
  {phase: 'dev', file: `docs/results/dev-mid-cx-${DATE}/scored/summary.json`},
  {phase: 'dev', file: 'docs/results/repair-pool/dev.json'},
];

for (const {phase, file} of REPAIRED) {
  test(`scored repair results in ${file} stop the ${phase}-phase Reel`, () => {
    const runs = registry();
    if (phase === 'dev') {
      at(runs, FRONTIER).status = 'registered';
    }
    commit(runs);

    expect(new Resolver(root).reelPool()).toHaveLength(4);

    put(file, {schema: 'repair-summary/1.0'});

    expect(() => new Resolver(root).reelPool()).toThrow(`${file} holds scored repair results`);
  });
}

test('repair results outside the pool leave the Reel alone', () => {
  commit(registry());
  for (const file of [
    // Pass B is never pooled.
    `docs/results/${PASS_B}/repair/summary.json`,
    `docs/results/test-pass-b-cx-${DATE}/scored/summary.json`,
    // A dev pass and the dev split, in the test phase.
    `docs/results/${DEV_MID}/repair/summary.json`,
    'docs/results/repair-pool/dev.json',
  ]) {
    put(file, {schema: 'repair-summary/1.0'});
  }

  expect(new Resolver(root).reelPool()).toEqual([PASS_A, SMALL, MID, FRONTIER]);
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
  // The anchor's two answers tie with the small run's on frames: the earlier
  // pool run wins over the lower item, then the lower item over the higher.
  expect(resolver.reelPick()).toEqual({run: ANCHOR, cond: 'C4', item: 'mei-0002', candidates: 4});

  // With one frame fewer the later pool run's answer wins: frames decide
  // before pool position.
  answers(SMALL_PROVISIONAL, [
    ['C4', 'mei-0001', 'ready', 'silent_wrong', 1],
    ['C4', 'mei-0004', 'ready', 'strong_exact', 0],
  ]);

  expect(new Resolver(root).reelPick()).toEqual({
    run: SMALL_PROVISIONAL,
    cond: 'C4',
    item: 'mei-0001',
    candidates: 4,
  });

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
