'use client';

/**
 * @fileoverview The overview's island: the verifier switch and the detail
 * line under the squares.
 *
 * The squares are server-rendered children; the island sets the figure's
 * data-view, which the page's style sheet reads to draw each square as its
 * verdict alone (data-a) or with the tail (data-t), so no square moves.
 * Both views' summaries are in the server's HTML. Pointing at a square
 * (data-q, its place in the facts) reads its answer out: its model,
 * condition, item and case as sourced values, its verdicts in fmt's
 * outcome words and its receipt. The line keeps the square while the
 * pointer stays on the overview, so the pointer can move down to the
 * line's links, and the view's summary comes back when it leaves or the
 * verifier switches. A square focused from the keyboard is read out until
 * focus leaves the overview, so Tab goes on to the line's links, and a
 * pointer meanwhile does not take the line. Pressing a square holds it
 * until Escape or another press. A ringed square is a link to its exhibit,
 * which controls.tsx opens on that answer.
 */

import {useEffect, useState} from 'react';
import type {FocusEvent, ReactNode, SyntheticEvent} from 'react';

import type {StrNode} from '@/lib/data';
import type {Alone, Tail} from '@/lib/exhibits-codes';
import {fmt} from '@/lib/fmt';
import {StrText} from '@/lib/sourced-text';

import {ViewSwitch} from './controls';
import type {View} from './words';

/** What the detail line says about one square. */
export interface SquareFacts {
  readonly model: StrNode;
  readonly condition: StrNode;
  readonly item_id: StrNode;
  readonly case_id: StrNode;
  readonly alone: Alone;
  readonly tail: Tail;
  /** The receipt's repository path. */
  readonly receipt: string;
  /** For a turned answer, its exhibit's case id and its place there. */
  readonly exhibit: string | null;
  readonly answer: number | null;
}

interface OverviewProps {
  /** One entry per square, in the order the rows render them. */
  readonly facts: readonly SquareFacts[];
  /** The repository's file permalink prefix at the build's commit. */
  readonly blob: string;
  readonly summaries: Readonly<Record<View, ReactNode>>;
  readonly children: ReactNode;
}

/** The square an event comes from, by its place in the facts. */
function squareOf(event: SyntheticEvent): number | null {
  const target = event.target instanceof Element ? event.target : null;
  const square = target?.closest<HTMLElement>('[data-q]');
  return square == null ? null : Number(square.dataset['q']);
}

function Line({facts, blob}: {readonly facts: SquareFacts; readonly blob: string}): ReactNode {
  const href = blob + facts.receipt.split('/').map(encodeURIComponent).join('/');
  return (
    <p className="xh-detail-t">
      <b>
        <StrText node={facts.model} />
      </b>{' '}
      <StrText node={facts.condition} /> <StrText node={facts.item_id} />, case{' '}
      <code>
        <StrText node={facts.case_id} />
      </code>
      . Captures alone: <b>{fmt(facts.alone, 'outcome')}</b>; with the tail:{' '}
      <b className={facts.tail === 'silent_wrong' ? 'dn' : undefined}>
        {fmt(facts.tail, 'outcome')}
      </b>
      .{' '}
      {facts.exhibit === null ? null : (
        <>
          <a
            data-answer={facts.answer ?? undefined}
            data-exhibit={facts.exhibit}
            href={`#${facts.exhibit}`}
          >
            Open its exhibit
          </a>
          .{' '}
        </>
      )}
      <a href={href}>Receipt</a>
    </p>
  );
}

/** The verifier switch, the squares and the detail line. */
export function OverviewRoot({facts, blob, summaries, children}: OverviewProps): ReactNode {
  const [view, setView] = useState<View>('tail');
  // The square under the pointer, the one the keyboard focused and the one
  // a press holds; the line reads the held one, else the focused, else the
  // pointed.
  const [pointed, setPointed] = useState<number | null>(null);
  const [keyed, setKeyed] = useState<number | null>(null);
  const [held, setHeld] = useState<number | null>(null);
  const shown = held ?? keyed ?? pointed;
  const square = shown === null ? undefined : facts[shown];

  const point = (event: SyntheticEvent) => {
    const at = squareOf(event);
    if (at !== null) {
      setPointed(at);
    }
  };
  // Only focus the keyboard moved (:focus-visible): a click also focuses
  // the ringed square whose link it follows, and the pointer must go on
  // reading squares after that.
  const focus = (event: FocusEvent) => {
    const at = squareOf(event);
    if (at !== null && event.target.matches(':focus-visible')) {
      setKeyed(at);
    }
  };
  // Focus that moves on within the overview, as Tab does to the line's
  // links, keeps the square.
  const blur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) {
      setKeyed(null);
    }
  };
  const switchTo = (next: View) => {
    setView(next);
    setPointed(null);
    setKeyed(null);
  };
  const press = (event: SyntheticEvent) => {
    const at = squareOf(event);
    // A ringed square is a link: it opens its exhibit instead.
    if (at !== null && facts[at]?.exhibit === null) {
      setHeld(held === at ? null : at);
    }
  };
  useEffect(() => {
    if (held === null) {
      return undefined;
    }
    const release = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setHeld(null);
      }
    };
    document.addEventListener('keydown', release);
    return () => document.removeEventListener('keydown', release);
  }, [held]);
  return (
    <div
      className="xh-ov"
      data-view={view}
      onBlur={blur}
      onPointerLeave={() => setPointed(null)}
    >
      <div className="xh-bar">
        <span className="lab">Verifier</span>
        <ViewSwitch onChange={switchTo} view={view} />
      </div>
      {held === null ? null : (
        <style>
          {`.xh-ov [data-q="${held}"]{outline:var(--held);position:relative;z-index:var(--up)}`}
        </style>
      )}
      <div className="xh-fig" onClick={press} onFocus={focus} onPointerOver={point}>
        {children}
      </div>
      <div aria-live="polite" className="xh-detail">
        {(['tail', 'alone'] as const).map((each) => (
          <div hidden={square !== undefined || view !== each} key={each}>
            {summaries[each]}
          </div>
        ))}
        {square === undefined ? null : <Line blob={blob} facts={square} />}
      </div>
    </div>
  );
}
