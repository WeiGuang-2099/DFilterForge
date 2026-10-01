/**
 * @fileoverview Makes invisible and reordering characters visible.
 *
 * Model output and committed text reach the page only as React text nodes,
 * so no markup ever runs. A control or bidirectional formatting character
 * still changes what a reader sees: a right-to-left override can make a
 * filter read differently from the bytes tshark ran, and a zero-width space
 * can hide inside a field name. visible() replaces each such character with
 * a visible mark, so the page shows every code point that is there. Tab and
 * line feed are kept, because they lay text out rather than hide it.
 */

// The Unicode Control Pictures block has one symbol per C0 control, in code
// point order, and one for DEL.
const CONTROL_PICTURES = 0x2400;
const DELETE = 0x7f;
const DELETE_PICTURE = 0x2421;
const LAST_C0 = 0x1f;
const KEPT = new Set([0x09, 0x0a]);

// Bidirectional formatting characters and invisible separators, by their
// usual abbreviations.
const NAMED = new Map<number, string>([
  [0x00ad, 'SHY'],
  [0x061c, 'ALM'],
  [0x200b, 'ZWSP'],
  [0x200c, 'ZWNJ'],
  [0x200d, 'ZWJ'],
  [0x200e, 'LRM'],
  [0x200f, 'RLM'],
  [0x2028, 'LSEP'],
  [0x2029, 'PSEP'],
  [0x202a, 'LRE'],
  [0x202b, 'RLE'],
  [0x202c, 'PDF'],
  [0x202d, 'LRO'],
  [0x202e, 'RLO'],
  [0x2060, 'WJ'],
  [0x2066, 'LRI'],
  [0x2067, 'RLI'],
  [0x2068, 'FSI'],
  [0x2069, 'PDI'],
  [0xfeff, 'BOM'],
]);

/** Whether a code point is a C1 control or a lone UTF-16 surrogate. */
function isUnnamedControl(code: number): boolean {
  return (code >= 0x80 && code <= 0x9f) || (code >= 0xd800 && code <= 0xdfff);
}

/** Returns the mark shown for one code point, or the character itself. */
function mark(character: string): string {
  const code = character.codePointAt(0) ?? 0;
  if (KEPT.has(code)) {
    return character;
  }
  if (code <= LAST_C0) {
    return String.fromCodePoint(CONTROL_PICTURES + code);
  }
  if (code === DELETE) {
    return String.fromCodePoint(DELETE_PICTURE);
  }
  const name = NAMED.get(code);
  if (name !== undefined) {
    return `[${name}]`;
  }
  if (isUnnamedControl(code)) {
    return `[U+${code.toString(16).toUpperCase().padStart(4, '0')}]`;
  }
  return character;
}

/**
 * Returns text with every control, bidirectional formatting character and
 * invisible separator replaced by a visible mark.
 *
 * @param text Any string, including model output.
 * @return The same text with C0 controls other than tab and line feed shown
 *     as control pictures, DEL as its picture, bidirectional and invisible
 *     characters as a bracketed abbreviation such as [RLO], and C1 controls
 *     and lone surrogates as a bracketed code point.
 */
export function visible(text: string): string {
  let shown = '';
  // for...of walks code points, so a lone surrogate arrives on its own.
  for (const character of text) {
    shown += mark(character);
  }
  return shown;
}
