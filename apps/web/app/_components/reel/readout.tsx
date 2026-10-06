/**
 * @fileoverview What the cursor reads: its frame's packet-list row and the
 * predicate trace there.
 *
 * Every frame's readout is rendered here, on the server, with sourced
 * values: the frame number, kind and generator name from captures.json,
 * the packet-list columns from packets.json and each leaf's tshark display
 * filter from the committed trace. The stage shows one frame at a time by
 * data-at and one probe's trace by data-p, so the cursor never renders a
 * value of its own. Whether the filter and the request select the frame,
 * and each leaf's value, are fixed words from the receipt's frame states
 * and the trace's matched frames; data-state and data-leaf keep them for
 * the consistency test. A leaf is traced only where the two disagree.
 */

import type {Reel, PickStrip, Trace} from '@/lib/reel-data';
import {Num, Str, Word} from '@/lib/sourced';

import {DISAGREES, REQUESTED, SELECTED} from './strips';

type Leaf = Trace['probes'][number]['filter'][number];
type Joins = NonNullable<Reel['pick']>['joins'];

// What each side's root says at a frame it selects, and at one it does not.
const WORDS = {
  filter: ['matched', 'not matched'],
  request: ['should match', 'should not match'],
} as const;

/** A frame's class: `on` where the filter and the request disagree. */
const lit = (strip: PickStrip, row: number, on: string) =>
  DISAGREES.has(strip.states[row] ?? 'tn') ? on : 'at';

// Whether a list of frame numbers holds the frame of a ladder row.
const has = (node: {readonly v: unknown}, row: number) =>
  Array.isArray(node.v) && node.v.includes(row + 1);

/** One leaf's value at each frame: true, false, or - where not traced. */
function LeafRow({leaf, frames, probe, side, at, strip}: {
  readonly leaf: Leaf;
  readonly frames: {readonly v: unknown};
  readonly probe: number;
  readonly side: 'filter' | 'request';
  readonly at: number;
  readonly strip: PickStrip;
}) {
  return (
    <p className="lf">
      <span aria-hidden="true" className={side === 'filter' ? 'key d' : 'key'} />
      <code>
        <Str node={leaf.filter} />
      </code>
      <span className="v">
        {strip.frame_rows.map((_, row) => {
          const traced = has(frames, row);
          const value = traced ? has(leaf.matched, row) : null;
          const state = strip.states[row];
          // The filter's leaves that decide a disagreement: false where it
          // missed a frame, true where it took one too many.
          const bad = side === 'filter' && traced && value === (state === 'fp');
          return (
            <span
              className={bad && DISAGREES.has(state ?? 'tn') ? 'at bad' : 'at'}
              data-at={`${probe}-${row}`}
              data-leaf={`${side}-${at}`}
              key={row}
            >
              {value === null ? '-' : String(value)}
            </span>
          );
        })}
      </span>
    </p>
  );
}

/** A side's root: whether the whole filter or request selects the frame. */
function RootRow({strip, probe, join, on, words}: {
  readonly strip: PickStrip;
  readonly probe: number;
  readonly join: Joins['filter'];
  readonly on: ReadonlySet<string>;
  readonly words: readonly [string, string];
}) {
  return (
    <p className="rt">
      <span className="rl">
        {join === null ? 'the whole filter' : <Word kind="join" node={join} />}
      </span>
      <span className="v">
        {strip.states.map((state, row) => (
          <span className="at" data-at={`${probe}-${row}`} key={row}>
            {on.has(state) ? words[0] : words[1]}
          </span>
        ))}
      </span>
    </p>
  );
}

interface ReadoutProps {
  readonly strips: readonly PickStrip[];
  readonly trace: Reel['trace'];
  readonly joins: Joins;
  /** Why the Reel shows no predicate trace, as fixed words. */
  readonly untraced: string;
}

/** The cursor's readout, one frame shown at a time. */
export function Readout({strips, trace, joins, untraced}: ReadoutProps) {
  return (
    <section aria-label="Cursor readout" className="ro">
      <div className="ro-head">
        <p className="ro-mode">
          <span className="m-pinned">Cursor pinned</span>
          <span className="m-sweep">Sweep</span>
          <span className="m-drag">Dragging the cursor</span>
          {strips.map((strip, probe) =>
            strip.frame_rows.map((frame, row) => (
              <span className="at ro-ctx" data-at={`${probe}-${row}`} key={`${probe}-${row}`}>
                <Word kind="frame_kind" node={frame.kind} /> frame, generator{' '}
                <Str node={frame.name} />
              </span>
            )),
          )}
        </p>
        <h2 className="ro-h">
          Frame{' '}
          {strips.map((strip, probe) =>
            strip.frame_rows.map((frame, row) => (
              <span className={lit(strip, row, 'at dn')} data-at={`${probe}-${row}`} key={row}>
                <Num kind="int" node={frame.n} />
              </span>
            )),
          )}{' '}
          of{' '}
          {strips.map((strip, probe) => (
            <code className="atp" data-p={probe} key={probe}>
              <Str node={strip.probe_id} />
            </code>
          ))}
        </h2>
      </div>
      <table className="pl-t">
        <thead>
          <tr>
            <th className="c-no" scope="col">No.</th>
            <th className="c-time" scope="col">Time</th>
            <th className="c-src" scope="col">Source</th>
            <th className="c-dst" scope="col">Destination</th>
            <th className="c-proto" scope="col">Protocol</th>
            <th scope="col">Length</th>
          </tr>
        </thead>
        {strips.map((strip, probe) =>
          strip.frame_rows.map((frame, row) => (
            <tbody className={lit(strip, row, 'at dis')} data-at={`${probe}-${row}`} key={row}>
              <tr>
                <td><Num kind="int" node={frame.n} /></td>
                <td className="c-time"><Str node={frame.time} /></td>
                <td><Str node={frame.src} /></td>
                <td><Str node={frame.dst} /></td>
                <td><Str node={frame.protocol} /></td>
                <td><Num kind="int" node={frame.length} /></td>
              </tr>
              <tr className="inf">
                <td colSpan={6}>
                  <span className="il">Info</span>
                  <Str node={frame.info} />
                </td>
              </tr>
            </tbody>
          )),
        )}
      </table>
      {strips.map((strip, probe) => {
        const traced = trace?.probes[probe];
        return (
          <div className="tr2 atp" data-p={probe} key={probe}>
            {(['request', 'filter'] as const).map((side) => (
              <div className="tr2-c" key={side}>
                <p className="tr2-h">{side}</p>
                {traced?.[side].map((leaf, at) => (
                  <LeafRow key={at} {...{at, leaf, probe, side, strip}} frames={traced.frames} />
                ))}
                <RootRow
                  join={joins[side]}
                  on={side === 'filter' ? SELECTED : REQUESTED}
                  probe={probe}
                  strip={strip}
                  words={WORDS[side]}
                />
              </div>
            ))}
            <p className="tr2-res">
              <span className="rl">Result</span>
              <span className="rs">filter against request</span>
              <span className="v">
                {strip.states.map((state, row) => (
                  <span
                    className={lit(strip, row, 'at dn')}
                    data-at={`${probe}-${row}`}
                    data-state={state}
                    key={row}
                  >
                    {DISAGREES.has(state) ? 'disagree' : 'agree'}
                  </span>
                ))}
              </span>
            </p>
            <p className="note tr2-note">
              {traced === undefined ? (
                <>Leaf values: {untraced}.</>
              ) : (
                <>
                  tshark traced each leaf on this probe only at frames where the two disagree:{' '}
                  <Num kind="ints" node={traced.frames} />. Elsewhere a leaf shows a dash.
                </>
              )}
            </p>
          </div>
        );
      })}
    </section>
  );
}
