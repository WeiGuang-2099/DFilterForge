/**
 * @fileoverview Checks that the parts of exhibits.json line up, and reads
 * a count or a verdict pair or fails the build.
 *
 * lib/exhibits-data.ts checks the document's shape and codes, re-exports
 * counted and pairOf, and calls checkReplay: every count the page shows
 * must hold as many entries as it counts, with a square per replayed
 * answer; each probe's frame table must list its frames in order, since a
 * frame's number finds its row; each turned square must point at the one
 * exhibit answer it is, and each such answer must be pointed at; each
 * strip must score the replayed probes in their order and agree with the
 * labels on every benchmark frame, which is what the page says the
 * captures alone saw; and the cases only the tail can score must label
 * the same probes.
 */

import 'server-only';

import {fail} from './data';
import type {NumNode} from './data';
import {PAIRS} from './exhibits-codes';
import type {Pair} from './exhibits-codes';
// Types only: the guard imports this module, never the other way at run time.
import type {Replay, ReplayProbe, Square, Strip} from './exhibits-data';

/** A count, as a number, or a build failure naming where. */
export function counted(node: NumNode, where: string): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    fail(where, `holds ${JSON.stringify(node.v)}, not a count`);
  }
  return node.v;
}

/** A square's verdict pair, as PAIRS lists it. */
export function pairOf(square: Square): Pair {
  const pair = `${square.alone.t}/${square.tail.t}`;
  return PAIRS.find((each) => each === pair) ?? fail('exhibits.json', `holds ${pair}`);
}

function checkStrip(strip: Strip, probe: ReplayProbe | undefined, where: string): void {
  const bench = counted(strip.benchmark_frames, where);
  if (probe === undefined || strip.probe_id.t !== probe.probe_id.t) {
    fail(where, 'does not score the replayed probes in their order');
  }
  if (strip.frames.v !== probe.frames.v || bench !== probe.benchmark_frames.v) {
    fail(where, 'counts other frames than its probe table');
  }
  const early = strip.states.slice(0, bench).some((state) => state === 'fp' || state === 'fn');
  if (strip.states.length !== strip.frames.v || early) {
    fail(where, 'does not agree with the labels on every benchmark frame');
  }
  if (strip.disagree.some((each) => counted(each.n, where) <= bench)) {
    fail(where, 'parts from the labels before the tail');
  }
}

export function checkReplay(replay: Replay): void {
  const {counts} = replay;
  const sizes: [number, NumNode, string][] = [
    [replay.rows.length, counts.runs, 'rows'],
    [replay.probes.length, counts.probes, 'probes'],
    [replay.exhibits.length, counts.exhibits, 'exhibits'],
    [replay.tail_only.cases.length, counts.tail_only, 'tail_only.cases'],
    [replay.rows.reduce((sum, row) => sum + row.squares.length, 0), counts.answers, 'squares'],
  ];
  for (const [length, node, where] of sizes) {
    if (length !== counted(node, `exhibits.json.${where}`)) {
      fail(`exhibits.json.${where}`, 'does not hold as many entries as its count');
    }
  }
  replay.probes.forEach((probe, at) => {
    const rows = probe.frame_rows;
    if (rows.length !== probe.frames.v || rows.some((row, n) => row.n.v !== n + 1)) {
      fail(`exhibits.json.probes[${at}]`, 'does not list its frames in order, one per frame');
    }
  });
  const pointed = new Set<string>();
  replay.rows.forEach((row, at) => {
    const where = `exhibits.json.rows[${at}]`;
    if (row.squares.length !== counted(row.answers, where)) {
      fail(where, 'does not hold one square per answer');
    }
    for (const square of row.squares) {
      pairOf(square);
      if (square.turned !== null) {
        const {exhibit, answer} = square.turned;
        const target = replay.exhibits[exhibit]?.answers[answer];
        const named = [row.run_id, square.condition, square.item_id].map((node) => node.t);
        const found = [target?.run_id, target?.condition, target?.item_id].map((node) => node?.t);
        if (found.join(' ') !== named.join(' ')) {
          fail(where, `points ${named.join(' ')} at another exhibit answer`);
        }
        pointed.add(`${exhibit} ${answer}`);
      }
    }
  });
  if (pointed.size !== counted(replay.turned, 'exhibits.json.turned')) {
    fail('exhibits.json', 'turns other answers than its squares point at');
  }
  replay.exhibits.forEach((exhibit, at) => {
    const where = `exhibits.json.exhibits[${at}]`;
    if (exhibit.answers.length !== counted(exhibit.turned, where)) {
      fail(where, 'does not hold one answer per answer it turns');
    }
    exhibit.answers.forEach((answer, place) => {
      const here = `${where}.answers[${place}]`;
      if (!pointed.has(`${at} ${place}`) || answer.probes.length !== replay.probes.length) {
        fail(here, 'is no square of a row, or scores other probes');
      }
      answer.probes.forEach((strip, p) => checkStrip(strip, replay.probes[p], `${here}[${p}]`));
    });
  });
  const probes = replay.probes.map((probe) => probe.probe_id.t).join();
  replay.tail_only.cases.forEach((item, at) => {
    if (item.probes.map((probe) => probe.probe_id.t).join() !== probes) {
      fail(`exhibits.json.tail_only.cases[${at}]`, 'labels other probes than the replay');
    }
  });
}
