/**
 * @fileoverview Who made the site and where its source lives.
 *
 * The masthead and the footer name the author and link the repository, and
 * every sourced number links its file there. The handle holds a digit, so a
 * page renders it with <Term> (lib/terms.ts lists it).
 */

/** The author's GitHub handle. */
export const AUTHOR = 'WeiGuang-2099';

/** The author's GitHub profile. */
export const AUTHOR_URL = `https://github.com/${AUTHOR}`;

/** The repository the site and every recorded run are published in. */
export const REPOSITORY = `${AUTHOR_URL}/DFilterForge`;
