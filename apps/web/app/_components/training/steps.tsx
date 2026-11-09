/**
 * @fileoverview Cheaper fixes first: the untrained baselines beside
 * fine-tuning.
 *
 * Server-rendered from training.json's baseline block, the ladder of
 * docs/results/sft-v1/ladder.json. A strip gives four strong-exact rates,
 * from the base model to the fine-tuned seed mean, with each registered step
 * between two of them. Each step is then a question: its closed receipt
 * holds the reading rule's two tests and where each row's ready answers
 * went. Every row's outcome counts and coverage split follow in a closed
 * table, shown and never read. The schema and example rows were designed
 * after the scores were known, so the heading and every label of theirs
 * carry the post hoc tag (docs/protocol.md, Training rules, amended
 * 2026-10-26). A bar's parts grow by counts, so nothing divides; every
 * number is a sourced value.
 */

import type {ReactNode} from 'react';

import type {NumNode, StrNode} from '@/lib/data';
import {Num, Str} from '@/lib/sourced';
import type {Baseline, BaselineRow, Interval, Rung} from '@/lib/training-data';

import {count, Scale, Value} from './marks';

// A step's committed reading as a tag: a gain filled with ink, a loss with
// carmine, an inconclusive step open. A reading not listed fails the build.
const TAGS = {
  gain: 'tr-tag',
  loss: 'tr-tag tr-tag-loss',
  inconclusive: 'tr-tag tr-tag-open',
} as const;

type Reading = keyof typeof TAGS;

function isReading(code: string): code is Reading {
  return Object.hasOwn(TAGS, code);
}

/** A step's committed reading, checked against the readings the page tags. */
function readingOf(node: StrNode): Reading {
  if (!isReading(node.t)) {
    throw new Error(`training: ${JSON.stringify(node.t)} is no reading the page can tag`);
  }
  return node.t;
}

/** A step's committed reading, as its tag. */
function ReadingTag({node}: {readonly node: StrNode}): ReactNode {
  return (
    <span className={TAGS[readingOf(node)]}>
      <Str node={node} />
    </span>
  );
}

/**
 * The protocol's label on a row designed after every score was known. It is
 * fixed words placed by position, so the consistency test finds it by its
 * attribute and derives each one again from the ladder file.
 */
function PostHoc(): ReactNode {
  return (
    <span className="tr-tag tr-tag-open" data-tag="post-hoc">
      post hoc
    </span>
  );
}

/** A bound a sourced node holds, which the rule's zero test reads. */
function bound(node: NumNode): number {
  if (typeof node.v !== 'number') {
    throw new Error(`training: ${JSON.stringify(node.v)} is no bound`);
  }
  return node.v;
}

/** One part of a row's ready answers: its key, its words and its count. */
interface Part {
  readonly key: string;
  readonly words: string;
  readonly pick: (row: BaselineRow) => NumNode;
}

// A row's ready answers in a fixed order, so the eye reads the strong-exact
// share from the left; a malformed answer is cut at the token cap or
// malformed otherwise. The exporter proves no answer is false ready and that
// the parts add up to the row's items.
const PARTS: readonly Part[] = [
  {key: 'strong_exact', words: 'strong exact', pick: (row) => row.outcomes.strong_exact},
  {key: 'silent_wrong', words: 'silent-wrong', pick: (row) => row.outcomes.silent_wrong},
  {key: 'invalid', words: 'invalid', pick: (row) => row.outcomes.invalid},
  {
    key: 'truncated',
    words: 'malformed, cut at the token cap',
    pick: (row) => row.malformed.truncated,
  },
  {key: 'malformed', words: 'malformed, other', pick: (row) => row.malformed.other},
  {key: 'shortcut', words: 'shortcut', pick: (row) => row.outcomes.shortcut},
  {key: 'abstained', words: 'abstained', pick: (row) => row.outcomes.abstained},
  {key: 'provider_failed', words: 'provider failed', pick: (row) => row.outcomes.provider_failed},
];

/** A ladder row with the label the page gives it. */
interface MixProps {
  readonly row: BaselineRow;
  readonly label: ReactNode;
}

/** A labelled row with a key of its own among the rows. */
interface Labelled extends MixProps {
  readonly key: string;
}

interface TestProps {
  readonly name: 'zero' | 'discordant';
  readonly passed: boolean;
  readonly children: ReactNode;
}

/**
 * One test of the reading rule, marked met or not met. The mark and the
 * words beside it are chosen from sourced values, so the consistency test
 * derives both again from the ladder file.
 */
function Test({name, passed, children}: TestProps): ReactNode {
  return (
    <li
      className={passed ? 'tr-pass' : 'tr-fail'}
      data-pass={passed ? 'yes' : 'no'}
      data-test={name}
    >
      <span aria-hidden="true" className="tr-mark" />
      <span className="tr-vh">{passed ? 'Met: ' : 'Not met: '}</span>
      {children}
    </li>
  );
}

/** One row's ready answers as a bar, each part as wide as its count. */
function Mix({row, label}: MixProps): ReactNode {
  return (
    <div className="tr-mix">
      <p className="tr-mix-nm">{label}</p>
      <div className="tr-mix-bar">
        {PARTS.map((part) => {
          const node = part.pick(row);
          const grow = count(node);
          return grow === 0 ? null : (
            <span className={`tr-seg tr-o-${part.key}`} key={part.key} style={{flexGrow: grow}}>
              <span className="tr-vh">
                <Num kind="int" link={false} node={node} /> {part.words},
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

interface LegendProps {
  readonly parts: readonly Part[];
  /** The rows' token cap, which a cut answer reached. */
  readonly cap: NumNode;
}

/** The bars' legend: the parts some ladder row holds. */
function Legend({parts, cap}: LegendProps): ReactNode {
  return (
    <ul aria-label="Bar legend" className="tr-legend">
      {parts.map((part) => (
        <li key={part.key}>
          <span aria-hidden="true" className={`tr-sw tr-o-${part.key}`} />
          {part.key === 'truncated' ? (
            <span>
              malformed, cut at the <Num kind="int" node={cap} />-token cap
            </span>
          ) : (
            part.words
          )}
        </li>
      ))}
    </ul>
  );
}

interface QuestionProps {
  readonly name: keyof Baseline['rungs'];
  readonly rung: Rung;
  readonly title: ReactNode;
  readonly what: ReactNode;
  /** The rows the step reads, its first row or rows above its second. */
  readonly mixes: readonly Labelled[];
  readonly baseline: Baseline;
  readonly legend: ReactNode;
}

/**
 * One registered step as a question: its difference on the minus one to one
 * scale, then, opened, the rule's two tests and the rows' bars. The summary
 * holds no link and no heading, so it stays one control.
 */
function Question({name, rung, title, what, mixes, baseline, legend}: QuestionProps): ReactNode {
  // baseline_ladder.py's rule: an interval excludes zero only when it lies
  // wholly on one side; an endpoint at zero does not exclude it.
  const zero = bound(rung.difference.low) > 0 || bound(rung.difference.high) < 0;
  const enough = count(rung.discordant_cases) >= count(baseline.bootstrap.min_discordant_cases);
  return (
    <li className={`tr-q tr-q-${readingOf(rung.reading)}`} data-rung={name}>
      <details>
        <summary>
          <span className="tr-row">
            <span className="tr-name">
              <b>{title}</b>
              <small>
                {what} <span aria-hidden="true" className="tr-q-mark" />
              </small>
            </span>
            <Scale interval={rung.difference} scale="difference" what={name} />
            <span className="tr-val">
              <span>
                <Value interval={rung.difference} link={false} />{' '}
                <ReadingTag node={rung.reading} />
              </span>
              <span className="tr-of">
                <Num kind="int" link={false} node={rung.first_better_cases} /> cases better,{' '}
                <Num kind="int" link={false} node={rung.second_better_cases} /> worse
              </span>
            </span>
          </span>
        </summary>
        <div className="tr-rcpt">
          <ul className="tr-rule">
            <Test name="zero" passed={zero}>
              The interval {zero ? 'excludes' : 'includes'} zero.
            </Test>
            <Test name="discordant" passed={enough}>
              <Num kind="int" node={rung.discordant_cases} /> of{' '}
              <Num kind="int" node={baseline.cases} /> cases are discordant; the rule needs{' '}
              <Num kind="int" node={baseline.bootstrap.min_discordant_cases} />.
            </Test>
            <li>
              So the step reads <ReadingTag node={rung.reading} />.
            </li>
          </ul>
          <div className="tr-mixes">
            {mixes.map((mix) => (
              <Mix key={mix.key} label={mix.label} row={mix.row} />
            ))}
            {legend}
          </div>
        </div>
      </details>
    </li>
  );
}

/** One level of the strip, with the step that leads to it. */
interface Level {
  readonly key: string;
  readonly name: ReactNode;
  readonly rate: Interval;
  readonly rung: Rung | null;
}

/** The four rates in a row, each step between two of them. */
function Strip({levels}: {readonly levels: readonly Level[]}): ReactNode {
  return (
    <ol aria-label="Strong exact, from the base model to fine-tuning" className="tr-flow">
      {levels.map((level) => (
        <li className={`tr-flow-${level.key}`} key={level.key}>
          {level.rung === null ? null : (
            <span className={`tr-flow-step tr-step-${readingOf(level.rung.reading)}`}>
              <span className="tr-vh">Step from the level before: </span>
              <Num kind="rate" node={level.rung.difference.value} />
              <span aria-hidden="true" className="tr-flow-ar" />
              <ReadingTag node={level.rung.reading} />
            </span>
          )}
          <span className="tr-flow-cell">
            <span className="tr-flow-nm">{level.name}</span>
            <span className="tr-flow-v">
              <Num kind="rate" node={level.rate.value} />
            </span>
            <span className="bd-ci">
              [<Num kind="rate" node={level.rate.low} />,{' '}
              <Num kind="rate" node={level.rate.high} />]
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}

interface RowTablesProps {
  readonly baseline: Baseline;
  /** Every ladder row, in the ladder's order. */
  readonly rows: readonly Labelled[];
}

/** Every row's outcome counts and coverage split, shown and never read. */
function RowTables({baseline, rows}: RowTablesProps): ReactNode {
  const items = baseline.coverage_items;
  return (
    <details className="tr-details">
      <summary>
        Every row&apos;s <Num kind="int" link={false} node={baseline.items} /> answers by outcome,
        and split by field coverage
      </summary>
      <p className="lab tr-tcap" id="tr-steps-outcomes">
        Ready test answers by outcome, shown and never read
      </p>
      <div className="tr-table-wrap">
        <table aria-labelledby="tr-steps-outcomes" className="tr-table tr-nowrap tr-row-labels">
          <thead>
            <tr>
              <th scope="col">Row</th>
              {PARTS.map((part) => (
                <th className="tr-n" key={part.key} scope="col">
                  {part.words}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({key, row, label}) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                {PARTS.map((part) => (
                  <td className="tr-n" key={part.key}>
                    <Num kind="int" node={part.pick(row)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="lab tr-tcap" id="tr-steps-coverage">
        Strong exact by field coverage, shown and never read
      </p>
      <div className="tr-table-wrap">
        <table aria-labelledby="tr-steps-coverage" className="tr-table tr-nowrap tr-row-labels">
          <thead>
            <tr>
              <th scope="col">Row</th>
              <th scope="col">
                Every gold field retrieved,{' '}
                <Num kind="int" node={items.every_gold_field_retrieved} /> items
              </th>
              <th scope="col">
                Some gold field missing, <Num kind="int" node={items.some_gold_field_missing} />{' '}
                items
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({key, row, label}) => (
              <tr key={key}>
                <th scope="row">{label}</th>
                <td>
                  <Value interval={row.coverage.every_gold_field_retrieved} />
                </td>
                <td>
                  <Value interval={row.coverage.some_gold_field_missing} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Cheaper fixes first: the strip, the three questions and every row's counts. */
export function Steps({baseline}: {readonly baseline: Baseline}): ReactNode {
  const {bootstrap, rungs} = baseline;
  const examples = <Num kind="int" link={false} node={baseline.examples} />;
  const base: Labelled = {key: 'base', row: baseline.base, label: 'Base model'};
  const schema: Labelled = {
    key: 'schema',
    row: baseline.schema,
    label: (
      <>
        Base + schema <PostHoc />
      </>
    ),
  };
  const fewShot: Labelled = {
    key: 'few_shot',
    row: baseline.few_shot,
    label: (
      <>
        Base + schema + {examples} examples <PostHoc />
      </>
    ),
  };
  const seeds = baseline.seeds.map(
    (row): Labelled => ({
      key: `seed-${JSON.stringify(row.seed.v)}`,
      row,
      label: (
        <>
          Fine-tuned, seed <Num kind="int" link={false} node={row.seed} />
        </>
      ),
    }),
  );
  const rows = [base, schema, fewShot, ...seeds];
  // One legend for every bar: the parts some ladder row holds, as the
  // approved prototype draws it.
  const legend = (
    <Legend
      cap={baseline.token_cap}
      parts={PARTS.filter((part) => rows.some(({row}) => count(part.pick(row)) > 0))}
    />
  );
  const levels: readonly Level[] = [
    {key: 'base', name: base.label, rate: baseline.base.rate, rung: null},
    {key: 'schema', name: schema.label, rate: baseline.schema.rate, rung: rungs.schema_minus_base},
    {
      key: 'few_shot',
      name: fewShot.label,
      rate: baseline.few_shot.rate,
      rung: rungs.few_shot_minus_schema,
    },
    {
      key: 'sft_mean',
      name: 'Fine-tuned, seed mean',
      rate: baseline.sft_mean.rate,
      rung: rungs.sft_mean_minus_few_shot,
    },
  ];
  return (
    <section aria-labelledby="tr-steps" className="tr-sec">
      <h2 id="tr-steps">
        Cheaper fixes first <PostHoc />
      </h2>
      <p className="tr-sec-lede">
        Strong exact over the <Num kind="int" node={baseline.cases} /> ready test cases in{' '}
        <Str node={baseline.condition} />: the base model{' '}
        <Num kind="rate" node={baseline.base.rate.value} />, held to the answer&apos;s schema{' '}
        <Num kind="rate" node={baseline.schema.rate.value} />, with{' '}
        <Num kind="int" node={baseline.examples} /> training examples in every prompt as well{' '}
        <Num kind="rate" node={baseline.few_shot.rate.value} />, and fine-tuned, with neither,{' '}
        <Num kind="rate" node={baseline.sft_mean.rate.value} />. By the registered rule the
        schema&apos;s step reads <ReadingTag node={rungs.schema_minus_base.reading} />, the
        examples&apos; step <ReadingTag node={rungs.few_shot_minus_schema.reading} />, and
        fine-tuning against both fixes together{' '}
        <ReadingTag node={rungs.sft_mean_minus_few_shot.reading} />.
      </p>
      <Strip levels={levels} />
      <p className="tr-sub">
        The two fixes that need no training, tried on the base model: decoding held to the
        answer&apos;s JSON schema, <Str node={baseline.response_schema} />, and then{' '}
        <Num kind="int" node={baseline.examples} /> training examples in every prompt as well. Both
        rows were designed after every base and fine-tuned test score was known, so they are
        labelled post hoc. Each question is one row minus another, paired by case over the{' '}
        <Num kind="int" node={baseline.cases} /> ready test cases with the same{' '}
        <Num kind="int" node={bootstrap.resamples} /> resamples, seed{' '}
        <Num kind="int" node={bootstrap.seed} />, as every row above. A step reads as a gain or a
        loss only when its interval excludes zero and at least{' '}
        <Num kind="int" node={bootstrap.min_discordant_cases} /> cases are discordant. Open a
        question for the rule&apos;s two tests and where each row&apos;s answers went.
      </p>
      <ol aria-labelledby="tr-steps" className="tr-ladder tr-qs">
        <Question
          baseline={baseline}
          legend={legend}
          mixes={[schema, base]}
          name="schema_minus_base"
          rung={rungs.schema_minus_base}
          title="Does holding decoding to the schema help?"
          what="Base + schema minus base"
        />
        <Question
          baseline={baseline}
          legend={legend}
          mixes={[fewShot, schema]}
          name="few_shot_minus_schema"
          rung={rungs.few_shot_minus_schema}
          title={<>Do {examples} training examples help on top of it?</>}
          what={<>Base + schema + {examples} examples minus base + schema</>}
        />
        <Question
          baseline={baseline}
          legend={legend}
          mixes={[...seeds, fewShot]}
          name="sft_mean_minus_few_shot"
          rung={rungs.sft_mean_minus_few_shot}
          title="Does fine-tuning beat both fixes?"
          what={<>Fine-tuned seed mean minus base + schema + {examples} examples</>}
        />
      </ol>
      <p aria-hidden="true" className="tr-axis tr-axis-q">
        <span />
        <span>
          <span>every case worse</span>
          <span>no change</span>
          <span>every case better</span>
        </span>
        <span />
      </p>
      <RowTables baseline={baseline} rows={rows} />
    </section>
  );
}
