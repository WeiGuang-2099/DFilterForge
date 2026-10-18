/**
 * @fileoverview The training page's marks: an interval on its scale and the
 * case strip.
 *
 * Server-rendered from training.json. An interval and its value are placed
 * where their committed bounds lie, zero to one for a rate and minus one to
 * one for a difference. A case column fills one block for each strong-exact
 * answer the seeds gained over the base row, or lost, counting each seed's
 * two paraphrases, so a column is drawn from counts and never divides.
 * Every number beside a mark is a sourced value.
 */

import type {CSSProperties, ReactNode} from 'react';

import type {NumNode} from '@/lib/data';
import {Num} from '@/lib/sourced';
import type {Headline, Interval} from '@/lib/training-data';

// Every case has two paraphrases (docs/protocol.md, Splits).
const PARAPHRASES = 2;

function number(node: NumNode, what: string): number {
  if (typeof node.v !== 'number') {
    throw new Error(`training: the ${what} is not a number`);
  }
  return node.v;
}

function count(node: NumNode): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    throw new Error(`training: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

interface ScaleProps {
  readonly interval: Interval;
  readonly scale: 'rate' | 'difference';
  readonly what: string;
}

/** An interval and its value drawn on their scale. */
export function Scale({interval, scale, what}: ScaleProps): ReactNode {
  const style = {
    '--lo': number(interval.low, what),
    '--hi': number(interval.high, what),
    '--v': number(interval.value, what),
  } as CSSProperties;
  return (
    <span aria-hidden="true" className={`tr-scale tr-scale-${scale}`} style={style}>
      <span className="tr-ci" />
      <span className="tr-dot" />
    </span>
  );
}

/** A value with its interval, as the board writes one. */
export function Value({interval}: {readonly interval: Interval}): ReactNode {
  return (
    <span>
      <Num kind="rate" node={interval.value} />{' '}
      <span className="bd-ci">
        [<Num kind="rate" node={interval.low} />, <Num kind="rate" node={interval.high} />]
      </span>
    </span>
  );
}

function blocks(total: number, key: string): ReactNode[] {
  return Array.from({length: total}, (_, index) => (
    <span className="tr-block" key={`${key}-${String(index)}`} />
  ));
}

/** The ready cases in the headline's order, one column each. */
export function CaseStrip({headline}: {readonly headline: Headline}): ReactNode {
  const seeds = headline.seeds.length;
  const slots = {'--slots': seeds * PARAPHRASES} as CSSProperties;
  return (
    <ol aria-hidden="true" className="tr-cases">
      {headline.cases_detail.map((item) => {
        const gained = item.seeds.reduce((sum, node) => sum + count(node), 0);
        const net = gained - seeds * count(item.base);
        return (
          <li className="tr-case" key={item.case_id.t}>
            <span className="tr-half tr-up" style={slots}>
              {blocks(Math.max(net, 0), 'up')}
            </span>
            <span className="tr-half tr-down" style={slots}>
              {blocks(Math.max(-net, 0), 'down')}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
