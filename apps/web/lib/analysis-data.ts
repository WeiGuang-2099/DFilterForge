/**
 * @fileoverview Reads analysis.json, the descriptive analyses of the
 * self-served rows that the analysis page and the board band show.
 *
 * scripts/export_web_data.py writes it from docs/results/sft-v1/analysis.json,
 * which scripts/sft_analysis.py computes by the rules docs/protocol.md
 * registers (Training rules, amended 2026-10-18); analysis is null before
 * that file exists. This module checks the document as lib/data.ts checks
 * the others, a schema id and a closed key set at every level, and that the
 * tables line up: one row for the base model and one per seed everywhere,
 * each class group adding up to its outcome, each seed's groups holding
 * every ready item once, and the classes and strata the page has words for.
 */

import 'server-only';

import {CLASS_OUTCOME, CLASSES, OUTCOMES, SIDES, STRATA} from './analysis-codes';
import type {Outcome} from './analysis-codes';
import {array, fail, literal, load, nullable, numNode, object, strNode, text} from './data';
import type {Guard, Guarded, NumNode} from './data';
import {RERUN} from './training-data';

/** A guard for one string of a closed list. */
function oneOf<T extends string>(values: readonly T[]): Guard<T> {
  return (value, where) =>
    typeof value === 'string' && (values as readonly string[]).includes(value)
      ? (value as T)
      : fail(where, `is not one of ${values.join(', ')}`);
}

const ENDS = object({low: numNode, high: numNode});

const ANSWER = object({
  outcome: strNode,
  filter: nullable(strNode),
  fields: nullable(array(strNode)),
  error_code: nullable(strNode),
  raw: nullable(strNode),
  question: nullable(strNode),
});

const EXAMPLE = object({
  item_id: strNode,
  case_id: strNode,
  request: strNode,
  reference: strNode,
  answer: ANSWER,
  disproof: nullable(
    object({
      probe: strNode,
      frame: numNode,
      name: strNode,
      side: oneOf(SIDES),
    }),
  ),
  file: text,
});

const ROW = object({
  run_id: strNode,
  outcomes: object(
    Object.fromEntries(OUTCOMES.map((outcome) => [outcome, numNode])) as Record<
      Outcome,
      Guard<NumNode>
    >,
  ),
  executed: numNode,
  classes: array(object({class: oneOf(CLASSES), count: numNode, example: nullable(EXAMPLE)})),
});

const RIBBON = object({
  from: oneOf(OUTCOMES),
  to: oneOf(OUTCOMES),
  count: numNode,
  items: array(object({item_id: strNode, case_id: strNode, answer: ANSWER})),
});

const COPIES = object({
  with_ir: numNode,
  copies: numNode,
  copies_exact: numNode,
  unlisted: numNode,
  unlisted_exact: numNode,
});

const ANALYSIS = object({
  schema: literal('web-analysis/1.0'),
  analysis: nullable(
    object({
      model_id: strNode,
      condition: strNode,
      items: numNode,
      cases: numNode,
      post_hoc: numNode,
      rerun_noise: RERUN,
      opening: object({
        loud: numNode,
        base_silent: numNode,
        base_exact: numNode,
        loud_ran: ENDS,
        loud_exact: ENDS,
        loud_silent: ENDS,
        silent_exact: ENDS,
        exact_silent: ENDS,
      }),
      seeds: array(numNode),
      rows: array(ROW),
      flows: array(array(RIBBON)),
      nearness: object({
        targets: numNode,
        strata: array(
          object({stratum: oneOf(STRATA), cases: numNode, items: numNode, rows: array(numNode)}),
        ),
        cases: array(
          object({
            case_id: strNode,
            stratum: oneOf(STRATA),
            atoms: numNode,
            request: strNode,
            reference: strNode,
            exact: array(numNode),
            nearest: object({id: strNode, request: strNode, filter: strNode, shared: numNode}),
          }),
        ),
      }),
      copies: array(object({every_gold_field_retrieved: COPIES, some_gold_field_missing: COPIES})),
      loss: array(
        object({
          seed: numNode,
          rows: numNode,
          epochs: numNode,
          steps: numNode,
          curve: array(object({step: numNode, loss: numNode})),
        }),
      ),
      band: object({
        rows: array(object({conditions: array(object({label: strNode, strong_exact: numNode}))})),
        mean: array(numNode),
      }),
    }),
  ),
});

/** analysis.json, checked. */
export type AnalysisDocument = Guarded<typeof ANALYSIS>;

/** The analyses, present once the analysis file is committed. */
export type Analysis = NonNullable<AnalysisDocument['analysis']>;

/** One row of the class table: the base model, then each seed. */
export type AnalysisRow = Analysis['rows'][number];

/** One class example, with its receipt. */
export type Example = NonNullable<AnalysisRow['classes'][number]['example']>;

/** The answers one base outcome led to under one seed. */
export type Ribbon = Analysis['flows'][number][number];

/** One answer to a ready item. */
export type Answer = Example['answer'];

/** One test case and the training target shown beside it. */
export type NearCase = Analysis['nearness']['cases'][number];

/** A count, as a number, or a build failure naming where. */
export function counted(node: NumNode, where: string): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    fail(where, `holds ${JSON.stringify(node.v)}, not a count`);
  }
  return node.v;
}

function check(analysis: Analysis): void {
  const rows = analysis.rows.length;
  const items = counted(analysis.items, 'analysis.json.items');
  if (analysis.post_hoc.v !== true) {
    fail('analysis.json.post_hoc', 'is not true; the classes and strata are post hoc');
  }
  if (rows !== analysis.seeds.length + 1 || analysis.flows.length !== analysis.seeds.length) {
    fail('analysis.json', 'does not give the base row and one row per seed');
  }
  const tables = [
    analysis.copies.length,
    analysis.band.rows.length,
    ...analysis.nearness.strata.map((stratum) => stratum.rows.length),
    ...analysis.nearness.cases.map((item) => item.exact.length),
  ];
  if (tables.some((length) => length !== rows) || analysis.loss.length !== rows - 1) {
    fail('analysis.json', 'has a table with other rows than the class table');
  }
  for (const [index, row] of analysis.rows.entries()) {
    const where = `analysis.json.rows[${index}]`;
    if (row.classes.map((each) => each.class).join() !== CLASSES.join()) {
      fail(where, 'does not list the registered classes in order');
    }
    for (const outcome of OUTCOMES) {
      const sum = row.classes
        .filter((each) => CLASS_OUTCOME[each.class] === outcome)
        .reduce((total, each) => total + counted(each.count, where), 0);
      if (sum !== counted(row.outcomes[outcome], where)) {
        fail(where, `has classes that do not add up to its ${outcome} count`);
      }
    }
  }
  for (const [index, ribbons] of analysis.flows.entries()) {
    const where = `analysis.json.flows[${index}]`;
    const listed = ribbons.flatMap((ribbon) => ribbon.items.map((item) => item.item_id.t));
    if (new Set(listed).size !== items || listed.length !== items) {
      fail(where, 'does not hold every ready item once');
    }
    if (ribbons.some((ribbon) => counted(ribbon.count, where) !== ribbon.items.length)) {
      fail(where, 'has a group whose count is not its items');
    }
  }
}

/** Returns analysis.json, checked. */
export function loadAnalysis(): AnalysisDocument {
  const document = load('analysis.json', ANALYSIS);
  if (document.analysis !== null) {
    check(document.analysis);
  }
  return document;
}
