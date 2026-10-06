/**
 * @fileoverview The ladder diagram of one probe capture.
 *
 * Time runs down, one row per frame. The left line is the probe's client
 * address, the address seen in most of its frames, and the right line is
 * every other host; each frame is an arrow from its sender to its
 * receiver, or a loop on the right line between two other hosts, labelled
 * with tshark's Info column. The request column marks the frames the
 * labels select and the filter column the frames the answer selects; a
 * frame where they disagree is drawn in carmine. Witness frames, the tail
 * every capture ends in, are collapsed into one short break row per run of
 * them, except one that disagrees, which keeps its full row. The cursor
 * still stops on each collapsed frame, a sliver of its break row. Geometry is in pixels down and in fractions of the
 * ladder's width across, so the SVG draws only lines and the numbers and
 * labels over it are sourced HTML.
 */

import type {PickStrip} from '@/lib/reel-data';
import {Num, Str} from '@/lib/sourced';

import {DISAGREES, REQUESTED, SELECTED} from './strips';

// The ladder's width and its columns across: frame numbers end at AXIS,
// the client line, the other hosts line, the request and filter marks.
export const W = 460;
const AXIS = 40;
const XL = 100;
const XR = 330;
const XQ = 390;
const XF = 438;
const LOOP = 16;
// Down: the host labels, the first row, a full row, the break row that a
// run of collapsed witness frames shares, an arrow's drop and the footer. An
// arrow's middle is 1 px below its row's middle and its label stands 3 px
// above it, tilted to the arrow (reel.css .l-out and .l-in); a loop and
// its label (.l-other) centre 2 px above the row's middle. A 24 px row
// holds a 13 px label tilted to a 6 px drop clear of the next row's label
// and of the arrows beside it.
const HOSTS = 14;
const TOP = 24;
const ROW = 24;
const BAND = 32;
const SLOPE = 6;
const FOOT = 34;

/** The rows of one ladder, in pixels from its top. */
export interface Track {
  readonly tops: readonly number[];
  readonly heights: readonly number[];
  readonly height: number;
}

interface Row {
  readonly top: number;
  readonly h: number;
  /** A collapsed witness frame: a sliver of its run's break row. */
  readonly tick: boolean;
}

/** A run of collapsed witness frames: its break row's top and its rows. */
interface Band {
  top: number;
  readonly first: number;
  last: number;
}

function layout(strip: PickStrip): {rows: Row[]; bands: Band[]; end: number} {
  const bands: Band[] = [];
  strip.frame_rows.forEach((frame, row) => {
    if (frame.kind.t !== 'witness' || DISAGREES.has(strip.states[row] ?? 'tn')) {
      return;
    }
    const band = bands.at(-1);
    if (band !== undefined && band.last === row - 1) {
      band.last = row;
    } else {
      bands.push({top: 0, first: row, last: row});
    }
  });
  let y = TOP;
  const rows = strip.frame_rows.map((_, row) => {
    const band = bands.find(({first, last}) => first <= row && row <= last);
    if (band === undefined) {
      y += ROW;
      return {top: y - ROW, h: ROW, tick: false};
    }
    if (row === band.first) {
      band.top = y;
      y += BAND;
    }
    const h = BAND / (band.last - band.first + 1);
    return {top: band.top + (row - band.first) * h, h, tick: true};
  });
  return {rows, bands, end: y};
}

/** Where each row of a strip's ladder lies, for the cursor. */
export function track(strip: PickStrip): Track {
  const {rows, end} = layout(strip);
  return {tops: rows.map((r) => r.top), heights: rows.map((r) => r.h), height: end + FOOT};
}

const across = (x: number) => `${(x * 100) / W}%`;

/** A row's arrow or loop, in viewBox units; a collapsed row draws none. */
function stroke(dir: string, {top, h, tick}: Row): string {
  const mid = top + h / 2;
  if (tick) {
    return '';
  }
  if (dir === 'other') {
    const loop = mid - 2 - SLOPE / 2;
    const [end, tip] = [loop + SLOPE, XR + 7];
    const head = `M${tip} ${end - 2.6}L${XR} ${end}L${tip} ${end + 2.6}Z`;
    return `M${XR} ${loop}h${LOOP}v${SLOPE}H${tip}${head}`;
  }
  const y = top + (h - SLOPE) / 2 + 1;
  const [from, to] = dir === 'out' ? [XL, XR] : [XR, XL];
  const back = dir === 'out' ? -7 : 7;
  const [end, tip] = [y + SLOPE, to + back];
  return `M${from} ${y}L${to} ${end}M${tip} ${end - 3}L${to} ${end}L${tip} ${end + 2.2}`;
}

/** Joined bars over consecutive full rows whose state is in `on`. */
function bars(rows: readonly Row[], states: readonly string[], on: ReadonlySet<string>, x: number) {
  const out: string[] = [];
  let open: [number, number] | null = null;
  rows.forEach((row, index) => {
    const set = !row.tick && on.has(states[index] ?? 'tn');
    const mid = row.top + row.h / 2;
    if (set) {
      open = [open?.[0] ?? mid - 4, mid + 4];
    }
    if ((!set || index === rows.length - 1) && open !== null) {
      out.push(`M${x - 4} ${open[0]}H${x + 4}V${open[1]}H${x - 4}Z`);
      open = null;
    }
  });
  return out.join('');
}

/** A lifeline, broken across each break row. */
function life(x: number, bands: readonly Band[], end: number): string {
  const parts = [`M${x} ${HOSTS + 7}`];
  for (const {top} of bands) {
    const mid = top + BAND / 2;
    parts.push(
      `V${mid - 4}`,
      `M${x - 6} ${mid - 2}L${x + 6} ${mid - 7}M${x - 6} ${mid + 7}L${x + 6} ${mid + 2}`,
      `M${x} ${mid + 4}`,
    );
  }
  return `${parts.join('')}V${end + 4}`;
}

/** What each row draws, worked out before any markup. */
function draw(strip: PickStrip, rows: readonly Row[]) {
  return strip.frame_rows.map((frame, row) => {
    const place = rows[row] ?? {top: 0, h: 0, tick: true};
    const state = strip.states[row] ?? 'tn';
    const mid = place.top + place.h / 2;
    const miss = state === 'fn' ? XF : state === 'fp' ? XQ : null;
    return {
      frame,
      place,
      state,
      cls: `fr${SELECTED.has(state) ? ' sel' : ''}${DISAGREES.has(state) ? ' dis' : ''}`,
      path: stroke(frame.dir, place),
      miss: miss === null ? null : {x: miss - 3.5, y: mid - 3.5, width: 7, height: 7},
    };
  });
}

interface LadderProps {
  readonly strip: PickStrip;
  readonly probe: number;
}

/** One probe's ladder: lines in SVG, then its numbers and labels. */
export function Ladder({strip, probe}: LadderProps) {
  const {rows, bands, end} = layout(strip);
  const height = end + FOOT;
  const drawn = draw(strip, rows);
  const frames = strip.frame_rows;
  const caps = [XL, XR].map((x) => ({x, cap: x - 5, d: life(x, bands, end)}));
  const top = {cap: HOSTS + 4, foot: end + 14};
  return (
    <div className="lad-p" data-p={probe} style={{height}}>
      <svg
        aria-hidden="true"
        className="lad-svg"
        focusable="false"
        preserveAspectRatio="none"
        viewBox={`0 0 ${W} ${height}`}
      >
        {caps.map(({x, cap, d}) => (
          <g key={x}>
            <rect className="l-cap" height={3} width={10} x={cap} y={top.cap} />
            <path className="l-life" d={d} />
          </g>
        ))}
        {drawn.map(({cls, path}, row) => (
          <path className={cls} d={path} key={row} />
        ))}
        <path className="m-on" d={bars(rows, strip.states, REQUESTED, XQ)} />
        <path className="m-on" d={bars(rows, strip.states, SELECTED, XF)} />
        {drawn.map(({miss}, row) =>
          miss === null ? null : (
            <rect className="m-miss" data-at={`${probe}-${row}`} key={row} {...miss} />
          ),
        )}
      </svg>
      <div className="lad-tx">
        <span className="l-host" style={{left: across(XL), top: HOSTS}}>
          <Str node={strip.client} />
        </span>
        <span className="l-host l-end" style={{left: across(XR), top: HOSTS}}>
          other hosts
        </span>
        <span className="l-col" style={{left: across(XQ), top: HOSTS}}>
          request
        </span>
        <span className="l-col" style={{left: across(XF), top: HOSTS}}>
          filter
        </span>
        {drawn.map(({frame, place, state, cls}, row) => (
          <div
            className={cls}
            data-at={`${probe}-${row}`}
            data-dir={frame.dir}
            data-state={state}
            key={row}
            style={{top: place.top, height: place.h}}
          >
            {place.tick ? null : (
              <>
                <span className="l-ax" style={{right: across(W - AXIS)}}>
                  <Num kind="int" link={false} node={frame.n} />
                </span>
                <span className={`l-lab l-${frame.dir}`}>
                  <Str node={frame.info} />
                </span>
              </>
            )}
          </div>
        ))}
        {bands.map(({top: at, first, last}) => {
          const [from, to] = [frames[first], frames[last]];
          return from === undefined || to === undefined ? null : (
            <span className="l-brk" key={first} style={{top: at + BAND / 2}}>
              {first === last ? (
                <>
                  witness frame <Num kind="int" node={from.n} />
                </>
              ) : (
                <>
                  witness frames <Num kind="int" node={from.n} /> to <Num kind="int" node={to.n} />
                </>
              )}
            </span>
          );
        })}
        <span className="l-foot" style={{top: top.foot}}>
          <Num kind="int" node={strip.frames} /> frames
          {strip.runtime_ms === null ? null : (
            <>
              , tshark ran <Num kind="runtime" node={strip.runtime_ms} /> ms
            </>
          )}
        </span>
      </div>
    </div>
  );
}
