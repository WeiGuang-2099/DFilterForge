import {Cursor} from '@/app/_components/reel/cursor';
import {Readout} from '@/app/_components/reel/readout';
import {PoolScene, RepairScene} from '@/app/_components/reel/scenes';
import {Controls, Stage} from '@/app/_components/reel/stage';
import {count, DISAGREES, Strips} from '@/app/_components/reel/strips';
import {loadReel} from '@/lib/reel-data';
import type {Reel} from '@/lib/reel-data';
import {roleLabel} from '@/lib/roles';
import {Num, Outcome, Str, Term, Unmeasured} from '@/lib/sourced';

import './_components/reel/reel.css';

// The home page plays the Disproof Reel: the answer rule reel-v1 picks
// (docs/decisions/disproof-reel.md), the frame that disproves it, the
// repair turn and the pool's headline. Every value is a sourced node of
// apps/web/data/reel.json; the words around them are fixed.

/** The pool without a silent-wrong answer: rule reel-v1 then shows none. */
function NoPick({reel}: {readonly reel: Reel}) {
  return (
    <article className="home">
      <h1 className="title">
        <span className="h1a">No answer in the pool is silent-wrong.</span>
      </h1>
      <PoolScene reel={reel} />
    </article>
  );
}

export default function HomePage() {
  const reel = loadReel();
  const {pick, highlight, receipt_panel: receipt, strips} = reel;
  if (pick === null || highlight === null || receipt === null) {
    return <NoPick reel={reel} />;
  }
  // One column per frame of the longest capture; a column shows the frame
  // number of the first probe that has it, and lights where any disagrees.
  const columns = Math.max(...strips.map((strip) => strip.frame_rows.length));
  const numbers = Array.from({length: columns}, (_, column) => {
    const row = strips.map((strip) => strip.frame_rows[column]).find((each) => each);
    if (row === undefined) {
      throw new Error(`home: no strip has column ${column}`);
    }
    return row.n;
  });
  const lit = numbers.map((_, column) =>
    strips.some((strip) => DISAGREES.has(strip.states[column] ?? 'tn')),
  );
  const role = reel.pool.find((run) => run.run === pick.run)?.role;
  return (
    <article className="home">
      <Stage highlight={count(highlight.frame) - 1} lit={lit} numbers={numbers}>
        <p className="memo">
          <span>
            <Str node={pick.run_id} />
            {role === undefined ? null : `, ${roleLabel(role)}`}
          </span>
          <span>
            Condition <Str node={pick.condition} />, scored <Outcome node={pick.outcome} />
          </span>
        </p>
        <div className="stage-grid">
          <section aria-label="The disproof" className="act act-disproof">
            <h1 className="title">
              <span className="h1a">
                <span aria-hidden="true" className="h1-pre">
                  Find the frame that disproves
                </span>
                <span className="h1-hit">
                  Frame{' '}
                  <span className="dn">
                    <Num kind="int" node={highlight.frame} />
                  </span>{' '}
                  disproves
                </span>
              </span>
              <code className="h1f">
                <Str node={pick.answer.filter} />
              </code>
            </h1>
            <p className="for">
              Written by{' '}
              <span className="m">
                <Str node={pick.model_id} />
              </span>
              {pick.provider === null ? null : (
                <>
                  {' '}
                  via <Str node={pick.provider} />
                </>
              )}{' '}
              for the request{' '}
              <q className="req">
                <Str node={pick.request} />
              </q>
            </p>
            <p className="ref">
              The reference filter is{' '}
              <code className="m">
                <Str node={pick.reference_filter} />
              </code>
            </p>
            <Controls />
            <Strips columns={columns} strips={strips}>
              <Cursor />
            </Strips>
            <Readout lit={lit} numbers={numbers} strips={strips} trace={reel.trace_reason ?? ''} />
          </section>
          <div className="side">
            <RepairScene columns={columns} repair={reel.repair} />
            <PoolScene reel={reel} />
          </div>
        </div>
      </Stage>
      <section aria-labelledby="replay-h" className="replay">
        <h2 id="replay-h">Replay this verdict</h2>
        <dl className="rc">
          <dt>
            Receipt <Term name="SHA-256" />
          </dt>
          <dd>
            <Str node={receipt.sha256} />
          </dd>
          <dt>Packet set hash</dt>
          <dd>
            <Str node={receipt.packet_set_hash} />
          </dd>
          {receipt.repair === null ? null : (
            <>
              <dt>Repair round</dt>
              <dd>
                <Unmeasured node={receipt.repair} />
              </dd>
            </>
          )}
        </dl>
        <p className="lab">Re-score the whole run offline from its committed answers</p>
        <pre className="cmd">
          {receipt.replay.map((part) =>
            typeof part === 'string' ? part : <Str key={JSON.stringify(part.src)} node={part} />,
          )}
        </pre>
        <p className="note">
          The run needs no API key: the scorer replays every committed answer with the pinned
          tshark build and compares the result with the committed receipts.
        </p>
      </section>
    </article>
  );
}
