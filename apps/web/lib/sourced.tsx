/**
 * @fileoverview The only way a value reaches a page.
 *
 * <Num> and <Str> render one sourced node from apps/web/data. The markup
 * keeps the node's source op (data-src), its value as JSON (data-v) and the
 * formatting kind (data-fmt), so tests/consistency.spec.ts can re-derive the
 * value from the committed files and check both the value and the text. A
 * number also links to the committed file it comes from, at the commit the
 * site was built from; a client island renders the same markup without the
 * link through lib/sourced-text.tsx. <Term> renders a reviewed name that
 * holds a digit, such as SHA-256. ESLint bans digits typed into markup, so
 * a hand-written number has no other way onto a page.
 */

import type {ReactNode} from 'react';

import {loadSite, sourcePaths} from './data';
import type {NumNode, Src, StrNode} from './data';
import {fmt} from './fmt';
import {REPOSITORY} from './site';
import {NumText, StrText} from './sourced-text';
import type {NumKind} from './sourced-text';
import type {TermName} from './terms';

/**
 * Returns the GitHub permalink prefix of the repository's files at the
 * source commit; a file's path follows it with each segment encoded.
 */
export function repositoryBlob(): string {
  return `${REPOSITORY}/blob/${encodeURIComponent(loadSite().source_commit)}/`;
}

/** Returns the GitHub permalink of a repository file at the source commit. */
export function repositoryFile(file: string): string {
  return repositoryBlob() + file.split('/').map(encodeURIComponent).join('/');
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
  readonly kind: NumKind;
  /** False where many numbers stand close, as on the ladder's axis. */
  readonly link?: boolean;
}

/** Renders a sourced number, boolean or integer list, linked to its file. */
export function Num({node, kind, link = true}: NumProps): ReactNode {
  const value = <NumText kind={kind} node={node} />;
  const href = link ? permalink(node.src) : null;
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
  return <StrText node={node} />;
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

/**
 * Renders a scored outcome code, such as silent_wrong, as the protocol's
 * words (fmt's outcome kind). The node keeps the code in data-v, so the
 * consistency test re-derives it, and a code fmt does not know fails the
 * build.
 */
export function Outcome({node}: StrProps): ReactNode {
  return (
    <span data-fmt="outcome" data-src={JSON.stringify(node.src)} data-v={JSON.stringify(node.t)}>
      {fmt(node.t, 'outcome')}
    </span>
  );
}

/**
 * Renders a SHA-256 digest as its first twelve hex digits in monospace
 * (fmt's digest kind), linked to the file it comes from. The full digest
 * stays in data-v and in the title, which a pointer shows on hover; the
 * consistency test checks both against the file.
 */
export function Digest({node}: StrProps): ReactNode {
  const value = (
    <code
      className="dg"
      data-fmt="digest"
      data-src={JSON.stringify(node.src)}
      data-v={JSON.stringify(node.t)}
      title={node.t}
    >
      {fmt(node.t, 'digest')}
    </code>
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

interface WordProps {
  readonly node: StrNode;
  readonly kind: 'frame_kind' | 'join';
}

/**
 * Renders a code as the fixed words fmt() gives its kind: a frame's kind,
 * or an IR's root operator. The node keeps the code in data-v, and a code
 * fmt does not know fails the build.
 */
export function Word({node, kind}: WordProps): ReactNode {
  return (
    <span data-fmt={kind} data-src={JSON.stringify(node.src)} data-v={JSON.stringify(node.t)}>
      {fmt(node.t, kind)}
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
