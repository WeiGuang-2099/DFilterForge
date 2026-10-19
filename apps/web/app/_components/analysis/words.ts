/**
 * @fileoverview The fixed words the analysis page gives each code.
 *
 * An outcome, a class or a stratum arrives as its code (lib/analysis-codes.ts);
 * these records key on the code types, so a code without words fails
 * typecheck. A class's words describe what the registered comparison found,
 * in the order docs/protocol.md gives, not why the answer failed.
 */

import type {ClassName, Outcome, Stratum} from '@/lib/analysis-codes';

/** An outcome as the figure's blocks and its key name it. */
export const OUTCOME_WORDS: Readonly<Record<Outcome, string>> = {
  strong_exact: 'Exact',
  shortcut: 'Shortcut',
  silent_wrong: 'Runs, wrong packets',
  invalid: 'Refused',
  malformed: 'Not valid Intent IR',
  provider_failed: 'No answer',
  abstained: 'Asked a question',
};

/** An outcome as a block's label says it where the figure is narrow. */
export const SHORT_WORDS: Readonly<Record<Outcome, string>> = {
  strong_exact: 'Exact',
  shortcut: 'Shortcut',
  silent_wrong: 'Wrong packets',
  invalid: 'Refused',
  malformed: 'Not valid IR',
  provider_failed: 'No answer',
  abstained: 'Asked',
};

/** An outcome before "answers", as a ribbon's list opens. */
export const KIND_WORDS: Readonly<Record<Outcome, string>> = {
  strong_exact: 'exact',
  shortcut: 'shortcut',
  silent_wrong: 'silently wrong',
  invalid: 'refused',
  malformed: 'malformed',
  provider_failed: 'unanswered',
  abstained: 'abstaining',
};

/** An outcome after "is" and after "are", as a ribbon's list says it. */
export const STATE_WORDS: Readonly<Record<Outcome, readonly [string, string]>> = {
  strong_exact: ['exact', 'exact'],
  shortcut: ['a shortcut', 'shortcuts'],
  silent_wrong: ['silently wrong', 'silently wrong'],
  invalid: ['refused', 'refused'],
  malformed: ['not valid Intent IR', 'not valid Intent IR'],
  provider_failed: ['unanswered', 'unanswered'],
  abstained: ['a question instead', 'questions instead'],
};

/** The heading of the classes of one outcome. */
export const GROUP_WORDS: Readonly<Record<Outcome, string>> = {
  strong_exact: 'Exact',
  shortcut: 'Shortcut',
  silent_wrong: 'Runs and selects the wrong packets',
  invalid: 'Refused before any packet is read',
  malformed: 'No valid answer',
  provider_failed: 'No answer',
  abstained: 'Asked instead of answering',
};

interface Words {
  readonly name: string;
  readonly what: string;
}

/** A class's name, and what the registered comparison found. */
export const CLASS_WORDS: Readonly<Record<ClassName, Words>> = {
  strong_exact: {
    name: 'Strong exact',
    what: "Selects exactly the reference's packets on every scored probe.",
  },
  provider_failed: {name: 'No answer', what: 'The provider returned nothing to score.'},
  truncated: {
    name: 'Ran out of tokens',
    what: 'The reply stopped at the output token limit before the answer closed.',
  },
  malformed: {
    name: 'Breaks the output contract',
    what: 'The reply is not a valid answer envelope holding Intent IR.',
  },
  abstained: {
    name: 'Asked a question',
    what: 'Asked for clarification on a request the reference treats as complete.',
  },
  unknown_field: {
    name: 'Unknown field',
    what: 'Names a field the frozen tshark catalog does not have.',
  },
  invalid_other: {
    name: 'Other refusal',
    what: 'A known field with a value of the wrong type, or a comparison it does not support.',
  },
  shortcut: {
    name: 'Shortcut',
    what: 'Matches every probe only by breaking a rule of the shortcut policy.',
  },
  missing_field: {name: 'Missing field', what: 'Leaves out a field the reference tests.'},
  extra_field: {name: 'Extra field', what: 'Tests a field the reference does not.'},
  operator: {
    name: 'Other comparison',
    what: "The reference's fields, at least one compared another way.",
  },
  value: {
    name: 'Other value',
    what: "The reference's fields and comparisons, with another value.",
  },
  structure: {
    name: 'Other structure',
    what: "The reference's predicates, joined or negated another way.",
  },
  same_form: {
    name: 'Same form',
    what: "The reference's canonical form, where the registered order ends.",
  },
};

/** A stratum's name, and what puts a case in it. */
export const STRATUM_WORDS: Readonly<Record<Stratum, Words>> = {
  same_atoms: {
    name: 'Same predicates',
    what: "A training target holds exactly the case's predicates, composed another way.",
  },
  inside_one_target: {
    name: 'Inside one target',
    what: "A training target holds every predicate of the case, and more.",
  },
  pairs_seen: {
    name: 'Pairs seen',
    what: "Every two of the case's predicates share a target, but no target holds them all.",
  },
  apart: {
    name: 'Apart',
    what: "Some two of the case's predicates share no target.",
  },
};

/** What the scorer's error code for a refused answer says, when known. */
export const ERROR_WORDS: Readonly<Record<string, string>> = {
  unknown_field: 'names a field the frozen catalog does not have',
  type_mismatch: 'compares a field with a value of the wrong type',
  unsupported_operator: 'uses a comparison the field does not support',
};
