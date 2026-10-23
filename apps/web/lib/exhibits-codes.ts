/**
 * @fileoverview The closed lists of codes exhibits.json carries.
 *
 * lib/exhibits-data.ts checks each code against these lists, so a code the
 * exhibits page has no words or drawing for fails the build. The lists sit
 * apart from the guard, which reads files on the server only, so a client
 * island can key its words on them.
 */

/** A verdict on the captures alone: unscorable where no label is left. */
export const ALONE = ['strong_exact', 'shortcut', 'silent_wrong', 'unscorable'] as const;

/** A verdict with the witness tail: the scored outcome. */
export const TAIL = ['strong_exact', 'shortcut', 'silent_wrong'] as const;

/** What the captures alone accept, so what the tail can turn silent-wrong. */
export const ACCEPTED = ['strong_exact', 'shortcut'] as const;

/** A frame's state: tp both select it, fp the answer only, fn the labels only. */
export const STATES = ['tp', 'fp', 'fn', 'tn'] as const;

/** The side of a frame where the answer and the labels part. */
export const SIDES = ['candidate_only', 'reference_only'] as const;

/** What a condition asks the model to write. */
export const CONTRACTS = ['display_filter', 'typed_ir'] as const;

/** Whether a condition lists catalog fields beside the request. */
export const RETRIEVALS = ['none', 'lexical'] as const;

/** The test-run registry's roles a pool pass can hold (test-runs.md, Runs). */
export const ROLES = [
  'aa_pass_a',
  'winner_small',
  'winner_mid',
  'winner_frontier',
  'fallback_small',
  'fallback_mid',
  'fallback_frontier',
] as const;

/** Where a frame goes from its probe's client address (packets.json). */
export const DIRECTIONS = ['out', 'in', 'other'] as const;

/** A frame of the benchmark, or of the witness tail (captures.json). */
export const FRAME_KINDS = ['recipe', 'witness'] as const;

/**
 * The verdict pairs a replayed answer can hold, alone then with the tail,
 * in the order a row of squares lists them. A tail adds frames, so it can
 * turn an accepted answer wrong but never a wrong one right, and a shortcut
 * flag comes from the outcome row, which the tail does not change.
 */
export const PAIRS = [
  'strong_exact/strong_exact',
  'strong_exact/silent_wrong',
  'shortcut/shortcut',
  'shortcut/silent_wrong',
  'unscorable/strong_exact',
  'unscorable/shortcut',
  'unscorable/silent_wrong',
  'silent_wrong/silent_wrong',
] as const;

export type Alone = (typeof ALONE)[number];
export type Tail = (typeof TAIL)[number];
export type FrameState = (typeof STATES)[number];
export type Side = (typeof SIDES)[number];
export type Contract = (typeof CONTRACTS)[number];
export type Retrieval = (typeof RETRIEVALS)[number];
export type Pair = (typeof PAIRS)[number];
