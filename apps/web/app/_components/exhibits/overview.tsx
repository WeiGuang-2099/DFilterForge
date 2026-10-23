/**
 * @fileoverview The overview: every replayed answer as one square.
 *
 * Server-rendered from exhibits.json: one row per pool pass, in pool order,
 * and in it one square per answer. A square is geometry from its two
 * sourced verdicts, alone (data-a) and with the tail (data-t), which the
 * page's style sheet draws under the island's data-view; it holds no text.
 * A row lists its squares by verdict pair, in the order PAIRS gives, then
 * in replay order, so no square moves when the verifier switches. The
 * squares the tail turns are ringed links to their exhibits, named by
 * their sourced model, condition and item. The island (overview-island.tsx)
 * reads out the square pointed at, focused or pressed from the same nodes.
 * Each square carries its place in its row as --i, which staggers its
 * change of colour when the verifier switches.
 */

import type {CSSProperties, ReactNode} from 'react';

import {PAIRS} from '@/lib/exhibits-codes';
import type {Alone} from '@/lib/exhibits-codes';
import {counted, pairOf} from '@/lib/exhibits-data';
import type {ExhibitAnswer, Replay, ReplayRow, Square} from '@/lib/exhibits-data';
import {fmt} from '@/lib/fmt';
import {Num, Str} from '@/lib/sourced';
import {StrText} from '@/lib/sourced-text';

import {OverviewRoot} from './overview-island';
import type {SquareFacts} from './overview-island';
import type {View} from './words';

// The stagger repeats every this many squares of a row, so a long row
// changes in waves rather than one slow sweep.
const STAGGER = 60;

// A verdict as one letter, which the style sheet keys on.
const LETTERS: Readonly<Record<Alone, string>> = {
  strong_exact: 'e',
  shortcut: 's',
  silent_wrong: 'w',
  unscorable: 'u',
};

/** A turned answer's exhibit, by case id, and its answer and place there. */
interface Target {
  readonly exhibit: string;
  readonly answer: ExhibitAnswer;
  readonly place: number;
}

interface Placed {
  readonly row: ReplayRow;
  readonly square: Square;
  /** The square's place across all rows, its key in the island's facts. */
  readonly at: number;
  /** The square's place in its row. */
  readonly nth: number;
  readonly target: Target | null;
}

/** The exhibit answer a turned square points at, or null for another square. */
function targetOf(replay: Replay, square: Square): Target | null {
  if (square.turned === null) {
    return null;
  }
  const exhibit = replay.exhibits[square.turned.exhibit];
  const answer = exhibit?.answers[square.turned.answer];
  if (exhibit === undefined || answer === undefined) {
    throw new Error('exhibits: a ringed square points at no exhibit answer');
  }
  return {exhibit: exhibit.case, answer, place: square.turned.answer};
}

/** Each row's squares by verdict pair, then in replay order, with their places. */
function place(replay: Replay): Placed[][] {
  let at = 0;
  return replay.rows.map((row) =>
    row.squares
      .map((square, order) => ({square, order, pair: PAIRS.indexOf(pairOf(square))}))
      .sort((first, second) => first.pair - second.pair || first.order - second.order)
      .map(({square}, nth) => ({row, square, at: at++, nth, target: targetOf(replay, square)})),
  );
}

/** A square's stagger index: its place in its row, in waves of STAGGER. */
function stagger(nth: number): CSSProperties {
  return {'--i': nth % STAGGER} as CSSProperties;
}

function Mark({square, at, nth, target}: Placed): ReactNode {
  const letters = {'data-a': LETTERS[square.alone.t], 'data-t': LETTERS[square.tail.t]};
  if (target === null) {
    return <span className="xh-q" data-q={at} style={stagger(nth)} {...letters} />;
  }
  return (
    <a
      className="xh-q xh-q-k"
      data-answer={target.place}
      data-exhibit={target.exhibit}
      data-q={at}
      href={`#${target.exhibit}`}
      style={stagger(nth)}
      {...letters}
    >
      <span className="xh-vh">
        <StrText node={target.answer.model_id} /> <StrText node={square.condition} />{' '}
        <StrText node={square.item_id} />, turned by the tail
      </span>
    </a>
  );
}

/** The detail line's opening for each view, before a square is pointed at. */
function summaries(replay: Replay): Readonly<Record<View, ReactNode>> {
  const {alone, tail, counts} = replay;
  return {
    tail: (
      <p className="xh-detail-t">
        With the tail: <b><Num kind="int" node={tail.strong_exact} /></b> strong exact,{' '}
        <b><Num kind="int" node={tail.shortcut} /></b> shortcuts and{' '}
        <b className="dn"><Num kind="int" node={tail.silent_wrong} /></b> silent-wrong. The{' '}
        <Num kind="int" node={replay.turned} /> ringed squares are the answers the tail turns.
        Point at a square to read its answer here, and press it to keep it; a ringed one opens
        its exhibit.
      </p>
    ),
    alone: (
      <p className="xh-detail-t">
        On the captures alone: <b><Num kind="int" node={alone.strong_exact} /></b> strong
        exact, <b><Num kind="int" node={alone.shortcut} /></b> shortcuts,{' '}
        <b><Num kind="int" node={alone.silent_wrong} /></b> silent-wrong, and{' '}
        <b><Num kind="int" node={alone.unscorable} /></b> answers to the{' '}
        <Num kind="int" node={counts.tail_only} /> cases the verifier cannot score without
        the tail. Here the <Num kind="int" node={replay.turned} /> ringed squares agree with
        the labels on every frame: <Num kind="int" node={replay.turned_exact} /> strong exact
        and <Num kind="int" node={replay.turned_shortcut} /> shortcut.
      </p>
    ),
  };
}

/** The swatches the squares are drawn with, named in fmt's verdict words. */
function Key(): ReactNode {
  const swatches = [
    ['e', fmt('strong_exact', 'outcome')],
    ['w', fmt('silent_wrong', 'outcome')],
    ['s', fmt('shortcut', 'outcome')],
    ['u', `${fmt('unscorable', 'outcome')} on the captures alone`],
  ] as const;
  return (
    <ul className="xh-key">
      {swatches.map(([letter, words]) => (
        <li key={letter}>
          <span aria-hidden="true" className="xh-q" data-k={letter} />
          {words}
        </li>
      ))}
      <li>
        <span aria-hidden="true" className="xh-q xh-q-k" data-k="k" />
        turned by the tail; opens its exhibit
      </li>
    </ul>
  );
}

/** The squares in rows, the verifier switch and the detail line. */
export function Overview({replay, blob}: {
  readonly replay: Replay;
  readonly blob: string;
}): ReactNode {
  const rows = place(replay);
  const facts: SquareFacts[] = rows.flat().map(({row, square, target}) => ({
    model: row.model_id,
    condition: square.condition,
    item_id: square.item_id,
    case_id: square.case_id,
    alone: square.alone.t,
    tail: square.tail.t,
    receipt: square.receipt,
    exhibit: target?.exhibit ?? null,
    answer: target?.place ?? null,
  }));
  return (
    <OverviewRoot blob={blob} facts={facts} summaries={summaries(replay)}>
      <Key />
      <div className="xh-rows">
        {replay.rows.map((row, index) => (
          <div className="xh-row" key={row.run}>
            <p className="xh-who">
              <span className="xh-model">
                <Str node={row.model_id} />
              </span>
              <span className="xh-who-n">
                <Num kind="int" node={row.answers} /> answers;{' '}
                <b><Num kind="int" node={row.alone.strong_exact} /></b> exact on the captures
                alone,{' '}
                <b className={counted(row.turned_exact, row.run) > 0 ? 'dn' : undefined}>
                  <Num kind="int" node={row.turned_exact} />
                </b>{' '}
                of them wrong with the tail
              </span>
            </p>
            <div className="xh-cells">
              {(rows[index] ?? []).map((each) => (
                <Mark key={each.at} {...each} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </OverviewRoot>
  );
}
