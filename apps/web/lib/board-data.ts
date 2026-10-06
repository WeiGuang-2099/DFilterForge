/**
 * @fileoverview Reads board.json, the test results the board page shows.
 *
 * scripts/export_web_data.py writes the dev selection rows, the test pool's
 * rows with pass B as their rerun, the registry's not-run rows and the
 * pooled test repair round with each pool pass's round. This module checks
 * the document as lib/data.ts checks the others: its schema id and a closed
 * key set at every level. It also checks that the repair round's passes are
 * the test rows, in the same pool order, so the page never pairs a model's
 * repair numbers with another model's row.
 */

import 'server-only';

import {array, fail, flag, literal, load, nullable, numNode, object, strNode, text} from './data';
import type {Guarded} from './data';

// A value with its bootstrap interval; the exporter writes null for a
// metric or a bound the summary does not hold.
const INTERVAL = nullable(
  object({value: nullable(numNode), low: nullable(numNode), high: nullable(numNode)}),
);

const SEGMENTS = object({
  strong_exact: numNode,
  shortcut: numNode,
  silent_wrong: numNode,
  invalid: numNode,
  malformed: numNode,
  provider_failed: numNode,
  abstained: numNode,
});

const RUN = {
  run: text,
  run_id: strNode,
  model_id: strNode,
  providers: array(strNode),
  provider_reported_usd: nullable(numNode),
  charged_usd_upper_bound: nullable(numNode),
  items: numNode,
};

const SELECTION_ROW = object({
  ...RUN,
  ready: numNode,
  segments: SEGMENTS,
  slot: text,
  rank: nullable(numNode),
  verdict: nullable(strNode),
  run_gates: nullable(strNode),
  strong_exact_ready: numNode,
});

const TEST_ROW = object({
  ...RUN,
  role: text,
  conditions: array(
    object({
      label: strNode,
      metrics: object({
        strong_exact: INTERVAL,
        silent_wrong_all: INTERVAL,
        silent_wrong_of_executable: INTERVAL,
        compile_valid: INTERVAL,
        over_abstention: INTERVAL,
        false_ready: INTERVAL,
        slot_match: INTERVAL,
      }),
      ready: numNode,
      segments: SEGMENTS,
    }),
  ),
  comparisons: array(
    object({
      first: strNode,
      second: strNode,
      metric: strNode,
      difference: INTERVAL,
      discordant_cases: numNode,
      first_better_cases: numNode,
      second_better_cases: numNode,
      inconclusive: numNode,
    }),
  ),
});

// A repair round's arms and its comparisons by case, pooled or per pass.
const ROUND = {
  arms: array(
    object({arm: strNode, repair_at_1: INTERVAL, repaired: numNode, triggered: numNode}),
  ),
  comparisons: array(
    object({
      first: strNode,
      second: strNode,
      difference: INTERVAL,
      discordant: numNode,
      first_better: numNode,
      second_better: numNode,
      inconclusive: numNode,
    }),
  ),
};

const REPAIR = object({
  ...ROUND,
  bootstrap: object({
    cases: numNode,
    resamples: numNode,
    seed: numNode,
    min_discordant_cases: numNode,
  }),
  models: array(
    object({
      ...ROUND,
      run: text,
      role: text,
      model_id: strNode,
      triggered_items: numNode,
      triggered_cases: numNode,
      not_run: array(object({arm: text, reason: strNode})),
    }),
  ),
});

const BOARD = object({
  schema: literal('web-board/1.0'),
  selection: object({ranking: text, status: nullable(strNode), rows: array(SELECTION_ROW)}),
  test_registered: flag,
  test: nullable(
    object({
      rows: array(TEST_ROW),
      rerun: nullable(TEST_ROW),
      not_run: array(object({role: text, run_id: strNode, reason: strNode})),
      // The A/A pair is not wired in yet (docs/decisions/web-site.md).
      aa: (value, where) => (value === null ? null : fail(where, 'is not null')),
      repair: nullable(REPAIR),
    }),
  ),
});

/** board.json, checked. */
export type Board = Guarded<typeof BOARD>;

/** The test block: the pool's rows, pass B's rerun and the repair round. */
export type BoardTest = NonNullable<Board['test']>;

/** One test pool row. */
export type TestRow = BoardTest['rows'][number];

/** The test repair round. */
export type Repair = NonNullable<BoardTest['repair']>;

/** A repair round's arm. */
export type Arm = Repair['arms'][number];

/** A value with its interval, or null where the summary holds none. */
export type Interval = Arm['repair_at_1'];

/** A repair round's comparison. */
export type ArmComparison = Repair['comparisons'][number];

/** Returns board.json, checked, with the repair round's passes in row order. */
export function loadBoard(): Board {
  const board = load('board.json', BOARD);
  const repair = board.test?.repair;
  if (repair !== null && repair !== undefined) {
    const rows = board.test?.rows.map((row) => row.run).join('\n');
    if (repair.models.map((model) => model.run).join('\n') !== rows) {
      fail('board.json.test.repair.models', 'are not the test rows in pool order');
    }
  }
  return board;
}
