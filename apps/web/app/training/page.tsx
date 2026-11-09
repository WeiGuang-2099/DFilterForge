import type {Metadata} from 'next';
import Link from 'next/link';
import type {ReactNode} from 'react';

import {SessionCost} from '@/app/_components/training/cost';
import {Against, Head, Ladder} from '@/app/_components/training/ladder';
import {CaseStrip, Scale} from '@/app/_components/training/marks';
import {RepairTurn} from '@/app/_components/training/repair';
import {Steps} from '@/app/_components/training/steps';
import {ConditionTable} from '@/app/_components/training/tables';
import {preview} from '@/lib/preview';
import {Num, repositoryFile, Str} from '@/lib/sourced';
import {loadTraining} from '@/lib/training-data';

import '@/app/_components/board/board.css';
import '@/app/_components/training/training.css';

export const metadata: Metadata = {
  title: 'Training',
  description: 'The small model before and after supervised fine-tuning, by the same verifier.',
  openGraph: preview(
    'og-training.png',
    'The top of the DFilterForge training page: the small model before and after ' +
      'supervised fine-tuning, on the frozen test split.',
  ),
};

// The training page shows docs/results/sft-v1/headline.json through
// training.json: the three-seed mean first, as docs/protocol.md registers
// (Training rules), then each seed, then the untrained baselines' ladder
// from ladder.json, the coverage strata, the cases, the hosted rows beside
// the mean and the untrained conditions, then the 1.7B repair round from the
// SFT pool and the seeds' rounds, and the sessions' cost from cost.json.
// Every value is a sourced node; the words around them are fixed.

const HEADLINE = 'docs/results/sft-v1/headline.json';
const LADDER = 'docs/results/sft-v1/ladder.json';
const COST = 'docs/results/sft-v1/cost.json';
const SFT_POOL = 'docs/results/repair-pool/test-qwen3-1.7b-sft.json';
const PROTOCOL = 'docs/protocol.md';
const ADR = 'docs/adr/0002-hosted-inference-and-small-model.md';
const NOTE = 'docs/decisions/self-served-runs.md';

const STRATA: Readonly<Record<string, string>> = {
  every_gold_field_retrieved: 'Every gold field retrieved',
  some_gold_field_missing: 'Some gold field missing',
};

export default function TrainingPage(): ReactNode {
  const {headline} = loadTraining();
  if (headline === null) {
    throw new Error('training: training.json has no headline, and the page shows one only');
  }
  const {bootstrap, rerun_noise: rerun, baseline, repair, cost} = headline;
  if (baseline === null || repair === null || cost === null) {
    throw new Error(
      'training: training.json lacks the baseline ladder, the repair round or the cost, ' +
        'and the page shows all three',
    );
  }
  const unread = cost.sessions.find((session) => session.unread !== null)?.unread;
  if (unread === undefined || unread === null) {
    throw new Error('training: the cost names no test passes reported not run');
  }
  return (
    <article className="training">
      <Head headline={headline} />
      <p className="tr-next">
        <Link href="/training/analysis">What fine-tuning fixed, and what it did not</Link>: where
        each of the base model&apos;s failed answers went under each seed, the kinds of mistake
        that remain, and how close the test split sits to training.
      </p>

      <section aria-labelledby="tr-rows" className="tr-sec">
        <h2 id="tr-rows">Every row on one scale</h2>
        <p className="tr-sub">
          Each line spans a row&apos;s interval: <Num kind="int" node={bootstrap.resamples} />{' '}
          case-level bootstrap resamples with seed <Num kind="int" node={bootstrap.seed} />, the
          same draws for every row. The interval holds the trained adapters fixed; the spread
          between seeds is their own rows.
        </p>
        <Ladder
          base={headline.base}
          mean={headline.mean}
          model={headline.model_id}
          seeds={headline.seeds}
        />
        <p aria-hidden="true" className="tr-axis">
          <span />
          <span>
            <span>no case exact</span>
            <span>every case exact</span>
          </span>
          <span />
        </p>
      </section>

      <Steps baseline={baseline} />

      <section aria-labelledby="tr-strata" className="tr-sec">
        <h2 id="tr-strata">Split by field coverage</h2>
        <p className="tr-sub">
          The training targets often name a field the retrieved list leaves out, so each row is
          split by whether the item&apos;s list held every gold field. Every row puts each item in
          the same stratum. The strata are shown and never read as a gain or a loss.
        </p>
        <div className="tr-strata">
          {headline.coverage.map((stratum) => (
            <div key={stratum.stratum}>
              <h3>
                {STRATA[stratum.stratum] ?? stratum.stratum},{' '}
                <Num kind="int" node={stratum.items} /> items
              </h3>
              <Ladder
                base={stratum.base}
                compact
                mean={stratum.mean}
                model={headline.model_id}
                seeds={stratum.seeds}
              />
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="tr-cases" className="tr-sec">
        <h2 id="tr-cases">Case by case</h2>
        <p className="tr-sub">
          One column per ready case, from the most strong-exact answers the seeds gained over the
          base model to the most they lost, each seed&apos;s two paraphrases counted. A block above
          the line is one answer gained; below it, one lost.
        </p>
        <p className="tr-counts">
          <span>
            <Num kind="int" node={headline.mean.first_better_cases} /> cases better
          </span>
          <span className="dn">
            <Num kind="int" node={headline.mean.second_better_cases} /> worse
          </span>
          <span>the rest tied</span>
        </p>
        <CaseStrip headline={headline} />
        <p aria-hidden="true" className="tr-key">
          <span>gained over base</span>
          <span>lost</span>
        </p>
        <details className="tr-details">
          <summary>Every case, with each row&apos;s strong-exact paraphrases</summary>
          <div className="tr-table-wrap">
            <table className="tr-table">
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">Base</th>
                  {headline.seeds.map((seed) => (
                    <th key={JSON.stringify(seed.seed.v)} scope="col">
                      Seed <Num kind="int" link={false} node={seed.seed} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {headline.cases_detail.map((item) => (
                  <tr key={item.case_id.t}>
                    <td className="tr-cell-name">
                      <Str node={item.case_id} />
                    </td>
                    <td>
                      <Num kind="int" node={item.base} />
                    </td>
                    {item.seeds.map((node, index) => (
                      <td key={JSON.stringify(headline.seeds[index]?.seed.v)}>
                        <Num kind="int" node={node} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section aria-labelledby="tr-hosted" className="tr-sec">
        <h2 id="tr-hosted">Beside the hosted models</h2>
        <p className="tr-sub">
          The mean of the seeds minus each hosted model&apos;s counted test row, case by case,
          as <a href={repositoryFile(ADR)}>the hosted-inference decision&apos;s amendment</a>{' '}
          words it. This is not a
          ranking: these models were not trained here, and the small model never enters the board.
        </p>
        <ol className="tr-ladder">
          {headline.hosted.map((row) => (
            <li className="tr-row tr-row-seed" key={row.model_id.t}>
              <span className="tr-name">
                <Str node={row.model_id} />
                <small>
                  test <Str node={headline.condition} /> <Num kind="rate" node={row.rate.value} />
                </small>
              </span>
              <Scale interval={row.difference} scale="difference" what="hosted difference" />
              <span className="tr-val">
                <Against other="the hosted row" paired={row} />
              </span>
            </li>
          ))}
        </ol>
        <p className="tr-note">
          The adapters were trained on compositions of exactly the predicates the dev and test gold
          uses, so test asks them for unseen compositions of seen atoms, not for unseen fields,
          operators or values.
        </p>
      </section>

      <section aria-labelledby="tr-conditions" className="tr-sec">
        <h2 id="tr-conditions">Untrained conditions, and dev first</h2>
        <p className="tr-sub">
          The adapters trained on <Str node={headline.condition} /> prompts only, so the other
          conditions are untrained and shown faint. Each row answered dev before any test
          request, and test only once dev settled. Dev chose nothing: every checkpoint is its final
          epoch, fixed before training.
        </p>
        <div className="tr-tables">
          <ConditionTable
            caption="Test"
            rows={headline.test}
            seeds={headline.seeds}
            trained={headline.condition.t}
          />
          <ConditionTable
            caption="Dev"
            rows={headline.dev}
            seeds={headline.seeds}
            trained={headline.condition.t}
          />
        </div>
      </section>

      <RepairTurn condition={headline.condition} repair={repair} />

      <SessionCost cost={cost} unread={unread} />

      <section aria-labelledby="tr-limits" className="tr-sec">
        <h2 id="tr-limits">Limits</h2>
        <ul className="tr-limits">
          <li>
            The interval resamples the <Num kind="int" node={headline.cases} /> ready cases with the
            adapters fixed, so it says nothing of how another seed would land; the seeds&apos;
            spread is shown instead.
          </li>
          <li>
            Sent again in a later session on the same stack, seed{' '}
            <Num kind="int" link={false} node={rerun.seed} />
            &apos;s adapter changed <Num kind="int" node={rerun.changed_answers} /> of its{' '}
            <Num kind="int" node={rerun.items} /> test answers and flipped{' '}
            <Num kind="int" node={rerun.trained.flipped_cases} /> of the{' '}
            <Num kind="int" node={rerun.trained.ready_cases} /> ready{' '}
            <Str node={rerun.trained.condition} /> cases; the{' '}
            <a href={repositoryFile(rerun.report.t)}>pair report</a> holds every condition.
          </li>
          <li>
            The estimator and these words were registered in the{' '}
            <a href={repositoryFile(PROTOCOL)}>protocol</a> when one seed&apos;s test score was
            known; the other two were scored after the registration was pushed.
          </li>
          <li>
            The schema and example rows were designed after every base and fine-tuned test score
            was known, the schema row after reading the base row&apos;s malformed test answers, so
            both are labelled post hoc. Their prompts, settings and reading were registered before
            any of their requests, and they change no registered row.
          </li>
          <li>
            Their first passes ran under a defect their dev passes showed: the client sorted the
            schema&apos;s keys, so the grammar let an answer only abstain. Those test passes are
            reported not run: they were never published or scored, and only their census was
            read. These rows are their re-runs, sent in a later session.
          </li>
          <li>
            The base row was sent in an earlier session than these two rows; how far a change of
            session alone moves the base model&apos;s greedy answers is not measured (the rerun
            line above measured one fine-tuned seed).
          </li>
          <li>
            The outcome counts and the field-coverage split are shown and never read as a gain or
            a loss.
          </li>
          <li>
            Ready test answers of the two post hoc rows that scored provider failed:{' '}
            <Num kind="int" node={baseline.schema.too_large} /> in the schema row and{' '}
            <Num kind="int" node={baseline.few_shot.too_large} /> in the example row. Each reply
            was larger than the client&apos;s reply size limit and counts as not exact.
          </li>
          <li>
            The repair round was registered after every base and fine-tuned score and the hosted
            round&apos;s results were known, so it is post hoc; its plans and reading were
            registered before its first request. The adapters were trained on single-turn
            prompts, so the bare and counterexample turns are chats they never saw in training;
            the repair interval covers case sampling with the three adapters fixed; and the round
            is never compared with the hosted models&apos; round on the board.
          </li>
          <li>
            The cost counts the <Num kind="int" node={unread.requests} /> requests of the{' '}
            <Num kind="int" node={unread.count} /> test passes reported not run as their prompt
            count, one request per prompt, since their records may not be opened; their share of
            the bill of the session that sent them stays in it, and their GPU time is left out.
          </li>
          <li>
            Neither cost figure is a price for any other serving, and the repair summaries&apos;
            spend columns are nominal, never a cost.
          </li>
          <li>
            The <a href={repositoryFile(NOTE)}>self-served note</a> holds the stack, the bills and
            the outages, among them a preemption that cost one seed some dev answers in an
            untrained condition.
          </li>
          <li>
            The numbers come from committed files. Committed scripts write the{' '}
            <a href={repositoryFile(HEADLINE)}>headline file</a>, the{' '}
            <a href={repositoryFile(LADDER)}>ladder file</a> and the{' '}
            <a href={repositoryFile(COST)}>cost file</a> from the scored runs, the runs&apos;
            records and the bills, and CI rebuilds all three. CI also derives the{' '}
            <a href={repositoryFile(SFT_POOL)}>repair pool file</a> and each seed&apos;s repair
            round again, re-scores every row&apos;s scored summary and outcomes, which give the
            tables by condition, the case-by-case counts and the replies refused as too large, and
            counts the rerun&apos;s pair report again from its two passes. The token cap, the
            response schema and the example count are the rows&apos; own records, the base and
            schema rows&apos; run manifests and the few-shot row&apos;s prepare, which CI reads and
            does not rebuild.
          </li>
        </ul>
      </section>
    </article>
  );
}
