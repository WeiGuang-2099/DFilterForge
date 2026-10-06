import {Fragment} from 'react';

import {Cursor, CursorBand} from '@/app/_components/reel/cursor';
import {Ladder, track} from '@/app/_components/reel/ladder';
import {Readout} from '@/app/_components/reel/readout';
import {PoolScene, RepairScene} from '@/app/_components/reel/scenes';
import {Controls, MiniMap, Stage} from '@/app/_components/reel/stage';
import {count, DISAGREES, ProbeBar} from '@/app/_components/reel/strips';
import {loadReel} from '@/lib/reel-data';
import {roleLabel} from '@/lib/roles';
import {Digest, Num, Outcome, Str, Term, Unmeasured} from '@/lib/sourced';

import './_components/reel/reel.css';

// The home page plays the Disproof Reel: the answer rule reel-v1 picks
// (docs/decisions/disproof-reel.md), the frame that disproves it on a
// ladder of its probe capture, the predicate trace there, the repair turn
// and the pool's headline. Every value is a sourced node of
// apps/web/data/reel.json; the words around them are fixed.

// The figure's legend, drawn as the ladder draws: a mark and its words.
const ARROW = 'M1 3L28 8M22 5.3L28 8L22.9 10.6';
const LEGEND = [
  [<path className="fr" d={ARROW} key="a" />, 'a frame, sender to receiver, with its Info column'],
  [<path className="fr sel" d={ARROW} key="a" />, 'the filter selects it'],
  [<path className="fr dis" d={ARROW} key="a" />, 'the filter and the request disagree on it'],
  [<rect className="m-on" height="8" key="a" width="8" x="2" y="2" />, 'that column selects it'],
  [<rect className="m-miss" height="7" key="a" width="7" x="2.5" y="2.5" />, 'the side that missed it'],
] as const;

export default function HomePage() {
  const reel = loadReel();
  const {pick, highlight, receipt_panel: receipt, strips} = reel;
  if (pick === null) {
    // Rule reel-v1 shows no answer when none in the pool is silent-wrong.
    return (
      <article className="home">
        <h1 className="h1a">No answer in the pool is silent-wrong.</h1>
        <PoolScene reel={reel} />
      </article>
    );
  }
  if (highlight === null || receipt === null) {
    throw new Error('home: rule reel-v1 picked an answer the export gives no highlight or receipt');
  }
  const tracks = strips.map((strip) => ({
    ...track(strip),
    lit: strip.states.map((state) => DISAGREES.has(state)),
  }));
  const numbers = strips.map((strip) => strip.frame_rows.map((row) => row.n));
  const spot = {probe: highlight.probe, row: count(highlight.frame) - 1};
  const disagree = strips.flatMap((strip) => strip.disagree.map((frame) => ({frame, strip})));
  const role = reel.pool.find((run) => run.run === pick.run)?.role;
  return (
    <article className="home">
      <Stage highlight={spot} numbers={numbers} tracks={tracks}>
        <div className="top">
          <div className="main">
            <p className="memo">
              <span>
                <Str node={pick.run_id} />
                {role === undefined ? null : `, ${roleLabel(role)}`}
              </span>
              <span>
                Condition <Str node={pick.condition} />, scored <Outcome node={pick.outcome} />
              </span>
            </p>
            <h1 className="title">
              <span className="h1a">
                Frame{' '}
                <span className="dn">
                  <Num kind="int" node={highlight.frame} />
                </span>{' '}
                disproves
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
            <p className="lede">
              DFilterForge asks a model for a Wireshark display filter, runs it with tshark on each
              synthetic probe capture and checks it against a label on every frame. A filter that
              runs but disagrees with a label is silent-wrong. The reference filter is{' '}
              <code className="m">
                <Str node={pick.reference_filter} />
              </code>
              . This answer disagrees with it on{' '}
              {disagree.map(({frame, strip}, at) => (
                <Fragment key={JSON.stringify(frame.n.src)}>
                  {at === 0 ? null : at === disagree.length - 1 ? ' and ' : ', '}
                  frame <Num kind="int" node={frame.n} /> of{' '}
                  <code className="m">
                    <Str node={strip.probe_id} />
                  </code>
                </Fragment>
              ))}
              .
            </p>
            <div className="figrow">
              <Controls hint="Drag the flag or press on the ladder; the flag takes arrow keys." />
              <div className="lad">
                <MiniMap
                  bars={strips.map((strip) => (
                    <Fragment key={JSON.stringify(strip.probe_id.src)}>
                      <span className="ps-id">
                        <Str node={strip.probe_id} />
                      </span>
                      <span className="ps-bar">
                        <ProbeBar strip={strip} />
                        <span aria-hidden="true" className="ps-tick" />
                      </span>
                    </Fragment>
                  ))}
                />
                <div className="lad-body">
                  <CursorBand />
                  {strips.map((strip, probe) => (
                    <Ladder key={JSON.stringify(strip.probe_id.src)} probe={probe} strip={strip} />
                  ))}
                  <Cursor />
                </div>
              </div>
              <div className="notes">
                <ul aria-label="Figure legend" className="legend-f">
                  {LEGEND.map(([mark, words]) => (
                    <li key={words}>
                      <svg aria-hidden="true" height="12" viewBox="0 0 30 12" width="30">
                        {mark}
                      </svg>
                      {words}
                    </li>
                  ))}
                </ul>
                <p className="note figcap">
                  Each probe capture is a ladder diagram. Time runs down, one row per frame. The
                  left line is the address seen in most of the probe&apos;s frames and the right
                  line is every other host. Recipe frames are the benchmark&apos;s packets; witness
                  frames, the tail every capture ends in, are collapsed into one break row unless
                  they disagree. The bars above the ladder are the probes, each frame that
                  disagrees in carmine. Choose one to draw it.
                </p>
              </div>
            </div>
          </div>
          <aside className="side">
            <Readout
              joins={pick.joins}
              strips={strips}
              trace={reel.trace}
              untraced={reel.trace_reason ?? ''}
            />
          </aside>
        </div>
      </Stage>
      <div className="after">
        <RepairScene repair={reel.repair} />
        <PoolScene reel={reel} />
        <section aria-labelledby="replay-h" className="act replay">
          <h2 className="act-h" id="replay-h">
            Replay this verdict
          </h2>
          <dl className="rc">
            <dt>
              Receipt <Term name="SHA-256" />
            </dt>
            <dd>
              <Digest node={receipt.sha256} />
            </dd>
            <dt>Packet set hash</dt>
            <dd>
              <Digest node={receipt.packet_set_hash} />
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
      </div>
    </article>
  );
}
