/**
 * @fileoverview The exhibits page's two tables.
 *
 * Server-rendered from exhibits.json. The first table gives the cases only
 * the tail can score; the second each pool pass's counts, its turned
 * answers linked to their exhibits. Every value is a sourced node. On a
 * narrow screen the style sheet stacks each row into a block and shows
 * each value after its column's name (data-h), so no column is dropped and
 * no table scrolls sideways. A table laid out that way can lose its
 * semantics in some browsers, so every part states its role.
 */

import type {ReactNode} from 'react';

import {counted} from '@/lib/exhibits-data';
import type {Replay} from '@/lib/exhibits-data';
import {roleLabel} from '@/lib/roles';
import {Num, Outcome, repositoryFile, Str} from '@/lib/sourced';
import {StrText} from '@/lib/sourced-text';

import {Cell, Listed} from './parts';

// The column names of the cases only the tail can score.
const ONLY = {
  reference: 'Reference',
  frames: 'Labelled frames',
  answers: 'Answers',
  exact: 'Strong exact',
  shortcut: 'Shortcut',
  wrong: 'Silent-wrong',
} as const;

// The column names of the counts by model.
const BY = {
  answers: 'Answers',
  exact: 'Exact alone',
  wrong: 'Of those, wrong with the tail',
  shortcut: 'Shortcuts alone',
  unscorable: 'Not scorable alone',
  turned: 'Turned answers',
} as const;

/** A header cell over a column. */
function Head({className, children}: {
  readonly className?: string;
  readonly children: ReactNode;
}): ReactNode {
  return (
    <th className={className} role="columnheader" scope="col">
      {children}
    </th>
  );
}

/** The cases that label only witness frames, and their answers with the tail. */
export function TailOnly({replay}: {readonly replay: Replay}): ReactNode {
  const {tail_only: only, counts, alone} = replay;
  const first = only.cases[0]?.probes[0];
  return (
    <section aria-labelledby="xh-only-h" className="xh-sec">
      <h2 id="xh-only-h">
        <Num kind="int" node={counts.tail_only} /> cases only the tail can score
      </h2>
      <p className="xh-sub">
        These test cases label no benchmark frame: every frame they select is a witness. The
        scorer refuses a case whose label sets are all empty, so on the captures alone their{' '}
        <Num kind="int" node={alone.unscorable} /> answers cannot be scored. With the tail,{' '}
        <Num kind="int" node={only.tail.strong_exact} /> of them are strong exact,{' '}
        <Num kind="int" node={only.tail.shortcut} /> shortcuts and{' '}
        <Num kind="int" node={only.tail.silent_wrong} /> silent-wrong.
      </p>
      <div className="xh-tw">
        <table className="xh-t" role="table">
          <thead role="rowgroup">
            <tr role="row">
              <Head>Case and request</Head>
              <Head>{ONLY.reference}</Head>
              <Head>
                {ONLY.frames} on {first === undefined ? null : <Str node={first.probe_id} />}
              </Head>
              <Head className="xh-n">{ONLY.answers}</Head>
              <Head className="xh-n">{ONLY.exact}</Head>
              <Head className="xh-n">{ONLY.shortcut}</Head>
              <Head className="xh-n">{ONLY.wrong}</Head>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {only.cases.map((item) => {
              const probe = item.probes[0];
              return (
                <tr key={item.case} role="row">
                  <Cell>
                    <a href={repositoryFile(item.spec)}>
                      <code>
                        <Str node={item.case_id} />
                      </code>
                    </a>
                    <span className="xh-what">
                      <Str node={item.intent} />
                    </span>
                  </Cell>
                  <Cell head={ONLY.reference}>
                    <code>
                      <Str node={item.reference} />
                    </code>
                  </Cell>
                  <Cell head={ONLY.frames}>
                    {probe === undefined ? null : (
                      <span aria-hidden="true" className="xh-cl">
                        on <Str node={probe.probe_id} />
                      </span>
                    )}
                    <Listed>
                      {(probe?.expected ?? []).map((frame) => (
                        <span className="xh-nowrap" key={JSON.stringify(frame.n.src)}>
                          <code>
                            <Str node={frame.name} />
                          </code>{' '}
                          (<Num kind="int" link={false} node={frame.n} />)
                        </span>
                      ))}
                    </Listed>
                  </Cell>
                  <Cell className="xh-n" head={ONLY.answers}>
                    <Num kind="int" node={item.answers} />
                  </Cell>
                  <Cell className="xh-n" head={ONLY.exact}>
                    <Num kind="int" node={item.tail.strong_exact} />
                  </Cell>
                  <Cell className="xh-n" head={ONLY.shortcut}>
                    <Num kind="int" node={item.tail.shortcut} />
                  </Cell>
                  <Cell
                    className={counted(item.tail.silent_wrong, item.case) > 0 ? 'xh-n dn' : 'xh-n'}
                    head={ONLY.wrong}
                  >
                    <Num kind="int" node={item.tail.silent_wrong} />
                  </Cell>
                </tr>
              );
            })}
            <tr className="xh-tot" role="row">
              <th colSpan={3} role="rowheader" scope="row">
                All
              </th>
              <Cell className="xh-n" head={ONLY.answers}>
                <Num kind="int" node={alone.unscorable} />
              </Cell>
              <Cell className="xh-n" head={ONLY.exact}>
                <Num kind="int" node={only.tail.strong_exact} />
              </Cell>
              <Cell className="xh-n" head={ONLY.shortcut}>
                <Num kind="int" node={only.tail.shortcut} />
              </Cell>
              <Cell className="xh-n dn" head={ONLY.wrong}>
                <Num kind="int" node={only.tail.silent_wrong} />
              </Cell>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * Each pool pass's counts, and the answers the tail turns linked to their
 * exhibits. A turned answer that is a shortcut on the captures alone says
 * so, since the column before counts only the strong exact ones.
 */
export function ByModel({replay}: {readonly replay: Replay}): ReactNode {
  const {counts, alone} = replay;
  return (
    <section aria-labelledby="xh-model-h" className="xh-sec">
      <h2 id="xh-model-h">By model</h2>
      <p className="xh-sub">
        Each row is one hosted model&apos;s test pass, every condition together, in pool order.
        The answers the tail turns link to their exhibits.
      </p>
      <div className="xh-tw">
        <table className="xh-t" role="table">
          <thead role="rowgroup">
            <tr role="row">
              <Head>Model</Head>
              <Head className="xh-n">{BY.answers}</Head>
              <Head className="xh-n">{BY.exact}</Head>
              <Head className="xh-n">{BY.wrong}</Head>
              <Head className="xh-n">{BY.shortcut}</Head>
              <Head className="xh-n">{BY.unscorable}</Head>
              <Head>{BY.turned}</Head>
            </tr>
          </thead>
          <tbody role="rowgroup">
            {replay.rows.map((row) => {
              const turned = row.squares.flatMap((square) => {
                const exhibit =
                  square.turned === null ? undefined : replay.exhibits[square.turned.exhibit];
                return square.turned === null || exhibit === undefined
                  ? []
                  : [{square, exhibit: exhibit.case, answer: square.turned.answer}];
              });
              return (
                <tr key={row.run} role="row">
                  <th role="rowheader" scope="row">
                    <code>
                      <Str node={row.model_id} />
                    </code>
                    <span className="xh-what">
                      {roleLabel(row.role)}, <Str node={row.run_id} />
                    </span>
                  </th>
                  <Cell className="xh-n" head={BY.answers}>
                    <Num kind="int" node={row.answers} />
                  </Cell>
                  <Cell className="xh-n" head={BY.exact}>
                    <Num kind="int" node={row.alone.strong_exact} />
                  </Cell>
                  <Cell
                    className={counted(row.turned_exact, row.run) > 0 ? 'xh-n dn' : 'xh-n'}
                    head={BY.wrong}
                  >
                    <Num kind="int" node={row.turned_exact} />
                  </Cell>
                  <Cell className="xh-n" head={BY.shortcut}>
                    <Num kind="int" node={row.alone.shortcut} />
                  </Cell>
                  <Cell className="xh-n" head={BY.unscorable}>
                    <Num kind="int" node={row.alone.unscorable} />
                  </Cell>
                  <Cell className="xh-turned" head={BY.turned}>
                    {turned.length === 0 ? (
                      <span className="xh-what">none</span>
                    ) : (
                      <Listed>
                        {turned.map(({square, exhibit, answer}) => (
                          <span className="xh-nowrap" key={square.receipt}>
                            <a data-answer={answer} data-exhibit={exhibit} href={`#${exhibit}`}>
                              <StrText node={square.condition} /> <StrText node={square.item_id} />
                            </a>
                            {square.alone.t === 'shortcut' ? (
                              <>
                                {' '}
                                (<Outcome node={square.alone} />)
                              </>
                            ) : null}
                          </span>
                        ))}
                      </Listed>
                    )}
                  </Cell>
                </tr>
              );
            })}
            <tr className="xh-tot" role="row">
              <th role="rowheader" scope="row">
                All
              </th>
              <Cell className="xh-n" head={BY.answers}>
                <Num kind="int" node={counts.answers} />
              </Cell>
              <Cell className="xh-n" head={BY.exact}>
                <Num kind="int" node={alone.strong_exact} />
              </Cell>
              <Cell className="xh-n dn" head={BY.wrong}>
                <Num kind="int" node={replay.turned_exact} />
              </Cell>
              <Cell className="xh-n" head={BY.shortcut}>
                <Num kind="int" node={alone.shortcut} />
              </Cell>
              <Cell className="xh-n" head={BY.unscorable}>
                <Num kind="int" node={alone.unscorable} />
              </Cell>
              <Cell head={BY.turned}>
                <Num kind="int" node={replay.turned} /> turned,{' '}
                <Num kind="int" node={replay.turned_shortcut} /> of them a shortcut
              </Cell>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
