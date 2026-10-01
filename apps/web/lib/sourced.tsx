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
  readonly kind: Exclude<FmtKind, 'text'>;
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

interface TermProps {
  readonly name: TermName;
}

/** Renders one reviewed name from lib/terms.ts. */
export function Term({name}: TermProps): ReactNode {
  return <span data-term="">{name}</span>;
}
