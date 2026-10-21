/**
 * @fileoverview Reads training.json, the SFT headline the training page shows.
 *
 * scripts/export_web_data.py writes it from docs/results/sft-v1/headline.json,
 * which scripts/sft_headline.py computes by the estimator docs/protocol.md
 * registers (Training rules, amended 2026-10-18); headline is null before
 * that file exists. This module checks the document as lib/data.ts checks
 * the others, a schema id and a closed key set at every level, and that the
 * rows the page sets side by side are the same rows in the same order: the
 * seeds of every ladder, and the test and dev rows of the condition tables.
 */

import 'server-only';

import {array, fail, literal, load, nullable, numNode, object, strNode, text} from './data';
import type {Guarded} from './data';

const INTERVAL = object({value: numNode, low: numNode, high: numNode});

// A paired difference against the base row; a stratum's has no reading.
const PAIRED = {
  difference: INTERVAL,
  first_better_cases: numNode,
  second_better_cases: numNode,
  discordant_cases: numNode,
  reading: nullable(strNode),
};

const LADDER = {
  base: INTERVAL,
  mean: object({rate: INTERVAL, ...PAIRED}),
  seeds: array(object({seed: numNode, rate: INTERVAL, ...PAIRED})),
};

const ROW = object({
  run_id: strNode,
  conditions: array(object({label: strNode, strong_exact: numNode, provider_failed: numNode})),
});

/**
 * Seed 2026's test pass sent again, from the pair report the headline names:
 * the report's path, the seed and the two run ids, the answers changed over
 * every condition, and the trained condition's changed answers and flipped
 * ready cases. The analysis page reads the same block.
 */
export const RERUN = object({
  report: strNode,
  seed: numNode,
  first_run: strNode,
  second_run: strNode,
  changed_answers: numNode,
  items: numNode,
  trained: object({
    condition: strNode,
    changed_answers: numNode,
    flipped_cases: numNode,
    ready_cases: numNode,
  }),
});

const TRAINING = object({
  schema: literal('web-training/1.0'),
  headline: nullable(
    object({
      model_id: strNode,
      condition: strNode,
      cases: numNode,
      items: numNode,
      bootstrap: object({seed: numNode, resamples: numNode, min_discordant_cases: numNode}),
      ...LADDER,
      coverage: array(object({stratum: text, items: numNode, ...LADDER})),
      hosted: array(object({model_id: strNode, rate: INTERVAL, ...PAIRED})),
      rerun_noise: RERUN,
      cases_detail: array(object({case_id: strNode, base: numNode, seeds: array(numNode)})),
      test: array(ROW),
      dev: array(ROW),
    }),
  ),
});

/** training.json, checked. */
export type Training = Guarded<typeof TRAINING>;

/** The headline, present once the SFT rows are scored. */
export type Headline = NonNullable<Training['headline']>;

/** A rate or a difference with its interval. */
export type Interval = Headline['base'];

/** One seed of a ladder. */
export type Seed = Headline['seeds'][number];

/** One row of a condition table. */
export type ConditionRow = Headline['test'][number];

function seedsOf(seeds: readonly Seed[]): string {
  return seeds.map((seed) => JSON.stringify(seed.seed.v)).join(',');
}

/** Returns training.json, checked, with every ladder's seeds in one order. */
export function loadTraining(): Training {
  const training = load('training.json', TRAINING);
  const headline = training.headline;
  if (headline === null) {
    return training;
  }
  const seeds = seedsOf(headline.seeds);
  for (const stratum of headline.coverage) {
    if (seedsOf(stratum.seeds) !== seeds) {
      fail(`training.json.coverage.${stratum.stratum}`, 'has other seeds than the headline');
    }
  }
  const rows = headline.seeds.length + 1;
  if (headline.test.length !== rows || headline.dev.length !== rows) {
    fail('training.json', 'does not give the base row and each seed on test and dev');
  }
  for (const item of headline.cases_detail) {
    if (item.seeds.length !== headline.seeds.length) {
      fail('training.json.cases_detail', 'does not count every seed');
    }
  }
  return training;
}
