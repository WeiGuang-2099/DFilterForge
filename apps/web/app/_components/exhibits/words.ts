/**
 * @fileoverview The fixed words the exhibits page gives each code.
 *
 * A contract, a retrieval mode, a frame's state or the side a killing frame
 * falls on arrives as its code (lib/exhibits-codes.ts); these records key
 * on the code types, so a code without words fails typecheck. A verdict
 * has no record here: an exhibit shows it through fmt's outcome kind as a
 * sourced value, and the overview's key and a square's readout format its
 * code with the same kind, so lib/fmt.ts holds the only copy of the verdict
 * words.
 */

import type {Contract, FrameState, Retrieval, Side} from '@/lib/exhibits-codes';

/** What a condition asks the model to write, as a request's citation says it. */
export const CONTRACT_WORDS: Readonly<Record<Contract, string>> = {
  display_filter: 'display filter',
  typed_ir: 'typed IR',
};

/** Whether a condition lists catalog fields, as a request's citation says it. */
export const RETRIEVAL_WORDS: Readonly<Record<Retrieval, string>> = {
  none: 'no retrieval',
  lexical: 'field retrieval',
};

/** The label of an answer: a typed answer is compiled before tshark runs it. */
export const ANSWER_WORDS: Readonly<Record<Contract, string>> = {
  display_filter: 'Answer',
  typed_ir: 'Answer, compiled from its IR',
};

/** What a frame's state says about it, as the frame readout ends. */
export const STATE_WORDS: Readonly<Record<FrameState, string>> = {
  tp: 'labelled and matched',
  tn: 'neither labelled nor matched',
  fp: 'matched; the labels leave it out',
  fn: 'labelled; the answer misses it',
};

/** What a killing frame's side says, as the packet list's last column. */
export const SIDE_WORDS: Readonly<Record<Side, string>> = {
  candidate_only: STATE_WORDS.fp,
  reference_only: STATE_WORDS.fn,
};

/** The two verifiers a toggle switches between. */
export type View = 'tail' | 'alone';

/** The toggle's words for each verifier; never v1 or v2. */
export const VIEW_WORDS: Readonly<Record<View, string>> = {
  tail: 'With the witness tail',
  alone: 'Captures alone',
};
