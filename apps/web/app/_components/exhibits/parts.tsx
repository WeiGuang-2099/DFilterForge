/**
 * @fileoverview Parts the exhibits page's modules share: values joined in
 * prose, and a table's data cell.
 */

import {Fragment} from 'react';
import type {ReactNode} from 'react';

/** Sourced strings joined by commas and a last "and". */
export function Listed({children}: {readonly children: readonly ReactNode[]}): ReactNode {
  return children.map((child, index) => (
    <Fragment key={index}>
      {index === 0 ? null : index === children.length - 1 ? ' and ' : ', '}
      {child}
    </Fragment>
  ));
}

/**
 * A data cell. On a narrow screen the page's style sheet stacks a table's
 * rows and shows the cell's column name (head, as data-h) before its value;
 * the header row names the column for a screen reader. The cell states its
 * role, since a table laid out that way can lose its semantics in some
 * browsers.
 */
export function Cell({head, className, children}: {
  readonly head?: string;
  readonly className?: string;
  readonly children: ReactNode;
}): ReactNode {
  return (
    <td className={className} data-h={head} role="cell">
      {children}
    </td>
  );
}
