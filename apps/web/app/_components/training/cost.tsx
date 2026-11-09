/**
 * @fileoverview What these runs cost: the self-served sessions' bills.
 *
 * Server-rendered from training.json's cost block, from
 * docs/results/sft-v1/cost.json: the cost per thousand requests first, then
 * the sessions' requests, bills and GPU time, one row per session, and what
 * the counts leave out (docs/protocol.md, Training rules, amended
 * 2026-11-09). Money stays the cost file's decimal strings, shown to the
 * cent through fmt's usd kind. The page never sums: every total is the
 * file's, and every number is a sourced value.
 */

import type {ReactNode} from 'react';

import {Num, Str, Usd} from '@/lib/sourced';
import type {Cost} from '@/lib/training-data';

/** The passes reported not run that a session sent, counted by prompt. */
type Unread = NonNullable<Cost['sessions'][number]['unread']>;

interface SessionCostProps {
  readonly cost: Cost;
  /** The passes reported not run, whose requests the GPU time leaves out. */
  readonly unread: Unread;
}

/** The cost per thousand requests, each session's bill and what is left out. */
export function SessionCost({cost, unread}: SessionCostProps): ReactNode {
  const {total} = cost;
  return (
    <section aria-labelledby="tr-cost" className="tr-sec">
      <h2 id="tr-cost">What these runs cost</h2>
      <p className="tr-cost-big">
        <span className="m">
          USD <Usd node={total.usd_per_1000_requests} />
        </span>{' '}
        per thousand requests
      </p>
      <p className="tr-sub">
        <Num kind="int" node={total.requests} /> requests in{' '}
        <Num kind="int" node={cost.session_count} /> sessions on Modal, billed USD{' '}
        <Usd node={total.bill_usd} />; the GPU time the committed runs&apos; latencies sum to,{' '}
        <Num kind="num" node={total.gpu_hours} /> hours, which leaves out the{' '}
        <Num kind="int" node={unread.requests} /> requests of the passes reported not run, comes
        to USD <Usd node={total.gpu_usd} /> at the GPU&apos;s USD{' '}
        <Usd node={cost.usd_per_gpu_hour} /> an hour. The sessions sent the schema and example rows
        and the repair turn, dev passes included.
      </p>
      <div className="tr-table-wrap">
        <table className="tr-table tr-nowrap">
          <caption className="lab" style={{captionSide: 'top', textAlign: 'left'}}>
            Each session&apos;s Modal bill
          </caption>
          <thead>
            <tr>
              <th scope="col">Session</th>
              <th scope="col">What it sent</th>
              <th className="tr-n" scope="col">
                Requests
              </th>
              <th className="tr-n" scope="col">
                GPU hours
              </th>
              <th className="tr-n" scope="col">
                Bill
              </th>
            </tr>
          </thead>
          <tbody>
            {cost.sessions.map((session) => (
              <tr key={session.date.t}>
                <th scope="row">
                  <Str node={session.date} />
                </th>
                <td className="tr-wrap">
                  <Num kind="int" node={session.runs} /> runs
                  {session.unread === null ? null : (
                    <>
                      , and <Num kind="int" node={session.unread.count} /> test passes reported
                      not run, counted as <Num kind="int" node={session.unread.requests} />{' '}
                      requests
                    </>
                  )}
                </td>
                <td className="tr-n">
                  <Num kind="int" node={session.requests} />
                </td>
                <td className="tr-n">
                  <Num kind="num" node={session.gpu_hours} />
                </td>
                <td className="tr-n">
                  USD <Usd node={session.bill_usd} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tr-note">
        A bill runs from the server&apos;s start to its stop, so it holds start-up and idle time
        that the GPU time the committed runs&apos; latencies sum to does not. An app of{' '}
        <Str node={cost.excluded.date} /> billed USD <Usd node={cost.excluded.bill_usd} /> and
        sent none of these requests, so the cost file names it and leaves it out. The schema
        probes and the requests that woke the server were billed and are not among the counted
        requests. Amounts are shown to the cent; the cost file holds them exact.
      </p>
    </section>
  );
}
