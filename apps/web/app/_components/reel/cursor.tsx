'use client';

/**
 * @fileoverview The measurement cursor over the capture strips.
 *
 * A vertical line through every strip with a flag on top that holds the
 * frame number. Drag the flag or anywhere on the strips, or focus the flag
 * and use the keys; a drag pauses on each column where a probe disagrees.
 * The flag is the one sourced value a client component renders: it shows
 * the frame number of its column through the same fmt() the consistency
 * test checks, and its slider attributes repeat that value. Everything
 * else the cursor points at is server-rendered; the stage only toggles
 * which readout column shows.
 */

import {useRef} from 'react';
import type {KeyboardEvent, PointerEvent} from 'react';

import {fmt} from '@/lib/fmt';

import {useReel} from './stage';

const PAGE = 10;

/** The cursor overlay; it sits over the plot column of the strips. */
export function Cursor() {
  const reel = useReel();
  const area = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const last = reel.numbers.length - 1;
  const node = reel.numbers[reel.at];
  const first = reel.numbers[0];
  const end = reel.numbers[last];
  if (node === undefined || first === undefined || end === undefined) {
    throw new Error('Cursor: the stage has no frame columns');
  }

  // Pointer geometry only: no value shown on the page comes from it.
  const columnAt = (clientX: number): number => {
    const box = area.current?.getBoundingClientRect();
    if (box === undefined || box.width === 0) {
      return reel.at;
    }
    return Math.floor(((clientX - box.left) * reel.numbers.length) / box.width);
  };

  const down = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) {
      return;
    }
    event.preventDefault();
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    const column = columnAt(event.clientX);
    reel.act((clock) => {
      clock.hover(null);
      clock.seek(column, 'drag');
    });
    event.currentTarget.querySelector<HTMLElement>('[role="slider"]')?.focus({preventScroll: true});
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    if (dragging.current) {
      reel.act((clock) => clock.seek(columnAt(event.clientX), 'drag'));
    } else if (event.pointerType === 'mouse') {
      reel.act((clock) => clock.hover(columnAt(event.clientX)));
    }
  };
  const up = () => {
    if (dragging.current) {
      dragging.current = false;
      reel.act((clock) => clock.release());
    }
  };

  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const steps: Readonly<Record<string, number>> = {
      ArrowLeft: -1,
      ArrowDown: -1,
      ArrowRight: 1,
      ArrowUp: 1,
      PageDown: -PAGE,
      PageUp: PAGE,
      Home: -last,
      End: last,
    };
    const step = steps[event.key];
    if (step === undefined) {
      return;
    }
    event.preventDefault();
    reel.act((clock) => clock.seek(reel.at + step, Math.abs(step) === PAGE ? 'page' : 'step'));
  };

  const disagrees = reel.lit[reel.at] === true;
  return (
    <div
      className="cur"
      onLostPointerCapture={up}
      onPointerCancel={up}
      onPointerDown={down}
      onPointerLeave={() => reel.act((clock) => clock.hover(null))}
      onPointerMove={move}
      onPointerUp={up}
      ref={area}
    >
      <div aria-hidden="true" className="cur-veil" />
      <div aria-hidden="true" className="cur-ghost" />
      <div aria-hidden="true" className="cur-band" />
      <div aria-hidden="true" className="cur-line" />
      <div
        aria-label="Frame cursor"
        aria-orientation="horizontal"
        aria-valuemax={Number(end.v)}
        aria-valuemin={Number(first.v)}
        aria-valuenow={Number(node.v)}
        aria-valuetext={`Frame ${fmt(node.v, 'int')}${disagrees ? ', a frame that disproves the filter' : ''}`}
        className="cur-flag"
        data-fmt="int"
        data-src={JSON.stringify(node.src)}
        data-v={JSON.stringify(node.v)}
        onKeyDown={key}
        role="slider"
        tabIndex={0}
      >
        {fmt(node.v, 'int')}
      </div>
    </div>
  );
}
