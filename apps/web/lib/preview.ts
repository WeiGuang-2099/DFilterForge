/**
 * @fileoverview The card a page unfurls into wherever its address is pasted.
 *
 * A card is the top of a page, recorded by scripts/record_previews.mjs into
 * public/ at the size below. The home page's card stands for every page
 * that names none of its own. Link previews need absolute addresses, so
 * every build names the published site, whatever prefix it is served under.
 */

import type {Metadata} from 'next';

import {DEFAULT_BASE_PATH} from '../scripts/base_path.mjs';

/** The published site: the repository's GitHub project page. */
export const SITE_URL = `https://weiguang-2099.github.io${DEFAULT_BASE_PATH}/`;

/** The size every card is recorded at, the one link previews expect. */
export const CARD = {width: 1200, height: 630} as const;

/**
 * Returns the Open Graph fields for a page's card. Next fills in the
 * page's own title and description, and the Twitter card copies all three.
 */
export function preview(card: string, alt: string): NonNullable<Metadata['openGraph']> {
  return {type: 'website', siteName: 'DFilterForge', images: [{url: card, ...CARD, alt}]};
}
