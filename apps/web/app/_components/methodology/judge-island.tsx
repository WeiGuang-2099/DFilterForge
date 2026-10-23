'use client';

/**
 * @fileoverview The judge figure's island: the mode switch, the squares'
 * one tab stop and the readout.
 *
 * The squares, every count for both modes and one detail block per answer
 * are server-rendered children; the island renders no value. It sets the
 * figure's data-mode, which the page's style sheet reads to fill each
 * square by its verdict in that mode and to show that mode's counts, and
 * shows the detail block of the square read out with a style rule keyed
 * on its place (data-q on the square, data-d on its block). The square
 * read out is the one focused from the keyboard while focus stays in the
 * figure, else the one last pointed at while the pointer stays among the
 * squares, else the one a press holds: pointing reads any square, even
 * while another is held, and moving the pointer off the squares, as on to
 * the readout and its link, brings the held square back. A press holds a
 * square, and so marks it pressed, until Escape or a second press; the
 * page opens with the server's pick held. The squares make one tab stop:
 * the arrow keys move along the rows and to the nearest square of the line
 * above or below, Home and End to a row's ends, and the tab stop follows.
 */

import {useEffect, useRef, useState} from 'react';
import type {
  FocusEvent,
  KeyboardEvent as KeyEvent,
  MouseEvent,
  ReactNode,
  SyntheticEvent,
} from 'react';

/** A judge mode: the request alone, or with the reference filter. */
export type Mode = 'primary' | 'secondary';

const MODES: readonly Mode[] = ['primary', 'secondary'];

interface FigureProps {
  /** The switch's words for each mode. */
  readonly labels: Readonly<Record<Mode, string>>;
  /** The square held when the page opens, which the server marks pressed. */
  readonly initial: number | null;
  readonly children: ReactNode;
}

/** The square an event comes from, by its place across the rows. */
function squareOf(event: SyntheticEvent): number | null {
  const target = event.target instanceof Element ? event.target : null;
  const square = target?.closest<HTMLElement>('[data-q]');
  return square == null ? null : Number(square.dataset['q']);
}

function placeOf(square: Element | null | undefined): number | null {
  return square instanceof HTMLElement ? Number(square.dataset['q']) : null;
}

/** The nearest square on the next line below (1) or above (-1). */
function nearest(squares: readonly HTMLElement[], from: HTMLElement, way: 1 | -1): number | null {
  const box = from.getBoundingClientRect();
  const middle = box.left + box.width / 2;
  const half = box.height / 2;
  let found: number | null = null;
  let rise = Infinity;
  let off = Infinity;
  for (const [at, square] of squares.entries()) {
    const rect = square.getBoundingClientRect();
    const down = (rect.top - box.top) * way;
    const aside = Math.abs(rect.left + rect.width / 2 - middle);
    if (down > half && (down < rise - half || (Math.abs(down - rise) <= half && aside < off))) {
      [found, rise, off] = [at, down, aside];
    }
  }
  return found;
}

/** Where a key moves from a square: a place, null to stay, or undefined. */
function step(
  key: string,
  squares: readonly HTMLElement[],
  from: number,
): number | null | undefined {
  const square = squares[from];
  const row = square?.parentElement;
  if (square === undefined || row == null) {
    return undefined;
  }
  switch (key) {
    case 'ArrowRight':
      return from + 1 < squares.length ? from + 1 : null;
    case 'ArrowLeft':
      return from > 0 ? from - 1 : null;
    case 'Home':
      return placeOf(row.firstElementChild);
    case 'End':
      return placeOf(row.lastElementChild);
    case 'ArrowDown':
      return nearest(squares, square, 1);
    case 'ArrowUp':
      return nearest(squares, square, -1);
    default:
      return undefined;
  }
}

/** The mode switch over the server-rendered figure. */
export function JudgeFigure({labels, initial, children}: FigureProps): ReactNode {
  const root = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>('primary');
  const [pointed, setPointed] = useState<number | null>(null);
  const [keyed, setKeyed] = useState<number | null>(null);
  const [held, setHeld] = useState<number | null>(initial);
  // The square that takes the figure's one tab stop.
  const [stop, setStop] = useState(0);
  const shown = keyed ?? pointed ?? held;

  const squares = (): HTMLElement[] =>
    Array.from(root.current?.querySelectorAll<HTMLElement>('[data-q]') ?? []);

  // The squares are the server's markup, so their tab stop and pressed
  // state are set on the elements.
  useEffect(() => {
    for (const square of root.current?.querySelectorAll<HTMLElement>('[data-q]') ?? []) {
      const at = placeOf(square);
      square.tabIndex = at === stop ? 0 : -1;
      square.setAttribute('aria-pressed', String(at === held));
    }
  }, [stop, held]);

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

  // A gap or a label among the squares keeps the square last pointed at;
  // the rest of the figure lets it go, so a held square comes back.
  const point = (event: SyntheticEvent) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('.jd-rows') == null) {
      setPointed(null);
      return;
    }
    const at = squareOf(event);
    if (at !== null) {
      setPointed(at);
    }
  };
  // Only focus the keyboard moved (:focus-visible): a click focuses the
  // square it presses, and the press, not the focus, says what to read.
  const focus = (event: FocusEvent<HTMLDivElement>) => {
    const at = squareOf(event);
    if (at !== null && event.target.matches(':focus-visible')) {
      setKeyed(at);
      setStop(at);
    }
  };
  // Focus that moves on within the figure, as Tab does to the block's
  // link, keeps the square.
  const blur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) {
      setKeyed(null);
    }
  };
  // Enter and Space press a button with no pointer (detail 0); the square
  // stays focused and read out from the keyboard.
  const press = (event: MouseEvent<HTMLDivElement>) => {
    const at = squareOf(event);
    if (at !== null) {
      setHeld(held === at ? null : at);
      setStop(at);
      setKeyed(event.detail === 0 ? at : null);
    }
  };
  const move = (event: KeyEvent<HTMLDivElement>) => {
    const from = squareOf(event);
    const all = squares();
    const to = from === null ? undefined : step(event.key, all, from);
    if (to === undefined) {
      return;
    }
    event.preventDefault();
    if (to !== null) {
      setStop(to);
      all[to]?.focus();
    }
  };
  const switchTo = (next: Mode) => {
    setMode(next);
    setPointed(null);
    setKeyed(null);
  };

  return (
    <div
      className="jd"
      data-mode={mode}
      onBlur={blur}
      onClick={press}
      onFocus={focus}
      onKeyDown={move}
      onPointerLeave={() => setPointed(null)}
      onPointerOver={point}
      ref={root}
    >
      <div className="jd-bar">
        <span className="lab" id="jd-mode-label">
          The judge saw
        </span>
        <div aria-labelledby="jd-mode-label" className="jd-seg" role="group">
          {MODES.map((each) => (
            <button
              aria-pressed={mode === each}
              id={`jd-mode-${each}`}
              key={each}
              onClick={() => switchTo(each)}
              type="button"
            >
              {labels[each]}
            </button>
          ))}
        </div>
      </div>
      {children}
      {shown === null ? null : (
        <style>{`.jd [data-d="${shown}"]{display:block}.jd .jd-hint{display:none}`}</style>
      )}
    </div>
  );
}
