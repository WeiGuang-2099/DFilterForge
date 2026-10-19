/**
 * @fileoverview Each seed's logged training loss, on a log scale.
 *
 * Server-rendered from each seed's run manifest. Steps run left to right
 * and each ruled line is a factor of ten below the one above it; the chart
 * holds no number, and the table under it gives each seed's first and last
 * logged loss as sourced values.
 */

import type {ReactNode} from 'react';

import type {Analysis} from '@/lib/analysis-data';
import type {NumNode} from '@/lib/data';
import {Num} from '@/lib/sourced';

const WIDTH = 760;
const HEIGHT = 240;
const PAD = 8;

type Seeds = Analysis['loss'];

function number(node: NumNode, what: string): number {
  if (typeof node.v !== 'number' || !(node.v > 0)) {
    throw new Error(`analysis: the ${what} ${JSON.stringify(node.v)} is not positive`);
  }
  return node.v;
}

/** The chart: one line per seed over the powers of ten it spans. */
export function LossChart({seeds}: {readonly seeds: Seeds}): ReactNode {
  const values = seeds.flatMap((seed) => seed.curve.map((point) => number(point.loss, 'loss')));
  const top = Math.ceil(Math.log10(Math.max(...values)));
  const bottom = Math.floor(Math.log10(Math.min(...values)));
  const y = (value: number) =>
    PAD + ((top - Math.log10(value)) / (top - bottom)) * (HEIGHT - 2 * PAD);
  const rules = Array.from({length: top - bottom + 1}, (_, index) => y(10 ** (top - index)));
  return (
    <svg aria-hidden="true" className="an-loss" preserveAspectRatio="none" viewBox={`0 0 ${WIDTH} ${HEIGHT}`}>
      {rules.map((rule) => (
        <line className="an-loss-rule" key={rule} x1={0} x2={WIDTH} y1={rule} y2={rule} />
      ))}
      {seeds.map((seed, index) => {
        const steps = number(seed.steps, 'step count');
        const points = seed.curve
          .map(
            (point) =>
              `${PAD + (number(point.step, 'step') / steps) * (WIDTH - 2 * PAD)},${y(number(point.loss, 'loss'))}`,
          )
          .join(' ');
        return (
          <polyline
            className={`an-loss-line an-loss-${String(index)}`}
            fill="none"
            key={JSON.stringify(seed.seed.v)}
            points={points}
          />
        );
      })}
    </svg>
  );
}

/** Each seed's run: rows, epochs, steps and its first and last logged loss. */
export function LossTable({seeds}: {readonly seeds: Seeds}): ReactNode {
  return (
    <div className="an-tw">
      <table className="an-table an-loss-table">
        <thead>
          <tr>
            <th scope="col">Seed</th>
            <th className="an-num" scope="col">
              Training rows
            </th>
            <th className="an-num" scope="col">
              Epochs
            </th>
            <th className="an-num" scope="col">
              Steps
            </th>
            <th className="an-num" scope="col">
              First logged loss
            </th>
            <th className="an-num" scope="col">
              Last logged loss
            </th>
          </tr>
        </thead>
        <tbody>
          {seeds.map((seed, index) => {
            const first = seed.curve[0];
            const last = seed.curve[seed.curve.length - 1];
            if (first === undefined || last === undefined) {
              throw new Error('analysis: a seed logged no loss');
            }
            return (
              <tr key={JSON.stringify(seed.seed.v)}>
                <th scope="row">
                  <span aria-hidden="true" className={`an-loss-sw an-loss-${String(index)}`} />
                  Seed <Num kind="int" node={seed.seed} />
                </th>
                <td className="an-num">
                  <Num kind="int" node={seed.rows} />
                </td>
                <td className="an-num">
                  <Num kind="int" node={seed.epochs} />
                </td>
                <td className="an-num">
                  <Num kind="int" node={seed.steps} />
                </td>
                <td className="an-num">
                  <Num kind="loss" node={first.loss} />
                </td>
                <td className="an-num">
                  <Num kind="loss" node={last.loss} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
