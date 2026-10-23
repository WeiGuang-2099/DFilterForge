/**
 * @fileoverview One exhibit: a test case whose answers the tail turns.
 *
 * Server-rendered from exhibits.json. The head names the case and the
 * witnesses that turn its answers. For each answer come its request, the
 * reference, the answer and both verdicts; beside them the case's reading
 * with the answer's addendum, the witnesses' notes and the receipt; under
 * them the figure: the verdict stamp, the frame tapes, the frame readout
 * and the killing frames, one probe at a time. Every answer's blocks and
 * every probe's packet list are in the HTML, each tagged with the answers
 * it shows (data-ans, a list where answers share their tapes) and its
 * probe (data-pr), and both verifiers' parts too (xh-only-tail,
 * xh-only-alone); the exhibit's island shows one of each (controls.tsx).
 */

import type {ReactNode} from 'react';

import type {StrNode} from '@/lib/data';
import type {Exhibit, ExhibitAnswer, Replay} from '@/lib/exhibits-data';
import {Digest, Num, Outcome, repositoryFile, Str, Term} from '@/lib/sourced';
import {StrText} from '@/lib/sourced-text';

import {ExhibitRoot, ExhibitView, FrameReadout, Picks, ProbeSwitch, TapesArea} from './controls';
import {Listed} from './parts';
import {PacketList, stateGroups, TapeKey, Tapes} from './tapes';
import {ANSWER_WORDS, CONTRACT_WORDS, RETRIEVAL_WORDS} from './words';

const WITNESSES = 'src/dfilterforge/witnesses.py';

/** Codes such as witness names, in monospace, joined as Listed joins them. */
function Codes({nodes}: {readonly nodes: readonly StrNode[]}): ReactNode {
  return (
    <Listed>
      {nodes.map((node) => (
        <code key={JSON.stringify(node.src)}>
          <Str node={node} />
        </code>
      ))}
    </Listed>
  );
}

/** The model ids of an exhibit's answers, each once. */
function models(exhibit: Exhibit): StrNode[] {
  const seen = new Set<string>();
  return exhibit.answers.flatMap((answer) => {
    const fresh = !seen.has(answer.model_id.t);
    seen.add(answer.model_id.t);
    return fresh ? [answer.model_id] : [];
  });
}

/** An answer's request, filters and verdicts. */
function AnswerText({answer}: {readonly answer: ExhibitAnswer}): ReactNode {
  return (
    <>
      <blockquote className="xh-req">
        <Str node={answer.request} />
        <cite>
          <StrText node={answer.item_id} />, <StrText node={answer.condition} />:{' '}
          {CONTRACT_WORDS[answer.contract.t]}, {RETRIEVAL_WORDS[answer.retrieval.t]}
        </cite>
      </blockquote>
      <dl className="xh-fl">
        <dt>Reference</dt>
        <dd>
          <code>
            <Str node={answer.reference} />
          </code>
        </dd>
        <dt>{ANSWER_WORDS[answer.contract.t]}</dt>
        <dd className="xh-ans">
          <code>
            <Str node={answer.filter} />
          </code>
        </dd>
        <dt>Verdicts</dt>
        <dd className="xh-vv">
          captures alone{' '}
          <b>
            <Outcome node={answer.alone} />
          </b>
          ; with the tail{' '}
          <b className="dn">
            <Outcome node={answer.tail} />
          </b>
        </dd>
      </dl>
    </>
  );
}

/** The readout's line before a frame is pointed at, for each verifier. */
function Resting({answer}: {readonly answer: ExhibitAnswer}): ReactNode {
  return (
    <>
      <p className="xh-only-tail">
        The answer and the labels part on <Num kind="int" node={answer.disagreeing} /> frames,
        every one in the tail. Point at a frame to read it.
      </p>
      <p className="xh-only-alone">
        On the captures alone each tape stops at its last benchmark frame. Point at a frame to
        read it.
      </p>
    </>
  );
}

interface ExhibitProps {
  readonly exhibit: Exhibit;
  readonly replay: Replay;
  /** The repository's file permalink prefix at the build's commit. */
  readonly blob: string;
}

/** One case's turned answers, its reading, its witnesses and its figure. */
export function ExhibitCard({exhibit, replay, blob}: ExhibitProps): ReactNode {
  const [heading, named] = [`${exhibit.case}-h`, `${exhibit.case}-case`];
  const {answers} = exhibit;
  const several = answers.length > 1;
  const groups = stateGroups(exhibit);
  return (
    <ExhibitRoot id={exhibit.case} labelledBy={heading} named={named}>
      <header className="xh-ex-head">
        <h3 id={heading}>
          <code id={named}>
            <Str node={exhibit.case_id} />
          </code>{' '}
          <span className="xh-ex-by">
            caught by <Codes nodes={exhibit.witnesses} />
          </span>
        </h3>
        <p className="xh-ex-count">
          <Num kind="int" node={exhibit.turned} /> {several ? 'answers' : 'answer'} the tail
          turns, from{' '}
          <Listed>
            {models(exhibit).map((node) => (
              <Str key={node.t} node={node} />
            ))}
          </Listed>
        </p>
      </header>
      <div className="xh-ex-text">
        {several ? (
          <Picks
            labels={answers.map((answer) => (
              <>
                <StrText node={answer.model_id} /> <StrText node={answer.condition} />{' '}
                <StrText node={answer.item_id} />
              </>
            ))}
          />
        ) : null}
        {answers.map((answer, j) => (
          <div className="xh-ex-answer" data-ans={j} key={answer.receipt}>
            <AnswerText answer={answer} />
          </div>
        ))}
      </div>
      <div className="xh-ex-side">
        <p className="xh-reading">
          <Str node={exhibit.reading} />
          {answers.map((answer, j) =>
            answer.addendum === null ? null : (
              <span data-ans={j} key={answer.receipt}>
                {' '}
                <Str node={answer.addendum} />
              </span>
            ),
          )}
        </p>
        <div className="xh-wnote">
          {exhibit.notes.map((note) => (
            <p key={JSON.stringify(note.note.src)}>
              <Codes nodes={note.witnesses} />: <Str node={note.note} />
            </p>
          ))}
          <p className="xh-wsrc">
            Quoted from the comments in <a href={repositoryFile(WITNESSES)}>{WITNESSES}</a>,
            written before any test answer was requested.
          </p>
        </div>
        {answers.map((answer, j) => (
          <p className="xh-rcpt" data-ans={j} key={answer.receipt}>
            <a href={blob + answer.receipt.split('/').map(encodeURIComponent).join('/')}>
              Receipt
            </a>
            <span>
              <Term name="SHA-256" /> <Digest node={answer.sha256} />
            </span>
            <a href={repositoryFile(exhibit.spec)}>Case specification</a>
          </p>
        ))}
      </div>
      <div className="xh-ex-fig">
        <div className="xh-fig-top">
          <ExhibitView />
          {answers.map((answer, j) => (
            <p className="xh-stamp" data-ans={j} key={answer.receipt}>
              <span className="xh-only-tail">
                <Outcome node={answer.tail} />
              </span>
              <span className="xh-only-alone">
                <Outcome node={answer.alone} />
              </span>
            </p>
          ))}
        </div>
        <TapesArea>
          {groups.map((group) => (
            <div
              className="xh-tapes-in"
              data-ans={group.answers.join(' ')}
              key={group.first.receipt}
            >
              <Tapes answer={group.first} probes={replay.probes} />
            </div>
          ))}
        </TapesArea>
        <TapeKey />
        <FrameReadout probes={replay.probes}>
          {answers.map((answer, j) => (
            <div data-ans={j} key={answer.receipt}>
              <Resting answer={answer} />
            </div>
          ))}
        </FrameReadout>
        <div className="xh-kills">
          <div className="xh-only-tail">
            <ProbeSwitch
              labels={replay.probes.map((probe) => (
                <StrText key={probe.probe_id.t} node={probe.probe_id} />
              ))}
            />
            {groups.map((group, g) =>
              group.first.probes.map((strip, p) => {
                const probe = replay.probes[p];
                return probe === undefined ? null : (
                  <div
                    data-ans={group.answers.join(' ')}
                    data-pr={p}
                    key={`${group.first.receipt} ${strip.probe_id.t}`}
                  >
                    <PacketList
                      caseId={exhibit.case_id}
                      id={`${exhibit.case}-pl-${String(g)}-${String(p)}`}
                      probe={probe}
                      strip={strip}
                    />
                  </div>
                );
              }),
            )}
          </div>
          {answers.map((answer, j) => (
            <p className="xh-only-alone xh-quiet" data-ans={j} key={answer.receipt}>
              On the captures alone no frame separates this answer from the reference: of the{' '}
              <Listed>
                {answer.probes.map((strip) => (
                  <Num key={strip.probe_id.t} kind="int" node={strip.benchmark_frames} />
                ))}
              </Listed>{' '}
              benchmark frames, every one agrees.
            </p>
          ))}
        </div>
      </div>
    </ExhibitRoot>
  );
}
