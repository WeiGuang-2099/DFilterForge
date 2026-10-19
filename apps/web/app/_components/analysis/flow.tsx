'use client';

/**
 * @fileoverview Where each of the base model's answers went under a seed.
 *
 * Two columns of outcome blocks, the base model's on the left and the
 * chosen seed's on the right, each as tall as its count. A ribbon joins the
 * answers one outcome led to another, as wide as their count, filled with
 * the outcome it reaches. Pressing a ribbon or focusing it lists its
 * answers with what the seed wrote; pointing at one only marks it, so the
 * list stays put while the reader moves down to it. Every seed's figure and
 * every list are in the server's HTML; the island only shows one seed and
 * one ribbon, so the consistency test reads every value in either state.
 * The geometry (flow-layout.ts) comes from the sourced counts and shows no
 * number of its own.
 */

import {useState} from 'react';
import type {CSSProperties, KeyboardEvent, ReactNode} from 'react';

import {OUTCOMES} from '@/lib/analysis-codes';
import type {Ribbon} from '@/lib/analysis-data';
import type {NumNode} from '@/lib/data';
import {NumText, StrText} from '@/lib/sourced-text';

import {AnswerText} from './answer';
import {
  BLOCK,
  blocksOf,
  count,
  draw,
  HEIGHT,
  LABEL_SPACE,
  LEFT,
  MIN_BLOCK,
  opening,
  percent,
  RIGHT,
  stack,
  unitsPerAnswer,
  VIEW_BOX,
  WIDTH,
} from './flow-layout';
import type {Block, Counts, SeedFlow} from './flow-layout';
import {KIND_WORDS, OUTCOME_WORDS, SHORT_WORDS, STATE_WORDS} from './words';

interface FlowProps {
  readonly base: Counts;
  readonly items: NumNode;
  readonly seeds: readonly SeedFlow[];
}

interface LabelProps {
  readonly block: Block;
  readonly counts: Counts;
  readonly items: NumNode;
  readonly side: 'left' | 'right';
}

function Label({block, counts, items, side}: LabelProps): ReactNode {
  const style: CSSProperties =
    side === 'left'
      ? {top: percent(block.label, HEIGHT), right: percent(WIDTH - LEFT + LABEL_SPACE, WIDTH)}
      : {top: percent(block.label, HEIGHT), left: percent(RIGHT + BLOCK + LABEL_SPACE, WIDTH)};
  return (
    <p className={`an-lab an-lab-${side}`} style={style}>
      <b>
        <span className="an-long">{OUTCOME_WORDS[block.outcome]}</span>
        <span className="an-short">{SHORT_WORDS[block.outcome]}</span>
      </b>
      <span>
        <NumText kind="int" node={counts[block.outcome]} /> of <NumText kind="int" node={items} />
      </span>
    </p>
  );
}

interface DetailProps {
  readonly id: string;
  readonly ribbon: Ribbon;
  readonly base: Counts;
  readonly seed: NumNode;
  readonly hidden: boolean;
}

/** One ribbon's answers, with what the seed wrote for each. */
function Detail({id, ribbon, base, seed, hidden}: DetailProps): ReactNode {
  const many = count(ribbon.count) !== 1;
  const [one, more] = STATE_WORDS[ribbon.to];
  return (
    <div className="an-detail" hidden={hidden}>
      <p className="an-detail-t" id={id}>
        <b>
          <NumText kind="int" node={ribbon.count} />
        </b>{' '}
        of the base model&apos;s <NumText kind="int" node={base[ribbon.from]} />{' '}
        {KIND_WORDS[ribbon.from]} answers {many ? 'are' : 'is'}{' '}
        {ribbon.from === ribbon.to ? 'still ' : null}
        {many ? more : one} under seed <NumText kind="int" node={seed} />.
      </p>
      <ul className="an-list">
        {ribbon.items.map((item) => (
          <li key={item.item_id.t}>
            <span className="an-who">
              <StrText node={item.case_id} />{' '}
              <span className="an-id">
                <StrText node={item.item_id} />
              </span>
            </span>
            <AnswerText answer={item.answer} />
          </li>
        ))}
      </ul>
    </div>
  );
}

interface SeedFigureProps {
  readonly base: Counts;
  readonly each: SeedFlow;
  readonly items: NumNode;
  readonly left: Block[];
  readonly scale: number;
  readonly seed: number;
  readonly chosen: number | undefined;
  readonly hidden: boolean;
  readonly onPick: (ribbon: number) => void;
}

/** One seed's blocks, ribbons and labels, and each ribbon's list. */
function SeedFigure(props: SeedFigureProps): ReactNode {
  const {base, each, items, left, scale, seed, hidden, onPick} = props;
  const right = stack(each.counts, scale);
  const drawn = draw(left, right, each.ribbons, scale);
  const chosen = props.chosen ?? 0;
  const id = (ribbon: number) => `an-flow-${String(seed)}-${String(ribbon)}`;
  const blocks = [
    ...left.map((block) => ({block, x: LEFT})),
    ...right.map((block) => ({block, x: RIGHT})),
  ];
  return (
    <div hidden={hidden}>
      <div className="an-scroll">
        <div className="an-canvas">
          <svg
            aria-label="Ribbons from the base model's outcomes to the seed's"
            className="an-svg"
            preserveAspectRatio="none"
            role="group"
            viewBox={VIEW_BOX}
          >
            {drawn.map((ribbon, index) => (
              <path
                aria-labelledby={id(index)}
                aria-pressed={index === chosen}
                className={`an-rib an-o-${ribbon.to}${index === chosen ? ' an-on' : ''}`}
                d={ribbon.path}
                key={`${ribbon.from}-${ribbon.to}`}
                onClick={() => onPick(index)}
                onFocus={() => onPick(index)}
                onKeyDown={(event: KeyboardEvent) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onPick(index);
                  }
                }}
                role="button"
                tabIndex={0}
              />
            ))}
            {blocks.map(({block, x}) => (
              <rect
                className={`an-node an-o-${block.outcome}`}
                height={Math.max(block.height, MIN_BLOCK)}
                key={`${String(x)}-${block.outcome}`}
                width={BLOCK}
                x={x}
                y={block.y}
              />
            ))}
          </svg>
          <p className="an-col an-col-left" style={{right: percent(WIDTH - LEFT - BLOCK, WIDTH)}}>
            Base model
          </p>
          <p className="an-col an-col-right" style={{left: percent(RIGHT, WIDTH)}}>
            Seed <NumText kind="int" node={each.seed} />
          </p>
          {left.map((block) => (
            <Label block={block} counts={base} items={items} key={block.outcome} side="left" />
          ))}
          {right.map((block) => (
            <Label block={block} counts={each.counts} items={items} key={block.outcome} side="right" />
          ))}
        </div>
      </div>
      {each.ribbons.map((ribbon, index) => (
        <Detail
          base={base}
          hidden={index !== chosen}
          id={id(index)}
          key={`${ribbon.from}-${ribbon.to}`}
          ribbon={ribbon}
          seed={each.seed}
        />
      ))}
    </div>
  );
}

/** The figure, one seed at a time, with the chosen ribbon's answers. */
export function Flow({base, items, seeds}: FlowProps): ReactNode {
  const [shown, setShown] = useState(0);
  const [picks, setPicks] = useState(() => seeds.map((each) => opening(each.ribbons)));
  const most = Math.max(blocksOf(base), ...seeds.map((each) => blocksOf(each.counts)));
  const scale = unitsPerAnswer(most, count(items));
  const left = stack(base, scale);
  const pick = (seed: number, ribbon: number) =>
    setPicks((now) => now.map((each, index) => (index === seed ? ribbon : each)));
  const present = OUTCOMES.filter(
    (outcome) =>
      count(base[outcome]) > 0 || seeds.some((each) => count(each.counts[outcome]) > 0),
  );
  return (
    <div className="an-flow">
      <div className="an-bar">
        <span className="lab" id="an-seed-label">
          Fine-tuned seed
        </span>
        <div aria-labelledby="an-seed-label" className="an-seg" role="group">
          {seeds.map((each, index) => (
            <button
              aria-pressed={index === shown}
              key={JSON.stringify(each.seed.v)}
              onClick={() => setShown(index)}
              type="button"
            >
              Seed <NumText kind="int" node={each.seed} />
            </button>
          ))}
        </div>
      </div>
      <ul className="an-key">
        {present.map((outcome) => (
          <li key={outcome}>
            <span aria-hidden="true" className={`an-sw an-o-${outcome}`} />
            {OUTCOME_WORDS[outcome]}
          </li>
        ))}
      </ul>
      {seeds.map((each, seed) => (
        <SeedFigure
          base={base}
          chosen={picks[seed]}
          each={each}
          hidden={seed !== shown}
          items={items}
          key={JSON.stringify(each.seed.v)}
          left={left}
          onPick={(ribbon) => pick(seed, ribbon)}
          scale={scale}
          seed={seed}
        />
      ))}
    </div>
  );
}
