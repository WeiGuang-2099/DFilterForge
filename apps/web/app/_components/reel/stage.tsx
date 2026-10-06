'use client';

/**
 * @fileoverview The Reel's stage: the root its clock writes on, the frame
 * the readout shows, the controls and the probe mini-map.
 *
 * The stage renders no value of its own. It holds the cursor's probe and
 * row and shows the server-rendered ladder of that probe and readout of
 * that frame alone, with style rules keyed on data-p and data-at, so every
 * frame's values stay in the HTML the server wrote and the consistency
 * test reads. The page opens on the highlighted frame; the sweep plays
 * once that frame's row is in view, unless the visitor acts first.
 */

import {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState} from 'react';
import type {CSSProperties, ReactNode} from 'react';

import type {NumNode} from '@/lib/data';

import {Clock} from './clock';
import type {Mode, Spot, Track} from './clock';

interface ReelState {
  readonly spot: Spot;
  readonly tracks: readonly Track[];
  /** Each probe's frame numbers, one per ladder row. */
  readonly numbers: readonly (readonly NumNode[])[];
  readonly playing: boolean;
  /** Runs an action on the clock once the stage has mounted. */
  readonly act: (action: (clock: Clock) => void) => void;
}

const ReelContext = createContext<ReelState | null>(null);

/** The stage's state, for the cursor and the controls inside it. */
export function useReel(): ReelState {
  const reel = useContext(ReelContext);
  if (reel === null) {
    throw new Error('useReel: outside <Stage>');
  }
  return reel;
}

interface StageProps {
  readonly tracks: readonly Track[];
  readonly numbers: readonly (readonly NumNode[])[];
  readonly highlight: Spot;
  readonly children: ReactNode;
}

// The sweep starts this long after the highlighted row is in full view,
// unless one of these events comes first.
const ARM = 1100;
const INPUTS = ['pointerdown', 'pointerup', 'keydown'] as const;

/** The stage root: owns the clock and the frame the readout shows. */
export function Stage({tracks, numbers, highlight, children}: StageProps) {
  const root = useRef<HTMLDivElement>(null);
  const clock = useRef<Clock | null>(null);
  const touched = useRef(false);
  const [spot, setSpot] = useState(highlight);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<Mode>('pinned');

  useEffect(() => {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const host = {root: () => root.current, spot: setSpot, mode: setMode, playing: setPlaying};
    const running = new Clock(host, tracks, highlight, still);
    clock.current = running;
    // Any input hands the stage to the visitor: no sweep starts by itself
    // after it, and input other than the play button stops one that plays.
    // A touch counts when it lifts, since one that scrolls is cancelled.
    const input = (event: Event) => {
      const touch = event instanceof PointerEvent && event.pointerType === 'touch';
      const counts =
        event instanceof KeyboardEvent
          ? !['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(event.key)
          : (event.type === 'pointerup') === touch;
      const target = event.target instanceof Element ? event.target : null;
      touched.current ||= counts;
      if (counts && target?.closest('[data-play]') == null) {
        running.stop();
      }
    };
    const hidden = () => document.visibilityState === 'hidden' && running.stop();
    let timer = 0;
    const {probe, row: shown} = highlight;
    const row = root.current?.querySelector(`[data-p="${probe}"] [data-at="${probe}-${shown}"]`);
    const seen = new IntersectionObserver(
      ([entry]) => {
        if (entry !== undefined && entry.intersectionRatio >= 0.99 && !still) {
          seen.disconnect();
          timer = window.setTimeout(() => touched.current || running.play(), ARM);
        }
      },
      {threshold: [0, 1]},
    );
    if (row != null) {
      seen.observe(row);
    }
    INPUTS.forEach((type) => document.addEventListener(type, input, true));
    document.addEventListener('visibilitychange', hidden);
    return () => {
      seen.disconnect();
      window.clearTimeout(timer);
      INPUTS.forEach((type) => document.removeEventListener(type, input, true));
      document.removeEventListener('visibilitychange', hidden);
      running.dispose();
      clock.current = null;
    };
  }, [tracks, highlight]);

  const act = useCallback((action: (running: Clock) => void) => {
    if (clock.current !== null) {
      action(clock.current);
    }
  }, []);
  const value = useMemo(
    () => ({spot, tracks, numbers, playing, act}),
    [spot, tracks, numbers, playing, act],
  );
  const at = `${spot.probe}-${spot.row}`;
  const lit = tracks[spot.probe]?.lit[spot.row] === true;
  const first = tracks[highlight.probe];
  const base = {
    '--cy': `${first?.tops[highlight.row] ?? 0}px`,
    '--ch': `${first?.heights[highlight.row] ?? 0}px`,
    '--fr': highlight.row,
  } as CSSProperties;
  return (
    <ReelContext.Provider value={value}>
      <div className="reel" data-lit={lit} data-mode={mode} ref={root} style={base}>
        <style>
          {`.reel .at:not([data-at="${at}"]),.reel :is(.lad-p,.atp):not([data-p="${spot.probe}"])` +
            `{display:none}.reel .fr[data-at="${at}"]{--halo:var(--band)}` +
            `.reel .m-miss[data-at="${at}"]{fill:var(--dis)}`}
        </style>
        {children}
      </div>
    </ReelContext.Provider>
  );
}

/** Play or stop the sweep, and step between the frames that disprove. */
export function Controls({hint}: {readonly hint: string}) {
  const reel = useReel();
  const step = (direction: 1 | -1) =>
    reel.act((clock) => {
      const next = clock.nextLit(direction);
      if (next !== undefined) {
        clock.jump(next.probe, next.row);
      }
    });
  return (
    <div className="ctl">
      <button
        className="btn"
        data-play=""
        data-state={reel.playing ? 'stop' : 'play'}
        onClick={() => reel.act((clock) => (reel.playing ? clock.stop() : clock.play()))}
        type="button"
      >
        <span aria-hidden="true" className="ico" />
        {reel.playing ? 'Stop the sweep' : 'Play the sweep'}
      </button>
      <button className="sbtn" onClick={() => step(-1)} type="button">
        Previous disproof
      </button>
      <button className="sbtn" onClick={() => step(1)} type="button">
        Next disproof
      </button>
      <p className="hint">{hint}</p>
    </div>
  );
}

/** The probes as bars over the ladder; choosing one draws its ladder. */
export function MiniMap({bars}: {readonly bars: readonly ReactNode[]}) {
  const reel = useReel();
  return (
    <div className="strips" role="group" aria-label="Probes. Choose one to draw its ladder.">
      {bars.map((bar, probe) => (
        <button
          aria-pressed={reel.spot.probe === probe}
          className="ps"
          key={probe}
          onClick={() => reel.act((clock) => clock.jump(probe, reel.spot.row))}
          type="button"
        >
          {bar}
        </button>
      ))}
    </div>
  );
}
