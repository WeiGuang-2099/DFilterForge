/**
 * @fileoverview The methodology page's judge study block.
 *
 * Server-rendered from methodology.json's judge: the lead, the figure and
 * the closing text. The figure draws one square per silent-wrong test
 * answer, a row per pool pass in pool order, the judge's own pass's row set
 * apart. A square carries its verdict in each mode as a letter, c rated
 * correct (a false acceptance) or i rated incorrect, in data-p for the
 * request alone and data-s with the reference filter, which the style
 * sheet draws under the island's data-mode (judge-island.tsx). Every count
 * for both modes, and one detail block per answer with its sourced values,
 * is in this HTML; the island only shows one, at first the first false
 * acceptance from the request alone. The block names a square, which is
 * labelled by its block's condition and item and its verdict in the active
 * mode. lib/judge-check.ts fails the build unless the squares are what the
 * counts say. No sentence compares the passes or the modes.
 */

import type {CSSProperties, ReactNode} from 'react';

import type {Judge, NumNode} from '@/lib/data';
import {checkJudge, counted, letter, MODES} from '@/lib/judge-check';
import type {JudgeAnswer as Answer, JudgeRow as Row, Letter, Mode} from '@/lib/judge-check';
import {Num, repositoryFile, Str} from '@/lib/sourced';

import {JudgeFigure} from './judge-island';

// What the switch, each detail block and the quiet line call each mode.
const MODE_WORDS: Readonly<Record<Mode, string>> = {
  primary: 'Request alone',
  secondary: 'With the reference filter',
};
const QUIET_OPENING: Readonly<Record<Mode, string>> = {
  primary: 'From the request alone',
  secondary: 'With the reference filter',
};
// A verdict letter in words, in each detail block and a square's name.
const RATED_WORDS: Readonly<Record<Letter, string>> = {
  c: 'rated correct, a false acceptance',
  i: 'rated incorrect',
};

const JUDGE_NOTE = 'docs/decisions/judge-study.md';
const TABLE = 'docs/results/judge-v2/table.json';

function Count({node, link = true}: {readonly node: NumNode; readonly link?: boolean}) {
  return <Num kind="int" link={link} node={node} />;
}

/** The judge's own model, named where its answers are listed apart. */
function Own(): ReactNode {
  return <span className="jd-own">the judge&apos;s own model</span>;
}

/** The two verdicts in words; the style sheet marks the active mode's. */
function Verdicts({answer, where}: {readonly answer: Answer; readonly where: string}) {
  return (
    <p className="jd-dv">
      {MODES.map((mode) => (
        <span data-line={mode} key={mode}>
          {MODE_WORDS[mode]}:{' '}
          {letter(answer, mode, where) === 'c' ? (
            <b className="dn">{RATED_WORDS.c}</b>
          ) : (
            <b>{RATED_WORDS.i}</b>
          )}
        </span>
      ))}
    </p>
  );
}

interface PlacedProps {
  readonly row: Row;
  readonly answer: Answer;
  /** The square's place across the rows. */
  readonly at: number;
  /** The square's place in its row. */
  readonly nth: number;
}

/** Where a build failure names an answer. */
function answerAt(at: number): string {
  return `methodology.json.judge.rows answer ${String(at)}`;
}

/** One answer's detail block, hidden until its square is read out. */
function Detail({row, answer, at}: PlacedProps): ReactNode {
  const where = answerAt(at);
  const frames = counted(answer.disagreeing, where);
  return (
    <div className="jd-d" data-d={at}>
      <p className="jd-dh">
        <b>
          <Str node={row.model_id} />
        </b>
        {row.self ? <Own /> : null}
        <span className="jd-dq" id={`jd-n-${at}`}>
          <Str node={answer.condition} /> <Str node={answer.item_id} />
        </span>
        <span>
          case <Str node={answer.case_id} />
        </span>
      </p>
      <Verdicts answer={answer} where={where} />
      <dl className="jd-dl">
        <dt>{answer.typed ? 'Filter that ran, compiled from its IR' : 'Filter that ran'}</dt>
        <dd>
          <code>
            <Str node={answer.filter} />
          </code>
        </dd>
        <dt>Reference filter</dt>
        <dd>
          <code>
            <Str node={answer.reference} />
          </code>
        </dd>
        <dt>Where tshark parts them</dt>
        <dd>
          <Count link={false} node={answer.disagreeing} /> {frames === 1 ? 'frame' : 'frames'} of
          the scored probes
        </dd>
        <dt>Receipt</dt>
        <dd>
          <a href={repositoryFile(answer.receipt)}>the scored answer&apos;s receipt</a>
        </dd>
      </dl>
    </div>
  );
}

/** One square, drawn by its two letters and named by its block. */
function Square({answer, at, nth, held}: PlacedProps & {readonly held: boolean}): ReactNode {
  const where = answerAt(at);
  const letters = {p: letter(answer, 'primary', where), s: letter(answer, 'secondary', where)};
  return (
    <button
      aria-labelledby={`jd-n-${at} jd-q-${at}`}
      aria-pressed={held}
      className="jd-q"
      data-p={letters.p}
      data-q={at}
      data-s={letters.s}
      id={`jd-q-${at}`}
      style={{'--i': nth} as CSSProperties}
      tabIndex={at === 0 ? 0 : -1}
      type="button"
    >
      <span className="jd-vh" data-m="primary">
        {RATED_WORDS[letters.p]}
      </span>
      <span className="jd-vh" data-m="secondary">
        {RATED_WORDS[letters.s]}
      </span>
    </button>
  );
}

/** A row's count for each mode; the style sheet shows the active one. */
function RowCount({row}: {readonly row: Row}): ReactNode {
  return (
    <span className="jd-n">
      {MODES.map((mode) => (
        <span data-m={mode} key={mode}>
          <b>
            <Count link={false} node={row.rated_correct[mode]} />
          </b>{' '}
          of <Count link={false} node={row.silent_wrong} /> rated correct
        </span>
      ))}
    </span>
  );
}

/**
 * The fewest columns, at least `least`, that leave no row ending on a line
 * with a single square.
 */
function columnsFor(lengths: readonly number[], least: number): number {
  let columns = least;
  while (lengths.some((length) => length > columns && length % columns === 1)) {
    columns += 1;
  }
  return columns;
}

/** The squares in rows, the key, the readout and the quiet line. */
function Figure({judge}: {readonly judge: Judge}): ReactNode {
  const lengths = judge.rows.map((row) => row.answers.length);
  const widest = Math.max(...lengths, 1);
  const columns = {
    '--c-wide': widest,
    '--c-mid': columnsFor(lengths, Math.ceil(widest / 2)),
    '--c-narrow': columnsFor(lengths, Math.ceil(widest / 3)),
  } as CSSProperties;
  let next = 0;
  const placed = judge.rows.map((row) =>
    row.answers.map((answer, nth) => ({row, answer, nth, at: next++})),
  );
  // The readout opens on the first false acceptance from the request alone.
  const first =
    placed.flat().find(({answer, at}) => letter(answer, 'primary', answerAt(at)) === 'c')?.at ??
    null;
  return (
    <JudgeFigure initial={first} labels={MODE_WORDS}>
      <p className="jd-cap">
        One square per silent-wrong test answer, a row per answering model in the pool&apos;s
        order, the judge&apos;s own model&apos;s row set apart. Point at a square to read its
        answer below, or tab to the squares and move with the arrow keys; press one to keep it.
      </p>
      <ul className="jd-key">
        {(['correct', 'incorrect'] as const).map((rating) => (
          <li key={rating}>
            <span aria-hidden="true" className={rating === 'correct' ? 'jd-sw jd-sw-c' : 'jd-sw'} />
            <span>
              {rating === 'correct' ? 'Rated correct, a false acceptance:' : 'Rated incorrect:'}
            </span>{' '}
            {MODES.map((mode) => (
              <b data-m={mode} key={mode}>
                <Count link={false} node={judge.modes[mode].all.silent_wrong[rating]} />
              </b>
            ))}
          </li>
        ))}
      </ul>
      <div className="jd-rows" style={columns}>
        {judge.rows.map((row, index) => (
          <div
            className={row.self ? 'jd-row jd-self' : 'jd-row'}
            key={row.run}
            style={{'--r': index} as CSSProperties}
          >
            <p className="jd-who">
              <span className="jd-id" id={`jd-r-${row.run}`}>
                <code>
                  <Str node={row.model_id} />
                </code>
                {row.self ? <Own /> : null}
              </span>
              <RowCount row={row} />
            </p>
            <div aria-labelledby={`jd-r-${row.run}`} className="jd-sqs" role="group">
              {(placed[index] ?? []).map((each) => (
                <Square held={each.at === first} key={each.at} {...each} />
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="jd-detail">
        <p className="jd-hint">
          A square&apos;s answer is read out here: its model, condition, item and case, the
          judge&apos;s verdict in each mode, the two filters, where tshark parts them and the
          receipt.
        </p>
        <div aria-live="polite">
          {placed.flat().map((each) => (
            <Detail key={each.at} {...each} />
          ))}
        </div>
      </div>
      {MODES.map((mode) => {
        const {all, self} = judge.modes[mode];
        return (
          <p className="jd-quiet" data-m={mode} key={mode}>
            {QUIET_OPENING[mode]}, the judge rated{' '}
            <b>
              <Count node={all.strong_exact.incorrect} />
            </b>{' '}
            of the <Count node={all.strong_exact.answers} /> strong-exact answers incorrect,{' '}
            <Count node={self.strong_exact.incorrect} /> of them among its own model&apos;s{' '}
            <Count node={self.strong_exact.answers} />. Strong exact holds on three probes, so
            that is disagreement, not error.
          </p>
        );
      })}
    </JudgeFigure>
  );
}

/** The judge study: its lead, the figure, the method and the limits. */
export function JudgeStudy({judge}: {readonly judge: Judge}): ReactNode {
  checkJudge(judge);
  const {primary, secondary} = judge.modes;
  return (
    <>
      <p className="mth-lead">
        <span className="dn">
          <Count node={primary.headline.silent_wrong_rated_correct} />
        </span>{' '}
        of the <Count node={primary.headline.silent_wrong} /> silent-wrong test answers rated
        correct, <Count node={primary.headline.self_silent_wrong_rated_correct} /> of the{' '}
        <Count node={primary.headline.self_silent_wrong} /> the judge&apos;s own model wrote
      </p>
      <p>
        Rated by <code><Str node={judge.model_id} /></code>, an LLM judge, from each
        answer&apos;s request and the filter that ran. tshark holds a probe frame that disproves
        every one of these answers, so each one rated correct is a false acceptance. Shown the
        reference filter as well, the judge rated{' '}
        <Count node={secondary.headline.silent_wrong_rated_correct} /> of the{' '}
        <Count node={secondary.headline.silent_wrong} /> correct,{' '}
        <Count node={secondary.headline.self_silent_wrong_rated_correct} /> of its own
        model&apos;s <Count node={secondary.headline.self_silent_wrong} />.
      </p>
      <Figure judge={judge} />
      <p>
        The judge read each answer&apos;s request and user assumptions, as the answering model saw
        them, and the filter that ran, compiled from the answer&apos;s IR in a typed condition;
        with the reference filter it also read the item&apos;s reference, named as a filter that
        selects exactly the requested packets. It rated all <Count node={judge.answers} /> answers
        of the Disproof Reel&apos;s test pool that ran on a ready case, in{' '}
        <Count node={judge.requests_per_mode} /> requests per mode, one per distinct item and
        filter, and no silent-wrong answer went without a verdict. The{' '}
        <a href={repositoryFile(JUDGE_NOTE)}>judge note</a> registered the study before any judge
        request; the <a href={repositoryFile(TABLE)}>table</a>, which CI rebuilds from the
        published replies, holds every count.
      </p>
      <p>
        One judge gave these verdicts, with thinking off and through one provider, and a request
        sent again need not get the same verdict; the counts are over answers, not cases, with no
        interval, say nothing about the answering models, and keep the judge&apos;s own
        model&apos;s answers apart, since a judge may favour its own style.
      </p>
    </>
  );
}
