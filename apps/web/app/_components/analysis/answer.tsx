/**
 * @fileoverview One answer to a ready item, as the scorer read it.
 *
 * Server pages and client islands both render it. An executed answer shows
 * its filter; a refused one the scorer's error code and the fields its IR
 * names, each once; a reply that is no valid answer its raw text, cut at the
 * exporter's cap; an abstention its question, when it asks one. Model text
 * is text only.
 */

import type {ReactNode} from 'react';

import type {Answer} from '@/lib/analysis-data';
import {StrText} from '@/lib/sourced-text';

import {ERROR_WORDS} from './words';

/** Renders one answer in the form its outcome gives it. */
export function AnswerText({answer}: {readonly answer: Answer}): ReactNode {
  if (answer.filter !== null) {
    return (
      <code className="an-code">
        <StrText node={answer.filter} />
      </code>
    );
  }
  if (answer.fields !== null && answer.error_code !== null) {
    const words = ERROR_WORDS[answer.error_code.t];
    const fields = answer.fields.filter(
      (field, index, all) => all.findIndex((each) => each.t === field.t) === index,
    );
    return (
      <span className="an-refused">
        Refused{words === undefined ? null : `, it ${words}`} (
        <code>
          <StrText node={answer.error_code} />
        </code>
        ). Its fields:{' '}
        {fields.map((field) => (
          <code className="an-code an-field" key={field.t}>
            <StrText node={field} />
          </code>
        ))}
      </span>
    );
  }
  if (answer.raw !== null) {
    return (
      <code className="an-raw">
        <StrText node={answer.raw} />
      </code>
    );
  }
  if (answer.question !== null) {
    return (
      <span>
        Asked: &ldquo;
        <StrText node={answer.question} />
        &rdquo;
      </span>
    );
  }
  return (
    <span>
      {answer.outcome.t === 'abstained' ? 'Abstained without a question.' : 'No answer.'}
    </span>
  );
}
