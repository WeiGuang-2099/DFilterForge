'use client';

/**
 * @fileoverview The kinds of mistake, row by row, and one receipt per kind.
 *
 * One table row per registered class, grouped under the outcome it belongs
 * to, and one column per row: the base model, then each seed. A count with
 * answers behind it is a button; pressing it shows the first of those
 * answers by item id, with its request, the reference, the answer, the
 * frame that disproves a silent-wrong answer and a link to the committed
 * file. Every receipt is in the server's HTML and the island shows one.
 */

import {Fragment, useState} from 'react';
import type {ReactNode} from 'react';

import {CLASS_OUTCOME, CLASSES} from '@/lib/analysis-codes';
import type {ClassName, Outcome} from '@/lib/analysis-codes';
import type {AnalysisRow, Example} from '@/lib/analysis-data';
import type {NumNode} from '@/lib/data';
import {NumText, StrText} from '@/lib/sourced-text';

import {AnswerText} from './answer';
import {CLASS_WORDS, GROUP_WORDS} from './words';

// The outcomes in the table's order: what ran, rightly and not, then what
// never ran.
const GROUPS: readonly Outcome[] = [
  'strong_exact',
  'silent_wrong',
  'invalid',
  'malformed',
  'abstained',
  'shortcut',
  'provider_failed',
];

interface KindsProps {
  readonly rows: readonly AnalysisRow[];
  readonly seeds: readonly NumNode[];
  /** The repository's file permalink prefix at the build's commit. */
  readonly blob: string;
}

interface Pick {
  readonly row: number;
  readonly kind: ClassName;
}

function count(node: NumNode): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    throw new Error(`analysis: ${JSON.stringify(node.v)} is not a count`);
  }
  return node.v;
}

function entry(row: AnalysisRow, kind: ClassName) {
  const found = row.classes.find((each) => each.class === kind);
  if (found === undefined) {
    throw new Error(`analysis: a row has no ${kind} count`);
  }
  return found;
}

/** The first seed's most frequent silent-wrong class, where the page opens. */
function opening(rows: readonly AnalysisRow[]): Pick {
  const row = rows.length > 1 ? 1 : 0;
  const silent = CLASSES.filter((kind) => CLASS_OUTCOME[kind] === 'silent_wrong');
  const counts = silent.map((kind) => {
    const found = rows[row];
    return found === undefined ? 0 : count(entry(found, kind).count);
  });
  const best = counts.indexOf(Math.max(...counts));
  return {row, kind: silent[best] ?? 'strong_exact'};
}

function RowName({index, seeds}: {readonly index: number; readonly seeds: readonly NumNode[]}) {
  const seed = seeds[index - 1];
  return seed === undefined ? (
    <>Base model</>
  ) : (
    <>
      Seed <NumText kind="int" node={seed} />
    </>
  );
}

/** The id of one row's receipt for one class. */
function receiptId(row: number, kind: ClassName): string {
  return `an-receipt-${kind}-${String(row)}`;
}

interface ReceiptProps {
  readonly id: string;
  readonly example: Example;
  readonly kind: ClassName;
  readonly total: NumNode;
  readonly row: ReactNode;
  readonly blob: string;
  readonly hidden: boolean;
}

/** One class's first answer, with what the files hold for it. */
function Receipt({id, example, kind, total, row, blob, hidden}: ReceiptProps): ReactNode {
  const {disproof} = example;
  const href = blob + example.file.split('/').map(encodeURIComponent).join('/');
  const executed = example.answer.filter !== null;
  return (
    <div className="an-receipt" hidden={hidden} id={id}>
      <h3>
        {CLASS_WORDS[kind].name}{' '}
        <span className="an-meta">
          {row}, <StrText node={example.case_id} /> <StrText node={example.item_id} />,{' '}
          {count(total) === 1 ? (
            'the only one'
          ) : (
            <>
              the first of <NumText kind="int" node={total} /> by item id
            </>
          )}
        </span>
      </h3>
      <dl>
        <dt>Request</dt>
        <dd>
          <StrText node={example.request} />
        </dd>
        <dt>Reference</dt>
        <dd>
          <code className="an-code an-ok">
            <StrText node={example.reference} />
          </code>
        </dd>
        <dt>Answer</dt>
        <dd className={executed && kind !== 'strong_exact' ? 'an-wrong' : undefined}>
          <AnswerText answer={example.answer} />
        </dd>
        {disproof === null ? null : (
          <>
            <dt>Disproof</dt>
            <dd>
              On probe{' '}
              <code>
                <StrText node={disproof.probe} />
              </code>
              , frame{' '}
              <span className="an-frame">
                <NumText kind="int" node={disproof.frame} />
              </span>{' '}
              (
              <code>
                <StrText node={disproof.name} />
              </code>
              ) is selected{' '}
              {disproof.side === 'reference_only'
                ? 'by the reference and missed by the answer.'
                : 'by the answer and not by the reference.'}
            </dd>
          </>
        )}
        <dt>Evidence</dt>
        <dd>
          <a href={href}>{executed ? 'The scored receipt' : 'The recorded reply'}</a>
        </dd>
      </dl>
    </div>
  );
}

/** The class table with one receipt shown at a time. */
export function Kinds({rows, seeds, blob}: KindsProps): ReactNode {
  const [shown, setShown] = useState(() => opening(rows));
  return (
    <>
      <div className="an-tw">
        <table className="an-table">
          <thead>
            <tr>
              <th scope="col">Kind</th>
              {rows.map((row, index) => (
                <th className="an-num" id={`an-k-row-${String(index)}`} key={row.run_id.t} scope="col">
                  <RowName index={index} seeds={seeds} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {GROUPS.map((outcome) => {
              const kinds = CLASSES.filter((kind) => CLASS_OUTCOME[kind] === outcome);
              return (
                <Fragment key={outcome}>
                  {kinds.length > 1 ? (
                    <tr className="an-grp">
                      <th scope="row">
                        <span aria-hidden="true" className={`an-sw an-o-${outcome}`} />
                        {GROUP_WORDS[outcome]}
                      </th>
                      {rows.map((row) => (
                        <td className="an-num" key={row.run_id.t}>
                          <NumText kind="int" node={row.outcomes[outcome]} />
                        </td>
                      ))}
                    </tr>
                  ) : null}
                  {kinds.map((kind) => (
                    <tr className={kinds.length > 1 ? 'an-in' : 'an-one'} key={kind}>
                      <th scope="row">
                        <span id={`an-k-${kind}`}>
                          {kinds.length > 1 ? null : (
                            <span aria-hidden="true" className={`an-sw an-o-${outcome}`} />
                          )}
                          {CLASS_WORDS[kind].name}
                        </span>
                        <span className="an-what">{CLASS_WORDS[kind].what}</span>
                      </th>
                      {rows.map((row, index) => {
                        const cell = entry(row, kind);
                        const on = shown.row === index && shown.kind === kind;
                        const id = `an-k-${kind}-${String(index)}`;
                        return (
                          <td className="an-num" key={row.run_id.t}>
                            {cell.example === null ? (
                              <span className="an-zero">
                                <NumText kind="int" node={cell.count} />
                              </span>
                            ) : (
                              <button
                                aria-controls={receiptId(index, kind)}
                                aria-labelledby={`an-k-${kind} an-k-row-${String(index)} ${id}`}
                                aria-pressed={on}
                                className="an-count"
                                id={id}
                                onClick={() => setShown({row: index, kind})}
                                type="button"
                              >
                                <NumText kind="int" node={cell.count} />
                              </button>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <div aria-live="polite">
        {rows.flatMap((row, index) =>
          row.classes.flatMap((cell) =>
            cell.example === null
              ? []
              : [
                  <Receipt
                    blob={blob}
                    example={cell.example}
                    hidden={!(shown.row === index && shown.kind === cell.class)}
                    id={receiptId(index, cell.class)}
                    key={`${row.run_id.t}-${cell.class}`}
                    kind={cell.class}
                    row={<RowName index={index} seeds={seeds} />}
                    total={cell.count}
                  />,
                ],
          ),
        )}
      </div>
    </>
  );
}
