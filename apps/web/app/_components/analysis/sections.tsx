/**
 * @fileoverview The analysis page's opening and its two tables.
 *
 * Server-rendered from analysis.json. The opening states where the base
 * model's loud failures went under the seeds, as ranges over the seeds; the
 * tables give strong exact per proximity stratum and, per row and coverage
 * stratum, the copies of a training target and the fields off the
 * retrieved list. Every value is a sourced node.
 */

import Link from 'next/link';
import type {ReactNode} from 'react';

import {COVERAGE} from '@/lib/analysis-codes';
import type {Analysis} from '@/lib/analysis-data';
import type {NumNode} from '@/lib/data';
import {Num, Str} from '@/lib/sourced';

import {STRATUM_WORDS} from './words';

const COVERAGE_WORDS: Readonly<Record<(typeof COVERAGE)[number], string>> = {
  every_gold_field_retrieved: 'Every gold field retrieved',
  some_gold_field_missing: 'Some gold field missing',
};

/** The low end of a range over the seeds, and the high end if it differs. */
export function Range({ends}: {readonly ends: {readonly low: NumNode; readonly high: NumNode}}) {
  return (
    <>
      <Num kind="int" node={ends.low} />
      {ends.low.v === ends.high.v ? null : (
        <>
          {' '}
          to <Num kind="int" node={ends.high} />
        </>
      )}
    </>
  );
}

export function RowName({analysis, index}: {readonly analysis: Analysis; readonly index: number}) {
  const seed = analysis.seeds[index - 1];
  return seed === undefined ? (
    <>base model</>
  ) : (
    <>
      seed <Num kind="int" link={false} node={seed} />
    </>
  );
}

/** The opening: where the base model's loud failures went. */
export function Head({analysis}: {readonly analysis: Analysis}): ReactNode {
  const {opening} = analysis;
  return (
    <header className="an-head">
      <p className="eyebrow">What fine-tuning fixed, and what it did not</p>
      <h1 className="an-h1">
        Fine-tuning made <Range ends={opening.loud_ran} /> of <Num kind="int" node={opening.loud} />{' '}
        loud failures run.{' '}
        <span className="dn">
          <Range ends={opening.loud_silent} /> of them now fail silently.
        </span>
      </h1>
      <p className="an-lede">
        The <Num kind="int" node={analysis.items} /> ready answers of the frozen test split in
        condition <Str node={analysis.condition} />, from the base model,{' '}
        <Str node={analysis.model_id} />, and from each fine-tuned seed. A loud failure never
        runs: the filter is refused, or the reply is no valid Intent IR. A silent failure runs
        and selects the wrong packets, and nothing flags it until the packets are checked. Of the
        loud failures that now run, <strong><Range ends={opening.loud_exact} /></strong> are
        exact. Each seed also made <strong><Range ends={opening.silent_exact} /></strong> of the base
        model&apos;s <Num kind="int" node={opening.base_silent} /> silent failures exact, and{' '}
        <strong><Range ends={opening.exact_silent} /></strong> of its{' '}
        <Num kind="int" node={opening.base_exact} /> exact answers silently wrong.
      </p>
      <p className="an-shares">
        <span>Of the answers that run, silently wrong:</span>
        {analysis.rows.map((row, index) => (
          <span className={index === 0 ? 'an-share-base' : undefined} key={row.run_id.t}>
            <RowName analysis={analysis} index={index} />{' '}
            <b>
              <Num kind="int" node={row.outcomes.silent_wrong} />
            </b>{' '}
            of <Num kind="int" node={row.executed} />
          </span>
        ))}
      </p>
      <p className="an-back">
        The headline and its intervals are on the <Link href="/training">training page</Link>.
      </p>
    </header>
  );
}

/** The strata's strong exact per row, as case means. */
export function StrataTable({analysis}: {readonly analysis: Analysis}): ReactNode {
  return (
    <div className="an-tw">
      <table className="an-table">
        <caption className="lab">Strong exact per stratum, the mean over its cases</caption>
        <thead>
          <tr>
            <th scope="col">Stratum</th>
            <th className="an-num" scope="col">
              Cases
            </th>
            {analysis.rows.map((row, index) => (
              <th className="an-num" key={row.run_id.t} scope="col">
                <RowName analysis={analysis} index={index} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {analysis.nearness.strata.map((stratum) => (
            <tr key={stratum.stratum}>
              <th scope="row">{STRATUM_WORDS[stratum.stratum].name}</th>
              <td className="an-num">
                <Num kind="int" node={stratum.cases} />
              </td>
              {stratum.rows.map((node) => (
                <td className="an-num" key={JSON.stringify(node.src)}>
                  <Num kind="rate" node={node} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Per row and coverage stratum: copies of a target, fields off the list. */
export function CopiesTable({analysis}: {readonly analysis: Analysis}): ReactNode {
  return (
    <div className="an-copies">
      {COVERAGE.map((stratum) => (
        <div className="an-tw" key={stratum}>
          <table className="an-table">
            <caption className="lab">{COVERAGE_WORDS[stratum]}</caption>
            <thead>
              <tr>
                <th scope="col">Row</th>
                <th className="an-num" scope="col">
                  With Intent IR
                </th>
                <th className="an-num" scope="col">
                  Copy a target
                </th>
                <th className="an-num" scope="col">
                  Field off the list
                </th>
              </tr>
            </thead>
            <tbody>
              {analysis.copies.map((row, index) => {
                const cell = row[stratum];
                return (
                  <tr key={JSON.stringify(cell.with_ir.src)}>
                    <th scope="row">
                      <RowName analysis={analysis} index={index} />
                    </th>
                    <td className="an-num">
                      <Num kind="int" node={cell.with_ir} />
                    </td>
                    <td className="an-num">
                      <Num kind="int" node={cell.copies} />{' '}
                      <span className="an-of">
                        (<Num kind="int" node={cell.copies_exact} /> exact)
                      </span>
                    </td>
                    <td className="an-num">
                      <Num kind="int" node={cell.unlisted} />{' '}
                      <span className="an-of">
                        (<Num kind="int" node={cell.unlisted_exact} /> exact)
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
