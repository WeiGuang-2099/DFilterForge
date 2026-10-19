/**
 * @fileoverview The codes the analyses arrive in, for server and client.
 *
 * docs/protocol.md registers the error classes and the proximity strata
 * (Training rules, amended 2026-10-18); the scorer writes the outcomes.
 * lib/analysis-data.ts refuses any other code, and the analysis page gives
 * each one fixed words.
 */

/** Every outcome a ready item can take, in the board's order. */
export const OUTCOMES = [
  'strong_exact',
  'shortcut',
  'silent_wrong',
  'invalid',
  'malformed',
  'provider_failed',
  'abstained',
] as const;

/** One scored outcome. */
export type Outcome = (typeof OUTCOMES)[number];

/** Strong exact, then the registered classes in their order. */
export const CLASSES = [
  'strong_exact',
  'provider_failed',
  'truncated',
  'malformed',
  'abstained',
  'unknown_field',
  'invalid_other',
  'shortcut',
  'missing_field',
  'extra_field',
  'operator',
  'value',
  'structure',
  'same_form',
] as const;

/** One registered class, or strong exact. */
export type ClassName = (typeof CLASSES)[number];

/** The outcome each class belongs to. */
export const CLASS_OUTCOME: Readonly<Record<ClassName, Outcome>> = {
  strong_exact: 'strong_exact',
  provider_failed: 'provider_failed',
  truncated: 'malformed',
  malformed: 'malformed',
  abstained: 'abstained',
  unknown_field: 'invalid',
  invalid_other: 'invalid',
  shortcut: 'shortcut',
  missing_field: 'silent_wrong',
  extra_field: 'silent_wrong',
  operator: 'silent_wrong',
  value: 'silent_wrong',
  structure: 'silent_wrong',
  same_form: 'silent_wrong',
};

/** The registered proximity strata, in their order. */
export const STRATA = ['same_atoms', 'inside_one_target', 'pairs_seen', 'apart'] as const;

/** One proximity stratum. */
export type Stratum = (typeof STRATA)[number];

/** The field-coverage strata of the copies table, in the headline's order. */
export const COVERAGE = ['every_gold_field_retrieved', 'some_gold_field_missing'] as const;

/** Which side of a disagreeing probe holds the shown frame. */
export const SIDES = ['reference_only', 'candidate_only'] as const;
