/**
 * @fileoverview The Reel's one clock: a requestAnimationFrame loop that
 * plays the timeline and eases the measurement cursor.
 *
 * Every moving part of the stage reads CSS custom properties this loop
 * writes on the stage's root, and no transition or keyframe moves the
 * stage, so Playwright's page.clock steps the whole Reel frame by frame.
 * The values on the stage are server-rendered: the loop only moves
 * geometry and opacity and says which column the readout shows. The
 * stylesheet's defaults are the final state, which a visitor without
 * JavaScript, or one who asks for reduced motion, sees.
 */

// The timeline, in seconds. The sweep runs from the first column to the
// highlighted one and beats on each column where a probe disagrees; the
// later scenes start at [delay after the arrival, length].
const LEAD = 0.6;
const PER_COLUMN = 0.075;
const BEAT = 0.45;
const SCENES = {
  '--h1': [0, 0.3],
  '--a2': [2.0, 0.5],
  '--scan2': [2.6, 1.2],
  '--a3': [4.4, 0.5],
  '--grow': [4.8, 1.0],
} as const;
const VEIL = [1.4, 0.4] as const;
const TAIL = 6.2;
// The cursor's glide toward its column, the hold on a disagreeing column a
// drag crosses, and the flag's nudge on arrival, in milliseconds.
const GLIDE = 40;
const DETENT = 240;
const NUDGE = 140;

/**
 * How a move reaches its column: a glide; a drag, held on each disagreeing
 * column it crosses; a step of one key press; or a page, which stops on the
 * first disagreeing column it crosses.
 */
export type Move = 'glide' | 'drag' | 'step' | 'page';

/** What the stage shows: the cursor pinned, the sweep, or a drag. */
export type Mode = 'pinned' | 'sweep' | 'drag';

/** What the clock tells the stage, which owns the markup. */
export interface Host {
  readonly root: () => HTMLElement | null;
  readonly column: (column: number) => void;
  readonly mode: (mode: Mode) => void;
  readonly playing: (playing: boolean) => void;
}

function ramp(t: number, [from, length]: readonly [number, number]): number {
  return Math.min(1, Math.max(0, (t - from) / length));
}

/** The cursor's column at each second of the sweep, as [time, column]. */
function sweep(lit: readonly boolean[], highlight: number): {keys: number[][]; arrive: number} {
  const keys = [
    [0, 0],
    [LEAD, 0],
  ];
  let [t, x] = [LEAD, 0];
  lit.forEach((on, column) => {
    if (on && column > 0 && column <= highlight) {
      t += (column - x) * PER_COLUMN;
      x = column;
      keys.push([t, x]);
      if (column < highlight) {
        t += BEAT;
        keys.push([t, x]);
      }
    }
  });
  return {keys, arrive: t};
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
  private x: number;
  private target: number;
  private pending: number | null = null;
  private hold = 0;
  private bump = -Infinity;
  private start: number | null = null;
  private then = 0;
  private frame = 0;
  private shown: number;
  private readonly last: number;
  private readonly plan: {keys: number[][]; arrive: number};

  /**
   * @param host What the clock tells the stage.
   * @param lit Whether any probe disagrees at each column.
   * @param highlight The column the cursor rests on.
   * @param still Reduced motion: the cursor jumps instead of gliding and a
   *     drag does not pause on a disagreeing column.
   */
  constructor(
    private readonly host: Host,
    private readonly lit: readonly boolean[],
    highlight: number,
    readonly still: boolean,
  ) {
    this.x = this.target = this.shown = highlight;
    this.last = lit.length - 1;
    this.plan = sweep(lit, highlight);
  }

  /** Plays the Reel from its first frame. */
  play(): void {
    Object.assign(this, {start: performance.now(), pending: null, x: 0, target: 0});
    this.host.playing(true);
    this.host.mode('sweep');
    this.wake();
  }

  /** Stops the Reel, if it plays, on its final state. */
  stop(): void {
    if (this.start === null) {
      return;
    }
    this.start = null;
    this.target = Math.round(this.x);
    this.write({'--h1': 1, '--veil': 0, '--a2': 1, '--scan2': 1, '--a3': 1, '--grow': 1});
    this.host.playing(false);
    this.host.mode('pinned');
  }

  /** Moves the cursor toward a column; any move stops the Reel. */
  seek(column: number, move: Move): void {
    this.stop();
    const goal = Math.min(this.last, Math.max(0, column));
    if (move === 'page') {
      this.aim(goal, Infinity);
      Object.assign(this, {pending: null, hold: 0});
    } else if (move === 'drag' && !this.still) {
      this.aim(goal, performance.now());
    } else {
      Object.assign(this, {target: goal, pending: null, hold: 0});
    }
    this.host.mode(move === 'drag' ? 'drag' : 'pinned');
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

  /** Shows a dashed line at the column under a mouse pointer, or hides it. */
  hover(column: number | null): void {
    const root = this.host.root();
    root?.toggleAttribute('data-ghost', column !== null);
    root?.style.setProperty('--gx', String(column ?? 0));
  }

  /** The column nearest the cursor's target in a direction, wrapping. */
  nextLit(direction: 1 | -1): number | undefined {
    const columns = this.lit.flatMap((on, column) => (on ? [column] : []));
    return direction > 0
      ? (columns.find((column) => column > this.target) ?? columns[0])
      : (columns.findLast((column) => column < this.target) ?? columns[columns.length - 1]);
  }

  /** Stops the loop; the stage calls it when it unmounts. */
  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  /**
   * Aims a dragged cursor at a column. The first disagreeing column on the
   * way holds it for the detent, and the rest of the drag waits behind it.
   */
  private aim(goal: number, now: number): void {
    if (now < this.hold) {
      this.pending = goal;
      return;
    }
    const step = goal > this.target ? 1 : -1;
    let crossed: number | null = null;
    for (let column = this.target + step; goal !== this.target; column += step) {
      if (this.lit[column] === true) {
        crossed = column;
      }
      if (crossed !== null || column === goal) {
        break;
      }
    }
    this.target = crossed ?? goal;
    this.pending = crossed !== null && crossed !== goal ? goal : null;
    this.hold = crossed !== null ? now + DETENT : 0;
  }

  private wake(): void {
    if (this.frame === 0) {
      this.then = performance.now();
      this.frame = requestAnimationFrame(this.tick);
    }
  }

  private write(vars: Readonly<Record<string, number>>): void {
    const root = this.host.root();
    for (const [name, value] of Object.entries(vars)) {
      root?.style.setProperty(name, String(Math.round(value * 1000) / 1000));
    }
  }

  private readonly tick = (now: number): void => {
    const dt = now - this.then;
    this.then = now;
    let busy = true;
    if (this.start !== null) {
      const t = Math.max(0, (now - this.start) / 1000);
      this.x = along(this.plan.keys, t);
      this.target = Math.round(this.x);
      const after = t - this.plan.arrive;
      const vars: Record<string, number> = {'--veil': 1 - ramp(after, VEIL)};
      for (const [name, window] of Object.entries(SCENES)) {
        vars[name] = ramp(after, window);
      }
      this.write(vars);
      this.host.mode(after < 0 ? 'sweep' : 'pinned');
      if (after >= TAIL) {
        this.stop();
      }
    } else {
      if (this.pending !== null && now >= this.hold) {
        this.aim(this.pending, now);
      }
      const gap = this.target - this.x;
      this.x =
        this.still || Math.abs(gap) < 0.002 ? this.target : this.x + gap * (1 - Math.exp(-dt / GLIDE));
      busy = this.x !== this.target || this.pending !== null || now - this.bump < NUDGE;
    }
    const shown = Math.min(this.last, Math.max(0, Math.round(this.x)));
    if (shown !== this.shown) {
      this.shown = shown;
      if (this.lit[shown] === true && !this.still) {
        this.bump = now;
      }
      this.host.column(shown);
    }
    const nudge = now - this.bump < NUDGE ? Math.sin((Math.PI * (now - this.bump)) / NUDGE) : 0;
    this.write({'--cx': this.x, '--nudge': nudge, '--cur': 1});
    this.frame = busy ? requestAnimationFrame(this.tick) : 0;
  };
}
