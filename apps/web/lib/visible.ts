/**
 * @fileoverview Makes invisible and reordering characters visible.
 *
 * Model output and committed text reach the page only as React text nodes,
 * so no markup ever runs. A control or bidirectional formatting character
 * still changes what a reader sees: a right-to-left override can make a
 * filter read differently from the bytes tshark ran, a zero-width space can
 * hide inside a field name, and Unicode tag characters can carry a whole
 * hidden sentence after a filter. visible() replaces each control, format,
 * default-ignorable and private-use code point with a visible mark, so none
 * can render at zero width or as a glyph the reader cannot name. Tab and line
 * feed are kept, because they lay text out rather than hide it.
 *
 * Unassigned code points are left as they are: a browser draws them as a
 * missing-glyph box, and which code points are unassigned changes with each
 * Unicode version, so the build and the test could disagree. The property
 * classes below are read from the JavaScript engine's Unicode data; CI builds
 * and tests on the same Node release.
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

// Format characters (tag characters, invisible operators, the Mongolian
// vowel separator), default-ignorable code points (variation selectors,
// Hangul fillers, the combining grapheme joiner) and private-use code points.
const INVISIBLE = /^[\p{Cf}\p{Default_Ignorable_Code_Point}\p{Co}]$/u;

/**
 * Whether a code point without a name is still marked: a C1 control, a lone
 * UTF-16 surrogate, or one of the INVISIBLE classes.
 */
function isUnnamed(code: number, character: string): boolean {
  return (
    (code >= 0x80 && code <= 0x9f) ||
    (code >= 0xd800 && code <= 0xdfff) ||
    INVISIBLE.test(character)
  );
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
  if (isUnnamed(code, character)) {
    return `[U+${code.toString(16).toUpperCase().padStart(4, '0')}]`;
  }
  return character;
}

/**
 * Returns text with every control, format, default-ignorable and private-use
 * code point replaced by a visible mark.
 *
 * @param text Any string, including model output.
 * @return The same text with C0 controls other than tab and line feed shown
 *     as control pictures, DEL as its picture, bidirectional and common
 *     invisible characters as a bracketed abbreviation such as [RLO], and
 *     every other marked code point, such as a C1 control, a lone surrogate
 *     or a tag character, as a bracketed code point such as [U+E0041].
 */
export function visible(text: string): string {
  let shown = '';
  // for...of walks code points, so a lone surrogate arrives on its own.
  for (const character of text) {
    shown += mark(character);
  }
  return shown;
}
