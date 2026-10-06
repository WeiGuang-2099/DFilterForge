/**
 * @fileoverview What the cursor reads: the frame under it on every probe.
 *
 * Every column's readout is rendered here, on the server, with sourced
 * values: the frame number, and on each probe the frame's kind and
 * generator name from captures.json. The stage shows one column at a time
 * by its data-at attribute, so the cursor never renders a value of its
 * own. Whether the filter and the request select a frame is said in fixed
 * words from the receipt's frame states, which data-state keeps for the
 * consistency test.
 */

import {Fragment} from 'react';

import type {NumNode} from '@/lib/data';
import type {PickStrip} from '@/lib/reel-data';
import {Num, Str} from '@/lib/sourced';

import {DISAGREES, REQUESTED, SELECTED} from './strips';

interface ReadoutProps {
  readonly strips: readonly PickStrip[];
  /** The frame number each column shows. */
  readonly numbers: readonly NumNode[];
  /** Whether any probe disagrees at each column. */
  readonly lit: readonly boolean[];
  /** Why the Reel shows no predicate trace, as fixed words. */
  readonly trace: string;
}

function yes(on: boolean): string {
  return on ? 'yes' : 'no';
}

/** The cursor's readout, one column shown at a time. */
export function Readout({strips, numbers, lit, trace}: ReadoutProps) {
  return (
    <section aria-label="Cursor readout" className="ro">
      <div className="ro-head">
        <p className="ro-mode">
          <span className="m-pinned">Cursor pinned</span>
          <span className="m-sweep">Sweep</span>
          <span className="m-drag">Dragging the cursor</span>
          <span className="ro-ctx">Predicate trace: {trace}</span>
        </p>
        <h2 className="ro-h">
          Frame{' '}
          {numbers.map((number, column) => (
            <span className={lit[column] === true ? 'at dn' : 'at'} data-at={column} key={column}>
              <Num kind="int" node={number} />
            </span>
          ))}
        </h2>
      </div>
      <div className="ro-grid">
        <span className="ro-th">Probe</span>
        <span className="ro-th">Kind</span>
        <span className="ro-th">Generator</span>
        <span className="ro-th">Filter selects</span>
        <span className="ro-th">Request selects</span>
        <span className="ro-th" />
        {strips.map((strip, probe) => (
          <Fragment key={JSON.stringify(strip.probe_id.src)}>
            <span className="ro-probe">
              <Str node={strip.probe_id} />
            </span>
            {numbers.map((_, column) => {
              const row = strip.frame_rows[column];
              const state = strip.states[column];
              if (row === undefined || state === undefined) {
                return (
                  <span className="at ro-cells ro-none" data-at={column} key={column}>
                    no such frame: this capture is shorter
                  </span>
                );
              }
              const disagrees = DISAGREES.has(state);
              return (
                <span
                  className={disagrees ? 'at ro-cells dis' : 'at ro-cells'}
                  data-at={column}
                  data-probe={probe}
                  data-state={state}
                  key={column}
                >
                  <span>
                    <Str node={row.kind} />
                  </span>
                  <span className="ro-name">
                    <Str node={row.name} />
                  </span>
                  <span>{yes(SELECTED.has(state))}</span>
                  <span>{yes(REQUESTED.has(state))}</span>
                  <span className="ro-verdict">{disagrees ? 'disagree' : 'agree'}</span>
                </span>
              );
            })}
          </Fragment>
        ))}
      </div>
      <p className="ro-legend">
        <span>
          <span aria-hidden="true" className="key key-wave" />
          request lane above the packets, filter lane below, each high on the frames it selects
        </span>
        <span>
          <span aria-hidden="true" className="key key-dis" />a frame where they disagree
        </span>
        <span>
          <span aria-hidden="true" className="key key-miss" />a pulse the filter missed
        </span>
      </p>
    </section>
  );
}
