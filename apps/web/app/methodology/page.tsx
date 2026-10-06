import type {Metadata} from 'next';
import {Fragment} from 'react';
import type {ReactNode} from 'react';

import {loadMethodology} from '@/lib/data';
import type {Methodology, NumNode, StrNode} from '@/lib/data';
import {Digest, Num, repositoryFile, Split, Str, Term, Unmeasured} from '@/lib/sourced';

import './methodology.css';

export const metadata: Metadata = {
  title: 'Methodology',
};

const SHORTCUT_ABLATION = 'docs/ablations/006-shortcut-policy.md';
const REPAIR_NOTE = 'docs/decisions/repair-round.md';

// Names for the scored summary's not_measured keys. Each follows the split
// that summary records, "Test repair round" or "Dev repair round", so the
// line says which round it describes. A key the page does not know fails
// the build, so a new gap is never shown under the wrong name.
const NOT_MEASURED: Readonly<Record<string, string>> = {
  repair_at_1: 'repair round',
};

function notMeasuredName(key: string): string {
  const name = NOT_MEASURED[key];
  if (name === undefined) {
    throw new Error(`methodology: no name for the not_measured key ${JSON.stringify(key)}`);
  }
  return name;
}

/** Sourced strings joined by commas. */
function Joined({nodes}: {readonly nodes: readonly StrNode[]}): ReactNode {
  return nodes.map((node, index) => (
    <Fragment key={JSON.stringify(node.src)}>
      {index > 0 ? ', ' : null}
      <Str node={node} />
    </Fragment>
  ));
}

function Fact({label, children}: {readonly label: ReactNode; readonly children: ReactNode}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function Count({node}: {readonly node: NumNode}) {
  return <Num kind="int" node={node} />;
}

interface SectionProps {
  readonly id: string;
  readonly title: string;
  /** One line in the margin under the heading. */
  readonly summary?: ReactNode;
  readonly children: ReactNode;
}

/** A section: its heading and summary in the margin, its content beside. */
function Section({id, title, summary, children}: SectionProps) {
  return (
    <section aria-labelledby={id} className="mth-sec">
      <header className="mth-side">
        <h2 id={id}>{title}</h2>
        {summary === undefined ? null : <p className="mth-sum">{summary}</p>}
      </header>
      <div className="mth-body">{children}</div>
    </section>
  );
}

interface MutantRowProps {
  readonly name: string;
  readonly counts: Methodology['mutants']['all'];
}

function MutantRow({name, counts}: MutantRowProps) {
  return (
    <tr>
      <th scope="row">{name}</th>
      <td>
        <Count node={counts.executed} />
      </td>
      <td>
        <Count node={counts.killed} />
      </td>
      <td>
        <Count node={counts.survived} />
      </td>
      <td>
        <Count node={counts.waived} />
      </td>
    </tr>
  );
}

// Every value below comes from apps/web/data/methodology.json, which the
// exporter builds from committed files, and links to the file it comes
// from; tests/consistency.spec.ts re-derives each one.
export default function MethodologyPage() {
  const data = loadMethodology();
  return (
    <article className="mth">
      <header className="mth-sec mth-top">
        <p className="eyebrow mth-side">Methodology</p>
        <div className="mth-body">
          <h1>Evidence has a boundary.</h1>
          <p className="mth-lede">
            DFilterForge compares packet sets under a pinned tshark build, profile, and suite of
            probe captures. Matching one capture is not a proof of global equivalence. The
            evaluation protocol, <a href={repositoryFile('docs/protocol.md')}>docs/protocol.md</a>,
            defines the prompt conditions, the splits and the metrics; this page lists what the
            committed result files record about them.
          </p>
        </div>
      </header>

      <Section
        id="m-conditions"
        summary="As the anchor pass of the model bake-off prepared them."
        title="Prompt conditions"
      >
        <table>
          <thead>
            <tr>
              <th scope="col">Condition</th>
              <th scope="col">Answer contract</th>
              <th scope="col">Field retrieval</th>
            </tr>
          </thead>
          <tbody>
            {data.conditions.map((condition) => (
              <tr key={condition.label.t}>
                <th scope="row">
                  <Str node={condition.label} />
                </th>
                <td>
                  <Str node={condition.output_contract} />
                </td>
                <td>
                  <Str node={condition.retrieval} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          Field retrieval lists at most <Count node={data.top_k} /> catalog fields per request.
        </p>
      </Section>

      <Section
        id="m-probes"
        summary="Scored probes grade an answer; a feedback probe only feeds a repair turn."
        title="Probe captures"
      >
        <p>
          Answers are scored on the scored probes of their split. A feedback probe is shown only to
          a repair round and never scored. Each probe is a benchmark capture followed by witness
          packets.
        </p>
        <div className="mth-tw">
          <table>
            <thead>
              <tr>
                <th scope="col">Probe</th>
                <th scope="col">Split</th>
                <th scope="col">Role</th>
                <th scope="col">Benchmark frames</th>
                <th scope="col">All frames</th>
                <th scope="col">
                  Capture <Term name="SHA-256" />
                </th>
              </tr>
            </thead>
            <tbody>
              {data.probes.map((probe) => (
                <tr key={probe.probe_id.t}>
                  <th scope="row">
                    <Str node={probe.probe_id} />
                  </th>
                  <td>
                    <Str node={probe.split} />
                  </td>
                  <td>
                    <Str node={probe.role} />
                  </td>
                  <td>
                    <Count node={probe.benchmark_frames} />
                  </td>
                  <td>
                    <Count node={probe.frames} />
                  </td>
                  <td>
                    <Digest node={probe.capture_sha256} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Witness packets separate near misses that the benchmark recipes alone cannot. The first
          probe capture holds <Count node={data.witnesses.count} /> of them.
        </p>
        <details className="mth-more">
          <summary>The witness generators of the first probe capture</summary>
          <ul className="mth-cols">
            {data.witnesses.names.map((node) => (
              <li key={JSON.stringify(node.src)}>
                <Str node={node} />
              </li>
            ))}
          </ul>
        </details>
      </Section>

      <Section
        id="m-environment"
        summary="As the anchor pass's score manifest records it."
        title="Scoring environment"
      >
        <dl>
          <Fact label="tshark version">
            <Str node={data.environment.tshark_version} />
          </Fact>
          <Fact label={<>tshark executable <Term name="SHA-256" /></>}>
            <Digest node={data.environment.executable_sha256} />
          </Fact>
          <Fact label={<>Runner source <Term name="SHA-256" /></>}>
            <Digest node={data.environment.runner_source_sha256} />
          </Fact>
          <Fact label="Identity scope">
            <Str node={data.environment.identity_scope} />
          </Fact>
          <Fact label="Environment hash">
            <Digest node={data.environment.environment_hash} />
          </Fact>
          <Fact label="Outside the environment identity">
            <Joined nodes={data.environment.unmeasured} />
          </Fact>
        </dl>
      </Section>

      <Section
        id="m-bootstrap"
        summary="Intervals come from case-level bootstrap resamples, as the anchor pass's summary records them."
        title="Bootstrap"
      >
        <dl>
          <Fact label="Ready cases resampled">
            <Count node={data.bootstrap.cases} />
          </Fact>
          <Fact label="Non-ready cases">
            <Count node={data.bootstrap.non_ready_cases} />
          </Fact>
          <Fact label="Resamples">
            <Count node={data.bootstrap.resamples} />
          </Fact>
          <Fact label="Seed">
            <Count node={data.bootstrap.seed} />
          </Fact>
          <Fact label="Discordant cases needed for a conclusive comparison">
            <Count node={data.bootstrap.min_discordant_cases} />
          </Fact>
        </dl>
      </Section>

      <Section
        id="m-mutants"
        summary="Each single-site mutant of a ready case is killed by a scored probe or waived."
        title="Mutation gate"
      >
        <p>
          Every single-site mutant of a ready case&apos;s canonical IR must differ from the labels
          on a scored probe of its split, unless a waiver names it with a reason. The counts come
          from the committed test-freeze gate record.
        </p>
        <table>
          <thead>
            <tr>
              <th scope="col">Split</th>
              <th scope="col">Executed</th>
              <th scope="col">Killed</th>
              <th scope="col">Survived</th>
              <th scope="col">Waived</th>
            </tr>
          </thead>
          <tbody>
            <MutantRow counts={data.mutants.dev} name="dev" />
            <MutantRow counts={data.mutants.test} name="test" />
            <MutantRow counts={data.mutants.all} name="all" />
          </tbody>
        </table>
        <p>
          Mutant categories: <Joined nodes={data.mutant_categories} />.
        </p>
      </Section>

      <Section
        id="m-shortcuts"
        summary="A filter that counts frames or reads the capture clock scores shortcut."
        title="Shortcut audit"
      >
        <p>
          A filter that matches every labelled frame by counting frames, reading the capture clock
          or copying a generator constant scores shortcut, not strong exact. The{' '}
          <a href={repositoryFile(SHORTCUT_ABLATION)}>shortcut-policy ablation</a> measured the
          policy on the gold and on the answers committed when it ran.
        </p>
        <dl>
          <Fact label="Frame-number and time fields in the frozen catalog">
            <Count node={data.shortcuts.position_typed_fields} />
          </Fact>
          <Fact label="Gold candidates checked">
            <Count node={data.shortcuts.gold_candidates} />
          </Fact>
          <Fact label="Gold candidates flagged">
            <Count node={data.shortcuts.gold_flagged} />
          </Fact>
          <Fact label="Committed answers checked">
            <Count node={data.shortcuts.answer_candidates} />
          </Fact>
          <Fact label="Committed answers flagged">
            <Count node={data.shortcuts.answers_flagged} />
          </Fact>
        </dl>
      </Section>

      {data.repair === null ? null : (
        <Section
          id="m-repair"
          summary="One more turn for each silent-wrong or invalid answer."
          title="Repair round"
        >
          <p>
            A repair round gives each silent-wrong or invalid answer of the typed, retrieval-backed
            condition one more turn in each arm the{' '}
            <a href={repositoryFile(REPAIR_NOTE)}>repair note</a> defines. An answer counts as
            repaired only when that turn scores strong exact.
          </p>
          <p>
            <Split node={data.repair.split} /> repair round of <Str node={data.repair.model_id} />:{' '}
            <Count node={data.repair.triggered_items} /> answers triggered.
          </p>
          <dl>
            {data.repair.arms.map((arm) => (
              <Fact key={arm.arm.t} label={<Str node={arm.arm} />}>
                <Count node={arm.repaired} /> repaired
              </Fact>
            ))}
            {data.repair.not_run.map((arm) => (
              <Fact key={arm.arm} label={arm.arm}>
                not run: <Str node={arm.reason} />
              </Fact>
            ))}
          </dl>
        </Section>
      )}

      {data.not_measured.length === 0 ? null : (
        <Section
          id="m-unmeasured"
          summary="What no committed round has measured."
          title="Not measured yet"
        >
          <dl>
            {data.not_measured.map((entry) => (
              <Fact
                key={entry.key}
                label={
                  <>
                    <Split node={entry.split} /> {notMeasuredName(entry.key)}
                  </>
                }
              >
                <Unmeasured node={entry.value} />
              </Fact>
            ))}
          </dl>
        </Section>
      )}

      <Section
        id="m-freeze"
        summary="The prompt sets a test request may answer."
        title="Held-out freeze"
      >
        <p className="mth-lead">
          <Count node={data.admitted_count} /> admitted prepares
        </p>
        <p>
          The held-out freeze record lists the <Term name="SHA-256" /> of each prepare manifest a
          test request may answer. The call step refuses any other test prompt set before a model
          client exists.
        </p>
        <details className="mth-more">
          <summary>
            The admitted manifests&apos; <Term name="SHA-256" /> digests
          </summary>
          <ul className="mth-dg">
            {data.admitted_prepares.map((node) => (
              <li key={JSON.stringify(node.src)}>
                <Digest node={node} />
              </li>
            ))}
          </ul>
        </details>
      </Section>

      <Section id="m-probes-why" title="Why multiple probes?">
        <p>
          A direction, boundary, missing-field, or empty-set mistake can look correct on one
          capture. Each semantic specification therefore includes positive, negative, boundary,
          direction, and distractor witnesses.
        </p>
      </Section>
      <Section id="m-ir-why" title="Why typed IR?">
        <p>
          The model selects supported intent structure. A deterministic compiler owns field names,
          value types, escaping, parentheses, and display-filter syntax.
        </p>
      </Section>
      <Section id="m-negative-why" title="Why show negative results?">
        <p>
          Benchmark and ablation pages retain failures and inconclusive outcomes. An improvement
          claim is useful only when its inputs and environment can be replayed.
        </p>
      </Section>
    </article>
  );
}
