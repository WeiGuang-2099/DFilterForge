import type {Metadata} from 'next';
import type {ReactNode} from 'react';

import {Comparisons} from '@/app/_components/board/comparisons';
import {ArmBars, OutcomeBar, OutcomeLegend, Rate} from '@/app/_components/board/marks';
import {loadBoard} from '@/lib/board-data';
import type {Arm, BoardTest, Repair, TestRow} from '@/lib/board-data';
import type {StrNode} from '@/lib/data';
import {roleLabel} from '@/lib/roles';
import {Num, repositoryFile, Str, Term} from '@/lib/sourced';

import '@/app/_components/board/board.css';

export const metadata: Metadata = {
  title: 'Board',
  description:
    'The hosted models on the frozen test split: what one feedback turn repaired, and the counted passes it repaired.',
};

// The board shows the test phase from board.json: the repair round first,
// then the counted passes in pool order, never ranked. Every value is a
// sourced node; the words around them are fixed. The registered comparisons
// between conditions are left to docs/results/locked-test-v1.md, which
// gives them their A/A reading and confound notes.

// docs/protocol.md, Repair: the round sends back the answers of the typed,
// retrieval-backed condition that a counted pass got silent-wrong or
// invalid on ready gold.
const REPAIR_CONDITION = 'C4';
const LOCKED_TEST = 'docs/results/locked-test-v1.md';
const PROTOCOL = 'docs/protocol.md';
const REPAIR_NOTE = 'docs/decisions/repair-round.md';

type Condition = TestRow['conditions'][number];

function repairCondition(row: TestRow): Condition {
  const found = row.conditions.find((condition) => condition.label.t === REPAIR_CONDITION);
  if (found === undefined) {
    throw new Error(`board: ${row.run} has no condition ${REPAIR_CONDITION}`);
  }
  return found;
}

function arm(arms: readonly Arm[], name: string): Arm {
  const found = arms.find((each) => each.arm.t === name);
  if (found === undefined) {
    throw new Error(`board: the pooled round has no ${name} arm`);
  }
  return found;
}

/** The opening: the strongest number and what it means. */
function Headline({repair, label}: {readonly repair: Repair; readonly label: StrNode}) {
  const counterexample = arm(repair.arms, 'counterexample');
  const {bootstrap} = repair;
  return (
    <header className="bd-head">
      <p className="eyebrow">Board, frozen test split</p>
      <h1 className="bd-h1" id="bd-h1">
        After one structured counterexample,{' '}
        <span className="dn">
          <Num kind="int" node={counterexample.repaired} />
        </span>{' '}
        of <Num kind="int" node={counterexample.triggered} /> failed test answers were repaired.
      </h1>
      <p className="bd-lede">
        A bare &ldquo;Your filter was incorrect&rdquo; turn repaired{' '}
        <Num kind="int" node={arm(repair.arms, 'bare').repaired} />, and asking again with the
        same prompt <Num kind="int" node={arm(repair.arms, 'resample').repaired} />. The failed
        answers are every <Str node={label} /> answer to ready gold, typed IR with field context,
        that a counted pass of the hosted models got silent-wrong or invalid. One counts as
        repaired only when the new answer is strong exact on every scored probe; the counterexample
        comes from an unscored feedback probe alone.
      </p>
      <ArmBars arms={repair.arms} labelledBy="bd-h1" />
      <p className="bd-note">
        Pooled over the models. Each bar has one column per failed answer and fills one per
        repaired answer; the line under it spans the interval of <Term name="repair@1" />, from{' '}
        <Num kind="int" node={bootstrap.resamples} /> case-level bootstrap resamples with seed{' '}
        <Num kind="int" node={bootstrap.seed} /> over <Num kind="int" node={bootstrap.cases} /> ready
        cases.
      </p>
    </header>
  );
}

/** The counted passes, in pool order. */
function Passes({test, label}: {readonly test: BoardTest; readonly label: StrNode}) {
  return (
    <section aria-labelledby="bd-passes" className="bd-sec">
      <h2 id="bd-passes">The counted test passes</h2>
      <p className="bd-sub">
        One counted pass per hosted model over the frozen test prompts, in the pool order of the
        Disproof Reel. The rows are descriptive, not a ranking: no comparison between models was
        registered. Each bar is a pass&apos;s ready items in <Str node={label} /> by outcome; its
        silent-wrong and invalid answers are the ones the repair round sent back.
      </p>
      <OutcomeLegend />
      <div aria-hidden="true" className="bd-rh">
        <span>Role</span>
        <span>Model</span>
        <span>Ready items by outcome</span>
        <span>Strong exact [interval]</span>
      </div>
      <ol aria-labelledby="bd-passes" className="bd-rows">
        {test.rows.map((row) => {
          const condition = repairCondition(row);
          const {segments} = condition;
          return (
            <li className="bd-row" key={row.run}>
              <span className="bd-role">{roleLabel(row.role)}</span>
              <span className="bd-model">
                <Str node={row.model_id} />
              </span>
              <OutcomeBar condition={condition} />
              <span className="bd-row-n">
                <Rate interval={condition.metrics.strong_exact} what="strong exact" />
                <span className="bd-of">
                  <Num kind="int" node={segments.strong_exact} /> of{' '}
                  <Num kind="int" node={condition.ready} /> strong exact
                </span>
                <span className="bd-of">
                  <Num kind="int" node={segments.silent_wrong} /> silent-wrong,{' '}
                  <Num kind="int" node={segments.invalid} /> invalid
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      {test.rerun === null ? null : (
        <p className="bd-note">
          Pass B, <Str node={test.rerun.run_id} />, is pass A&apos;s rerun with the same model and
          settings. It measures rerun noise and is not a row.
        </p>
      )}
      {test.not_run.map((row) => (
        <p className="bd-note" key={row.run_id.t}>
          Ruled not run, the {roleLabel(row.role)} <Str node={row.run_id} />:{' '}
          <Str node={row.reason} />
        </p>
      ))}
      <p className="bd-note">
        The registered comparisons between conditions are on the{' '}
        <a href={repositoryFile(LOCKED_TEST)}>locked test results page</a>, with the A/A reading
        and the rate-limiting notes that bound them. The board leaves them out.
      </p>
    </section>
  );
}

/** The repair round's comparisons: pooled, then per model. */
function Round({repair}: {readonly repair: Repair}) {
  return (
    <section aria-labelledby="bd-repair" className="bd-sec">
      <h2 id="bd-repair">The repair round</h2>
      <p className="bd-sub">
        Each failed answer was sent once more in each arm, with its pass&apos;s model and
        settings. Resample asks again with the same prompt. Bare adds the counted answer and the
        turn &ldquo;Your filter was incorrect. Reply with a corrected answer in the same JSON
        format.&rdquo; Counterexample appends a card from the unscored feedback probe: the frames
        where the answer and the labels disagree, with their header fields, or the error the
        answer raised. The <a href={repositoryFile(PROTOCOL)}>protocol</a> and the{' '}
        <a href={repositoryFile(REPAIR_NOTE)}>repair note</a> register the round.
      </p>
      <h3 className="bd-h3" id="bd-pooled">
        Pooled over the models
      </h3>
      <p className="bd-sub">
        Each difference is the first arm&apos;s <Term name="repair@1" /> minus the second&apos;s, on
        the same resamples. Pooled, the unit is the case: a case is discordant when the two arms
        repaired a different number of its answers, the models&apos; taken together, and it counts
        once, for the arm that repaired more. With fewer than{' '}
        <Num kind="int" node={repair.bootstrap.min_discordant_cases} /> discordant cases a
        comparison is inconclusive, whatever its interval.
      </p>
      <Comparisons comparisons={repair.comparisons} labelledBy="bd-pooled" pooled />
      <h3 className="bd-h3" id="bd-models">
        Per model
      </h3>
      <p className="bd-sub">
        The registered primary comparison is counterexample against bare, per model, on each
        case&apos;s repaired share; the two comparisons with resample are registered too. A
        model&apos;s discordant cases cannot exceed the cases its failed answers fall in, so few
        of them can reach a reading.
      </p>
      {repair.models.map((model, index) => (
        <div className="bd-pm" key={model.run}>
          <div className="bd-pm-id">
            <h4 id={`bd-model-${index}`}>
              <Str node={model.model_id} />
            </h4>
            <p className="bd-of">
              {roleLabel(model.role)}: <Num kind="int" node={model.triggered_items} /> failed
              answers in <Num kind="int" node={model.triggered_cases} /> cases
            </p>
            {model.not_run.map((stopped) => (
              <p className="bd-of" key={stopped.arm}>
                {stopped.arm} not run: <Str node={stopped.reason} />
              </p>
            ))}
            <ArmBars arms={model.arms} compact labelledBy={`bd-model-${index}`} />
          </div>
          <Comparisons
            comparisons={model.comparisons}
            labelledBy={`bd-model-${index}`}
            pooled={false}
          />
        </div>
      ))}
    </section>
  );
}

/** What the numbers above do not say. */
function Limits(): ReactNode {
  return (
    <section aria-labelledby="bd-limits" className="bd-sec bd-limits">
      <h2 id="bd-limits">Limits</h2>
      <ul>
        <li>
          No A/A bound reads an arm comparison. The A/A pair&apos;s bound covers the comparisons
          between conditions only; the arm comparisons are read by the discordant-case rule alone,
          and no arm run was repeated.
        </li>
        <li>
          The frontier slot winner&apos;s arms were answered by another provider than its counted
          pass, under an owner ruling the <a href={repositoryFile(REPAIR_NOTE)}>repair note</a>{' '}
          records. Its bare and counterexample turns put one provider&apos;s answer before
          another&apos;s correction, its resample also measures the provider change, and the pool
          mixes the two.
        </li>
        <li>
          The failed answers are the counted passes&apos;: an item that rate limiting left without
          an answer scored provider failed and could not trigger.
        </li>
        <li>
          Some repaired counterexample answers hold a value their card showed for that field. They
          count as repaired; the locked test results page counts them as a diagnostic.
        </li>
        <li>
          The counted passes and the repair arms were sent on different days. The served models
          and providers are recorded, not controlled.
        </li>
        <li>
          The dev bake-off chose these models; its counts are model selection and appear on no
          page as a result. The dev repair round was a pipeline check and is not reported.
        </li>
        <li>
          Nothing here speaks to other Wireshark versions, real traffic or protocols outside the
          synthetic captures (<a href={repositoryFile(PROTOCOL)}>protocol</a>, Claim boundary).
        </li>
      </ul>
    </section>
  );
}

export default function BoardPage() {
  const {test} = loadBoard();
  if (test === null) {
    throw new Error('board: board.json has no test block, and the board shows test passes only');
  }
  const [first] = test.rows;
  if (first === undefined) {
    throw new Error('board: the test pool is empty');
  }
  const {label} = repairCondition(first);
  return (
    <article className="board">
      {test.repair === null ? (
        <header className="bd-head">
          <p className="eyebrow">Board, frozen test split</p>
          <h1 className="bd-h1">The counted test passes.</h1>
          <p className="bd-lede">The repair round is not pooled yet.</p>
        </header>
      ) : (
        <Headline label={label} repair={test.repair} />
      )}
      <Passes label={label} test={test} />
      {test.repair === null ? null : <Round repair={test.repair} />}
      <Limits />
    </article>
  );
}
