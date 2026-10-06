/**
 * @fileoverview The counterexample card of the repair turn as a table.
 *
 * A frames card is the JSON the counterexample arm sent: for each frame of
 * the feedback probe where the first answer and the labels disagree, its
 * number, whether it should match and whether the answer matched it, and
 * its header fields. The table shows one row per field and one column per
 * frame. Each value is a sourced node into the card's text (the exporter's
 * json op), and the field names are a closed list, so a field the list
 * does not name fails the build instead of reaching the page unnamed.
 */

import {Fragment} from 'react';

import type {Reel} from '@/lib/reel-data';
import {Num, Str} from '@/lib/sourced';

type Turn = NonNullable<NonNullable<Reel['repair']>['turn']>;
type CardFrame = NonNullable<Turn['card_frames']>[number];
type CardNode = CardFrame[number]['value'][number];

// The fields a frames card may hold, in the table's order: the frame and
// its two verdicts, then the header fields SHOWN_FIELDS in
// src/dfilterforge/counterexample.py lets a card show.
const FIELDS = [
  'frame',
  'should_match',
  'answer_matched',
  'ip.src',
  'ip.dst',
  'ip.ttl',
  'ip.dsfield.ecn',
  'tcp.srcport',
  'tcp.dstport',
  'tcp.flags',
  'tcp.len',
  'udp.srcport',
  'udp.dstport',
  'dns.flags.response',
  'dns.flags.rcode',
  'dns.qry.type',
] as const;

/** One value: a string, a yes or no, or an integer; a list joined. */
function Value({nodes}: {readonly nodes: readonly CardNode[]}) {
  return nodes.map((node, at) => (
    <Fragment key={JSON.stringify(node.src)}>
      {at === 0 ? null : ', '}
      {'t' in node ? (
        <Str node={node} />
      ) : (
        <Num kind={typeof node.v === 'boolean' ? 'bool' : 'int'} node={node} />
      )}
    </Fragment>
  ));
}

/** The card's frames as a field-by-frame table. */
export function CardTable({frames}: {readonly frames: readonly CardFrame[]}) {
  const known: ReadonlySet<string> = new Set(FIELDS);
  const unknown = frames.flat().find((field) => !known.has(field.name));
  if (unknown !== undefined) {
    throw new Error(`card: no row for the card field ${JSON.stringify(unknown.name)}`);
  }
  const rows = FIELDS.filter((name) => frames.some((frame) => frame.some((f) => f.name === name)));
  return (
    <table aria-label="The counterexample card, field by frame" className="cx">
      <tbody>
        {rows.map((name) => (
          <tr className={name === 'frame' ? 'cx-n' : undefined} key={name}>
            <th scope="row">{name}</th>
            {frames.map((frame, at) => {
              const field = frame.find((each) => each.name === name);
              return <td key={at}>{field === undefined ? '-' : <Value nodes={field.value} />}</td>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
