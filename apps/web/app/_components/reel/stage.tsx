'use client';

/**
 * @fileoverview The Reel's stage: the root its clock writes on, the column
 * the readout shows, and the controls.
 *
 * The stage renders no value of its own. It holds the cursor's column and
 * shows the server-rendered readout of that column alone, with one style
 * rule keyed on data-at, so every column's values stay in the HTML that
 * the server wrote and the consistency test reads.
 */

import {createContext, useCallback, useContext, useEffect, useMemo, useRef, useState} from 'react';
import type {CSSProperties, ReactNode} from 'react';

import type {NumNode} from '@/lib/data';

import {Clock} from './clock';
import type {Mode} from './clock';

interface ReelState {
  readonly at: number;
  readonly numbers: readonly NumNode[];
  readonly lit: readonly boolean[];
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
  /** The frame number each column shows, from the strips' frame lists. */
  readonly numbers: readonly NumNode[];
  /** Whether any probe disagrees with its labels at each column. */
  readonly lit: readonly boolean[];
  /** The column of the frame rule reel-v1 highlights. */
  readonly highlight: number;
  readonly children: ReactNode;
}

/** The stage root: owns the clock and the column the readout shows. */
export function Stage({numbers, lit, highlight, children}: StageProps) {
  const root = useRef<HTMLDivElement>(null);
  const clock = useRef<Clock | null>(null);
  const [at, setAt] = useState(highlight);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<Mode>('pinned');

  useEffect(() => {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const host = {root: () => root.current, column: setAt, mode: setMode, playing: setPlaying};
    const running = new Clock(host, lit, highlight, still);
    clock.current = running;
    // The Reel plays once, when the page is first visible, and stops on its
    // final state when the page is hidden.
    let played = still;
    const visibility = () => {
      if (document.visibilityState === 'hidden') {
        running.stop();
      } else if (!played) {
        played = true;
        running.play();
      }
    };
    document.addEventListener('visibilitychange', visibility);
    visibility();
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      running.dispose();
      clock.current = null;
    };
  }, [lit, highlight]);

  const act = useCallback((action: (running: Clock) => void) => {
    if (clock.current !== null) {
      action(clock.current);
    }
  }, []);
  const value = useMemo(() => ({at, numbers, lit, playing, act}), [at, numbers, lit, playing, act]);
  const base = {'--cx0': highlight, '--cols': numbers.length} as CSSProperties;
  return (
    <ReelContext.Provider value={value}>
      <div className="reel" data-lit={lit[at] === true} data-mode={mode} ref={root} style={base}>
        <style>{`.reel .at:not([data-at="${at}"]){display:none}`}</style>
        {children}
      </div>
    </ReelContext.Provider>
  );
}

/** Play or stop the Reel, and step between the frames that disprove. */
export function Controls() {
  const reel = useReel();
  const step = (direction: 1 | -1) =>
    reel.act((clock) => {
      const column = clock.nextLit(direction);
      if (column !== undefined) {
        clock.seek(column, 'glide');
      }
    });
  return (
    <div className="ctl">
      <button
        className="btn"
        data-state={reel.playing ? 'stop' : 'play'}
        onClick={() => reel.act((clock) => (reel.playing ? clock.stop() : clock.play()))}
        type="button"
      >
        <span aria-hidden="true" className="ico" />
        {reel.playing ? 'Stop the reel' : 'Play the reel'}
      </button>
      <button className="sbtn" onClick={() => step(-1)} type="button">
        Previous disproof
      </button>
      <button className="sbtn" onClick={() => step(1)} type="button">
        Next disproof
      </button>
      <p className="hint">Drag the cursor along the strips, or focus its flag and use the arrow keys.</p>
    </div>
  );
}
