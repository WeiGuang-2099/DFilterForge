/**
 * @fileoverview Reads training.json, the SFT headline the training page shows.
 *
 * scripts/export_web_data.py writes it from docs/results/sft-v1/headline.json,
 * which scripts/sft_headline.py computes by the estimator docs/protocol.md
 * registers (Training rules, amended 2026-10-18); headline is null before
 * that file exists. Inside the headline sit three blocks, each null before
 * its file exists:
 * - baseline, the untrained-baseline ladder from
 *   docs/results/sft-v1/ladder.json;
 * - repair, the SFT seeds' test repair round, pooled in
 *   docs/results/repair-pool/test-qwen3-1.7b-sft.json, then each seed's own;
 * - cost, the sessions' cost from docs/results/sft-v1/cost.json.
 * The exporter refuses any of them that breaks a rule the page's fixed words
 * depend on. This module checks the document as lib/data.ts checks the
 * others, a schema id and a closed key set at every level, and that the rows
 * the page sets side by side are the same rows in the same order: the seeds
 * of every ladder, and the test and dev rows of the condition tables.
 */

import 'server-only';

import {ROUND} from './board-data';
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

// A step of the baseline ladder: its first row minus its second, by case.
const RUNG = object({
  difference: INTERVAL,
  first_better_cases: numNode,
  second_better_cases: numNode,
  discordant_cases: numNode,
  reading: strNode,
});

// A ladder row: its strong exact, its ready answers by outcome with the
// malformed ones split at the token cap, its field-coverage split, and its
// answers the client refused as too large.
const BASELINE_ROW = {
  rate: INTERVAL,
  outcomes: object({
    strong_exact: numNode,
    shortcut: numNode,
    silent_wrong: numNode,
    invalid: numNode,
    malformed: numNode,
    provider_failed: numNode,
    abstained: numNode,
  }),
  malformed: object({truncated: numNode, other: numNode}),
  coverage: object({every_gold_field_retrieved: INTERVAL, some_gold_field_missing: INTERVAL}),
  too_large: numNode,
};

// The untrained-baseline ladder: the base, schema and few-shot rows, the
// SFT seeds and their mean, and the three registered steps.
const BASELINE = object({
  condition: strNode,
  cases: numNode,
  items: numNode,
  bootstrap: object({seed: numNode, resamples: numNode, min_discordant_cases: numNode}),
  coverage_items: object({every_gold_field_retrieved: numNode, some_gold_field_missing: numNode}),
  token_cap: numNode,
  response_schema: strNode,
  examples: numNode,
  base: object(BASELINE_ROW),
  schema: object(BASELINE_ROW),
  few_shot: object(BASELINE_ROW),
  seeds: array(object({seed: numNode, ...BASELINE_ROW})),
  sft_mean: object({rate: INTERVAL}),
  rungs: object({
    schema_minus_base: RUNG,
    few_shot_minus_schema: RUNG,
    sft_mean_minus_few_shot: RUNG,
  }),
});

// The SFT seeds' test repair round: pooled by case, then each seed's own.
const SFT_REPAIR = object({
  ...ROUND,
  bootstrap: object({
    cases: numNode,
    resamples: numNode,
    seed: numNode,
    min_discordant_cases: numNode,
  }),
  seeds: array(
    object({...ROUND, seed: numNode, triggered_items: numNode, triggered_cases: numNode}),
  ),
});

// The sessions' cost. Money is the cost file's decimal strings; requests,
// GPU hours and run counts are numbers.
const COST = object({
  usd_per_gpu_hour: strNode,
  total: object({
    bill_usd: strNode,
    gpu_usd: strNode,
    usd_per_1000_requests: strNode,
    requests: numNode,
    gpu_hours: numNode,
  }),
  session_count: numNode,
  sessions: array(
    object({
      date: strNode,
      bill_usd: strNode,
      requests: numNode,
      gpu_hours: numNode,
      runs: numNode,
      unread: nullable(object({count: numNode, requests: numNode})),
    }),
  ),
  excluded: object({date: strNode, bill_usd: strNode}),
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
      baseline: nullable(BASELINE),
      repair: nullable(SFT_REPAIR),
      cost: nullable(COST),
    }),
  ),
});

/** training.json, checked. */
export type Training = Guarded<typeof TRAINING>;

/** The headline, present once the SFT rows are scored. */
export type Headline = NonNullable<Training['headline']>;

/** The untrained-baseline ladder. */
export type Baseline = NonNullable<Headline['baseline']>;

/** One of its rows. */
export type BaselineRow = Baseline['base'];

/** One of its steps. */
export type Rung = Baseline['rungs']['schema_minus_base'];

/** The SFT seeds' test repair round, pooled and per seed. */
export type SftRepair = NonNullable<Headline['repair']>;

/** The sessions' cost. */
export type Cost = NonNullable<Headline['cost']>;

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
