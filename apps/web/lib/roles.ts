/**
 * @fileoverview The one table that names a run's role on a page.
 *
 * reel.json's pool, site.json's runs and board.json's rows carry roles
 * verbatim, with no slot field: the dev selection's anchor and slots, and
 * the test-run registry's eight roles (docs/decisions/test-runs.md). A page
 * shows a role only through roleLabel(), so every page names it the same
 * way, and a role this table does not know fails the build rather than
 * show a raw key.
 */

const ROLE_LABELS: Readonly<Record<string, string>> = {
  // Dev: the bake-off anchor, and a pass's slot.
  anchor: 'anchor',
  small: 'small slot',
  mid: 'mid slot',
  frontier: 'frontier slot',
  // Test: the A/A pair, then each slot's winner and its fallback.
  aa_pass_a: 'pass A',
  aa_pass_b: 'pass B',
  winner_small: 'small slot winner',
  fallback_small: 'small slot fallback',
  winner_mid: 'mid slot winner',
  fallback_mid: 'mid slot fallback',
  winner_frontier: 'frontier slot winner',
  fallback_frontier: 'frontier slot fallback',
};

/** The words a page shows for a run's role. */
export function roleLabel(role: string): string {
  const label = Object.hasOwn(ROLE_LABELS, role) ? ROLE_LABELS[role] : undefined;
  if (label === undefined) {
    throw new Error(`roles: no label for the role ${JSON.stringify(role)}`);
  }
  return label;
}
