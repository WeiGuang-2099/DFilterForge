/**
 * @fileoverview The Reel's later scenes: the repair turn and the pool.
 *
 * Both are server-rendered from reel.json. The repair scene shows rule
 * reel-v1's step 5: the card the counterexample arm sent, verbatim, the
 * model's second answer and its probe bars. The pool scene shows the headline
 * counts and one bar per pool run, in pool order and never ranked. A bar's
 * segments grow by the counts they stand for (flex-grow), so the page never
 * divides; the counts beside each bar are the sourced values.
 */

import type {NumNode} from '@/lib/data';
import type {Reel} from '@/lib/reel-data';
import {roleLabel} from '@/lib/roles';
import {fmt} from '@/lib/fmt';
import {Num, Outcome, Str} from '@/lib/sourced';

import {ProbeBar} from './strips';

type Turn = NonNullable<NonNullable<Reel['repair']>['turn']>;

/** Step 5: the counterexample turn for the picked answer. */
export function RepairScene({repair}: {readonly repair: Reel['repair']}) {
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
          <p className="note">
            The card sent back: frames of the unscored feedback probe where the first answer and
            the labels disagree.
          </p>
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
          <ul className="bars2">
            {turn.strips.map((strip) => (
              <li key={JSON.stringify(strip.probe_id.src)}>
                <code>
                  <Str node={strip.probe_id} />
                </code>
                <ProbeBar strip={strip} />
                <span className="lab">
                  exact <Num kind="bool" node={strip.exact} />
                </span>
              </li>
            ))}
          </ul>
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
        {reel.board.map((row) => (
          <li key={row.run}>
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
        {[...OWN, 'other'].map((kind) => (
          <li key={kind}>
            <span aria-hidden="true" className={`sw o-${kind}`} />
            {kind === 'other' ? 'did not run' : fmt(kind, 'outcome')}
          </li>
        ))}
      </ul>
    </section>
  );
}
