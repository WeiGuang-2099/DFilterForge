/**
 * @fileoverview A turned answer's frame tapes and its killing frames.
 *
 * Server-rendered from exhibits.json. A tape is one probe capture as a row
 * of frame cells: the benchmark frames, then the witness tail on a wash of
 * its own, each cell filled by the frame's state on the answer's receipt
 * (data-s); on a narrow screen the tail is a second row under the
 * benchmark frames. The cells hold no text: the island reads a cell out by
 * its probe (data-p) and frame (data-n), and the page's style sheet folds
 * the tail away on the captures alone. The killing frames are the receipt's
 * disagreeing frames, every one in the tail, shown as tshark's packet list
 * prints them, from the replayed probe's frame table. Answers of one case
 * whose states agree on every frame share their tapes and packet lists.
 */

import type {ReactNode} from 'react';

import type {StrNode} from '@/lib/data';
import {counted} from '@/lib/exhibits-data';
import type {Exhibit, ExhibitAnswer, ReplayProbe, Strip} from '@/lib/exhibits-data';
import {Num, Str} from '@/lib/sourced';

import {Cell} from './parts';
import {SIDE_WORDS, STATE_WORDS} from './words';

// The packet list's columns: tshark's, then the witness and what the
// answer does on the frame.
const COLUMNS = {
  n: 'No.',
  time: 'Time',
  source: 'Source',
  destination: 'Destination',
  protocol: 'Protocol',
  length: 'Length',
  info: 'Info',
  witness: 'Witness',
  side: 'On this frame',
} as const;

/** Answers of one exhibit whose frame states agree on every probe. */
export interface StateGroup {
  /** Their places among the exhibit's answers, as data-ans lists them. */
  readonly answers: readonly number[];
  readonly first: ExhibitAnswer;
}

/** An exhibit's answers grouped by their frame states, in answer order. */
export function stateGroups(exhibit: Exhibit): StateGroup[] {
  const found = new Map<string, {answers: number[]; first: ExhibitAnswer}>();
  exhibit.answers.forEach((answer, place) => {
    const key = JSON.stringify(answer.probes.map((strip) => strip.states));
    const group = found.get(key);
    if (group === undefined) {
      found.set(key, {answers: [place], first: answer});
    } else {
      group.answers.push(place);
    }
  });
  return [...found.values()];
}

/** One cell per frame, its state from the receipt. */
function Cells({strip, from, to}: {
  readonly strip: Strip;
  readonly from: number;
  readonly to: number;
}): ReactNode {
  return strip.states.slice(from, to).map((state, offset) => {
    const at = from + offset;
    return <i className="xh-f" data-n={at + 1} data-s={state} key={at} />;
  });
}

/** An answer's probes as tapes of frames: benchmark frames, then the tail. */
export function Tapes({answer, probes}: {
  readonly answer: ExhibitAnswer;
  readonly probes: readonly ReplayProbe[];
}): ReactNode {
  return answer.probes.map((strip, p) => {
    const bench = counted(strip.benchmark_frames, 'exhibits.json strip');
    const probe = probes[p];
    if (probe === undefined) {
      throw new Error('exhibits: a strip has no replayed probe');
    }
    return (
      <div className="xh-tape" data-p={p} key={strip.probe_id.t}>
        <p className="xh-tape-l">
          <b>
            <Str node={strip.probe_id} />
          </b>
          <span>
            <Num kind="int" link={false} node={strip.benchmark_frames} />
            <span className="xh-only-tail">
              {' '}
              + <Num kind="int" link={false} node={probe.tail_frames} />
            </span>{' '}
            frames
          </span>
        </p>
        <div className="xh-strip">
          <span className="xh-seg-b">
            <Cells from={0} strip={strip} to={bench} />
          </span>
          <span className="xh-seg-t">
            <Cells from={bench} strip={strip} to={strip.states.length} />
          </span>
        </div>
      </div>
    );
  });
}

/** What the tapes' fills and wash mean. */
export function TapeKey(): ReactNode {
  return (
    <ul className="xh-tkey">
      {(['tp', 'tn', 'fp', 'fn'] as const).map((state) => (
        <li key={state}>
          <i aria-hidden="true" className="xh-f" data-s={state} />
          {STATE_WORDS[state]}
        </li>
      ))}
      <li>
        <i aria-hidden="true" className="xh-tkey-tail" />
        the witness tail
      </li>
    </ul>
  );
}

/**
 * One probe's killing frames as tshark's packet list prints them. Below
 * its full width the list scrolls sideways, so its box is a named region
 * the keyboard can focus and scroll; the case id in its caption tells the
 * exhibits' regions apart. On a narrow screen each frame stacks into a
 * block of its values, each after its column's name, and nothing scrolls.
 */
export function PacketList({strip, probe, caseId, id}: {
  readonly strip: Strip;
  readonly probe: ReplayProbe;
  readonly caseId: StrNode;
  /** The caption's id, unique on the page. */
  readonly id: string;
}): ReactNode {
  return (
    <div aria-labelledby={id} className="xh-tw" role="region" tabIndex={0}>
      <table className="xh-pl" role="table">
        <caption className="xh-vh" id={id}>
          <Str node={caseId} />: the frames of <Str node={probe.probe_id} /> where the answer
          and the labels part
        </caption>
        <thead role="rowgroup">
          <tr role="row">
            {Object.values(COLUMNS).map((head) => (
              <th key={head} role="columnheader" scope="col">
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody role="rowgroup">
          {strip.disagree.map((kill) => {
            const row = probe.frame_rows[counted(kill.n, 'exhibits.json frame') - 1];
            if (row === undefined) {
              throw new Error('exhibits: a killing frame is no frame of its probe');
            }
            return (
              <tr key={JSON.stringify(row.n.src)} role="row">
                <Cell head={COLUMNS.n}>
                  <Num kind="int" link={false} node={row.n} />
                </Cell>
                <Cell head={COLUMNS.time}>
                  <Str node={row.time} />
                </Cell>
                <Cell head={COLUMNS.source}>
                  <Str node={row.source} />
                </Cell>
                <Cell head={COLUMNS.destination}>
                  <Str node={row.destination} />
                </Cell>
                <Cell head={COLUMNS.protocol}>
                  <Str node={row.protocol} />
                </Cell>
                <Cell head={COLUMNS.length}>
                  <Num kind="int" link={false} node={row.length} />
                </Cell>
                <Cell className="xh-pl-info" head={COLUMNS.info}>
                  <Str node={row.info} />
                </Cell>
                <Cell head={COLUMNS.witness}>
                  <code>
                    <Str node={kill.name} />
                  </code>
                </Cell>
                <Cell className="xh-pl-side" head={COLUMNS.side}>
                  {SIDE_WORDS[kill.side]}
                </Cell>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
