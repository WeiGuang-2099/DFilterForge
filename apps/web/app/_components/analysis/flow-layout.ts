/**
 * @fileoverview The geometry of the flow figure, in its view box's units.
 *
 * A row's outcome blocks stack from the top in the board's order, each as
 * tall as its count; a ribbon joins its two blocks, stacked in order at
 * both ends; labels keep a step apart inside the figure. Pure functions of
 * the sourced counts: no value shown on the page comes from here.
 */

import {OUTCOMES} from '@/lib/analysis-codes';
import type {Outcome} from '@/lib/analysis-codes';
import type {Ribbon} from '@/lib/analysis-data';
import type {NumNode} from '@/lib/data';

// The figure's units: its view box, the blocks, their gaps and the room a
// label needs. The labels sit outside the blocks, left and right.
export const WIDTH = 760;
export const HEIGHT = 400;
const TOP = 30;
const BOTTOM = 6;
const GAP = 12;
export const BLOCK = 14;
export const LEFT = 200;
export const RIGHT = WIDTH - LEFT - BLOCK;
const LABEL_STEP = 34;
const LABEL_HALF = 17;
export const LABEL_SPACE = 10;
// A block of one answer is still drawn this tall.
export const MIN_BLOCK = 1;
export const VIEW_BOX = `0 0 ${WIDTH} ${HEIGHT}`;

/** The outcome counts of one row. */
export type Counts = Readonly<Record<Outcome, NumNode>>;

/** One seed's answers, grouped by what the base model did with each. */
export interface SeedFlow {
  readonly seed: NumNode;
  readonly counts: Counts;
  readonly ribbons: readonly Ribbon[];
}

/** View-box units per answer, so a column of blocks fits with its gaps. */
export function unitsPerAnswer(blocks: number, answers: number): number {
  return (HEIGHT - TOP - BOTTOM - GAP * (blocks - 1)) / answers;
}

/** A sourced count as a number, or a build failure. */
export function count(node: NumNode): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    throw new Error(`analysis: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

export interface Block {
  readonly outcome: Outcome;
  readonly y: number;
  readonly height: number;
  readonly label: number;
}

/** Keeps label centres a step apart and inside the figure, in order. */
function spread(centres: readonly number[]): number[] {
  const out = [...centres];
  for (let index = 1; index < out.length; index += 1) {
    out[index] = Math.max(out[index] ?? 0, (out[index - 1] ?? 0) + LABEL_STEP);
  }
  const over = (out[out.length - 1] ?? 0) + LABEL_HALF - HEIGHT;
  if (over > 0) {
    for (let index = out.length - 1; index >= 0; index -= 1) {
      const next = out[index + 1];
      const moved = (out[index] ?? 0) - over;
      out[index] = next === undefined ? moved : Math.min(out[index] ?? 0, next - LABEL_STEP);
    }
  }
  return out;
}

/** Stacks a row's non-empty outcomes from the top, in the board's order. */
export function stack(counts: Counts, scale: number): Block[] {
  let y = TOP;
  const blocks: {outcome: Outcome; y: number; height: number}[] = [];
  for (const outcome of OUTCOMES) {
    const height = count(counts[outcome]) * scale;
    if (height > 0) {
      blocks.push({outcome, y, height});
      y += height + GAP;
    }
  }
  const labels = spread(blocks.map((block) => block.y + block.height / 2));
  return blocks.map((block, index) => ({...block, label: labels[index] ?? block.y}));
}

export function blocksOf(counts: Counts): number {
  return OUTCOMES.filter((outcome) => count(counts[outcome]) > 0).length;
}

interface Drawn {
  readonly from: Outcome;
  readonly to: Outcome;
  readonly path: string;
}

/** Places each ribbon, stacked in order at both of its blocks. */
export function draw(left: Block[], right: Block[], ribbons: readonly Ribbon[], scale: number): Drawn[] {
  const start = new Map(left.map((block) => [block.outcome, block.y]));
  const end = new Map(right.map((block) => [block.outcome, block.y]));
  const x0 = LEFT + BLOCK;
  const x1 = RIGHT;
  const middle = (x0 + x1) / 2;
  return ribbons.map((ribbon) => {
    const height = count(ribbon.count) * scale;
    const y0 = start.get(ribbon.from);
    const y1 = end.get(ribbon.to);
    if (y0 === undefined || y1 === undefined) {
      throw new Error(`analysis: a ribbon from ${ribbon.from} to ${ribbon.to} has no block`);
    }
    start.set(ribbon.from, y0 + height);
    end.set(ribbon.to, y1 + height);
    const path =
      `M${x0},${y0} C${middle},${y0} ${middle},${y1} ${x1},${y1} ` +
      `L${x1},${y1 + height} C${middle},${y1 + height} ${middle},${y0 + height} ` +
      `${x0},${y0 + height} Z`;
    return {from: ribbon.from, to: ribbon.to, path};
  });
}

/** The ribbon a seed opens on: refused answers that now run wrongly, if any. */
export function opening(ribbons: readonly Ribbon[]): number {
  const found = ribbons.findIndex((each) => each.from === 'invalid' && each.to === 'silent_wrong');
  return Math.max(found, 0);
}

export function percent(value: number, whole: number): string {
  return `${(value / whole) * 100}%`;
}
