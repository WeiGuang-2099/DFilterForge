/**
 * @fileoverview Reads reel.json, the Disproof Reel that rule reel-v1 picks.
 *
 * scripts/export_web_data.py projects the Reel (docs/decisions/
 * disproof-reel.md); this module checks the document as lib/data.ts checks
 * the others: its schema id and a closed key set at every level. The codes
 * the page shows as words or draws, a strip's frame states, a frame's
 * direction, the trace reason and the repair reason, are checked against
 * closed lists here, so an unknown code fails the build instead of reaching
 * a page.
 */

import 'server-only';

import {array, fail, flag, literal, load, nullable, numNode, object, strNode, text} from './data';
import type {Guard, Guarded} from './data';

/**
 * A frame's state on one probe: whether the filter selected it and whether
 * the request did. tp both, fp the filter only, fn the request only, tn
 * neither; fp and fn are the frames that disprove the filter.
 */
export type FrameState = 'tp' | 'fp' | 'fn' | 'tn';

/** Where a frame goes from the probe's client address (packets.json). */
export type Direction = 'out' | 'in' | 'other';

/** A guard for one of a closed list of codes. */
function oneOf<T extends string>(codes: readonly T[], name: string): Guard<T> {
  return (value, where) =>
    codes.includes(value as T) ? (value as T) : fail(where, `is not a ${name}`);
}

const state = oneOf<FrameState>(['tp', 'fp', 'fn', 'tn'], 'frame state');
const direction = oneOf<Direction>(['out', 'in', 'other'], 'direction');

const index: Guard<number> = (value, where) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? value
    : fail(where, 'is not an index');

// A predicate trace: per probe, the frames it traced, those where the
// answer and the labels disagree, and each leaf of both filters with the
// traced frames tshark matched it on.
const LEAF = object({filter: strNode, matched: numNode});
const TRACE = object({
  path: text,
  sha256: strNode,
  probes: array(
    object({probe_id: strNode, frames: numNode, filter: array(LEAF), request: array(LEAF)}),
  ),
});

// Why the Reel shows no trace, and why it shows no repair turn, as the
// fixed words a page shows for each code.
const TRACE_REASONS: Readonly<Record<string, string>> = {
  not_traced: 'not traced',
  trace_limit: 'not traced: the trace reached its limit',
};
const REPAIR_REASONS: Readonly<Record<string, string>> = {
  no_round: 'no repair round is scored for this pass yet',
};

function words(table: Readonly<Record<string, string>>, list: string): Guard<string> {
  return (value, where) =>
    typeof value === 'string' && Object.hasOwn(table, value)
      ? (table[value] ?? fail(where, `is no known ${list}`))
      : fail(where, `is no known ${list}`);
}

const PROBE = {
  probe_id: strNode,
  exact: numNode,
  runtime_ms: nullable(numNode),
  frames: numNode,
  benchmark_frames: numNode,
  expected: numNode,
  candidate: numNode,
  states: array(state),
  disagree: array(object({side: text, n: numNode, name: strNode, kind: strNode})),
};

const STRIP = object(PROBE);

// The pick's strips also list every frame, which the cursor reads: its
// number, kind and name from captures.json and its packet-list columns
// and direction from packets.json.
const PICK_STRIP = object({
  ...PROBE,
  client: strNode,
  frame_rows: array(
    object({
      n: numNode,
      kind: strNode,
      name: strNode,
      time: strNode,
      source: strNode,
      destination: strNode,
      protocol: strNode,
      length: numNode,
      info: strNode,
      dir: direction,
    }),
  ),
});

const HEADER = {model_id: strNode, run: text, run_id: strNode};
const RUN = {...HEADER, role: text};

const SEGMENTS = object({
  strong_exact: numNode,
  shortcut: numNode,
  silent_wrong: numNode,
  invalid: numNode,
  malformed: numNode,
  provider_failed: numNode,
  abstained: numNode,
});

const TURN = object({
  item: text,
  run_id: strNode,
  model_id: strNode,
  request: strNode,
  base_outcome: strNode,
  card_kind: strNode,
  card: nullable(strNode),
  outcome: strNode,
  filter: nullable(strNode),
  raw: nullable(strNode),
  raw_truncated: flag,
  strips: array(STRIP),
});

const REEL = object({
  schema: literal('web-reel/1.0'),
  rule: literal('reel-v1'),
  phase: text,
  pool: array(object(RUN)),
  candidate_condition: nullable(text),
  candidates: numNode,
  pick: nullable(
    object({
      ...HEADER,
      cond: text,
      item: text,
      case: text,
      provider: nullable(strNode),
      condition: strNode,
      request: strNode,
      answer: object({fields: array(strNode), filter: strNode}),
      reference_filter: strNode,
      outcome: strNode,
      disagreeing: numNode,
      joins: object({filter: nullable(strNode), request: strNode}),
    }),
  ),
  strips: array(PICK_STRIP),
  highlight: nullable(
    object({
      probe: index,
      probe_id: strNode,
      frame: numNode,
      name: strNode,
      kind: strNode,
      filter_selects: flag,
      request_selects: flag,
    }),
  ),
  trace: nullable(TRACE),
  trace_reason: nullable(words(TRACE_REASONS, 'trace reason')),
  receipt_panel: nullable(
    object({
      sha256: strNode,
      packet_set_hash: strNode,
      replay: array((value, where) => (typeof value === 'string' ? value : strNode(value, where))),
      repair: nullable(strNode),
    }),
  ),
  repair_applies: nullable(flag),
  repair: nullable(
    object({reason: nullable(words(REPAIR_REASONS, 'repair reason')), turn: nullable(TURN)}),
  ),
  training: (value, where) => (value === null ? null : fail(where, 'is not null')),
  board: array(object({...RUN, ready: numNode, segments: SEGMENTS})),
  headline: object({compiled: numNode, silent_wrong: numNode}),
  inputs_sha256: text,
});

/** reel.json, checked; trace_reason and repair.reason hold fixed words. */
export type Reel = Guarded<typeof REEL>;

/** One of the pick's strips, with every frame listed. */
export type PickStrip = Reel['strips'][number];

/** One strip of the repair turn's answer. */
export type TurnStrip = Guarded<typeof STRIP>;

/** The pick's predicate trace, one entry per strip. */
export type Trace = Guarded<typeof TRACE>;

/** Returns reel.json, checked, with each strip's frames in order. */
export function loadReel(): Reel {
  const reel = load('reel.json', REEL);
  reel.strips.forEach((strip, at) => {
    const where = `reel.json.strips[${at}]`;
    const rows = strip.frame_rows;
    if (rows.length !== strip.states.length || rows.some((row, n) => row.n.v !== n + 1)) {
      fail(where, 'does not list its frames in order, one per state');
    }
  });
  if (reel.trace !== null && reel.trace.probes.length !== reel.strips.length) {
    fail('reel.json.trace', 'does not trace each strip');
  }
  return reel;
}
