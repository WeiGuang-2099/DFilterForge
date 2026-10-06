'use client';

/**
 * @fileoverview The measurement cursor across the ladder.
 *
 * A band behind the cursor's row, a line across the ladder with a flag at
 * its left end that holds the frame number, and a veil over the rows the
 * sweep has not reached. Drag the flag, or press anywhere on the ladder
 * and drag; a drag holds on each row where the filter and the request
 * disagree. Focus the flag for the keys. The flag is the one sourced value
 * a client component renders: the frame number of its row, through the
 * same fmt() the consistency test checks. Everything else the cursor
 * points at is server-rendered; the stage only says which frame shows.
 */

import {useRef} from 'react';
import type {KeyboardEvent, MouseEvent, PointerEvent} from 'react';

import {fmt} from '@/lib/fmt';

import type {Clock, Move} from './clock';
import {useReel} from './stage';

const PAGE = 10;
// A drag scrolls the page this many pixels a frame within EDGE of the
// window's top or bottom.
const EDGE = 56;
const SCROLL = 6;

/** The band, which sits behind the ladder's lines. */
export function CursorBand() {
  return <div aria-hidden="true" className="cur-band" />;
}

/** The cursor overlay; it covers the rows of the shown ladder. */
export function Cursor() {
  const reel = useReel();
  const area = useRef<HTMLDivElement>(null);
  const drag = useRef<{offset: number; y: number; scroll: number} | null>(null);
  const {probe, row} = reel.spot;
  const numbers = reel.numbers[probe] ?? [];
  const node = numbers[row];
  if (node === undefined) {
    throw new Error('Cursor: the stage shows no frame');
  }

  // Pointer geometry only: no value shown on the page comes from it.
  const down = (y: number) => y - (area.current?.getBoundingClientRect().top ?? 0);
  const follow = (clock: Clock) => {
    const held = drag.current;
    const found = held === null ? null : clock.rowAt(down(held.y) - held.offset, true);
    if (found !== null) {
      clock.seek(found, 'drag');
    }
  };
  const scroll = () => {
    const held = drag.current;
    if (held === null) {
      return;
    }
    const by = held.y < EDGE ? -SCROLL : held.y > window.innerHeight - EDGE ? SCROLL : 0;
    if (by !== 0) {
      window.scrollBy(0, by);
      reel.act(follow);
    }
    held.scroll = by === 0 ? 0 : requestAnimationFrame(scroll);
  };
  const start = (event: PointerEvent<HTMLElement>, offset: number) => {
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {offset, y: event.clientY, scroll: 0};
    area.current?.querySelector<HTMLElement>('[role="slider"]')?.focus({preventScroll: true});
  };

  const onArea = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== 'mouse' || event.button !== 0) {
      return;
    }
    const y = down(event.clientY);
    reel.act((clock) => {
      const found = clock.rowAt(y, false);
      if (found !== null) {
        start(event, 0);
        clock.seek(found, 'drag');
      }
    });
  };
  const onFlag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) {
      return;
    }
    event.stopPropagation();
    const box = event.currentTarget.getBoundingClientRect();
    start(event, event.clientY - (box.top + box.height / 2));
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const held = drag.current;
    if (held !== null) {
      held.y = event.clientY;
      reel.act(follow);
      held.scroll ||= requestAnimationFrame(scroll);
    }
  };
  const up = () => {
    if (drag.current !== null) {
      cancelAnimationFrame(drag.current.scroll);
      drag.current = null;
      reel.act((clock) => clock.release());
    }
  };
  // A tap pins the frame under it; a touch that scrolls the page does not.
  const tap = (event: MouseEvent<HTMLDivElement>) => {
    const native = event.nativeEvent;
    const mouse = !('pointerType' in native) || native.pointerType === 'mouse';
    if (!mouse && drag.current === null) {
      const y = down(event.clientY);
      reel.act((clock) => {
        const found = clock.rowAt(y, false);
        if (found !== null) {
          clock.seek(found, 'glide');
        }
      });
    }
  };

  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Readonly<Record<string, [number, Move]>> = {
      ArrowDown: [1, 'step'],
      ArrowRight: [1, 'step'],
      ArrowUp: [-1, 'step'],
      ArrowLeft: [-1, 'step'],
      PageDown: [PAGE, 'page'],
      PageUp: [-PAGE, 'page'],
      Home: [-numbers.length, 'step'],
      End: [numbers.length, 'step'],
    };
    const found = moves[event.key];
    if (found !== undefined) {
      event.preventDefault();
      reel.act((clock) => clock.step(...found));
    }
  };

  const lit = reel.tracks[probe]?.lit[row] === true;
  return (
    <div
      className="cur"
      onClick={tap}
      onLostPointerCapture={up}
      onPointerCancel={up}
      onPointerDown={onArea}
      onPointerMove={move}
      onPointerUp={up}
      ref={area}
    >
      <div aria-hidden="true" className="cur-veil" />
      <div aria-hidden="true" className="cur-line" />
      <div
        aria-label="Frame cursor"
        aria-orientation="vertical"
        aria-valuenow={Number(node.v)}
        aria-valuetext={`Frame ${fmt(node.v, 'int')}${lit ? ', which disproves the filter' : ''}`}
        className="cur-flag"
        data-fmt="int"
        data-src={JSON.stringify(node.src)}
        data-v={JSON.stringify(node.v)}
        onKeyDown={key}
        onPointerDown={onFlag}
        role="slider"
        tabIndex={0}
      >
        {fmt(node.v, 'int')}
      </div>
    </div>
  );
}
