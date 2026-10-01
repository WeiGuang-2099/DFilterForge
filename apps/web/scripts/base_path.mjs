/**
 * @fileoverview The URL prefix the static site is built and served under.
 *
 * This module is the one place that resolves it; next.config.ts, the static
 * server and the Playwright config all import it. A GitHub project page
 * serves the site under /DFilterForge, the default. A host that serves it at
 * the domain root, such as Cloudflare Pages, sets PAGES_BASE_PATH to the
 * empty string, with no code change. Next inlines the value at build time,
 * so the build and the server must see the same environment.
 */

const DEFAULT_BASE_PATH = '/DFilterForge';

// Empty, or one or more "/segment" parts with no trailing slash, the form
// Next accepts. A segment starts with a letter or digit, so neither "." nor
// ".." can be one.
const BASE_PATH_PATTERN = /^(?:\/[A-Za-z0-9][A-Za-z0-9._-]*)*$/;

/**
 * Returns PAGES_BASE_PATH, or the default when it is unset.
 *
 * @return {string}
 */
function resolveBasePath() {
  const value = process.env['PAGES_BASE_PATH'] ?? DEFAULT_BASE_PATH;
  if (!BASE_PATH_PATTERN.test(value)) {
    throw new Error(
      'PAGES_BASE_PATH must be empty or "/name" segments without a trailing ' +
        `slash; got ${JSON.stringify(value)}`,
    );
  }
  return value;
}

/** The base path for this process. */
export const basePath = resolveBasePath();
