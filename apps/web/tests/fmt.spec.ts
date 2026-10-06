import {expect, test} from '@playwright/test';

import type {NumNode} from '../lib/data';
import {fmt, FMT_KINDS, isFmtKind} from '../lib/fmt';
import type {FmtKind} from '../lib/fmt';
import type {Num} from '../lib/sourced';
import {visible} from '../lib/visible';

// lib/fmt.ts is the only formatter, and the consistency test formats each
// re-derived value with it, so a wrong format would pass that test. These
// cases pin what each kind shows.

/** The kinds <Num> accepts, read from its props. */
type NumKind = Parameters<typeof Num>[0]['kind'];

// One value per kind <Num> accepts, of the type a NumNode holds. The
// compiler checks this record against NumKind both ways: a kind <Num>
// refuses is an excess property here, and a kind <Num> accepts that is not
// listed is a missing one. So a kind added to FMT_KINDS fails typecheck
// here until it is listed, if fmt formats a NumNode value with it, or
// excluded from <Num>'s kind prop. Without this, a string-only kind passes
// typecheck and lint on <Num> and throws only in next build.
const NUM_KIND_SAMPLES: Readonly<Record<NumKind, NumNode['v']>> = {
  int: 3,
  num: 0.5,
  bool: true,
  ints: [3, 9],
  rate: 0.6375,
  runtime: 60.32937800000582,
};

function isNumKind(kind: FmtKind): kind is NumKind {
  return Object.hasOwn(NUM_KIND_SAMPLES, kind);
}

test('int shows a safe integer in plain digits', () => {
  expect(fmt(0, 'int')).toBe('0');
  expect(fmt(-0, 'int')).toBe('0');
  expect(fmt(12, 'int')).toBe('12');
  expect(fmt(-3, 'int')).toBe('-3');
  expect(fmt(2470, 'int')).toBe('2470');
  expect(fmt(Number.MAX_SAFE_INTEGER, 'int')).toBe('9007199254740991');
});

test('int refuses anything but a safe integer', () => {
  for (const value of [1.5, Number.NaN, Infinity, 2 ** 53, true, '3', null, [1]]) {
    expect(() => fmt(value, 'int'), JSON.stringify(value)).toThrow(TypeError);
  }
});

test('num shows a finite number as committed, never rounded', () => {
  expect(fmt(67.48, 'num')).toBe('67.48');
  expect(fmt(0.475, 'num')).toBe('0.475');
  expect(fmt(0.1 + 0.2, 'num')).toBe('0.30000000000000004');
  expect(fmt(1000, 'num')).toBe('1000');
  expect(fmt(-0.5, 'num')).toBe('-0.5');
  for (const value of [Number.NaN, Infinity, -Infinity, '1', false, null]) {
    expect(() => fmt(value, 'num'), String(value)).toThrow(TypeError);
  }
});

test('bool shows yes or no', () => {
  expect(fmt(true, 'bool')).toBe('yes');
  expect(fmt(false, 'bool')).toBe('no');
  for (const value of [0, 1, 'true', null]) {
    expect(() => fmt(value, 'bool'), String(value)).toThrow(TypeError);
  }
});

test('ints joins integers and names an empty list', () => {
  expect(fmt([3, 9, 17], 'ints')).toBe('3, 9, 17');
  expect(fmt([17], 'ints')).toBe('17');
  expect(fmt([], 'ints')).toBe('none');
  for (const value of [[1.5], ['3'], [true], 3, 'none']) {
    expect(() => fmt(value, 'ints'), JSON.stringify(value)).toThrow(TypeError);
  }
});

test('text shows a string with its controls made visible', () => {
  expect(fmt('dns.qry.type == 28', 'text')).toBe('dns.qry.type == 28');
  expect(fmt('', 'text')).toBe('');
  for (const value of [3, null, ['a']]) {
    expect(() => fmt(value, 'text'), JSON.stringify(value)).toThrow(TypeError);
  }
});

test('unmeasured shows not measured yet for not_run, never the key', () => {
  // The scorer writes not_run for a measurement no round has made; the
  // protocol keeps "not run" for a run ruled not run, so the key is never
  // shown as written.
  expect(fmt('not_run', 'unmeasured')).toBe('not measured yet');
  for (const value of ['scored', 'not run', 'not measured yet', '', 'toString', 3, null]) {
    expect(() => fmt(value, 'unmeasured'), JSON.stringify(value)).toThrow(TypeError);
  }
});

test('split shows a run split as the word that names its round', () => {
  // The methodology page labels its repair line "Test repair round" or
  // "Dev repair round" with it; any other value fails the build.
  expect(fmt('test', 'split')).toBe('Test');
  expect(fmt('dev', 'split')).toBe('Dev');
  for (const value of ['train', 'Test', 'TEST', '', 'toString', 3, null]) {
    expect(() => fmt(value, 'split'), JSON.stringify(value)).toThrow(TypeError);
  }
});

test('rate rounds the committed decimal to three places, halves away from zero', () => {
  // The cases locked-test-v1.md shows: a summary's six places, rounded on
  // the decimal digits, never on the binary float, which toFixed would.
  expect(fmt(0.6375, 'rate')).toBe('0.638');
  expect(fmt(0.8125, 'rate')).toBe('0.813');
  expect(fmt(-0.0625, 'rate')).toBe('-0.063');
  expect(fmt(0.347, 'rate')).toBe('0.347');
  expect(fmt(1.0005, 'rate')).toBe('1.001');
  expect(fmt(0.9995, 'rate')).toBe('1.000');
  expect(fmt(0.30000000000000004, 'rate')).toBe('0.300');
  expect(fmt(1, 'rate')).toBe('1.000');
  expect(fmt(0, 'rate')).toBe('0.000');
  expect(fmt(-0, 'rate')).toBe('0.000');
  expect(fmt(0.0004, 'rate')).toBe('0.000');
  expect(fmt(-0.0004, 'rate')).toBe('-0.000');
  expect(fmt(5e-4, 'rate')).toBe('0.001');
  expect(fmt(1e-7, 'rate')).toBe('0.000');
  expect(fmt(1.5e21, 'rate')).toBe('1500000000000000000000.000');
  for (const value of [Number.NaN, Infinity, '0.5', true, null, [1]]) {
    expect(() => fmt(value, 'rate'), String(value)).toThrow(TypeError);
  }
});

test('runtime shows milliseconds to one decimal, never the raw float', () => {
  expect(fmt(60.32937800000582, 'runtime')).toBe('60.3');
  expect(fmt(60.89140100000634, 'runtime')).toBe('60.9');
  expect(fmt(7077.999999994063, 'runtime')).toBe('7078.0');
  expect(fmt(99.95, 'runtime')).toBe('100.0');
  expect(fmt(0.05, 'runtime')).toBe('0.1');
  expect(fmt(12, 'runtime')).toBe('12.0');
  for (const value of [Number.NaN, -Infinity, '60', null]) {
    expect(() => fmt(value, 'runtime'), String(value)).toThrow(TypeError);
  }
});

test('outcome shows a scored outcome code as the protocol words it', () => {
  expect(fmt('strong_exact', 'outcome')).toBe('strong exact');
  expect(fmt('silent_wrong', 'outcome')).toBe('silent-wrong');
  expect(fmt('provider_failed', 'outcome')).toBe('provider failed');
  expect(fmt('false_ready', 'outcome')).toBe('false ready');
  for (const value of ['exact', 'silent-wrong', '', 'toString', 3, null]) {
    expect(() => fmt(value, 'outcome'), JSON.stringify(value)).toThrow(TypeError);
  }
});

test('visible keeps layout whitespace and ordinary text', () => {
  expect(visible('a\tb\nc')).toBe('a\tb\nc');
  expect(visible('tcp.port == 443 && ip.addr == 192.0.2.1')).toBe(
    'tcp.port == 443 && ip.addr == 192.0.2.1',
  );
  const mixed = 'Gr\u00f6\u00dfe \u540d\u524d \u00e9';
  expect(visible(mixed)).toBe(mixed);
  expect(visible('\u{1D400}')).toBe('\u{1D400}');
});

test('visible shows C0 controls and DEL as control pictures', () => {
  expect(visible('\u0000')).toBe('\u2400');
  expect(visible('a\rb')).toBe('a\u240db');
  expect(visible('\u001b[31m')).toBe('\u241b[31m');
  expect(visible('\u001f')).toBe('\u241f');
  expect(visible('\u007f')).toBe('\u2421');
});

test('visible names bidirectional and invisible characters', () => {
  // A right-to-left override can make a filter read differently from the
  // bytes that ran; the page must show it is there.
  expect(visible('ip.src\u202e == 1')).toBe('ip.src[RLO] == 1');
  expect(visible('\u2066x\u2069')).toBe('[LRI]x[PDI]');
  expect(visible('dns\u200b.qry')).toBe('dns[ZWSP].qry');
  expect(visible('\ufeffa')).toBe('[BOM]a');
  expect(visible('a\u2028b')).toBe('a[LSEP]b');
  expect(visible('\u061c\u200e\u200f')).toBe('[ALM][LRM][RLM]');
});

test('visible shows format, default-ignorable and private-use code points', () => {
  // Tag characters render at zero width and can carry a hidden sentence
  // after a filter that looks complete.
  expect(visible('ip.src == 10.0.0.1\u{E0069}\u{E0067}\u{E006E}')).toBe(
    'ip.src == 10.0.0.1[U+E0069][U+E0067][U+E006E]',
  );
  expect(visible('\u{E0001}\u{E0041}\u{E007F}')).toBe('[U+E0001][U+E0041][U+E007F]');
  // Invisible operators and separators, variation selectors, the combining
  // grapheme joiner and Hangul fillers.
  for (const code of [
    0x034f, 0x115f, 0x180e, 0x2061, 0x2063, 0x2064, 0x206a, 0x206f, 0x3164, 0xfe00, 0xfe0f,
    0xffa0, 0xfff9, 0x1d173, 0xe0100,
  ]) {
    const hex = code.toString(16).toUpperCase().padStart(4, '0');
    expect(visible(`tcp${String.fromCodePoint(code)}.port`), hex).toBe(`tcp[U+${hex}].port`);
  }
  // Private use, in the basic plane and in plane fifteen.
  expect(visible('\ue000\u{F0000}')).toBe('[U+E000][U+F0000]');
});

test('visible leaves visible symbols and unassigned code points as they are', () => {
  // An emoji without a variation selector, a mathematical letter and a
  // code point no Unicode version has assigned, which renders as a
  // missing-glyph box.
  for (const text of ['\u{1F600}', '\u{1D400}', '\u0378', '\u2400', '\u00a0']) {
    expect(visible(text), text).toBe(text);
  }
});

test('visible shows C1 controls and lone surrogates by code point', () => {
  expect(visible('\u0085')).toBe('[U+0085]');
  expect(visible('\u009f')).toBe('[U+009F]');
  expect(visible('a\ud800b')).toBe('a[U+D800]b');
  expect(visible('\udfff')).toBe('[U+DFFF]');
});

test('every kind is named', () => {
  expect([...FMT_KINDS]).toEqual([
    'int',
    'num',
    'bool',
    'ints',
    'text',
    'unmeasured',
    'split',
    'rate',
    'runtime',
    'outcome',
  ]);
  for (const kind of FMT_KINDS) {
    expect(isFmtKind(kind)).toBe(true);
  }
  expect(isFmtKind('percent')).toBe(false);
  expect(isFmtKind('')).toBe(false);
});

test('Num accepts exactly the kinds that format a number node', () => {
  // NUM_KIND_SAMPLES keeps the string-only kinds off <Num> at compile time.
  // This checks that each kind it lists formats its sample, and that no
  // kind left out could format any of them.
  for (const kind of FMT_KINDS.filter(isNumKind)) {
    expect(() => fmt(NUM_KIND_SAMPLES[kind], kind), kind).not.toThrow();
  }
  const others = FMT_KINDS.filter((kind) => !isNumKind(kind));
  expect(others).toEqual(['text', 'unmeasured', 'split', 'outcome']);
  for (const kind of others) {
    for (const value of Object.values(NUM_KIND_SAMPLES)) {
      expect(() => fmt(value, kind), `${kind} ${JSON.stringify(value)}`).toThrow(TypeError);
    }
  }
});
