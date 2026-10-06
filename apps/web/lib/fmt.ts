/**
 * @fileoverview The site's only formatter: turns a sourced value into text.
 *
 * Every rendered value passes through fmt() with a kind that the page names
 * and that the markup records as data-fmt, so the consistency test formats
 * the value it re-derives from the committed files the same way and compares
 * the text. fmt never scales, divides or localizes. A number is shown as the
 * committed file holds it, in the shortest form that reads back to the same
 * value, except under the two rounded kinds, rate and runtime. They round
 * that decimal form, never the binary float, so a value exactly halfway is
 * rounded away from zero as docs/results/locked-test-v1.md rounds it.
 * ESLint bans the number-formatting APIs everywhere else.
 */

import {visible} from './visible';

/** The kinds fmt() knows, as data-fmt records them. */
export const FMT_KINDS = [
  'int',
  'num',
  'bool',
  'ints',
  'text',
  'unmeasured',
  'split',
  'rate',
  'runtime',
  'outcome',
  'frame_kind',
  'join',
] as const;

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

// What the scorer's outcome codes say on a page, in docs/protocol.md's
// words. A code is never shown as written; one not listed fails the build.
const OUTCOMES: Readonly<Record<string, string>> = {
  strong_exact: 'strong exact',
  shortcut: 'shortcut',
  silent_wrong: 'silent-wrong',
  invalid: 'invalid',
  malformed: 'malformed',
  provider_failed: 'provider failed',
  abstained: 'abstained',
  false_ready: 'false ready',
};

// What captures.json's frame kinds say on a page: a recipe frame is one of
// the benchmark's packets, a witness frame one of the tail every capture
// ends in (docs/decisions/evidence/web/captures.json, notes).
const FRAME_KINDS: Readonly<Record<string, string>> = {
  recipe: 'recipe',
  witness: 'witness',
};

// What the root operator of an intent IR says about its leaves, as the
// trace table joins them.
const JOINS: Readonly<Record<string, string>> = {
  all: 'every leaf',
  any: 'any leaf',
  not: 'the leaf negated',
  predicate: 'the leaf',
};

// Decimal places of the rounded kinds: a rate, difference or bound as
// locked-test-v1.md shows it, and a tshark runtime in milliseconds.
const PLACES = {rate: 3, runtime: 1} as const;

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

/** Adds one to a string of decimal digits, carrying as far as it must. */
function increment(digits: string): string {
  const out = digits.split('');
  for (let index = out.length - 1; index >= 0; index -= 1) {
    if (out[index] !== '9') {
      out[index] = String(Number(out[index]) + 1);
      return out.join('');
    }
    out[index] = '0';
  }
  return `1${out.join('')}`;
}

/**
 * Rounds a finite number to a number of decimal places by string arithmetic
 * on its shortest round-trip form, the digits the committed JSON holds. The
 * first dropped digit decides: five or more rounds the magnitude up, so a
 * value exactly halfway goes away from zero. A negative value keeps its
 * sign even when it rounds to zero, as Python's ROUND_HALF_UP does.
 */
function rounded(value: unknown, places: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`fmt: ${JSON.stringify(value)} is not a finite number`);
  }
  const [mantissa = '', exponent = '0'] = String(Math.abs(value)).split('e');
  const [head = '', tail = ''] = mantissa.split('.');
  const point = head.length + Number(exponent);
  const digits = point < 1 ? '0'.repeat(1 - point) + head + tail : head + tail;
  const whole = Math.max(point, 1);
  const padded = digits.padEnd(whole + places + 1, '0');
  const kept = padded.slice(0, whole + places);
  const result = (padded[whole + places] ?? '0') >= '5' ? increment(kept) : kept;
  const cut = result.length - places;
  const text = places === 0 ? result : `${result.slice(0, cut)}.${result.slice(cut)}`;
  return value < 0 ? `-${text}` : text;
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
 *     split, a run's split as the capitalized word that names its round;
 *     rate, a rate, difference or bound to three decimals; runtime, a
 *     duration in milliseconds to one decimal; outcome, a scored outcome
 *     code as the protocol's words; frame_kind, a frame's kind in
 *     captures.json as a word; join, an intent IR's root operator as the
 *     words that join its leaves.
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
    case 'rate':
    case 'runtime':
      return rounded(value, PLACES[kind]);
    case 'outcome':
      return word(value, OUTCOMES, 'outcome');
    case 'frame_kind':
      return word(value, FRAME_KINDS, 'frame kind');
    case 'join':
      return word(value, JOINS, 'join');
  }
}
