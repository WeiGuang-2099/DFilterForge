/**
 * @fileoverview Checks the judge study's squares against its counts, and
 * reads a count or a square's verdict letter or fails the build.
 *
 * The methodology page draws one square per silent-wrong answer from its
 * marks and prints each row's and each mode's counts from other nodes, so
 * checkJudge holds them together: one row is the judge's own pass, each
 * row holds a square per silent-wrong answer, the squares add up to the
 * headline's silent-wrong counts, over every answer and the own pass's,
 * each mark is 0 or 1, and in each mode the marks add up to each row's
 * rated-correct count and over the rows to the headline's, over every
 * answer and the own pass's, and to the key's rated correct and rated
 * incorrect.
 */

import 'server-only';

import {fail} from './data';
import type {Judge, NumNode} from './data';

/** A judge mode: the request alone, or with the reference filter. */
export type Mode = keyof Judge['modes'];

/** The modes in the order the page names them. */
export const MODES: readonly Mode[] = ['primary', 'secondary'];

export type JudgeRow = Judge['rows'][number];
export type JudgeAnswer = JudgeRow['answers'][number];

/** A square's verdict letter: c rated correct, a false acceptance; i not. */
export type Letter = 'c' | 'i';

/** A count, as a number, or a build failure naming where. */
export function counted(node: NumNode, where: string): number {
  if (typeof node.v !== 'number' || !Number.isSafeInteger(node.v) || node.v < 0) {
    fail(where, `holds ${JSON.stringify(node.v)}, not a count`);
  }
  return node.v;
}

/** An answer's mark in a mode as its letter; a mark is 1 or 0. */
export function letter(answer: JudgeAnswer, mode: Mode, where: string): Letter {
  const mark = counted(answer.verdicts[mode], where);
  return mark === 1 ? 'c' : mark === 0 ? 'i' : fail(where, `marks an answer ${mark} times`);
}

export function checkJudge(judge: Judge): void {
  if (judge.rows.filter((row) => row.self).length !== 1) {
    fail('methodology.json.judge.rows', "does not set the judge's own pass apart once");
  }
  let squares = 0;
  let mine = 0;
  judge.rows.forEach((row, at) => {
    const where = `methodology.json.judge.rows[${at}]`;
    squares += row.answers.length;
    mine += row.self ? row.answers.length : 0;
    if (row.answers.length !== counted(row.silent_wrong, where)) {
      fail(where, 'does not hold one square per silent-wrong answer');
    }
  });
  for (const mode of MODES) {
    const {headline, all: key} = judge.modes[mode];
    const where = `methodology.json.judge.modes.${mode}`;
    let all = 0;
    let own = 0;
    judge.rows.forEach((row, at) => {
      const here = `methodology.json.judge.rows[${at}]`;
      const marks = row.answers.filter((answer) => letter(answer, mode, here) === 'c').length;
      if (marks !== counted(row.rated_correct[mode], here)) {
        fail(here, `marks other answers than its ${mode} count`);
      }
      all += marks;
      own += row.self ? marks : 0;
    });
    if (
      squares !== counted(headline.silent_wrong, where) ||
      mine !== counted(headline.self_silent_wrong, where) ||
      all !== counted(headline.silent_wrong_rated_correct, where) ||
      own !== counted(headline.self_silent_wrong_rated_correct, where) ||
      all !== counted(key.silent_wrong.correct, where) ||
      squares - all !== counted(key.silent_wrong.incorrect, where)
    ) {
      fail(where, 'counts other squares or marks than the rows');
    }
  }
}
