import {existsSync, readdirSync} from 'node:fs';
import path from 'node:path';

import {expect, test} from '@playwright/test';

import {fmt, isFmtKind} from '../lib/fmt';
import {TERMS} from '../lib/terms';
import {capFor, capUtf8, RAW_TEXT_CAP, Resolver} from './support/resolve';

// Proves that every value on every built page is what the committed files
// hold. Each [data-src] element is re-derived from the raw files under
// docs/ and the held-out freeze record by an independent resolver, never
// from apps/web/data; its JSON value must equal the resolved value and its
// text must be fmt() of it. Then any number character outside a sourced
// value, script or style, or a reviewed term, fails the page. Run on the
// static export in out/, after `pnpm build`.

const WEB = path.join(__dirname, '..');
const OUT = path.join(WEB, 'out');

// Attributes a browser shows or a screen reader announces; the lint bans
// digit literals in the same set. A list shows its start as the first
// marker.
const SWEPT_ATTRIBUTES = [
  'alt',
  'aria-description',
  'aria-label',
  'aria-placeholder',
  'aria-roledescription',
  'aria-valuemax',
  'aria-valuemin',
  'aria-valuenow',
  'aria-valuetext',
  'label',
  'placeholder',
  'start',
  'title',
  'value',
];

interface Sweep {
  readonly terms: readonly string[];
  readonly attributes: readonly string[];
}

const SWEEP: Sweep = {terms: [...TERMS], attributes: SWEPT_ATTRIBUTES};

/**
 * Lists every number a page shows outside a sourced value, a script or
 * style, or a reviewed term: in text, a swept attribute or the document
 * title. A number is any Unicode number character, so a fullwidth or
 * Arabic-Indic digit, a superscript or a Roman numeral counts as well as an
 * ASCII digit. Runs inside the page, so it uses nothing from module scope.
 */
function strayNumbers({terms, attributes}: Sweep): string[] {
  const digit = /\p{N}/u;
  const found: string[] = [];
  const exempt = (element: Element | null): boolean => {
    if (element === null) {
      return false;
    }
    if (element.closest('script, style, [data-src]') !== null) {
      return true;
    }
    const term = element.closest('[data-term]');
    return term !== null && terms.includes(term.textContent ?? '');
  };
  const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const text = node.nodeValue ?? '';
    if (digit.test(text) && !exempt(node.parentElement)) {
      found.push(`text in <${node.parentElement?.localName ?? '?'}>: ${text.trim()}`);
    }
  }
  for (const element of Array.from(document.querySelectorAll('*'))) {
    if (element.closest('script, style, [data-src]') !== null) {
      continue;
    }
    for (const name of attributes) {
      const value = element.getAttribute(name);
      if (value !== null && digit.test(value)) {
        found.push(`${name} on <${element.localName}>: ${value}`);
      }
    }
  }
  if (digit.test(document.title)) {
    found.push(`document.title: ${document.title}`);
  }
  return found;
}

// Routes that hold no sourced value on purpose: the home page until the
// Reel renders on it, and the not-found pages. A listed route must stay
// free of data, so this list can only shrink as pages gain values.
const DATA_FREE = new Set(['', '404/', '_not-found/', 'no-such-page/']);

interface Route {
  readonly path: string;
  readonly status: number;
}

/** Every index.html under out/ as a path relative to the base path. */
function builtRoutes(directory = OUT, prefix = ''): string[] {
  return readdirSync(directory, {withFileTypes: true}).flatMap((entry) => {
    if (entry.isFile() && entry.name === 'index.html') {
      return [prefix];
    }
    if (entry.isDirectory() && entry.name !== '_next') {
      return builtRoutes(path.join(directory, entry.name), `${prefix}${entry.name}/`);
    }
    return [];
  });
}

const BUILT = builtRoutes().sort();
const ROUTES: Route[] = [
  ...BUILT.map((route) => ({path: route, status: 200})),
  {path: 'no-such-page/', status: 404},
];

const resolver = new Resolver();

interface Sourced {
  readonly src: string;
  readonly v: string | null;
  readonly kind: string | null;
  readonly cap: string | null;
  readonly text: string;
}

/** Deep equality with Object.is for every number, as the design asks. */
function sameValue(first: unknown, second: unknown): boolean {
  if (Array.isArray(first) && Array.isArray(second)) {
    return (
      first.length === second.length &&
      first.every((item: unknown, index) => sameValue(item, second[index]))
    );
  }
  return Object.is(first, second);
}

/**
 * Re-derives one sourced value and lists what does not match. The cut of
 * model text comes from the source, never from the page's data-cap, which
 * must agree with it.
 */
function mismatches(value: Sourced): string[] {
  const where = value.src;
  if (value.kind === null || !isFmtKind(value.kind)) {
    return [`${where}: data-fmt ${JSON.stringify(value.kind)} is no known kind`];
  }
  if (value.v === null) {
    return [`${where}: no data-v`];
  }
  let expected: unknown;
  let cap: number | null;
  try {
    const source: unknown = JSON.parse(where);
    expected = resolver.resolve(source);
    cap = capFor(source);
  } catch (error) {
    return [`${where}: ${error instanceof Error ? error.message : String(error)}`];
  }
  if (value.cap !== (cap === null ? null : String(cap))) {
    return [
      `${where}: data-cap is ${JSON.stringify(value.cap)}; ` +
        (cap === null ? 'only a model answer is cut' : `a model answer is cut at ${cap} bytes`),
    ];
  }
  if (cap !== null) {
    expected = capUtf8(String(expected), cap);
  }
  if (!sameValue(JSON.parse(value.v), expected)) {
    return [`${where}: the page holds ${value.v}; the files hold ${JSON.stringify(expected)}`];
  }
  const text = fmt(expected, value.kind);
  if (value.text !== text) {
    return [`${where}: the page shows ${JSON.stringify(value.text)}, not ${JSON.stringify(text)}`];
  }
  return [];
}

/** Decodes the entities React writes into attribute values. */
function decodeEntities(text: string): string {
  const named: Readonly<Record<string, string>> = {
    amp: '&',
    apos: "'",
    gt: '>',
    lt: '<',
    quot: '"',
  };
  return text.replace(
    /&(?:#([0-9]+)|#x([0-9a-fA-F]+)|([a-z]+));/g,
    (entity, decimal?: string, hex?: string, name?: string) => {
      if (decimal !== undefined) {
        return String.fromCodePoint(Number(decimal));
      }
      if (hex !== undefined) {
        return String.fromCodePoint(Number.parseInt(hex, 16));
      }
      return named[name ?? ''] ?? entity;
    },
  );
}

/** The data-src values in server-rendered HTML, outside scripts, sorted. */
function staticSources(html: string): string[] {
  const markup = html.replace(/<script\b[\s\S]*?<\/script>/gi, '');
  return Array.from(markup.matchAll(/\sdata-src="([^"]*)"/g), (match) =>
    decodeEntities(match[1] ?? ''),
  ).sort();
}

test.use({contextOptions: {reducedMotion: 'reduce'}});

for (const route of ROUTES) {
  test(`/${route.path} shows only values the committed files hold`, async ({page, request}) => {
    const target = route.path === '' ? './' : route.path;
    const response = await page.goto(target, {waitUntil: 'networkidle'});
    expect(response?.status()).toBe(route.status);

    const {values, nested} = await page.evaluate(() => {
      const elements = Array.from(document.querySelectorAll('[data-src]'));
      return {
        values: elements.map((element) => ({
          src: element.getAttribute('data-src') ?? '',
          v: element.getAttribute('data-v'),
          kind: element.getAttribute('data-fmt'),
          cap: element.getAttribute('data-cap'),
          text: element.textContent ?? '',
        })),
        nested: elements
          .filter((element) => element.parentElement?.closest('[data-src]'))
          .map((element) => element.getAttribute('data-src')),
      };
    });

    // 1. Every sourced value equals its re-derivation, as value and text.
    expect(nested, 'a sourced value inside another').toEqual([]);
    expect(values.flatMap(mismatches)).toEqual([]);

    // 2. No number outside a sourced value, a script or style, or a term.
    expect(await page.evaluate(strayNumbers, SWEEP)).toEqual([]);

    // 3. A page shows at least one value unless it is data-free on purpose.
    if (DATA_FREE.has(route.path)) {
      expect(values).toEqual([]);
    } else {
      expect(values.length).toBeGreaterThan(0);
    }

    // The server-rendered HTML already holds every value the page shows.
    const html = await request.get(target, {failOnStatusCode: false});
    expect(html.status()).toBe(route.status);
    expect(staticSources(await html.text())).toEqual(values.map((value) => value.src).sort());
  });
}

test('dynamic routes are exactly the committed rows the site shows', () => {
  // A route family is checked once its page exists in app/; until then no
  // page of that family may be built.
  const routeExists = (...segments: string[]) =>
    existsSync(path.join(WEB, 'app', ...segments, 'page.tsx'));
  const receipts = resolver
    .executedRoutes()
    .map(({run, cond, item}) => `receipts/${run}/${cond}/${item}/`)
    .sort();
  const cases = resolver
    .caseIds()
    .map((caseId) => `cases/${caseId}/`)
    .sort();

  expect(receipts.length).toBeGreaterThan(0);
  expect(new Set(receipts).size).toBe(receipts.length);
  expect(cases.length).toBeGreaterThan(0);
  for (const route of [...receipts, ...cases]) {
    expect(route, 'a dotted last segment loses its slash').not.toMatch(/\.[^/]*\/$/);
  }
  expect(BUILT.filter((route) => route.startsWith('receipts/'))).toEqual(
    routeExists('receipts', '[run]', '[cond]', '[item]') ? receipts : [],
  );
  expect(BUILT.filter((route) => route.startsWith('cases/'))).toEqual(
    routeExists('cases', '[case]') ? cases : [],
  );
});

test('model text is cut only at the contract size and only where the exporter cuts it', () => {
  // A page that hides most of an answer, or cuts a string that is not model
  // output, must fail even when its data-cap agrees with what it shows.
  const run = resolver.shownRuns()[0] ?? '';
  const answer = ['ptr', `docs/results/${run}/completions/C1.json`, '/completions/0/response_text'];
  const label = ['ptr', `docs/results/${run}/prepare.json`, '/conditions/0/label'];
  const shown = (source: readonly string[], cap: number | null): Sourced => {
    const whole = String(resolver.resolve(source));
    const text = cap === null ? whole : capUtf8(whole, cap);
    return {
      src: JSON.stringify(source),
      v: JSON.stringify(text),
      kind: 'text',
      cap: cap === null ? null : String(cap),
      text: fmt(text, 'text'),
    };
  };

  expect(capFor(answer)).toBe(RAW_TEXT_CAP);
  expect(capFor(label)).toBeNull();
  expect(mismatches(shown(answer, RAW_TEXT_CAP))).toEqual([]);
  expect(mismatches(shown(label, null))).toEqual([]);
  expect(mismatches(shown(answer, 64))).toHaveLength(1);
  expect(mismatches(shown(answer, 1))).toHaveLength(1);
  expect(mismatches(shown(answer, null))).toHaveLength(1);
  expect(mismatches(shown(label, 1))).toHaveLength(1);
  expect(mismatches(shown(label, RAW_TEXT_CAP))).toHaveLength(1);
});

test('the sweep finds a number in any script, in a list start and outside the terms', async ({
  page,
}) => {
  // Fullwidth digits, a Roman numeral and a superscript are hand-written
  // numbers as much as ASCII digits; a list shows its start as a marker.
  await page.setContent(
    '<title>Plant</title>' +
    '<ol start="56"><li>first item</li></ol>' +
    '<p>９０ runs</p><p>Round Ⅷ</p><p>x²</p><p>Cases: 12</p>' +
    '<p><span data-src="[]">99</span></p>' +
    '<p><span data-term="">SHA-256</span> <span data-term="">SHA-512</span></p>',
  );

  expect(await page.evaluate(strayNumbers, SWEEP)).toEqual([
    'text in <p>: ９０ runs',
    'text in <p>: Round Ⅷ',
    'text in <p>: x²',
    'text in <p>: Cases: 12',
    'text in <span>: SHA-512',
    'start on <ol>: 56',
  ]);
});
