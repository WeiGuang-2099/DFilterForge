/**
 * @fileoverview The board's marks: outcome bars, repair bars and intervals.
 *
 * Server-rendered from board.json. No mark divides: an outcome bar's
 * segments grow by the counts they stand for (flex-grow), and a repair bar
 * is a grid of one column per triggered answer whose fill spans one column
 * per repaired answer. An interval is drawn where its committed bounds lie
 * on the mark's scale, zero to one for a rate and minus one to one for a
 * difference. Every number beside a mark is a sourced value.
 */

import type {CSSProperties, ReactNode} from 'react';

import type {Arm, Interval, TestRow} from '@/lib/board-data';
import type {NumNode} from '@/lib/data';
import {Num, Str, Term} from '@/lib/sourced';

/** A count a sourced node holds; a mark is drawn only from counts. */
function count(node: NumNode): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    throw new Error(`board: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

/** A bound a sourced node holds, which places an interval on its scale. */
function bound(node: NumNode | null, what: string): number {
  if (node === null || typeof node.v !== 'number') {
    throw new Error(`board: the ${what} has no value`);
  }
  return node.v;
}

/** The value of an interval, which the board always shows. */
function shown(interval: Interval, what: string) {
  if (interval === null || interval.value === null) {
    throw new Error(`board: the ${what} has no value`);
  }
  return {value: interval.value, low: interval.low, high: interval.high};
}

interface RateProps {
  readonly interval: Interval;
  readonly what: string;
}

/** A rate or difference and its interval, as locked-test-v1.md writes it. */
export function Rate({interval, what}: RateProps): ReactNode {
  const {value, low, high} = shown(interval, what);
  return (
    <span className="bd-rate">
      <Num kind="rate" node={value} />
      {low === null || high === null ? null : (
        <span className="bd-ci">
          {' ['}
          <Num kind="rate" node={low} />
          {', '}
          <Num kind="rate" node={high} />]
        </span>
      )}
    </span>
  );
}

interface SpanProps {
  readonly interval: Interval;
  readonly what: string;
  readonly scale: 'rate' | 'difference';
}

/** An interval drawn on its scale; a difference also marks zero and its value. */
export function Span({interval, what, scale}: SpanProps): ReactNode {
  const {value, low, high} = shown(interval, what);
  const style = {
    '--lo': bound(low, what),
    '--hi': bound(high, what),
    '--v': bound(value, what),
  } as CSSProperties;
  return (
    <span aria-hidden="true" className={`bd-span bd-span-${scale}`} style={style}>
      <span className="bd-span-ci" />
      {scale === 'difference' ? <span className="bd-span-v" /> : null}
    </span>
  );
}

// The outcomes an outcome bar draws on its own: the strong-exact answers and
// the two kinds the repair round sends back. The rest share one segment.
const OWN = ['strong_exact', 'shortcut', 'silent_wrong', 'invalid'] as const;
const REST = ['malformed', 'provider_failed', 'abstained'] as const;

/** The legend of an outcome bar's segments. */
export function OutcomeLegend(): ReactNode {
  return (
    <ul aria-label="Bar legend" className="bd-legend">
      <li>
        <span aria-hidden="true" className="bd-sw bd-o-strong_exact" />
        strong exact
      </li>
      <li>
        <span aria-hidden="true" className="bd-sw bd-o-shortcut" />
        shortcut
      </li>
      <li>
        <span aria-hidden="true" className="bd-sw bd-o-silent_wrong" />
        silent-wrong, sent to the repair round
      </li>
      <li>
        <span aria-hidden="true" className="bd-sw bd-o-invalid" />
        invalid, sent to the repair round
      </li>
      <li>
        <span aria-hidden="true" className="bd-sw bd-o-other" />
        malformed, provider failed or abstained
      </li>
      <li>
        <span aria-hidden="true" className="bd-sw bd-sw-ci" />
        strong-exact interval
      </li>
    </ul>
  );
}

type Condition = TestRow['conditions'][number];

/** One condition's ready items by outcome, with the strong-exact interval. */
export function OutcomeBar({condition}: {readonly condition: Condition}): ReactNode {
  const {segments} = condition;
  const rest = REST.reduce((sum, kind) => sum + count(segments[kind]), 0);
  const parts: [string, number][] = [
    ...OWN.map((kind): [string, number] => [kind, count(segments[kind])]),
    ['other', rest],
  ];
  return (
    <span className="bd-mark">
      <span aria-hidden="true" className="bd-seg">
        {parts.map(([kind, grow]) =>
          grow === 0 ? null : (
            <span className={`bd-o-${kind}`} key={kind} style={{flexGrow: grow}} />
          ),
        )}
      </span>
      <Span interval={condition.metrics.strong_exact} scale="rate" what="strong exact" />
    </span>
  );
}

/** A grid of one equal column per triggered answer. */
function columns(triggered: number): CSSProperties {
  return {gridTemplateColumns: `repeat(${triggered}, minmax(0, 1fr))`};
}

interface ArmBarsProps {
  readonly arms: readonly Arm[];
  // The id of the heading that names the round; a model id holds digits,
  // which no label attribute may.
  readonly labelledBy: string;
  readonly compact?: boolean;
}

/** A round's arms: repaired of triggered answers, repair@1 and its interval. */
export function ArmBars({arms, labelledBy, compact = false}: ArmBarsProps): ReactNode {
  return (
    <ol aria-labelledby={labelledBy} className={compact ? 'bd-arms bd-arms-compact' : 'bd-arms'}>
      {arms.map((arm) => {
        const repaired = count(arm.repaired);
        return (
          <li key={arm.arm.t}>
            <span className="bd-arm">
              <Str node={arm.arm} />
            </span>
            <span className="bd-mark">
              <span
                aria-hidden="true"
                className="bd-track"
                style={columns(count(arm.triggered))}
              >
                {repaired === 0 ? null : (
                  <span className="bd-fill" style={{gridColumn: `span ${repaired}`}} />
                )}
              </span>
              <Span interval={arm.repair_at_1} scale="rate" what="repair rate" />
            </span>
            <span className="bd-arm-n">
              <span>
                <Term name="repair@1" /> <Rate interval={arm.repair_at_1} what="repair rate" />
              </span>
              <span className="bd-of">
                <Num kind="int" node={arm.repaired} /> of <Num kind="int" node={arm.triggered} />{' '}
                repaired
              </span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
