/**
 * @fileoverview One repair turn, on the fine-tuned model.
 *
 * Server-rendered from training.json's repair block: the SFT seeds' test
 * repair round pooled by case, then each seed's own round. Each arm draws one
 * square per failed answer and fills one per repaired answer, so the squares
 * come from the two counts and nothing divides. The comparisons and each
 * seed's arms use the board's components, which label every pooled
 * comparison secondary and, per seed, counterexample against bare primary
 * (docs/protocol.md, Repair, amended 2026-10-26). Every number is a sourced
 * value.
 */

import type {ReactNode} from 'react';

import {Comparisons} from '@/app/_components/board/comparisons';
import {ArmBars, Rate} from '@/app/_components/board/marks';
import type {Arm} from '@/lib/board-data';
import type {StrNode} from '@/lib/data';
import {Num, Str, Term} from '@/lib/sourced';
import type {SftRepair} from '@/lib/training-data';

import {count} from './marks';

// The registered arms, in the order the page shows them: the card first and
// the repeatability check last (docs/protocol.md, Repair).
const ARMS = ['counterexample', 'bare', 'resample'] as const;

type ArmCode = (typeof ARMS)[number];

/** A round's arm by its code, or a throw naming the round and the arm missing. */
function arm(arms: readonly Arm[], code: ArmCode, round: string): Arm {
  const found = arms.find((each) => each.arm.t === code);
  if (found === undefined) {
    throw new Error(`training: ${round} has no ${code} arm`);
  }
  return found;
}

/**
 * A round's arms in the page's order. A round with an arm the protocol does
 * not register, or without one it does, fails the build, so the lede, the
 * arm blocks and each seed's bars and comparisons show the same arms.
 */
function registered(arms: readonly Arm[], round: string): readonly Arm[] {
  if (arms.length !== ARMS.length) {
    throw new Error(
      `training: ${round} has the arms ${JSON.stringify(arms.map((each) => each.arm.t))}, ` +
        `not ${JSON.stringify(ARMS)}`,
    );
  }
  return ARMS.map((code) => arm(arms, code, round));
}

/** One square per failed answer, the repaired ones filled first. */
function Squares({arm: drawn}: {readonly arm: Arm}): ReactNode {
  const triggered = count(drawn.triggered);
  const repaired = count(drawn.repaired);
  if (repaired > triggered) {
    throw new Error(`training: the ${drawn.arm.t} arm repaired more answers than it was sent`);
  }
  return (
    <div aria-hidden="true" className="tr-squares">
      {Array.from({length: triggered}, (_, index) => (
        <span
          className={index < repaired ? 'tr-sq tr-sq-on' : 'tr-sq'}
          key={`sq-${String(index)}`}
        />
      ))}
    </div>
  );
}

interface ArmBlockProps {
  readonly arm: Arm;
  readonly name: string;
  /** What the arm sent back, after its code. */
  readonly note: ReactNode;
}

/** One arm: repaired of failed answers, what it sent, its squares and repair@1. */
function ArmBlock({arm: shown, name, note}: ArmBlockProps): ReactNode {
  return (
    <div className="tr-arm">
      <p className="tr-arm-h">
        <span>{name}</span>
        <span className="m">
          <Num kind="int" node={shown.repaired} /> of <Num kind="int" node={shown.triggered} />
        </span>
      </p>
      <p className="tr-arm-n">
        <code>
          <Str node={shown.arm} />
        </code>
        : {note}
      </p>
      <Squares arm={shown} />
      <p className="tr-arm-r">
        <Term name="repair@1" /> <Rate interval={shown.repair_at_1} what="repair rate" />
      </p>
    </div>
  );
}

interface RepairTurnProps {
  readonly repair: SftRepair;
  /** The condition whose answers the round sent back, as the headline names it. */
  readonly condition: StrNode;
}

/** The SFT seeds' test repair round: the pooled arms, then each seed's round. */
export function RepairTurn({repair, condition}: RepairTurnProps): ReactNode {
  const round = 'the pooled round';
  const pooled = registered(repair.arms, round);
  const counterexample = arm(pooled, 'counterexample', round);
  const bare = arm(pooled, 'bare', round);
  const resample = arm(pooled, 'resample', round);
  const {bootstrap} = repair;
  return (
    <section aria-labelledby="tr-repair" className="tr-sec">
      <h2 id="tr-repair">One repair turn, on the fine-tuned model</h2>
      <p className="tr-sec-lede">
        Of the{' '}
        <b>
          <Num kind="int" node={counterexample.triggered} />
        </b>{' '}
        test answers the verifier failed, the fine-tuned model repaired{' '}
        <b>
          <Num kind="int" node={counterexample.repaired} />
        </b>{' '}
        when shown a counterexample card,{' '}
        <b>
          <Num kind="int" node={bare.repaired} />
        </b>{' '}
        when told only that its filter was wrong, and{' '}
        <b>
          <Num kind="int" node={resample.repaired} />
        </b>{' '}
        when sent the same prompt again, a repeatability check rather than a second chance.
      </p>
      <p className="tr-sub">
        Each seed&apos;s silent-wrong and invalid <Str node={condition} /> answers to ready test
        gold went back once in each arm, with that seed&apos;s adapter, settings and server. An
        answer counts as repaired only when the new one is strong exact on every scored probe;{' '}
        <Term name="repair@1" /> is the share repaired, every failed answer in its denominator.
        Each square is one failed answer, filled when it was repaired; filled squares come first,
        not in item order.
      </p>
      <div className="tr-arms">
        <ArmBlock
          arm={counterexample}
          name="Shown the counterexample"
          note={
            <>
              its failed answer, the turn that says its filter was incorrect, and a card from the
              unscored feedback probe: up to three frames where the answer and the labels
              disagree, or the error the answer raised.
            </>
          }
        />
        <ArmBlock
          arm={bare}
          name="Told it was wrong"
          note={
            <>
              its failed answer and the turn &ldquo;Your filter was incorrect. Reply with a
              corrected answer in the same JSON format.&rdquo;, with no card.
            </>
          }
        />
        <ArmBlock
          arm={resample}
          name="The same prompt again (repeatability check)"
          note={
            <>
              the first prompt sent again as a first turn. Served greedily on an unchanged stack it
              re-sends identical bytes, so it measures whether the stack repeats itself across
              sessions, not a second chance.
            </>
          }
        />
      </div>
      <h3 className="bd-h3" id="tr-repair-pooled">
        Pooled over the seeds
      </h3>
      <p className="tr-sub">
        Each difference is the first arm&apos;s <Term name="repair@1" /> minus the second&apos;s
        (resample is the repeatability check), paired by case over the{' '}
        <Num kind="int" node={bootstrap.cases} /> ready test cases with{' '}
        <Num kind="int" node={bootstrap.resamples} /> bootstrap resamples, seed{' '}
        <Num kind="int" node={bootstrap.seed} />, the draws used above. Pooled, a case is
        discordant when the two arms repaired a different number of its answers, the seeds&apos;
        taken together. These pooled comparisons are secondary. A comparison reads as a difference
        only when its interval excludes zero and at least{' '}
        <Num kind="int" node={bootstrap.min_discordant_cases} /> cases are discordant.
      </p>
      <Comparisons comparisons={repair.comparisons} labelledBy="tr-repair-pooled" pooled />
      <h3 className="bd-h3" id="tr-repair-seeds">
        Per seed
      </h3>
      <p className="tr-sub">
        Per seed, counterexample against bare is the registered primary comparison, and the two
        comparisons with resample are registered too. A seed&apos;s discordant cases cannot exceed
        the cases its failed answers fall in.
      </p>
      <details className="tr-details">
        <summary>Each seed&apos;s arms and comparisons</summary>
        {repair.seeds.map((seed, index) => {
          // A seed id holds digits, which no label attribute may, so each
          // round is labelled by its heading.
          const heading = `tr-seed-${String(index)}`;
          const arms = registered(seed.arms, `seed ${JSON.stringify(seed.seed.v)}'s round`);
          return (
            <div className="bd-pm" key={JSON.stringify(seed.seed.v)}>
              <div className="bd-pm-id">
                <h4 id={heading}>
                  Seed <Num kind="int" link={false} node={seed.seed} />
                </h4>
                <p className="bd-of">
                  <Num kind="int" node={seed.triggered_items} /> failed answers in{' '}
                  <Num kind="int" node={seed.triggered_cases} /> cases
                </p>
                <ArmBars arms={arms} compact labelledBy={heading} />
              </div>
              <Comparisons comparisons={seed.comparisons} labelledBy={heading} pooled={false} />
            </div>
          );
        })}
      </details>
    </section>
  );
}
