'use client';

/**
 * @fileoverview How close each test case sits to the training targets.
 *
 * One square per ready test case, in the column of its proximity stratum,
 * filled by the share of the seeds' answers on it that are strong exact,
 * with a dot when the base model got one exact. Pressing a square shows the
 * case's request and reference beside the training target that shares the
 * most of its predicates. Every case's panel is in the server's HTML and the
 * island shows one; the fill is geometry from sourced counts.
 */

import {useState} from 'react';
import type {CSSProperties, ReactNode} from 'react';

import type {Stratum} from '@/lib/analysis-codes';
import type {NearCase} from '@/lib/analysis-data';
import type {NumNode} from '@/lib/data';
import {NumText, StrText} from '@/lib/sourced-text';

import {STRATUM_WORDS} from './words';

// Every case has two paraphrases (docs/protocol.md, Splits), so a square
// fills by the seeds' exact answers over twice the seeds.
const PARAPHRASES = 2;

interface Column {
  readonly stratum: Stratum;
  readonly cases: NumNode;
}

interface NearnessProps {
  readonly columns: readonly Column[];
  readonly cases: readonly NearCase[];
  readonly seeds: readonly NumNode[];
}

function count(node: NumNode): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    throw new Error(`analysis: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

function panelId(index: number): string {
  return `an-near-${String(index)}`;
}

function titleId(index: number): string {
  return `an-near-${String(index)}-t`;
}

interface PanelProps {
  readonly item: NearCase;
  readonly index: number;
  readonly seeds: readonly NumNode[];
  readonly hidden: boolean;
}

/** One case beside its training target. */
function Panel({item, index, seeds, hidden}: PanelProps): ReactNode {
  const [base, ...rest] = item.exact;
  return (
    <div className="an-receipt" hidden={hidden} id={panelId(index)}>
      <h3 id={titleId(index)}>
        <StrText node={item.case_id} />{' '}
        <span className="an-meta">{STRATUM_WORDS[item.stratum].name}</span>
      </h3>
      <dl>
        <dt>Test request</dt>
        <dd>
          <StrText node={item.request} />
        </dd>
        <dt>Test reference</dt>
        <dd>
          <code className="an-code an-ok">
            <StrText node={item.reference} />
          </code>
        </dd>
        <dt>Training request</dt>
        <dd>
          <StrText node={item.nearest.request} />{' '}
          <span className="an-meta">
            <StrText node={item.nearest.id} />, holding <NumText kind="int" node={item.nearest.shared} />{' '}
            of the case&apos;s <NumText kind="int" node={item.atoms} /> predicates
          </span>
        </dd>
        <dt>Training target</dt>
        <dd>
          <code className="an-code">
            <StrText node={item.nearest.filter} />
          </code>
        </dd>
        <dt>Exact answers</dt>
        <dd className="an-exact">
          {base === undefined ? null : (
            <span>
              base model: <NumText kind="int" node={base} />
            </span>
          )}
          {rest.map((node, place) => {
            const seed = seeds[place];
            return seed === undefined ? null : (
              <span key={JSON.stringify(seed.v)}>
                seed <NumText kind="int" node={seed} />: <NumText kind="int" node={node} />
              </span>
            );
          })}
        </dd>
      </dl>
    </div>
  );
}

/** The strata as columns of squares, with the chosen case's panel. */
export function Nearness({columns, cases, seeds}: NearnessProps): ReactNode {
  const [shown, setShown] = useState(0);
  const most = seeds.length * PARAPHRASES;
  return (
    <>
      <div className="an-strata">
        {columns.map((column) => (
          <div className="an-stratum" key={column.stratum}>
            <h3>{STRATUM_WORDS[column.stratum].name}</h3>
            <p>
              <NumText kind="int" node={column.cases} /> cases.{' '}
              {STRATUM_WORDS[column.stratum].what}
            </p>
            <div className="an-squares">
              {cases.map((item, index) => {
                if (item.stratum !== column.stratum) {
                  return null;
                }
                const [base, ...rest] = item.exact.map(count);
                const exact = rest.reduce((sum, each) => sum + each, 0);
                const style = {'--fill': exact / most} as CSSProperties;
                return (
                  <button
                    aria-controls={panelId(index)}
                    aria-labelledby={titleId(index)}
                    aria-pressed={index === shown}
                    className="an-sq"
                    key={item.case_id.t}
                    onClick={() => setShown(index)}
                    style={style}
                    type="button"
                  >
                    <span aria-hidden="true" className="an-sq-fill" />
                    {base === undefined || base === 0 ? null : (
                      <span aria-hidden="true" className="an-sq-dot" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="an-sqkey">
        <span>
          <span aria-hidden="true" className="an-sq an-sq-key">
            <span className="an-sq-fill" />
          </span>
          Fill: the share of the seeds&apos; answers on the case that are strong exact.
        </span>
        <span>
          <span aria-hidden="true" className="an-sq-dot an-sq-dot-key" />
          The base model got one exact.
        </span>
      </p>
      <div aria-live="polite">
        {cases.map((item, index) => (
          <Panel
            hidden={index !== shown}
            index={index}
            item={item}
            key={item.case_id.t}
            seeds={seeds}
          />
        ))}
      </div>
    </>
  );
}
