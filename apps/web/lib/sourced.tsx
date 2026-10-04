/**
 * @fileoverview The only way a value reaches a page.
 *
 * <Num> and <Str> render one sourced node from apps/web/data. The markup
 * keeps the node's source op (data-src), its value as JSON (data-v) and the
 * formatting kind (data-fmt), so tests/consistency.spec.ts can re-derive the
 * value from the committed files and check both the value and the text. A
 * number also links to the committed file it comes from, at the commit the
 * site was built from. <Term> renders a reviewed name that holds a digit,
 * such as SHA-256. ESLint bans digits typed into markup, so a hand-written
 * number has no other way onto a page.
 */

import type {ReactNode} from 'react';

import {loadSite, sourcePaths} from './data';
import type {NumNode, Src, StrNode} from './data';
import {fmt} from './fmt';
import type {FmtKind} from './fmt';
import type {TermName} from './terms';

const REPOSITORY = 'https://github.com/WeiGuang-2099/DFilterForge';

/** Returns the GitHub permalink of a repository file at the source commit. */
export function repositoryFile(file: string): string {
  const encoded = file.split('/').map(encodeURIComponent).join('/');
  return `${REPOSITORY}/blob/${encodeURIComponent(loadSite().source_commit)}/${encoded}`;
}

/**
 * Returns the permalink of the one file a source reads, or null when it
 * reads several, as a sum over runs does; no single file holds that value.
 */
function permalink(source: Src): string | null {
  const files = new Set(sourcePaths(source));
  if (files.size !== 1) {
    return null;
  }
  const [file = ''] = files;
  return repositoryFile(file);
}

interface NumProps {
  readonly node: NumNode;
  // Leaves out fmt's string-only kinds, which throw on every value a NumNode
  // holds. A kind added to FMT_KINDS fails typecheck in tests/fmt.spec.ts
  // until it is either excluded here or listed in NUM_KIND_SAMPLES there.
  readonly kind: Exclude<FmtKind, 'text' | 'unmeasured' | 'split'>;
}

/** Renders a sourced number, boolean or integer list, linked to its file. */
export function Num({node, kind}: NumProps): ReactNode {
  const json = JSON.stringify(node.v);
  const value = (
    <data data-fmt={kind} data-src={JSON.stringify(node.src)} data-v={json} value={json}>
      {fmt(node.v, kind)}
    </data>
  );
  const href = permalink(node.src);
  return href === null ? (
    value
  ) : (
    <a className="num" href={href}>
      {value}
    </a>
  );
}

interface StrProps {
  readonly node: StrNode;
}

/** Renders a sourced string with its controls made visible. */
export function Str({node}: StrProps): ReactNode {
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

/**
 * Renders a scored summary's not_measured status as fixed words, never as
 * the status key (fmt's unmeasured kind). The node stays in data-src and
 * data-v, so the consistency test still re-derives the key, and a status
 * fmt does not know fails the build.
 */
export function Unmeasured({node}: StrProps): ReactNode {
  return (
    <span
      data-fmt="unmeasured"
      data-src={JSON.stringify(node.src)}
      data-v={JSON.stringify(node.t)}
    >
      {fmt(node.t, 'unmeasured')}
    </span>
  );
}

/**
 * Renders the split a scored summary records as the word that names its
 * round, such as "Test" in "Test repair round" (fmt's split kind). The node
 * stays in data-src and data-v, so the consistency test re-derives the
 * split from the summary, and a split fmt does not know fails the build.
 */
export function Split({node}: StrProps): ReactNode {
  return (
    <span data-fmt="split" data-src={JSON.stringify(node.src)} data-v={JSON.stringify(node.t)}>
      {fmt(node.t, 'split')}
    </span>
  );
}

interface TermProps {
  readonly name: TermName;
}

/** Renders one reviewed name from lib/terms.ts. */
export function Term({name}: TermProps): ReactNode {
  return <span data-term="">{name}</span>;
}
