import {expect, test} from '@playwright/test';

import {fmt, FMT_KINDS, isFmtKind} from '../lib/fmt';
import {visible} from '../lib/visible';

// lib/fmt.ts is the only formatter, and the consistency test formats each
// re-derived value with it, so a wrong format would pass that test. These
// cases pin what each kind shows.

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

test('visible shows C1 controls and lone surrogates by code point', () => {
  expect(visible('\u0085')).toBe('[U+0085]');
  expect(visible('\u009f')).toBe('[U+009F]');
  expect(visible('a\ud800b')).toBe('a[U+D800]b');
  expect(visible('\udfff')).toBe('[U+DFFF]');
});

test('every kind is named', () => {
  expect([...FMT_KINDS]).toEqual(['int', 'num', 'bool', 'ints', 'text']);
  for (const kind of FMT_KINDS) {
    expect(isFmtKind(kind)).toBe(true);
  }
  expect(isFmtKind('percent')).toBe(false);
  expect(isFmtKind('')).toBe(false);
});
