/**
 * @fileoverview The board's band for the self-served small model.
 *
 * The board shows the hosted models' counted passes; the small model was
 * served on this project's own stack and fine-tuned here, so it gets a band
 * of its own under them and is never ranked with them. One row for the
 * mean of the seeds, the base model and each seed, one column per condition
 * from the rows' summaries; the adapters trained on one condition only, so
 * the others are hatched. Every value is a sourced node.
 */

import Link from 'next/link';
import {Fragment} from 'react';
import type {ReactNode} from 'react';

import type {Analysis} from '@/lib/analysis-data';
import {Num, Str} from '@/lib/sourced';

/** The band: strong exact per condition, the trained one plain. */
export function SmallModelBand({analysis}: {readonly analysis: Analysis}): ReactNode {
  const [first] = analysis.band.rows;
  if (first === undefined) {
    throw new Error('board: the small model band has no rows');
  }
  const trained = analysis.condition.t;
  const untrained = first.conditions.filter((condition) => condition.label.t !== trained);
  const hatch = (label: string) => (label === trained ? 'an-num' : 'an-num an-hatch');
  return (
    <section aria-labelledby="bd-small" className="bd-sec">
      <h2 id="bd-small">The small model, in a band of its own</h2>
      <p className="bd-sub">
        <Str node={analysis.model_id} /> answered the same frozen test prompts on this
        project&apos;s own stack and was scored by the same verifier, before and after supervised
        fine-tuning. It ranks with nothing above: the adapters trained on{' '}
        <Str node={analysis.condition} /> prompts only, so{' '}
        {untrained.map((condition, index) => (
          <Fragment key={condition.label.t}>
            {index === 0 ? null : index === untrained.length - 1 ? ' and ' : ', '}
            <Str node={condition.label} />
          </Fragment>
        ))}{' '}
        are untrained conditions and hatched.
      </p>
      <div className="bd-tw">
        <table className="an-table an-band">
          <caption className="lab">Strong exact on ready gold, frozen test split</caption>
          <thead>
            <tr>
              <th scope="col">Row</th>
              {first.conditions.map((condition) => (
                <th className={hatch(condition.label.t)} key={condition.label.t} scope="col">
                  <Str node={condition.label} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="an-band-mean">
              <th scope="row">SFT, mean of the seeds</th>
              {analysis.band.mean.map((node, index) => (
                <td className={hatch(first.conditions[index]?.label.t ?? '')} key={JSON.stringify(node.src)}>
                  <Num kind="rate" node={node} />
                </td>
              ))}
            </tr>
            {analysis.band.rows.map((row, index) => {
              const seed = analysis.seeds[index - 1];
              return (
                <tr key={JSON.stringify(row.conditions[0]?.label.src)}>
                  <th scope="row">
                    {seed === undefined ? (
                      'Base model'
                    ) : (
                      <>
                        SFT seed <Num kind="int" link={false} node={seed} />
                      </>
                    )}
                  </th>
                  {row.conditions.map((condition) => (
                    <td className={hatch(condition.label.t)} key={condition.label.t}>
                      <Num kind="rate" node={condition.strong_exact} />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="bd-note">
        The <Link href="/training">training page</Link> gives each row its interval, and the{' '}
        <Link href="/training/analysis">analysis page</Link> follows every failed answer from the
        base model to each seed.
      </p>
    </section>
  );
}
