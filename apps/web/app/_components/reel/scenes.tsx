/**
 * @fileoverview The Reel's later scenes: the repair turn and the pool.
 *
 * Both are server-rendered from reel.json. The repair scene shows rule
 * reel-v1's step 5: the card the counterexample arm sent, verbatim, the
 * model's second answer and its strips. The pool scene shows the headline
 * counts and one bar per pool run, in pool order and never ranked. A bar's
 * segments grow by the counts they stand for (flex-grow), so the page never
 * divides; the counts beside each bar are the sourced values.
 */

import type {CSSProperties} from 'react';

import type {NumNode} from '@/lib/data';
import type {Reel} from '@/lib/reel-data';
import {roleLabel} from '@/lib/roles';
import {Num, Outcome, Str} from '@/lib/sourced';

import {Strips} from './strips';

type Turn = NonNullable<NonNullable<Reel['repair']>['turn']>;

interface RepairProps {
  readonly repair: Reel['repair'];
  readonly columns: number;
}

/** Step 5: the counterexample turn for the picked answer. */
export function RepairScene({repair, columns}: RepairProps) {
  const turn: Turn | null = repair?.turn ?? null;
  return (
    <section aria-labelledby="act-repair" className="act act-repair">
      <h2 className="act-h" id="act-repair">
        The repair turn
      </h2>
      {turn === null ? (
        <p className="note">{repair?.reason ?? 'this answer has no repair turn'}</p>
      ) : (
        <>
          <p className="note">The card sent back: a missed frame of the unscored feedback probe.</p>
          {turn.card === null ? null : (
            <pre className="card">
              <Str node={turn.card} />
            </pre>
          )}
          <p className="lab">
            Second answer, <Outcome node={turn.outcome} />
          </p>
          {turn.filter === null ? null : (
            <code className="ans2">
              <Str node={turn.filter} />
            </code>
          )}
          <Strips columns={columns} compact strips={turn.strips} />
          {turn.raw === null ? null : (
            <details className="raw">
              <summary>The second answer as the model wrote it</summary>
              <pre className="answer">
                <Str node={turn.raw} />
              </pre>
            </details>
          )}
        </>
      )}
    </section>
  );
}

// The outcomes a pool bar draws on its own; the rest share one segment.
const OWN = ['strong_exact', 'shortcut', 'silent_wrong'] as const;
const REST = ['invalid', 'malformed', 'provider_failed', 'abstained'] as const;

function Segment({nodes, kind}: {readonly nodes: readonly NumNode[]; readonly kind: string}) {
  const grow = nodes.reduce((sum, node) => sum + Number(node.v), 0);
  return grow === 0 ? null : <span className={`seg o-${kind}`} style={{flexGrow: grow}} />;
}

/** The headline counts and one bar per pool run. */
export function PoolScene({reel}: {readonly reel: Reel}) {
  return (
    <section aria-labelledby="act-pool" className="act act-pool">
      <h2 className="act-h" id="act-pool">
        The pool
      </h2>
      <p className="headline">
        Of <Num kind="int" node={reel.headline.compiled} /> filters that compiled and ran,{' '}
        <span className="dn">
          <Num kind="int" node={reel.headline.silent_wrong} />
        </span>{' '}
        were silent-wrong.
      </p>
      <ol className="bars">
        {reel.board.map((row, index) => (
          <li key={row.run} style={{'--row': index} as CSSProperties}>
            <span className="bar-id">
              <Str node={row.model_id} /> <span className="bar-role">{roleLabel(row.role)}</span>
            </span>
            <span aria-hidden="true" className="bar">
              {OWN.map((kind) => (
                <Segment key={kind} kind={kind} nodes={[row.segments[kind]]} />
              ))}
              <Segment kind="other" nodes={REST.map((kind) => row.segments[kind])} />
            </span>
            <span className="bar-n">
              <Num kind="int" node={row.segments.strong_exact} /> strong exact,{' '}
              <span className="dn">
                <Num kind="int" node={row.segments.silent_wrong} />
              </span>{' '}
              silent-wrong, of <Num kind="int" node={row.ready} />
            </span>
          </li>
        ))}
      </ol>
      <ul aria-label="Bar legend" className="legend">
        <li>
          <span aria-hidden="true" className="sw o-strong_exact" />
          strong exact
        </li>
        <li>
          <span aria-hidden="true" className="sw o-shortcut" />
          shortcut
        </li>
        <li>
          <span aria-hidden="true" className="sw o-silent_wrong" />
          silent-wrong
        </li>
        <li>
          <span aria-hidden="true" className="sw o-other" />
          did not run
        </li>
      </ul>
    </section>
  );
}
