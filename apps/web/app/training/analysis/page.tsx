import type {Metadata} from 'next';
import type {ReactNode} from 'react';

import {Flow} from '@/app/_components/analysis/flow';
import {Kinds} from '@/app/_components/analysis/kinds';
import {LossChart, LossTable} from '@/app/_components/analysis/loss';
import {Nearness} from '@/app/_components/analysis/nearness';
import {CopiesTable, Head, StrataTable} from '@/app/_components/analysis/sections';
import {loadAnalysis} from '@/lib/analysis-data';
import {preview} from '@/lib/preview';
import {Num, repositoryBlob, repositoryFile} from '@/lib/sourced';

import '@/app/_components/analysis/analysis.css';

export const metadata: Metadata = {
  title: 'What fine-tuning fixed',
  description:
    "Where the small model's failed test answers went after supervised fine-tuning, the kinds of mistake that remain, and how close the test split sits to training.",
  openGraph: preview(
    'og-analysis.png',
    "The top of the DFilterForge analysis page: where the small model's failed test answers " +
      'went after supervised fine-tuning.',
  ),
};

// The analysis page shows docs/results/sft-v1/analysis.json through
// analysis.json: the moves from the base model to each seed first, then the
// registered error classes and proximity strata, each labelled post hoc as
// docs/protocol.md requires (Training rules, amended 2026-10-18), then the
// training loss. Every value is a sourced node; the words around them are
// fixed.

const ANALYSIS = 'docs/results/sft-v1/analysis.json';
const CHECK = 'docs/results/sft-v1/class-check.md';
const PROTOCOL = 'docs/protocol.md';
const NOTE = 'docs/decisions/self-served-runs.md';

export default function AnalysisPage(): ReactNode {
  const {analysis} = loadAnalysis();
  if (analysis === null) {
    throw new Error('analysis: analysis.json has no analysis, and the page shows one only');
  }
  const [base, ...seeds] = analysis.rows;
  if (base === undefined) {
    throw new Error('analysis: analysis.json has no rows');
  }
  const [loss] = analysis.loss;
  return (
    <article className="analysis">
      <Head analysis={analysis} />

      <section aria-labelledby="an-flow-h" className="an-sec an-sec-flow">
        <h2 id="an-flow-h">Where each answer went</h2>
        <p className="an-sub">
          Each block is one outcome of the <Num kind="int" node={analysis.items} /> ready answers,
          the base model&apos;s on the left and the chosen seed&apos;s on the right; a ribbon is as
          wide as the answers that moved from one outcome to another. Press a ribbon, or tab to
          it, to list its answers with what the seed wrote.
        </p>
        <Flow
          base={base.outcomes}
          items={analysis.items}
          seeds={seeds.map((row, index) => {
            const seed = analysis.seeds[index];
            const ribbons = analysis.flows[index];
            if (seed === undefined || ribbons === undefined) {
              throw new Error('analysis: a seed has no flows');
            }
            return {seed, counts: row.outcomes, ribbons};
          })}
        />
      </section>

      <section aria-labelledby="an-kinds-h" className="an-sec">
        <h2 id="an-kinds-h">
          The kinds of mistake <span className="an-tag">Post hoc</span>
        </h2>
        <p className="an-sub">
          Every answer that is not strong exact takes the first class that applies, in the order
          the <a href={repositoryFile(PROTOCOL)}>protocol</a> registered: an unanswered, refused,
          malformed, abstained or shortcut answer by its outcome, the scorer&apos;s error code and
          whether the reply hit the token limit; a silent-wrong answer by the first set that differs
          between its Intent IR and the reference&apos;s, fields first. The classes
          were defined when one seed&apos;s test scores were known; they describe and decide
          nothing, and a class names the first difference, not the cause. Press a count to see
          the first of its answers.
        </p>
        <Kinds blob={repositoryBlob()} rows={analysis.rows} seeds={analysis.seeds} />
        <p className="an-note">
          A <a href={repositoryFile(CHECK)}>hand check</a> of a random sample of the classified
          answers found each one classed by the rule, most of them with other errors beside the one
          their class names.
        </p>
      </section>

      <section aria-labelledby="an-near-h" className="an-sec">
        <h2 id="an-near-h">
          How close the test split is to training <span className="an-tag">Post hoc</span>
        </h2>
        <p className="an-sub">
          The training targets compose the predicates the test references use, never a
          reference&apos;s own form. Each of the <Num kind="int" node={analysis.cases} /> ready
          test cases takes the first stratum its predicates reach among the{' '}
          <Num kind="int" node={analysis.nearness.targets} /> ready training targets, negation and
          grouping ignored. Press a square to see the case beside the target that holds the most
          of its predicates.
        </p>
        <Nearness
          cases={analysis.nearness.cases}
          columns={analysis.nearness.strata.map((stratum) => ({
            stratum: stratum.stratum,
            cases: stratum.cases,
          }))}
          seeds={analysis.seeds}
        />
        <StrataTable analysis={analysis} />
        <h3 className="an-h3">Copies, and fields off the retrieved list</h3>
        <p className="an-sub">
          Of each row&apos;s answers with Intent IR, how many copy a training target&apos;s
          canonical form, and how many test a field the item&apos;s retrieved list does not
          name, each with how many of them are strong exact. The base model never saw the
          training set, so its copies are the rate an untrained model reaches unaided.
        </p>
        <CopiesTable analysis={analysis} />
      </section>

      <section aria-labelledby="an-loss-h" className="an-sec">
        <h2 id="an-loss-h">Training loss measures memory</h2>
        <p className="an-sub">
          {loss === undefined ? null : (
            <>
              Each seed trained <Num kind="int" node={loss.epochs} /> epochs over the same{' '}
              <Num kind="int" node={loss.rows} /> training rows.{' '}
            </>
          )}
          The loss falls by orders of magnitude, each ruled line a factor of ten below the last:
          the adapters reproduce their training targets almost token for token. That is memory of
          a closed world, the fields and predicates of the training grammar. Only the test split
          says how much of it carries over to requests the adapters never saw.
        </p>
        <LossChart seeds={analysis.loss} />
        <LossTable seeds={analysis.loss} />
      </section>

      <section aria-labelledby="an-limits-h" className="an-sec">
        <h2 id="an-limits-h">Limits</h2>
        <ul className="an-limits">
          <li>
            The error classes and the proximity strata were registered when one seed&apos;s test
            scores were known, so they are post hoc. They describe the answers: no training data,
            prompt, checkpoint or seed changed because of them, and no test failure became
            training data.
          </li>
          <li>
            A class names the first difference the registered order finds between an
            answer&apos;s Intent IR and the reference&apos;s, not the cause of the failure; the{' '}
            <a href={repositoryFile(CHECK)}>hand check</a> lists answers whose class stands beside
            other errors.
          </li>
          <li>
            Proximity compares predicates, not the wording of the requests, and ignores negation
            and grouping: a case whose predicates a target holds negated, or joined the other way,
            counts as near.
          </li>
          <li>
            There are <Num kind="int" node={analysis.cases} /> ready test cases and{' '}
            <Num kind="int" node={analysis.items} /> answers per row, so a class or stratum with a
            handful of answers can change with any one of them.
          </li>
          <li>
            The transitions of the test items whose gold is not ready, and the field-coverage
            split of the hosted rows, are in the analysis file and not drawn here.
          </li>
          {analysis.rerun_noise.t === 'not_measured' ? (
            <li>
              The self-served model&apos;s rerun noise is not measured, so a move of a single
              answer between two rows may be noise as well as fine-tuning; the{' '}
              <a href={repositoryFile(NOTE)}>self-served note</a> holds the serving stack.
            </li>
          ) : null}
          <li>
            The classes, strata, ranges and copies come from the{' '}
            <a href={repositoryFile(ANALYSIS)}>analysis file</a>, which a committed script writes
            from the scored runs and CI rebuilds; the outcome counts and answers come from each
            row&apos;s own scored files, and the loss from each seed&apos;s run manifest.
          </li>
        </ul>
      </section>
    </article>
  );
}
