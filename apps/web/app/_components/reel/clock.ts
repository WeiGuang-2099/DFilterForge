/**
 * @fileoverview The Reel's one clock: a requestAnimationFrame loop that
 * plays the sweep and eases the measurement cursor down the ladder.
 *
 * Every moving part of the stage reads CSS custom properties this loop
 * writes on the stage's root, and no transition or keyframe moves it, so
 * Playwright's page.clock steps the whole Reel frame by frame. The sweep
 * starts at the first animation frame after play(), whose timestamp the
 * fake clock sets, so two recordings of one build give the same frames.
 * The loop only moves geometry and says which frame the readout shows;
 * the values are server-rendered.
 */

// The sweep, in seconds: the hold on the first frame, the time per full
// and per collapsed row (one shorter than SHORT pixels), the veil's fade
// after the cursor arrives and the time from the arrival to the end.
const [LEAD, FULL, TICKED, TAIL, SHORT] = [0.4, 0.11, 0.035, 0.8, 12];
const VEIL = [0.2, 0.45] as const;
// The cursor's glide toward its row, the hold on a disagreeing row a drag
// crosses, and the flag's nudge on arrival, in milliseconds.
const GLIDE = 40;
const DETENT = 240;
const NUDGE = 140;

/**
 * How a move reaches its row: a glide; a drag, held on each disagreeing
 * row it crosses; a step of one key press; or a page, which stops on the
 * first disagreeing row it crosses.
 */
export type Move = 'glide' | 'drag' | 'step' | 'page';

/** What the stage shows: the cursor pinned, the sweep, or a drag. */
export type Mode = 'pinned' | 'sweep' | 'drag';

/** One probe's ladder rows, in pixels, and whether each disagrees. */
export interface Track {
  readonly tops: readonly number[];
  readonly heights: readonly number[];
  readonly lit: readonly boolean[];
}

/** A probe and a row of its ladder; the row is the frame number less one. */
export interface Spot {
  readonly probe: number;
  readonly row: number;
}

/** What the clock tells the stage, which owns the markup. */
export interface Host {
  readonly root: () => HTMLElement | null;
  readonly spot: (spot: Spot) => void;
  readonly mode: (mode: Mode) => void;
  readonly playing: (playing: boolean) => void;
}

/** The cursor's row at each second of the sweep, as [time, row] keys. */
function sweep({heights}: Track, to: number): {keys: number[][]; arrive: number} {
  const keys = [
    [0, 0],
    [LEAD, 0],
  ];
  for (let row = 1; row <= to; row += 1) {
    const [t = 0] = keys[keys.length - 1] ?? [];
    keys.push([t + ((heights[row] ?? 0) < SHORT ? TICKED : FULL), row]);
  }
  return {keys, arrive: keys[keys.length - 1]?.[0] ?? 0};
}

function along(keys: readonly number[][], t: number): number {
  const after = keys.findIndex(([at = 0]) => at > t);
  if (after <= 0) {
    return after === 0 ? 0 : (keys[keys.length - 1]?.[1] ?? 0);
  }
  const [t0 = 0, x0 = 0] = keys[after - 1] ?? [];
  const [t1 = 0, x1 = 0] = keys[after] ?? [];
  return x0 + ((x1 - x0) * (t - t0)) / (t1 - t0);
}

/** The timeline and the cursor's motion, outside React. */
export class Clock {
  private probe: number;
  private x: number;
  private target: number;
  private pending: number | null = null;
  private hold = 0;
  private bump = -Infinity;
  // The sweep's start: null when it does not play, 'next' until its first
  // animation frame.
  private start: number | 'next' | null = null;
  private then: number | null = null;
  private frame = 0;
  private shown: number;
  private readonly plan: {keys: number[][]; arrive: number};

  /**
   * @param host What the clock tells the stage.
   * @param tracks Each probe's ladder rows.
   * @param highlight The spot the page opens on, where the sweep ends.
   * @param still Reduced motion: the cursor jumps instead of gliding and a
   *     drag does not pause on a disagreeing row.
   */
  constructor(
    private readonly host: Host,
    private readonly tracks: readonly Track[],
    private readonly highlight: Spot,
    readonly still: boolean,
  ) {
    this.probe = highlight.probe;
    this.x = this.target = this.shown = highlight.row;
    this.plan = sweep(this.track, highlight.row);
  }

  private get track(): Track {
    const track = this.tracks[this.probe];
    if (track === undefined) {
      throw new Error(`clock: no probe ${this.probe}`);
    }
    return track;
  }

  /** Sweeps the highlighted probe from its first frame to the highlight. */
  play(): void {
    this.jump(this.highlight.probe, 0);
    this.start = 'next';
    this.host.playing(true);
    this.host.mode('sweep');
    this.write({'--veil': 1});
  }

  /** Stops the sweep, if it plays, where the cursor is. */
  stop(): void {
    if (this.start !== null) {
      this.start = null;
      this.target = Math.round(this.x);
      this.write({'--veil': 0});
      this.host.playing(false);
      this.host.mode('pinned');
    }
  }

  /** Moves the cursor toward a row of this probe; any move stops the sweep. */
  seek(row: number, move: Move): void {
    this.stop();
    const goal = Math.min(this.track.tops.length - 1, Math.max(0, row));
    if (move === 'page' || (move === 'drag' && !this.still)) {
      this.aim(goal, move === 'page' ? Infinity : performance.now());
    } else {
      Object.assign(this, {target: goal, pending: null, hold: 0});
    }
    if (move === 'page') {
      Object.assign(this, {pending: null, hold: 0});
    }
    this.host.mode(move === 'drag' ? 'drag' : 'pinned');
    this.wake();
  }

  /**
   * Moves the cursor by rows from where it is headed, not from the row on
   * screen, so key presses during a glide add up.
   */
  step(rows: number, move: Move): void {
    this.seek(this.target + rows, move);
  }

  /** Shows another probe, or this one, at a row, with no glide between. */
  jump(probe: number, row: number): void {
    this.stop();
    this.probe = probe;
    const goal = Math.min(this.track.tops.length - 1, Math.max(0, row));
    Object.assign(this, {x: goal, target: goal, pending: null, hold: 0, shown: -1});
    this.wake();
  }

  /** Ends a drag where it was headed. */
  release(): void {
    if (this.pending !== null) {
      Object.assign(this, {target: this.pending, pending: null, hold: 0});
    }
    this.host.mode('pinned');
    this.wake();
  }

  /**
   * The row under a point this many pixels down the ladder; past either
   * end, the end row when `clamp` holds, else null. The row the cursor is
   * headed for keeps three pixels each side, so a pointer resting on a
   * row's edge does not flutter between two frames.
   */
  rowAt(y: number, clamp: boolean): number | null {
    const {tops, heights} = this.track;
    const [kept = 0, high = 0] = [tops[this.target], heights[this.target]];
    const row = tops.findLastIndex((top) => top <= y);
    const last = tops.length - 1;
    if (y >= kept - 3 && y < kept + high + 3) {
      return this.target;
    }
    if (row >= 0 && y < (tops[last] ?? 0) + (heights[last] ?? 0)) {
      return row;
    }
    return clamp ? (row < 0 ? 0 : last) : null;
  }

  /** The disagreeing spot after or before the cursor's, over every probe. */
  nextLit(direction: 1 | -1): Spot | undefined {
    const spots = this.tracks.flatMap((track, probe) =>
      track.lit.flatMap((on, row) => (on ? [{probe, row}] : [])),
    );
    const order = (spot: Spot) => spot.probe - this.probe || spot.row - this.target;
    return direction > 0
      ? (spots.find((spot) => order(spot) > 0) ?? spots[0])
      : (spots.findLast((spot) => order(spot) < 0) ?? spots[spots.length - 1]);
  }

  /** Stops the loop; the stage calls it when it unmounts. */
  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  /**
   * Aims a dragged cursor at a row. The first disagreeing row on the way
   * holds it for the detent, and the rest of the drag waits behind it.
   */
  private aim(goal: number, now: number): void {
    if (now < this.hold) {
      this.pending = goal;
      return;
    }
    const step = goal > this.target ? 1 : -1;
    let crossed: number | null = null;
    for (let row = this.target + step; goal !== this.target; row += step) {
      crossed = this.track.lit[row] === true ? row : null;
      if (crossed !== null || row === goal) {
        break;
      }
    }
    this.target = crossed ?? goal;
    this.pending = crossed !== null && crossed !== goal ? goal : null;
    this.hold = crossed !== null ? now + DETENT : 0;
  }

  private wake(): void {
    if (this.frame === 0) {
      this.then = null;
      this.frame = requestAnimationFrame(this.tick);
    }
  }

  private write(vars: Readonly<Record<string, number | string>>): void {
    for (const [name, value] of Object.entries(vars)) {
      const text = typeof value === 'number' ? String(Math.round(value * 1000) / 1000) : value;
      this.host.root()?.style.setProperty(name, text);
    }
  }

  private readonly tick = (now: number): void => {
    this.start = this.start === 'next' ? now : this.start;
    const dt = this.then === null ? 16 : now - this.then;
    this.then = now;
    let busy = true;
    if (this.start !== null) {
      const t = (now - this.start) / 1000;
      this.x = along(this.plan.keys, t);
      this.target = Math.round(this.x);
      const after = t - this.plan.arrive;
      const [delay, fade] = VEIL;
      this.write({'--veil': 1 - Math.min(1, Math.max(0, (after - delay) / fade))});
      this.host.mode(after < 0 ? 'sweep' : 'pinned');
      if (after >= TAIL) {
        this.stop();
      }
    } else {
      if (this.pending !== null && now >= this.hold) {
        this.aim(this.pending, now);
      }
      const gap = this.target - this.x;
      const close = this.still || Math.abs(gap) < 0.002;
      this.x = close ? this.target : this.x + gap * (1 - Math.exp(-dt / GLIDE));
      busy = this.x !== this.target || this.pending !== null || now - this.bump < NUDGE;
    }
    const {tops, heights, lit} = this.track;
    const shown = Math.min(tops.length - 1, Math.max(0, Math.round(this.x)));
    if (shown !== this.shown) {
      this.shown = shown;
      this.bump = lit[shown] === true && !this.still ? now : this.bump;
      this.host.spot({probe: this.probe, row: shown});
    }
    // The cursor's band, between the rows on either side of x.
    const low = Math.floor(this.x);
    const at = (list: readonly number[]) =>
      (list[low] ?? 0) + (this.x - low) * ((list[low + 1] ?? list[low] ?? 0) - (list[low] ?? 0));
    const px = (value: number) => `${Math.round(value * 100) / 100}px`;
    const nudge = now - this.bump < NUDGE ? Math.sin((Math.PI * (now - this.bump)) / NUDGE) : 0;
    this.write({'--cy': px(at(tops)), '--ch': px(at(heights)), '--fr': this.x, '--nudge': nudge});
    this.frame = busy ? requestAnimationFrame(this.tick) : 0;
  };
}
