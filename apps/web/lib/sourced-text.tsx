/**
 * @fileoverview The markup of a sourced value, without its link.
 *
 * <Num> and <Str> in lib/sourced.tsx render through these, and a client
 * island renders the same markup with them: a number's link names the
 * build's source commit, which only the server reads. The markup keeps the
 * node's source op (data-src), its value as JSON (data-v) and the
 * formatting kind (data-fmt), which tests/consistency.spec.ts re-derives.
 */

import type {ReactNode} from 'react';

import type {NumNode, StrNode} from './data';
import {fmt} from './fmt';
import type {FmtKind} from './fmt';

// The kinds that show a string: as written, as fixed words for a code, or
// as a digest's leading digits.
type WordKind = 'text' | 'unmeasured' | 'split' | 'outcome' | 'frame_kind' | 'join' | 'digest';

/**
 * The kinds a number node can take. It leaves out fmt's string-only kinds,
 * which throw on every value a NumNode holds; a kind added to FMT_KINDS
 * fails typecheck in tests/fmt.spec.ts until it is either excluded here or
 * listed in NUM_KIND_SAMPLES there.
 */
export type NumKind = Exclude<FmtKind, WordKind>;

/** Renders a sourced number, boolean or integer list. */
export function NumText({node, kind}: {readonly node: NumNode; readonly kind: NumKind}): ReactNode {
  const json = JSON.stringify(node.v);
  return (
    <data data-fmt={kind} data-src={JSON.stringify(node.src)} data-v={json} value={json}>
      {fmt(node.v, kind)}
    </data>
  );
}

/** Renders a sourced string with its controls made visible. */
export function StrText({node}: {readonly node: StrNode}): ReactNode {
  return (
    <span
      data-cap={node.cap}
      data-fmt="text"
      data-src={JSON.stringify(node.src)}
      data-v={JSON.stringify(node.t)}
    >
      {fmt(node.t, 'text')}
    </span>
  );
}
