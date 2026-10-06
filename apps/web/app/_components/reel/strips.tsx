/**
 * @fileoverview Capture strips drawn as logic-analyser lanes.
 *
 * One row per scored probe, one column per frame: a row of packet cells,
 * recipe frames filled and witness frames light, with the request lane
 * above it, high on the frames the request selects, and the filter lane
 * below, high on the frames the filter selects, both read from the
 * receipt's frame states. A frame where they differ disproves the filter
 * and is drawn in carmine, with a dashed pulse where the filter missed it
 * or a solid one where it took a frame too many. Every strip of a figure shares one column scale, so the
 * cursor reads the same frame number on all of them. The SVG carries no
 * text; every number beside it is a sourced value.
 */

import type {CSSProperties, ReactNode} from 'react';

import type {FrameState, PickStrip, TurnStrip} from '@/lib/reel-data';
import {Num, Str} from '@/lib/sourced';

// viewBox units: one frame column, the strip's height, each lane's high
// and low levels, and the row of packet cells between the two lanes. Only
// x stretches with the plot's width; strokes stay one pixel wide.
const PITCH = 10;
const HEIGHT = 34;
const REQUEST_LANE = [1, 8] as const;
const FILTER_LANE = [26, 33] as const;
const CELLS = [12, 10] as const;
// The gap on each side of a packet cell.
const GAP = 1;

/** The request selects the frame. */
export const REQUESTED: ReadonlySet<FrameState> = new Set(['tp', 'fn']);
/** The filter selects the frame. */
export const SELECTED: ReadonlySet<FrameState> = new Set(['tp', 'fp']);
/** The filter and the request disagree on the frame. */
export const DISAGREES: ReadonlySet<FrameState> = new Set(['fp', 'fn']);

type Strip = PickStrip | TurnStrip;

/** A count a sourced node holds, which the guard leaves typed loosely. */
export function count(node: {readonly v: unknown}): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v)) {
    throw new Error(`strips: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

/** A lane's path: high on the frames whose state is in `on`. */
function wave(
  states: readonly FrameState[],
  on: ReadonlySet<FrameState>,
  [high, low]: readonly [number, number],
): string {
  let path = `M0 ${low}`;
  let level = low;
  states.forEach((state, column) => {
    const next = on.has(state) ? high : low;
    if (next !== level) {
      path += `H${column * PITCH}V${next}`;
      level = next;
    }
  });
  return `${path}H${states.length * PITCH}${level === high ? `V${low}` : ''}`;
}

/** The pulses one lane draws on the frames in `pick`, as one path. */
function pulses(
  states: readonly FrameState[],
  pick: FrameState,
  [high, low]: readonly [number, number],
): string {
  return states
    .flatMap((state, column) =>
      state === pick ? [`M${column * PITCH} ${low}V${high}H${(column + 1) * PITCH}V${low}`] : [],
    )
    .join('');
}

function Lanes({strip, columns}: {readonly strip: Strip; readonly columns: number}) {
  const {states} = strip;
  const recipe = count(strip.benchmark_frames);
  const [top, tall] = CELLS;
  return (
    <svg
      aria-hidden="true"
      className="lanes"
      focusable="false"
      preserveAspectRatio="none"
      viewBox={`0 0 ${columns * PITCH} ${HEIGHT}`}
    >
      {states.map((state, column) => (
        <rect
          className={DISAGREES.has(state) ? 'ln-dis' : column < recipe ? 'ln-recipe' : 'ln-witness'}
          height={tall}
          key={column}
          width={PITCH - GAP - GAP}
          x={column * PITCH + GAP}
          y={top}
        />
      ))}
      <path className="ln-req" d={wave(states, REQUESTED, REQUEST_LANE)} />
      <path className="ln-flt" d={wave(states, SELECTED, FILTER_LANE)} />
      <path className="ln-miss" d={pulses(states, 'fn', FILTER_LANE)} />
      <path className="ln-extra" d={pulses(states, 'fp', FILTER_LANE)} />
    </svg>
  );
}

interface StripsProps {
  readonly strips: readonly Strip[];
  /** The frame columns of the figure: its longest capture. */
  readonly columns: number;
  /** Smaller strips that name each probe's exactness, not its runtime. */
  readonly compact?: boolean;
  /** The cursor overlay, placed over the plot column. */
  readonly children?: ReactNode;
}

/** The strips of one answer, one row per scored probe. */
export function Strips({strips, columns, compact = false, children}: StripsProps) {
  const scale = {'--cols': columns} as CSSProperties;
  return (
    <div className={compact ? 'sx sx-compact' : 'sx'} style={scale}>
      {compact ? null : <div aria-hidden="true" className="sx-axis" />}
      {strips.map((strip) => (
        <div className="sx-row" key={JSON.stringify(strip.probe_id.src)}>
          <p className="sx-id">
            <Str node={strip.probe_id} />
            <span className="sx-meta">
              {compact ? (
                <>
                  exact <Num kind="bool" node={strip.exact} />
                </>
              ) : strip.runtime_ms === null ? null : (
                <>
                  tshark <Num kind="runtime" node={strip.runtime_ms} /> ms
                </>
              )}
            </span>
          </p>
          {compact ? null : (
            <p aria-hidden="true" className="sx-lanes">
              <span>request</span>
              <span>filter</span>
            </p>
          )}
          <Lanes columns={columns} strip={strip} />
        </div>
      ))}
      {children}
    </div>
  );
}
