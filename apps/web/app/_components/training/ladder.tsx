/**
 * @fileoverview The training page's ladders and its opening.
 *
 * A ladder sets the base row, each seed in seed order and the mean of the
 * seeds on one scale, each with its interval and, beside the base row, the
 * paired difference, its counts and any reading the headline records. The
 * opening states the mean first, as docs/protocol.md registers (Training
 * rules). Every value is a sourced node.
 */

import type {ReactNode} from 'react';

import type {NumNode, StrNode} from '@/lib/data';
import {Num, Str} from '@/lib/sourced';
import type {Headline, Interval, Seed} from '@/lib/training-data';

import {Scale, Value} from './marks';

interface Paired {
  readonly difference: Interval;
  readonly first_better_cases: NumNode;
  readonly second_better_cases: NumNode;
  readonly reading: StrNode | null;
}

/** A paired difference against a row: interval, counts and any reading. */
export function Against({paired, other}: {readonly paired: Paired; readonly other: string}) {
  return (
    <>
      <span className="tr-of">
        <Value interval={paired.difference} /> against {other}
      </span>
      <span className="tr-of">
        <Num kind="int" node={paired.first_better_cases} /> cases better,{' '}
        <Num kind="int" node={paired.second_better_cases} /> worse
      </span>
      {paired.reading === null ? null : (
        <span className="tr-read">
          <Str node={paired.reading} />
        </span>
      )}
    </>
  );
}

interface LadderProps {
  readonly base: Interval;
  readonly mean: Paired & {readonly rate: Interval};
  readonly seeds: readonly Seed[];
  readonly model: StrNode;
  readonly compact?: boolean;
}

/** The base row, each seed in seed order and the mean, on one scale. */
export function Ladder({base, mean, seeds, model, compact = false}: LadderProps): ReactNode {
  return (
    <ol className="tr-ladder">
      <li className="tr-row tr-row-base">
        <span className="tr-name">
          Base model{compact ? null : <small><Str node={model} />, thinking off</small>}
        </span>
        <Scale interval={base} scale="rate" what="base rate" />
        <span className="tr-val">
          <Value interval={base} />
        </span>
      </li>
      {seeds.map((seed) => (
        <li className="tr-row tr-row-seed" key={JSON.stringify(seed.seed.v)}>
          <span className="tr-name">
            SFT seed <Num kind="int" link={false} node={seed.seed} />
          </span>
          <Scale interval={seed.rate} scale="rate" what="seed rate" />
          <span className="tr-val">
            <Value interval={seed.rate} />
            {compact ? null : <Against other="base" paired={seed} />}
          </span>
        </li>
      ))}
      <li className="tr-row tr-row-mean">
        <span className="tr-name">SFT, mean of the seeds</span>
        <Scale interval={mean.rate} scale="rate" what="mean rate" />
        <span className="tr-val">
          <Value interval={mean.rate} />
          <Against other="base" paired={mean} />
        </span>
      </li>
    </ol>
  );
}

export function Head({headline}: {readonly headline: Headline}) {
  const {mean} = headline;
  return (
    <header className="tr-head">
      <p className="eyebrow">Post-training, frozen test split</p>
      <h1 className="tr-h1">
        Supervised fine-tuning lifts <Str node={headline.model_id} /> from{' '}
        <Num kind="rate" node={headline.base.value} /> to{' '}
        <Num kind="rate" node={mean.rate.value} />
      </h1>
      <p className="tr-lede">
        Strong exact over the <Num kind="int" node={headline.cases} /> ready cases of the frozen
        test split, answered as a typed intent with retrieved field context (
        <Str node={headline.condition} />
        ), for the mean of the fine-tuned seeds. Paired by case, the difference from the base
        model is{' '}
        <strong>
          <Value interval={mean.difference} />
        </strong>
        : <Num kind="int" node={mean.first_better_cases} /> cases better and{' '}
        <Num kind="int" node={mean.second_better_cases} /> worse.{' '}
        {mean.reading === null ? null : (
          <span className="tr-tag">
            <Str node={mean.reading} />
          </span>
        )}{' '}
        by the registered rule: the interval excludes zero, and{' '}
        <Num kind="int" node={headline.mean.discordant_cases} /> cases are discordant.
      </p>
    </header>
  );
}
