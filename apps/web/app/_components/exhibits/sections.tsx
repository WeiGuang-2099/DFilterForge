/**
 * @fileoverview The exhibits page's opening.
 *
 * Server-rendered from exhibits.json. The opening states the headline, the
 * count of answers the captures alone pass as exact and how many of them
 * the tail shows wrong, with what passing means. Every value is a sourced
 * node; the page's two tables are in tables.tsx.
 */

import type {ReactNode} from 'react';

import type {NumNode} from '@/lib/data';
import {counted} from '@/lib/exhibits-data';
import type {Replay} from '@/lib/exhibits-data';
import {Num} from '@/lib/sourced';

import {Listed} from './parts';

/** A count's noun, singular for one. */
function noun(node: NumNode, one: string, many: string): string {
  return counted(node, 'exhibits.json count') === 1 ? one : many;
}

/** The standing line, the headline, the lede and the shares. */
export function Head({replay}: {readonly replay: Replay}): ReactNode {
  const {counts, alone} = replay;
  return (
    <header className="xh-head">
      <p className="xh-standing">
        <b>Every published score uses the witness tail.</b> The board, the receipts and every
        headline read probe captures that end in{' '}
        <Num kind="int" node={counts.tail_frames} /> witness packets. This page replays the test
        answers on the <Num kind="int" node={counts.probes} /> test captures without them.
      </p>
      <p className="eyebrow">Exhibits: what the witness packets catch</p>
      <h1 className="xh-h1">
        Without the witness packets, the verifier passes{' '}
        <Num kind="int" node={alone.strong_exact} /> answers as exact.{' '}
        <span className="dn">
          <Num kind="int" node={replay.turned_exact} /> of them are wrong.
        </span>
      </h1>
      <p className="xh-lede">
        The <Num kind="int" node={counts.probes} /> test captures hold{' '}
        <Listed>
          {replay.probes.map((probe) => (
            <Num key={probe.probe_id.t} kind="int" node={probe.benchmark_frames} />
          ))}
        </Listed>{' '}
        benchmark frames, and the witness tail adds{' '}
        <Num kind="int" node={counts.tail_frames} /> packets to each, written to separate near
        misses such as a port tested on either side, DNS judged by its port or a bound off by
        one. Replayed on the captures alone,{' '}
        <strong>
          <Num kind="int" node={alone.strong_exact} /> of the{' '}
          <Num kind="int" node={counts.answers} />
        </strong>{' '}
        executed answers from <Num kind="int" node={counts.runs} /> hosted models are strong
        exact: each selects exactly the labelled frames on every probe. With the tail,{' '}
        <strong>
          <Num kind="int" node={replay.turned_exact} /> of those
        </strong>{' '}
        miss a labelled witness or match one the labels leave out, and so{' '}
        {noun(replay.turned_shortcut, 'does', 'do')}{' '}
        <Num kind="int" node={replay.turned_shortcut} />{' '}
        {noun(replay.turned_shortcut, 'answer', 'answers')} the scorer had already flagged as a
        shortcut. Passed means strong exact here: shortcuts are counted apart, and the{' '}
        <Num kind="int" node={alone.unscorable} /> answers to the{' '}
        <Num kind="int" node={counts.tail_only} /> cases that label only witness frames cannot be
        scored without the tail, so none of them counts as passed.
      </p>
      <p className="xh-shares">
        <span>
          <b><Num kind="int" node={counts.answers} /></b> answers replayed
        </span>
        <span>
          <b><Num kind="int" node={alone.strong_exact} /></b> exact on the captures alone
        </span>
        <span className="xh-shares-dn">
          <b><Num kind="int" node={replay.turned_exact} /></b> of them wrong with the tail
        </span>
        <span>
          <b><Num kind="int" node={alone.unscorable} /></b> answers only the tail can score
        </span>
      </p>
    </header>
  );
}
