/**
 * @fileoverview The training page's condition tables, test and dev.
 *
 * One row for the base model and one per seed, in the headline's order, and
 * one column per condition from the rows' summaries. The adapters trained
 * on C4 prompts only (docs/protocol.md, Training rules), so every other
 * condition is shown faint. A cell whose condition lost answers to the
 * provider says how many, as a sourced count.
 */

import type {ReactNode} from 'react';

import {Num, Str} from '@/lib/sourced';
import type {ConditionRow, Seed} from '@/lib/training-data';

interface TableProps {
  readonly caption: string;
  readonly rows: readonly ConditionRow[];
  readonly seeds: readonly Seed[];
  /** The condition the adapters were trained on, as the headline names it. */
  readonly trained: string;
}

function lost(row: ConditionRow): ReactNode[] {
  return row.conditions.flatMap((condition) =>
    typeof condition.provider_failed.v === 'number' && condition.provider_failed.v > 0
      ? [
          <span key={condition.label.t}>
            <Str node={condition.label} />: <Num kind="int" node={condition.provider_failed} />{' '}
            answers lost to the provider, scored as failures.{' '}
          </span>,
        ]
      : [],
  );
}

/** Strong exact per condition for the base model and each seed. */
export function ConditionTable({caption, rows, seeds, trained}: TableProps): ReactNode {
  const [first] = rows;
  if (first === undefined) {
    throw new Error(`training: the ${caption} table has no rows`);
  }
  const notes = rows.flatMap((row, index) => {
    const found = lost(row);
    const seed = seeds[index - 1];
    return found.length === 0
      ? []
      : [
          <p className="tr-note" key={row.run_id.t}>
            {seed === undefined ? (
              'Base model'
            ) : (
              <>
                Seed <Num kind="int" link={false} node={seed.seed} />
              </>
            )}
            , {found}
          </p>,
        ];
  });
  return (
    <div className="tr-table-wrap">
      <table className="tr-table">
        <caption className="lab" style={{captionSide: 'top', textAlign: 'left'}}>
          {caption}, strong exact on ready gold
        </caption>
        <thead>
          <tr>
            <th scope="col">Row</th>
            {first.conditions.map((condition) => (
              <th
                className={condition.label.t === trained ? undefined : 'tr-faint'}
                key={condition.label.t}
                scope="col"
              >
                <Str node={condition.label} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const seed = seeds[index - 1];
            return (
              <tr key={row.run_id.t}>
                <td className="tr-cell-name">
                  {seed === undefined ? (
                    'Base model'
                  ) : (
                    <>
                      Seed <Num kind="int" link={false} node={seed.seed} />
                    </>
                  )}
                </td>
                {row.conditions.map((condition) => (
                  <td
                    className={condition.label.t === trained ? undefined : 'tr-faint'}
                    key={condition.label.t}
                  >
                    <Num kind="rate" node={condition.strong_exact} />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {notes}
    </div>
  );
}
