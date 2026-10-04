import type {Metadata} from 'next';
import {Fragment} from 'react';
import type {ReactNode} from 'react';

import {loadMethodology} from '@/lib/data';
import type {Methodology, NumNode, StrNode} from '@/lib/data';
import {Num, repositoryFile, Split, Str, Term, Unmeasured} from '@/lib/sourced';

export const metadata: Metadata = {
  title: 'Methodology',
};

const SHORTCUT_ABLATION = 'docs/ablations/006-shortcut-policy.md';

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
    <article className="prose-page">
      <p className="eyebrow">Methodology</p>
      <h1>Evidence has a boundary.</h1>
      <p>
        DFilterForge compares packet sets under a pinned tshark build, profile, and suite of probe
        captures. Matching one capture is not a proof of global equivalence. The evaluation
        protocol, <a href={repositoryFile('docs/protocol.md')}>docs/protocol.md</a>, defines the
        prompt conditions, the splits and the metrics; this page lists what the committed result
        files record about them.
      </p>

      <h2>Prompt conditions</h2>
      <p>As the anchor pass of the model bake-off prepared them.</p>
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

      <h2>Probe captures</h2>
      <p>
        Answers are scored on the scored probes of their split. A feedback probe is shown only to
        a repair round and never scored. Each probe is a benchmark capture followed by witness
        packets.
      </p>
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
                <code>
                  <Str node={probe.capture_sha256} />
                </code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        Witness packets separate near misses that the benchmark recipes alone cannot. The first
        probe capture holds <Count node={data.witnesses.count} /> of them:{' '}
        <Joined nodes={data.witnesses.names} />.
      </p>

      <h2>Scoring environment</h2>
      <p>As the anchor pass&apos;s score manifest records it.</p>
      <dl>
        <Fact label="tshark version">
          <Str node={data.environment.tshark_version} />
        </Fact>
        <Fact label={<>tshark executable <Term name="SHA-256" /></>}>
          <code>
            <Str node={data.environment.executable_sha256} />
          </code>
        </Fact>
        <Fact label={<>Runner source <Term name="SHA-256" /></>}>
          <code>
            <Str node={data.environment.runner_source_sha256} />
          </code>
        </Fact>
        <Fact label="Identity scope">
          <Str node={data.environment.identity_scope} />
        </Fact>
        <Fact label="Environment hash">
          <code>
            <Str node={data.environment.environment_hash} />
          </code>
        </Fact>
        <Fact label="Outside the environment identity">
          <Joined nodes={data.environment.unmeasured} />
        </Fact>
      </dl>

      <h2>Bootstrap</h2>
      <p>
        Intervals come from case-level bootstrap resamples, as the anchor pass&apos;s summary
        records them.
      </p>
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

      <h2>Mutation gate</h2>
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

      <h2>Shortcut audit</h2>
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

      <h2>Not measured yet</h2>
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

      <h2>Held-out freeze</h2>
      <p>
        The <Term name="SHA-256" /> of every prepare manifest a test request may answer, as the
        held-out freeze record admits them:{' '}
        <code>
          <Joined nodes={data.admitted_prepares} />
        </code>
        .
      </p>

      <h2>Why multiple probes?</h2>
      <p>
        A direction, boundary, missing-field, or empty-set mistake can look correct on one capture.
        Each semantic specification therefore includes positive, negative, boundary, direction, and
        distractor witnesses.
      </p>
      <h2>Why typed IR?</h2>
      <p>
        The model selects supported intent structure. A deterministic compiler owns field names,
        value types, escaping, parentheses, and display-filter syntax.
      </p>
      <h2>Why show negative results?</h2>
      <p>
        Benchmark and ablation pages retain failures and inconclusive outcomes. An improvement
        claim is useful only when its inputs and environment can be replayed.
      </p>
    </article>
  );
}
