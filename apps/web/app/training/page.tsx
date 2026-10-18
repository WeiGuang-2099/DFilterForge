import type {Metadata} from 'next';
import type {ReactNode} from 'react';

import {Against, Head, Ladder} from '@/app/_components/training/ladder';
import {CaseStrip, Scale} from '@/app/_components/training/marks';
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
// (Training rules), then each seed, the coverage strata, the cases, the
// hosted rows beside the mean and the untrained conditions. Every value is
// a sourced node; the words around them are fixed.

const HEADLINE = 'docs/results/sft-v1/headline.json';
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
  const {bootstrap} = headline;
  return (
    <article className="training">
      <Head headline={headline} />

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

      <section aria-labelledby="tr-limits" className="tr-sec">
        <h2 id="tr-limits">Limits</h2>
        <ul className="tr-limits">
          <li>
            The interval resamples the <Num kind="int" node={headline.cases} /> ready cases with the
            adapters fixed, so it says nothing of how another seed would land; the seeds&apos;
            spread is shown instead.
          </li>
          {headline.rerun_noise.t === 'not_measured' ? (
            <li>The self-served model&apos;s rerun noise is not measured yet.</li>
          ) : null}
          <li>
            The estimator and these words were registered in the{' '}
            <a href={repositoryFile(PROTOCOL)}>protocol</a> when one seed&apos;s test score was
            known; the other two were scored after the registration was pushed.
          </li>
          <li>
            The <a href={repositoryFile(NOTE)}>self-served note</a> holds the stack, the bills and
            the outages, among them a preemption that cost one seed some dev answers in an
            untrained condition.
          </li>
          <li>
            The numbers come from the <a href={repositoryFile(HEADLINE)}>headline file</a>, which a
            committed script writes from the scored runs and CI rebuilds.
          </li>
        </ul>
      </section>
    </article>
  );
}
