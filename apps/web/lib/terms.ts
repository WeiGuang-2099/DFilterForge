/**
 * @fileoverview The closed list of names that may show a digit outside a
 * sourced value.
 *
 * A digit on a page is either part of a value rendered from a committed file
 * or part of a name that holds a digit, such as SHA-256. Such a name is
 * rendered with <Term> from lib/sourced.tsx, which accepts only this list,
 * and the consistency sweep exempts a term element only when its whole text
 * is one of these entries. Every entry holds a letter, so none can be a bare
 * number. Adding an entry needs review: tests/lint-rules.spec.ts pins the
 * list.
 */

/** The reviewed names. */
export const TERMS = ['IPv4', 'SHA-256'] as const;

/** One reviewed name. */
export type TermName = (typeof TERMS)[number];
