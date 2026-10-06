/**
 * @fileoverview A probe bar: one capture drawn as a thin strip of frames.
 *
 * One three-pixel cell per frame: the benchmark's recipe frames filled,
 * the witness tail outlined, and each frame where the answer and the
 * labels disagree in carmine, as the chosen prototype draws its probes.
 * The Reel's mini-map and the repair turn's second answer use it. The SVG
 * carries no text; the probe ids and numbers beside it are sourced values.
 */

import type {FrameState, PickStrip, TurnStrip} from '@/lib/reel-data';

// One frame's width and the bar's height, in pixels.
export const CELL = 3;
const HEIGHT = 10;

/** The request selects the frame. */
export const REQUESTED: ReadonlySet<FrameState> = new Set(['tp', 'fn']);
/** The filter selects the frame. */
export const SELECTED: ReadonlySet<FrameState> = new Set(['tp', 'fp']);
/** The filter and the request disagree on the frame. */
export const DISAGREES: ReadonlySet<FrameState> = new Set(['fp', 'fn']);

/** A count a sourced node holds, which the guard leaves typed loosely. */
export function count(node: {readonly v: unknown}): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v)) {
    throw new Error(`strips: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

/** One capture as a bar of frame cells. */
export function ProbeBar({strip}: {readonly strip: PickStrip | TurnStrip}) {
  const width = strip.states.length * CELL;
  const recipe = count(strip.benchmark_frames) * CELL;
  // The witness tail's outline, inset half a pixel to stay inside the bar.
  const tail = {x: recipe + 0.5, width: width - recipe - 1, height: HEIGHT - 1};
  return (
    <svg
      aria-hidden="true"
      className="pb"
      focusable="false"
      height={HEIGHT}
      viewBox={`0 0 ${width} ${HEIGHT}`}
      width={width}
    >
      <rect className="pb-r" height={HEIGHT} width={recipe} />
      {width > recipe ? (
        <rect className="pb-w" height={tail.height} width={tail.width} x={tail.x} y={0.5} />
      ) : null}
      {strip.states.map((state, column) =>
        DISAGREES.has(state) ? (
          <rect className="pb-d" height={HEIGHT} key={column} width={CELL} x={column * CELL} />
        ) : null,
      )}
    </svg>
  );
}
