/**
 * @fileoverview Reads exhibits.json: the Reel pool's test answers replayed on
 * the test captures without their witness tail, for /exhibits.
 *
 * scripts/export_web_data.py writes it from the committed replay and its
 * readings; replay is null outside the test phase or before the replay is
 * committed. This module checks the document as lib/data.ts checks the
 * others, a schema id and a closed key set at every level, and every code
 * against lib/exhibits-codes.ts; lib/exhibits-check.ts then checks that
 * its parts line up.
 */

import 'server-only';

import {array, fail, literal, load, nullable, numNode, object, strNode, text} from './data';
import type {Guard, Guarded, NumNode, StrNode} from './data';
import {checkReplay} from './exhibits-check';
import * as codes from './exhibits-codes';

export {counted, pairOf} from './exhibits-check';

// A case id names an element and an address on the page.
const CASE_ID = /^[a-z][a-z0-9-]*$/;

/** A sourced string whose text is one of a closed list of codes. */
export interface CodeNode<T extends string> extends StrNode {
  readonly t: T;
}

function oneOf<T extends string>(values: readonly T[]): Guard<T> {
  return (value, where) =>
    typeof value === 'string' && (values as readonly string[]).includes(value)
      ? (value as T)
      : fail(where, `is not one of ${values.join(', ')}`);
}

function code<T extends string>(values: readonly T[]): Guard<CodeNode<T>> {
  return (value, where) => {
    const node = strNode(value, where);
    oneOf(values)(node.t, `${where}.t`);
    return node as CodeNode<T>;
  };
}

const index: Guard<number> = (value, where) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value
    : fail(where, 'is not an index');

const caseId: Guard<string> = (value, where) => {
  const found = text(value, where);
  return CASE_ID.test(found) ? found : fail(where, 'is not a case id');
};

/** A count per code of a list, keyed by the code. */
function counts<T extends string>(list: readonly T[]) {
  const shape = Object.fromEntries(list.map((each) => [each, numNode]));
  return object(shape as Record<T, Guard<NumNode>>);
}

const TAIL_COUNTS = counts(codes.TAIL);
const VERDICTS = {
  alone: counts(codes.ALONE),
  tail: TAIL_COUNTS,
  turned: numNode,
  turned_exact: numNode,
  turned_shortcut: numNode,
};

const FRAME_ROW = object({
  n: numNode,
  kind: code(codes.FRAME_KINDS),
  name: strNode,
  time: strNode,
  source: strNode,
  destination: strNode,
  protocol: strNode,
  length: numNode,
  info: strNode,
  dir: oneOf(codes.DIRECTIONS),
});

const PROBE = object({
  probe_id: strNode,
  frames: numNode,
  benchmark_frames: numNode,
  tail_frames: numNode,
  alone_sha256: strNode,
  tail_sha256: strNode,
  client: strNode,
  frame_rows: array(FRAME_ROW),
});

const SQUARE = object({
  condition: strNode,
  item_id: strNode,
  case_id: strNode,
  alone: code(codes.ALONE),
  tail: code(codes.TAIL),
  receipt: text,
  turned: nullable(object({exhibit: index, answer: index})),
});

const ROW = object({
  run: text,
  run_id: strNode,
  model_id: strNode,
  role: oneOf(codes.ROLES),
  answers: numNode,
  ...VERDICTS,
  squares: array(SQUARE),
});

const STRIP = object({
  probe_id: strNode,
  exact: numNode,
  runtime_ms: nullable(numNode),
  frames: numNode,
  benchmark_frames: numNode,
  expected: numNode,
  candidate: numNode,
  states: array(oneOf(codes.STATES)),
  disagree: array(
    object({side: oneOf(codes.SIDES), n: numNode, name: strNode, kind: code(codes.FRAME_KINDS)}),
  ),
  disagreeing: numNode,
});

const ANSWER = object({
  run: text,
  role: oneOf(codes.ROLES),
  run_id: strNode,
  model_id: strNode,
  condition: strNode,
  item_id: strNode,
  contract: code(codes.CONTRACTS),
  retrieval: code(codes.RETRIEVALS),
  request: strNode,
  reference: strNode,
  filter: strNode,
  // The captures alone accept every turned answer; the tail finds it wrong.
  alone: code(codes.ACCEPTED),
  tail: code(['silent_wrong'] as const),
  receipt: text,
  sha256: strNode,
  addendum: nullable(strNode),
  disagreeing: numNode,
  probes: array(STRIP),
});

const EXHIBIT = object({
  case: caseId,
  case_id: strNode,
  reading: strNode,
  turned: numNode,
  witnesses: array(strNode),
  notes: array(object({witnesses: array(strNode), note: strNode})),
  spec: text,
  answers: array(ANSWER),
});

const TAIL_ONLY = object({
  case: caseId,
  case_id: strNode,
  intent: strNode,
  reference: strNode,
  spec: text,
  answers: numNode,
  tail: TAIL_COUNTS,
  probes: array(
    object({
      probe_id: strNode,
      capture_sha256: strNode,
      frames: numNode,
      benchmark_frames: numNode,
      expected: array(object({n: numNode, name: strNode})),
    }),
  ),
});

const COUNTS = counts([
  'answers',
  'runs',
  'probes',
  'tail_only',
  'tail_frames',
  'exhibits',
  'killing_witnesses',
] as const);

const EXHIBITS = object({
  schema: literal('web-exhibits/1.0'),
  replay: nullable(
    object({
      counts: COUNTS,
      ...VERDICTS,
      notes: array(strNode),
      probes: array(PROBE),
      rows: array(ROW),
      exhibits: array(EXHIBIT),
      tail_only: object({tail: TAIL_COUNTS, cases: array(TAIL_ONLY)}),
    }),
  ),
});

/** exhibits.json, checked. */
export type ExhibitsDocument = Guarded<typeof EXHIBITS>;
/** The replay, present in the test phase once it is committed. */
export type Replay = NonNullable<ExhibitsDocument['replay']>;
/** One replayed probe with every frame of its capture. */
export type ReplayProbe = Replay['probes'][number];
/** One pool pass: its counts and one square per replayed answer. */
export type ReplayRow = Replay['rows'][number];
/** One replayed answer as a square. */
export type Square = ReplayRow['squares'][number];
/** One test case whose answers the tail turns. */
export type Exhibit = Replay['exhibits'][number];
/** One answer the tail turns, with its strips. */
export type ExhibitAnswer = Exhibit['answers'][number];
/** One probe of a turned answer: its frame states and killing frames. */
export type Strip = ExhibitAnswer['probes'][number];

/** Returns exhibits.json, checked, its parts lined up (lib/exhibits-check.ts). */
export function loadExhibits(): ExhibitsDocument {
  const document = load('exhibits.json', EXHIBITS);
  if (document.replay !== null) {
    checkReplay(document.replay);
  }
  return document;
}
