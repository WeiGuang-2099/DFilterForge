import type {Metadata} from 'next';
import type {ReactNode} from 'react';

import {ExhibitCard} from '@/app/_components/exhibits/exhibit';
import {Overview} from '@/app/_components/exhibits/overview';
import {Listed} from '@/app/_components/exhibits/parts';
import {Head} from '@/app/_components/exhibits/sections';
import {ByModel, TailOnly} from '@/app/_components/exhibits/tables';
import {loadExhibits} from '@/lib/exhibits-data';
import {preview} from '@/lib/preview';
import {Digest, Num, repositoryBlob, repositoryFile, Str} from '@/lib/sourced';

import '@/app/_components/exhibits/exhibits.css';

export const metadata: Metadata = {
  title: 'What the witness packets catch',
  description:
    "The hosted models' test answers replayed on the test captures without their witness tail: the answers the verifier would pass as exact, and the witness packets that show them wrong.",
  openGraph: preview(
    'og-exhibits.png',
    'The top of the DFilterForge exhibits page: without the witness packets, the verifier ' +
      'passes test answers as exact that are wrong.',
  ),
};

// The exhibits page shows exhibits.json: the Reel pool's test answers
// replayed on the test captures with their witness tail cut off, every one
// as a square, then one exhibit per case whose answers the tail turns, the
// cases only the tail can score and each pass's counts. Every value is a
// sourced node; the words around them are fixed. No published score
// changes: they all use the tail.

const REPLAY = 'docs/decisions/evidence/web/exhibits.json';
const ABLATION = 'docs/ablations/005-probe-witnesses.md';
const CAPTURES = 'docs/decisions/evidence/web/captures.json';
const PACKETS = 'docs/decisions/evidence/web/packets.json';

export default function ExhibitsPage(): ReactNode {
  const {replay} = loadExhibits();
  if (replay === null) {
    throw new Error('exhibits: exhibits.json has no replay, and the page shows one only');
  }
  const {counts, alone} = replay;
  const blob = repositoryBlob();
  return (
    <article className="xh">
      <Head replay={replay} />

      <section aria-labelledby="xh-ov-h" className="xh-sec">
        <h2 id="xh-ov-h">Every answer, one square</h2>
        <p className="xh-sub">
          One square per executed answer to a ready test case, a row per model in pool order.
          Switch the verifier to the captures alone: the ringed squares, which the tail turns
          silent-wrong, then agree with the labels on every frame.
        </p>
        <Overview blob={blob} replay={replay} />
      </section>

      <section aria-labelledby="xh-ex-h" className="xh-sec">
        <h2 id="xh-ex-h">The exhibits</h2>
        <p className="xh-sub">
          One exhibit per test case where the tail turns answers that agree with the labels on
          every benchmark frame, <Num kind="int" node={counts.exhibits} /> in all, most turned
          answers first;{' '}
          <Num kind="int" node={counts.killing_witnesses} /> of the{' '}
          <Num kind="int" node={counts.tail_frames} /> witnesses catch one. Each shows the
          request, the reference, the answer and the frames where they part. Switch an exhibit
          to the captures alone to see what the verifier saw before the tail: every frame
          agrees.
        </p>
        {replay.exhibits.map((exhibit) => (
          <ExhibitCard blob={blob} exhibit={exhibit} key={exhibit.case} replay={replay} />
        ))}
      </section>

      <TailOnly replay={replay} />
      <ByModel replay={replay} />

      <section aria-labelledby="xh-limits-h" className="xh-sec">
        <h2 id="xh-limits-h">Limits</h2>
        <ul className="xh-limits">
          <li>
            The replay covers the <Num kind="int" node={counts.answers} /> executed answers to
            ready test cases from the <Num kind="int" node={counts.runs} /> hosted test passes the
            Reel reads: pass A and the slot winners. Pass B, the repair rounds, the dev passes
            and the small model, base and fine-tuned, are not replayed.
          </li>
          <li>
            &ldquo;Captures alone&rdquo; means the <Num kind="int" node={counts.probes} /> test
            captures without the tail, the files the Simplified arm of the{' '}
            <a href={repositoryFile(ABLATION)}>probe-witness ablation</a> read; the replay
            matches their digests to that ablation&apos;s capture manifest:{' '}
            <Listed>
              {replay.probes.map((probe) => (
                <span key={probe.probe_id.t}>
                  <Str node={probe.probe_id} /> <Digest node={probe.alone_sha256} /> without the
                  tail, <Digest node={probe.tail_sha256} /> with it
                </span>
              ))}
            </Listed>
            . tshark reads a capture in one pass, so the benchmark frames dissect the same with or
            without the tail, and the replay checks every answer&apos;s frames on the captures
            alone against its receipt before it writes a verdict.
          </li>
          <li>
            An answer counts as passed only when it is strong exact. The{' '}
            <Num kind="int" node={alone.shortcut} /> shortcuts on the captures alone are counted
            apart, and the <Num kind="int" node={counts.tail_only} /> cases that label only
            witness frames count as not scorable without the tail: the scorer refuses a case
            whose label sets are all empty, so none of their{' '}
            <Num kind="int" node={alone.unscorable} /> answers is passed.
          </li>
          <li>
            Shortcut flags come from each answer&apos;s outcome row. They depend on the filter
            text and the request, not on the captures, so the tail cannot change them.
          </li>
          {replay.notes.map((note) => (
            <li key={JSON.stringify(note.src)}>
              <Str node={note} />
            </li>
          ))}
          <li>
            No published score changes: every number on the board, in the receipts and in the
            headlines still uses the tail, and this page only shows what the tail is for. The
            verdicts come from the <a href={repositoryFile(REPLAY)}>replay file</a>, which a
            committed script rebuilds with the pinned tshark and CI compares byte for byte. The
            requests come from each pass&apos;s prepared prompts, the filters and frame states
            from its scored receipts, and the packet rows from the committed frame tables,{' '}
            <a href={repositoryFile(CAPTURES)}>captures.json</a> and{' '}
            <a href={repositoryFile(PACKETS)}>packets.json</a>. A case only the tail can score
            shows the request, the reference and the labelled frames of its case specification.
          </li>
        </ul>
      </section>
    </article>
  );
}
