/**
 * @fileoverview A repair round's comparisons, each with its reading.
 *
 * One row per comparison: the first arm minus the second, the difference
 * and its interval drawn against zero, the discordant cases each arm won,
 * and the verdict, which the protocol's minimum of discordant cases alone
 * decides. The registered label comes from docs/protocol.md (Repair): per
 * model, counterexample against bare is the primary comparison and the two
 * against resample carry no label; pooled over the models, all three are
 * secondary.
 */

import type {ReactNode} from 'react';

import type {ArmComparison} from '@/lib/board-data';
import {Num, Str} from '@/lib/sourced';

import {Rate, Span} from './marks';

type Label = 'primary' | 'secondary' | null;

/** The label docs/protocol.md registers for a comparison. */
function registered(comparison: ArmComparison, pooled: boolean): Label {
  if (pooled) {
    return 'secondary';
  }
  const {first, second} = comparison;
  return first.t === 'counterexample' && second.t === 'bare' ? 'primary' : null;
}

/** A comparison's registered label, as a tag beside its name. */
function Tag({label}: {readonly label: NonNullable<Label>}): ReactNode {
  return <span className={`bd-tag bd-tag-${label}`}>{label}</span>;
}

interface ComparisonsProps {
  readonly comparisons: readonly ArmComparison[];
  readonly pooled: boolean;
  // The id of the heading that names the round; see ArmBars.
  readonly labelledBy: string;
}

/** The comparisons of one round, pooled or one model's. */
export function Comparisons({comparisons, pooled, labelledBy}: ComparisonsProps): ReactNode {
  return (
    <div className="bd-tw">
      <table aria-labelledby={labelledBy} className="bd-cmp">
        <thead>
          <tr>
            <th scope="col">Comparison</th>
            <th scope="col">Difference [interval]</th>
            <th className="bd-c-span" scope="col">
              Against zero
            </th>
            <th scope="col">First better</th>
            <th scope="col">Second better</th>
            <th scope="col">Discordant cases</th>
            <th scope="col">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {comparisons.map((comparison) => {
            const label = registered(comparison, pooled);
            const classes = [
              label === 'primary' ? 'bd-primary' : '',
              comparison.inconclusive.v === true ? 'bd-faint' : '',
            ];
            return (
              <tr
                className={classes.join(' ').trim() || undefined}
                data-label={label ?? 'none'}
                key={`${comparison.first.t} ${comparison.second.t}`}
              >
                <th scope="row">
                  <Str node={comparison.first} /> - <Str node={comparison.second} />
                  {label === null ? null : (
                    <>
                      {' '}
                      <Tag label={label} />
                    </>
                  )}
                </th>
                <td>
                  <Rate interval={comparison.difference} what="difference" />
                </td>
                <td className="bd-c-span">
                  <Span interval={comparison.difference} scale="difference" what="difference" />
                </td>
                <td>
                  <Num kind="int" node={comparison.first_better} />
                </td>
                <td>
                  <Num kind="int" node={comparison.second_better} />
                </td>
                <td>
                  <Num kind="int" node={comparison.discordant} />
                </td>
                <td>
                  <Num kind="verdict" node={comparison.inconclusive} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
