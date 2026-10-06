/**
 * @fileoverview The site's only formatter: turns a sourced value into text.
 *
 * Every rendered value passes through fmt() with a kind that the page names
 * and that the markup records as data-fmt, so the consistency test formats
 * the value it re-derives from the committed files the same way and compares
 * the text. fmt never rounds, scales, divides or localizes: a number is shown
 * as the committed file holds it, in the shortest form that reads back to
 * the same value. ESLint bans the number-formatting APIs everywhere else.
 */

import {visible} from './visible';

/** The kinds fmt() knows, as data-fmt records them. */
export const FMT_KINDS = ['int', 'num', 'bool', 'ints', 'text', 'unmeasured', 'split'] as const;

// What a scored summary's not_measured status keys say on a page. A key is
// never shown as written: the scorer writes not_run for a measurement no
// round has made yet, while docs/protocol.md reserves "not run" for a run
// ruled not run, so the words are those of the "Not measured yet" section
// of docs/decisions/repair-round.md. A status not listed here fails the
// build.
const UNMEASURED: Readonly<Record<string, string>> = {
  not_run: 'not measured yet',
};

// What a run's split says as the word that names its round at the start of
// a label: the methodology page's "Test repair round" or "Dev repair round".
// A run id names one of these two splits; any other split fails the build.
const SPLITS: Readonly<Record<string, string>> = {
  dev: 'Dev',
  test: 'Test',
};

/** One formatting kind. */
export type FmtKind = (typeof FMT_KINDS)[number];

/** Whether a string names a formatting kind. */
export function isFmtKind(value: string): value is FmtKind {
  return (FMT_KINDS as readonly string[]).includes(value);
}

/** Looks a string up in a closed word list, or throws naming the list. */
function word(value: unknown, words: Readonly<Record<string, string>>, list: string): string {
  const found =
    typeof value === 'string' && Object.hasOwn(words, value) ? words[value] : undefined;
  if (found === undefined) {
    throw new TypeError(`fmt: ${JSON.stringify(value)} is no known ${list}`);
  }
  return found;
}

function integer(value: unknown): string {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new TypeError(`fmt: ${JSON.stringify(value)} is not a safe integer`);
  }
  // String(-0) is "0", which is what the committed "-0" reads as.
  return String(value);
}

/**
 * Formats one sourced value.
 *
 * @param value The value a sourced node holds.
 * @param kind How to show it: int, a safe integer in plain digits; num, a
 *     finite number in its shortest round-trip form; bool, yes or no; ints,
 *     integers joined by a comma and a space, or none when empty; text, a
 *     string with its controls made visible; unmeasured, a scored summary's
 *     not_measured status as fixed words, never the status key itself;
 *     split, a run's split as the capitalized word that names its round.
 * @return The text the page shows.
 * @throws TypeError When the value does not fit the kind, so a build fails
 *     rather than show a value in the wrong form.
 */
export function fmt(value: unknown, kind: FmtKind): string {
  switch (kind) {
    case 'int':
      return integer(value);
    case 'num':
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        throw new TypeError(`fmt: ${JSON.stringify(value)} is not a finite number`);
      }
      return String(value);
    case 'bool':
      if (typeof value !== 'boolean') {
        throw new TypeError(`fmt: ${JSON.stringify(value)} is not a boolean`);
      }
      return value ? 'yes' : 'no';
    case 'ints':
      if (!Array.isArray(value)) {
        throw new TypeError(`fmt: ${JSON.stringify(value)} is not an array`);
      }
      return value.length === 0 ? 'none' : value.map(integer).join(', ');
    case 'text':
      if (typeof value !== 'string') {
        throw new TypeError(`fmt: ${JSON.stringify(value)} is not a string`);
      }
      return visible(value);
    case 'unmeasured':
      return word(value, UNMEASURED, 'not_measured status');
    case 'split':
      return word(value, SPLITS, 'split');
  }
}
