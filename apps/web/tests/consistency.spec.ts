import {existsSync, readdirSync, readFileSync} from 'node:fs';
import path from 'node:path';

import {expect, test} from '@playwright/test';
import type {Browser, Page} from '@playwright/test';

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

// Routes that hold no sourced value on purpose: the not-found pages. A
// listed route must stay free of data, so this list can only shrink as
// pages gain values.
const DATA_FREE = new Set(['404/', '_not-found/', 'no-such-page/']);

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
  readonly title: string | null;
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
 * Whether a source names a scored summary's not_measured status. A page
 * shows one only as fixed words (fmt's unmeasured kind), never as the
 * status key: the scorer writes not_run there, which the protocol reserves
 * for a run ruled not run.
 */
function isNotMeasured(source: unknown): boolean {
  if (!Array.isArray(source) || source[0] !== 'ptr' || source.length !== 3) {
    return false;
  }
  const [, file, pointer] = source as readonly unknown[];
  return (
    typeof file === 'string' &&
    file.endsWith('/scored/summary.json') &&
    typeof pointer === 'string' &&
    /^\/not_measured\/[^/]+$/.test(pointer)
  );
}

/**
 * Whether a source names a comparison's inconclusive flag, in a scored
 * summary, a repair round or the repair pool. A page shows one only as its
 * verdict word (fmt's verdict kind): as yes or no it reads as the opposite
 * of a conclusive reading, and the verdict words on any other flag would
 * state a reading no comparison made.
 */
function isInconclusive(source: unknown): boolean {
  if (!Array.isArray(source) || source[0] !== 'ptr' || source.length !== 3) {
    return false;
  }
  const pointer: unknown = source[2];
  return (
    typeof pointer === 'string' && /^\/comparisons\/(?:0|[1-9][0-9]*)\/inconclusive$/.test(pointer)
  );
}

// A SHA-256 digest in lowercase hex, and how many of its digits a page
// shows: written here apart from lib/fmt.ts, so the two must agree.
const SHA256_HEX = /^[0-9a-f]{64}$/;
const DIGEST_SHOWN = 12;

/**
 * Lists what is wrong with how a value is shown as a digest, or not. A
 * SHA-256 digest must be shown with the digest kind, and only one may be:
 * a page shows its first twelve digits and keeps the whole digest in its
 * title, as well as in data-v, so the full value is there to check.
 */
function digestMismatches(value: Sourced, expected: unknown): string[] {
  const digest = typeof expected === 'string' && SHA256_HEX.test(expected);
  if (digest !== (value.kind === 'digest')) {
    return [
      `${value.src}: data-fmt is ${JSON.stringify(value.kind)}; ` +
        'a SHA-256 digest, and only one, is shown as a digest',
    ];
  }
  if (!digest) {
    return [];
  }
  const problems: string[] = [];
  if (value.title !== expected) {
    problems.push(`${value.src}: the title holds ${JSON.stringify(value.title)}, not the digest`);
  }
  if (value.text !== expected.slice(0, DIGEST_SHOWN)) {
    problems.push(`${value.src}: the page shows ${JSON.stringify(value.text)}, not its first digits`);
  }
  return problems;
}

/**
 * Re-derives one sourced value and lists what does not match. The cut of
 * model text comes from the source, never from the page's data-cap, which
 * must agree with it. A not_measured status must be shown with the
 * unmeasured kind, and only it may be; so must a comparison's inconclusive
 * flag with the verdict kind, and a SHA-256 digest with the digest kind. A
 * USD amount, shown to the cent, keeps the exact amount in its title.
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
  let notMeasured: boolean;
  let inconclusive: boolean;
  try {
    const source: unknown = JSON.parse(where);
    expected = resolver.resolve(source);
    cap = capFor(source);
    notMeasured = isNotMeasured(source);
    inconclusive = isInconclusive(source);
  } catch (error) {
    return [`${where}: ${error instanceof Error ? error.message : String(error)}`];
  }
  if (notMeasured !== (value.kind === 'unmeasured')) {
    return [
      `${where}: data-fmt is ${JSON.stringify(value.kind)}; ` +
        'a not_measured status, and only one, is shown as unmeasured',
    ];
  }
  if (inconclusive !== (value.kind === 'verdict')) {
    return [
      `${where}: data-fmt is ${JSON.stringify(value.kind)}; ` +
        "a comparison's inconclusive flag, and only one, is shown as a verdict",
    ];
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
  const digest = digestMismatches(value, expected);
  if (digest.length > 0) {
    return digest;
  }
  // The sweep skips a sourced value's attributes, so the amount a pointer
  // shows on hover is checked here.
  if (value.kind === 'usd' && value.title !== expected) {
    return [`${where}: the title holds ${JSON.stringify(value.title)}, not the amount`];
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

/** The data-src values in server-rendered HTML, outside scripts, in order. */
function markupSources(html: string): string[] {
  const markup = html.replace(/<script\b[\s\S]*?<\/script>/gi, '');
  return Array.from(markup.matchAll(/\sdata-src="([^"]*)"/g), (match) =>
    decodeEntities(match[1] ?? ''),
  );
}

/** The data-src values in server-rendered HTML, outside scripts, sorted. */
function staticSources(html: string): string[] {
  return markupSources(html).sort();
}

/** Every [data-src] element of the page and any nested in another. */
function sourcedValues(): {values: Sourced[]; nested: (string | null)[]} {
  const elements = Array.from(document.querySelectorAll('[data-src]'));
  return {
    values: elements.map((element) => ({
      src: element.getAttribute('data-src') ?? '',
      v: element.getAttribute('data-v'),
      kind: element.getAttribute('data-fmt'),
      cap: element.getAttribute('data-cap'),
      text: element.textContent ?? '',
      title: element.getAttribute('title'),
    })),
    nested: elements
      .filter((element) => element.parentElement?.closest('[data-src]'))
      .map((element) => element.getAttribute('data-src')),
  };
}

/** What a visitor is shown at one address. */
interface Visit {
  readonly status: number | undefined;
  readonly values: readonly Sourced[];
  readonly nested: readonly (string | null)[];
  readonly stray: readonly string[];
}

/**
 * Opens one address in a fresh context and reads what it shows. With
 * JavaScript the page is read after hydration; without it, as the server
 * rendered it, which is what a crawler, a visitor without JavaScript and
 * every first paint see. A plant, if given, answers the address instead of
 * the server, so a test can prove what this function catches.
 */
async function visit(
  browser: Browser,
  baseURL: string | undefined,
  target: string,
  javaScriptEnabled: boolean,
  plant?: string,
): Promise<Visit> {
  if (baseURL === undefined) {
    throw new Error('playwright.config.ts must set use.baseURL');
  }
  const context = await browser.newContext({baseURL, javaScriptEnabled, reducedMotion: 'reduce'});
  try {
    if (plant !== undefined) {
      await context.route(`**/${target}`, (route) =>
        route.fulfill({contentType: 'text/html', body: plant}),
      );
    }
    const page = await context.newPage();
    const response = await page.goto(target, {
      waitUntil: javaScriptEnabled ? 'networkidle' : 'load',
    });
    const {values, nested} = await page.evaluate(sourcedValues);
    const stray = await page.evaluate(strayNumbers, SWEEP);
    return {status: response?.status(), values, nested, stray};
  } finally {
    await context.close();
  }
}

test.use({contextOptions: {reducedMotion: 'reduce'}});

for (const route of ROUTES) {
  test(`/${route.path} shows only values the committed files hold`, async ({
    browser,
    baseURL,
    request,
  }) => {
    const target = route.path === '' ? './' : route.path;

    // Every check runs on the hydrated page and on the server-rendered one:
    // a client island could show a number on either alone.
    const hydrated = await visit(browser, baseURL, target, true);
    const server = await visit(browser, baseURL, target, false);
    for (const [where, shown] of [
      ['hydrated', hydrated],
      ['server-rendered', server],
    ] as const) {
      expect(shown.status, where).toBe(route.status);

      // 1. Every sourced value equals its re-derivation, as value and text.
      expect(shown.nested, `${where}: a sourced value inside another`).toEqual([]);
      expect(shown.values.flatMap(mismatches), where).toEqual([]);

      // 2. No number outside a sourced value, a script or style, or a term.
      expect(shown.stray, where).toEqual([]);

      // 3. A page shows at least one value unless it is data-free on purpose.
      if (DATA_FREE.has(route.path)) {
        expect(shown.values, where).toEqual([]);
      } else {
        expect(shown.values.length, where).toBeGreaterThan(0);
      }
    }

    // The raw HTML bytes hold the same values as the hydrated page.
    const html = await request.get(target, {failOnStatusCode: false});
    expect(html.status()).toBe(route.status);
    expect(staticSources(await html.text())).toEqual(
      hydrated.values.map((value) => value.src).sort(),
    );
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

test('the committed registry shows and pools the published test runs', () => {
  // The five planned test runs are published and scored and the eleven
  // conditional rows are unused, so the test phase is on. These are the
  // figures tests/test_export_web_data.py pins on the exporter's output,
  // derived here from the committed files alone; a results change updates
  // both pins in one commit.
  expect(resolver.shownRuns()).toEqual([
    'dev-qwen3-32b-2026-09-26',
    'dev-qwen3.5-9b-2026-09-26',
    'dev-ministral-8b-2512-2026-09-26',
    'dev-granite-4.2-8b-2026-09-26',
    'dev-qwen3.5-122b-a10b-2026-09-26',
    'dev-mistral-medium-3-5-2026-09-26',
    'dev-nemotron-3-super-120b-a12b-2026-09-26',
    'dev-deepseek-v4-pro-0813-2026-09-26',
    'dev-glm-5.2-2026-09-26',
    'dev-kimi-k2.6-2026-09-26',
    'test-qwen3-32b-2026-09-26',
    'test-qwen3-32b-passb-2026-09-26',
    'test-qwen3.5-9b-2026-09-26',
    'test-qwen3.5-122b-a10b-2026-09-26',
    'test-deepseek-v4-pro-0813-2026-09-26',
  ]);
  // Pass A, then the three slot winners; pass B is never pooled.
  expect(resolver.reelPool()).toEqual([
    'test-qwen3-32b-2026-09-26',
    'test-qwen3.5-9b-2026-09-26',
    'test-qwen3.5-122b-a10b-2026-09-26',
    'test-deepseek-v4-pro-0813-2026-09-26',
  ]);
  expect(resolver.reelPick()).toEqual({
    run: 'test-qwen3-32b-2026-09-26',
    cond: 'C4',
    item: 'mei-1038',
    candidates: 54,
  });
  expect(resolver.executedRoutes()).toHaveLength(1854);
  expect(resolver.caseIds()).toHaveLength(76);
  // Step 5: the pick's turn in pass A's counterexample arm run.
  expect(resolver.reelRepair()).toEqual({
    reason: null,
    run: 'test-qwen3-32b-cx-2026-09-26',
    item: 'mei-1038',
  });
  // The methodology's repair line describes the test round: pass A's, now
  // scored.
  expect(resolver.repairStatusSummary()).toBe(
    'docs/results/test-qwen3-32b-2026-09-26/scored/summary.json',
  );
  expect(resolver.repairStatusSplit()).toBe('test');
  expect(resolver.methodologyRound()).toBe(
    'docs/results/test-qwen3-32b-2026-09-26/repair/summary.json',
  );
});

test('the methodology page shows the repair status of the run the phase names', () => {
  // A status the page takes from another summary would pass the value
  // checks: every summary still says not_run after a scored round, so once
  // the named run's round is scored the page shows no status at all. The
  // server-rendered HTML holds the hydrated page's sources.
  const html = readFileSync(path.join(OUT, 'methodology', 'index.html'), 'utf8');
  const files = staticSources(html)
    .map((source): unknown => JSON.parse(source))
    .filter(isNotMeasured)
    .map((source) => (source as readonly unknown[])[1]);
  const summary = resolver.repairStatusSummary();
  const measured = resolver.methodologyRound() !== null;

  expect([...new Set(files)]).toEqual(summary === null || measured ? [] : [summary]);
});

test("the methodology page's repair round reads the cited run's round", () => {
  // A line from another pass's round would pass the value checks. Every
  // value of the page read from a repair/summary.json, the round's split
  // that labels the line included, must come from methodologyRound().
  const html = readFileSync(path.join(OUT, 'methodology', 'index.html'), 'utf8');
  const files = staticSources(html)
    .map((source) => (JSON.parse(source) as readonly unknown[])[1])
    .filter((file) => typeof file === 'string' && file.endsWith('/repair/summary.json'));
  const round = resolver.methodologyRound();

  expect([...new Set(files)]).toEqual(round === null ? [] : [round]);
  if (round !== null) {
    expect(staticSources(html)).toContain(JSON.stringify(['ptr', round, '/split']));
  }
});

test('the methodology page names the round its repair line describes', async ({page}) => {
  // Once rounds of both splits are committed, a line that names no split
  // reads as if no repair round had been measured. Its label must start
  // with the cited summary's own split, shown through fmt's split kind, so
  // a split taken from another run fails here although its value and text
  // pass the value checks.
  const summary = resolver.repairStatusSummary();
  const split = resolver.repairStatusSplit();
  // Today a summary's only not_measured key is repair_at_1, which the page
  // leaves out once the cited run's round is scored.
  const statuses =
    summary === null
      ? []
      : Object.keys(resolver.resolve(['ptr', summary, '/not_measured']) as object);
  const measured = resolver.methodologyRound() !== null;
  const keys = statuses.filter((key) => !(measured && key === 'repair_at_1'));

  await page.goto('methodology/');
  const section = page.locator('section', {
    has: page.getByRole('heading', {level: 2, name: 'Not measured yet', exact: true}),
  });
  const labels = section.locator('dl > dt');
  const sources = await labels
    .locator('[data-fmt="split"]')
    .evaluateAll((elements) => elements.map((element) => element.getAttribute('data-src')));

  expect(statuses).toEqual(summary === null ? [] : ['repair_at_1']);
  expect(await labels.allTextContents()).toEqual(
    keys.map(() => `${fmt(split, 'split')} repair round`),
  );
  expect(sources.map((source): unknown => JSON.parse(source ?? 'null'))).toEqual(
    keys.map(() => ['ptr', summary, '/split']),
  );
});

interface Accepted {
  readonly run: string;
  readonly condition: string;
  readonly item_id: string;
}

test("the methodology page's judge figure draws the table's verdicts on the pool", async ({
  page,
}) => {
  // A square's fill is a letter in its markup, c rated correct or i rated
  // incorrect, which no value check sees, and a count passes the value
  // checks whatever table pointer or pass it reads. So each row is derived
  // again from the Reel's pool, in order: its model, its counts and its
  // squares, each with the condition and item that label it and its two
  // letters, one per mode, from the committed table's lists of false
  // acceptances; and the lead and the paragraph after it must read the
  // headline counts in their order.
  const table = 'docs/results/judge-v2/table.json';
  const manifest = 'docs/results/judge-v2/test/manifest.json';
  await page.goto('methodology/');
  const section = page.locator('section[aria-labelledby="m-judge"]');
  if (!resolver.exists(table)) {
    await expect(section).toHaveCount(0);
    return;
  }
  const sourcesOf = (index: number) =>
    section
      .locator('.mth-body > p')
      .nth(index)
      .evaluate((element) =>
        Array.from(element.querySelectorAll('[data-src]'), (node): unknown =>
          JSON.parse(node.getAttribute('data-src') ?? 'null'),
        ),
      );
  const headline = (mode: string, key: string) => ['ptr', table, `/modes/${mode}/headline/${key}`];
  expect(await sourcesOf(0)).toEqual([
    headline('primary', 'silent_wrong_rated_correct'),
    headline('primary', 'silent_wrong'),
    headline('primary', 'self_silent_wrong_rated_correct'),
    headline('primary', 'self_silent_wrong'),
  ]);
  expect(await sourcesOf(1)).toEqual([
    ['ptr', manifest, '/settings/model_id'],
    headline('secondary', 'silent_wrong_rated_correct'),
    headline('secondary', 'silent_wrong'),
    headline('secondary', 'self_silent_wrong_rated_correct'),
    headline('secondary', 'self_silent_wrong'),
  ]);

  const accepted = (mode: string) => {
    const list = `/modes/${mode}/silent_wrong_rated_correct`;
    const entries = resolver.resolve(['ptr', table, list]) as readonly Accepted[];
    return new Set(entries.map((entry) => `${entry.run} ${entry.condition} ${entry.item_id}`));
  };
  const [primary, secondary] = [accepted('primary'), accepted('secondary')];
  const drawn = await section.locator('.jd-row').evaluateAll((rows) =>
    rows.map((row) => {
      const source = (node: Element | null): unknown =>
        JSON.parse(node?.getAttribute('data-src') ?? 'null');
      return {
        model: source(row.querySelector('.jd-id [data-src]')),
        counts: Array.from(row.querySelectorAll('.jd-n [data-src]'), source),
        squares: Array.from(row.querySelectorAll('.jd-q'), (square) => {
          const label = document.getElementById(`jd-n-${square.getAttribute('data-q') ?? ''}`);
          return {
            label: Array.from(label?.querySelectorAll('[data-src]') ?? [], source),
            letters: `${square.getAttribute('data-p') ?? '?'}${square.getAttribute('data-s') ?? '?'}`,
          };
        }),
      };
    }),
  );
  const pool = resolver.reelPool();
  expect(drawn.map(({model}) => model)).toEqual(
    pool.map((run) => ['ptr', `docs/results/${run}/scored/summary.json`, '/model_id']),
  );
  drawn.forEach(({counts, squares}, index) => {
    const run = pool[index] ?? '';
    const outcomes = `docs/results/${run}/scored/outcomes.jsonl`;
    const wrong = resolver
      .rows(outcomes)
      .filter((row) => row['gold_status'] === 'ready' && row['outcome'] === 'silent_wrong');
    const total = ['count', outcomes, null, {gold_status: ['ready'], outcome: ['silent_wrong']}];
    const correct = (mode: string) => [
      'count',
      table,
      `/modes/${mode}/silent_wrong_rated_correct`,
      {run: [run]},
    ];
    expect(counts, run).toEqual([correct('primary'), total, correct('secondary'), total]);
    expect(squares, run).toEqual(
      wrong.map((row) => {
        const keys = {condition: row['condition'], item_id: row['item_id']};
        const key = `${run} ${String(keys.condition)} ${String(keys.item_id)}`;
        return {
          label: [
            ['row', outcomes, keys, '/condition'],
            ['row', outcomes, keys, '/item_id'],
          ],
          letters: `${primary.has(key) ? 'c' : 'i'}${secondary.has(key) ? 'c' : 'i'}`,
        };
      }),
    );
  });
});

test('the board shows the pool in its order and repair numbers from the allowed files', () => {
  // A value read from another file passes the value checks. The board's
  // passes must be the Reel's pool in pool order, never ranked, both as
  // counted rows and as repair rounds, and a repair number may come only
  // from the pool file or a pool pass's repair/summary.json, never from an
  // arm run's scored summary (docs/decisions/web-site.md, Sourced values).
  // The self-served small model's band follows the passes, named by the
  // base row of the analysis file once that file is committed.
  const html = readFileSync(path.join(OUT, 'board', 'index.html'), 'utf8');
  const sources = markupSources(html).map(
    (source) => JSON.parse(source) as readonly [string, string, unknown],
  );
  const runsOf = (suffix: string) =>
    sources
      .filter(([op, file, at]) => op === 'ptr' && file.endsWith(suffix) && at === '/model_id')
      .map(([, file]) => file.split('/')[2]);
  const pool = resolver.reelPool();
  const rounds = pool.map((run) => `docs/results/${run}/repair/summary.json`);
  const files = new Set(sources.map(([, file]) => file));

  const analysis = 'docs/results/sft-v1/analysis.json';
  const band = existsSync(path.join(WEB, '..', '..', ...analysis.split('/')))
    ? [String(resolver.resolve(['ptr', analysis, '/base_run']))]
    : [];

  expect(runsOf('/scored/summary.json')).toEqual([...pool, ...band]);
  expect(runsOf('/repair/summary.json')).toEqual(pool);
  expect([...files].filter((file) => /-(?:cx|bare|res)(?:-r2)?-[0-9]{4}-/.test(file))).toEqual([]);
  expect([...files].filter((file) => file.includes('/repair')).sort()).toEqual(
    ['docs/results/repair-pool/test.json', ...rounds].sort(),
  );
});

/**
 * Holds the comparison labels on one page to the registered ones: the
 * pooled round's three comparisons, then each of the rounds' own three, in
 * order. Pooled, every comparison is secondary; in a round of its own,
 * counterexample against bare is primary and the two against resample carry
 * no label (docs/protocol.md, Repair).
 */
async function expectRegisteredLabels(page: Page, route: string, rounds: number): Promise<void> {
  await page.goto(route);
  const labelled = await page.locator('tr[data-label]').evaluateAll((rows) =>
    rows.map((row) => [
      row.getAttribute('data-label'),
      ...Array.from(row.querySelectorAll('th [data-fmt="text"]'), (cell) => cell.textContent),
      row.querySelector('.bd-tag')?.textContent ?? 'none',
    ]),
  );
  const pooled = ['secondary', 'secondary', 'secondary'];
  const perRound = ['primary', 'none', 'none'];

  expect(labelled.map(([label]) => label)).toEqual([
    ...pooled,
    ...Array.from({length: rounds}, () => perRound).flat(),
  ]);
  for (const [label, first, second, tag] of labelled) {
    expect(tag).toBe(label);
    expect(label === 'primary', `${first} - ${second}`).toBe(
      first === 'counterexample' && second === 'bare' && label !== 'secondary',
    );
  }
}

test('the board labels only the registered primary comparison primary', async ({page}) => {
  // The label is fixed words, which no value check sees. Per model,
  // counterexample against bare is primary (docs/protocol.md, Repair);
  // pooled, every comparison is secondary.
  await expectRegisteredLabels(page, 'board/', resolver.reelPool().length);
});

test("the training page labels only each seed's counterexample-bare comparison primary", async ({
  page,
}) => {
  // Pooled over the seeds every comparison is secondary; per seed
  // counterexample against bare is primary (docs/protocol.md, Repair,
  // amended 2026-10-26). The labels are fixed words no value check sees.
  const pool = 'docs/results/repair-pool/test-qwen3-1.7b-sft.json';
  await expectRegisteredLabels(
    page,
    'training/',
    resolver.resolve(['len', pool, '/bases']) as number,
  );
});

interface LadderRow {
  readonly row: string;
  readonly run: string;
  readonly post_hoc: boolean;
}

interface LadderRung {
  readonly rung: string;
  /** The rows the step subtracts, by name; sft_mean names the seed rows. */
  readonly first: string;
  readonly second: string;
  readonly reading: string;
  readonly discordant_cases: number;
  readonly difference: {readonly low: number; readonly high: number};
}

/** The few-shot row's example count, as the training page sources it. */
function examplesSource(ladder: string): readonly unknown[] {
  const rows = resolver.resolve(['ptr', ladder, '/rows']) as readonly LadderRow[];
  const run = rows.find((row) => row.row === 'few_shot')?.run ?? '';
  return ['ptr', `docs/results/${run}/prepare.json`, '/few_shot/k'];
}

/** The parsed data-src values under the first match of a selector, in order. */
function sourcesIn(page: Page, selector: string): Promise<unknown[]> {
  return page
    .locator(selector)
    .first()
    .evaluate((element) =>
      Array.from(element.querySelectorAll('[data-src]'), (node): unknown =>
        JSON.parse(node.getAttribute('data-src') ?? 'null'),
      ),
    );
}

/** The ladder rows that data-src values read, each once, in order. */
function ladderRows(ladder: string, sources: readonly string[]): number[] {
  const rows = sources.flatMap((source) => {
    const [, file, at] = JSON.parse(source) as [string, string, unknown];
    const found = file === ladder && typeof at === 'string' ? /^\/rows\/(\d+)\//.exec(at) : null;
    return found === null ? [] : [Number(found[1])];
  });
  return [...new Set(rows)];
}

/**
 * The value of the one sourced node, of [data-src, data-v] pairs, whose
 * pointer ends with the given keys; undefined unless exactly one does.
 */
function valueAt(shown: readonly (readonly (string | null)[])[], keys: string): unknown {
  const found = shown.filter(([source]) => {
    const at: unknown = (JSON.parse(source ?? 'null') as unknown[] | null)?.[2];
    return typeof at === 'string' && at.endsWith(`/${keys}`);
  });
  return found.length === 1 ? JSON.parse(found[0]?.[1] ?? 'null') : undefined;
}

// The outcome table's columns in the page's order: the words each shows and
// the keys it reads in a ladder row (steps.tsx, PARTS, which the bars share).
const OUTCOME_COLUMNS = [
  ['strong exact', 'outcomes/strong_exact'],
  ['silent-wrong', 'outcomes/silent_wrong'],
  ['invalid', 'outcomes/invalid'],
  ['malformed, cut at the token cap', 'malformed/truncated'],
  ['malformed, other', 'malformed/other'],
  ['shortcut', 'outcomes/shortcut'],
  ['abstained', 'outcomes/abstained'],
  ['provider failed', 'outcomes/provider_failed'],
] as const;

test("the training page's receipts mark the rule's two tests as the ladder holds them", async ({
  page,
}) => {
  // Each mark and the zero words beside it are fixed words chosen from
  // values, which no value check sees. baseline_ladder.py's rule: a step
  // reads only when its interval excludes zero, an endpoint at zero not
  // excluding it, and at least the minimum of cases are discordant; it then
  // reads a gain above zero and a loss below it. A question's summary reads
  // its own step and, besides it, only the example count, so no step stands
  // under another step's title.
  const ladder = 'docs/results/sft-v1/ladder.json';
  const rungs = resolver.resolve(['ptr', ladder, '/rungs']) as readonly LadderRung[];
  const minimum = resolver.resolve(['ptr', ladder, '/bootstrap/min_discordant_cases']) as number;
  const examples = JSON.stringify(examplesSource(ladder));
  await page.goto('training/');
  const drawn = await page.locator('li.tr-q').evaluateAll((items) =>
    items.map((item) => ({
      rung: item.getAttribute('data-rung'),
      summary: Array.from(
        item.querySelectorAll(':scope > details > summary [data-src]'),
        (node) => node.getAttribute('data-src') ?? '',
      ),
      tests: Array.from(item.querySelectorAll('[data-test]'), (test) => ({
        test: test.getAttribute('data-test'),
        pass: test.getAttribute('data-pass'),
        text: test.textContent ?? '',
      })),
    })),
  );

  expect(drawn.map(({rung}) => rung)).toEqual(rungs.map(({rung}) => rung));
  rungs.forEach((rung, index) => {
    const own = (source: string) => {
      const [, file, at] = JSON.parse(source) as [string, string, unknown];
      return file === ladder && typeof at === 'string' && at.startsWith(`/rungs/${String(index)}/`);
    };
    const summary = drawn[index]?.summary ?? [];
    expect(summary.some(own), rung.rung).toBe(true);
    expect(
      summary.filter((source) => !own(source)),
      rung.rung,
    ).toEqual(summary.filter((source) => source === examples));
    const zero = rung.difference.low > 0 || rung.difference.high < 0;
    const enough = rung.discordant_cases >= minimum;
    const tests = drawn[index]?.tests ?? [];
    expect(
      tests.map(({test, pass}) => [test, pass]),
      rung.rung,
    ).toEqual([
      ['zero', zero ? 'yes' : 'no'],
      ['discordant', enough ? 'yes' : 'no'],
    ]);
    expect(tests[0]?.text, rung.rung).toContain(zero ? 'excludes zero' : 'includes zero');
    // The committed reading is the rule's word, which the page shows: a gain
    // or a loss only when both tests hold, by the interval's side of zero.
    expect(rung.reading, rung.rung).toBe(
      zero && enough ? (rung.difference.low > 0 ? 'gain' : 'loss') : 'inconclusive',
    );
  });
});

test('the training page tags exactly the post hoc rows post hoc', async ({page}) => {
  // No value check sees the tag; the protocol labels both baseline rows
  // post hoc wherever they are shown (Training rules, amended 2026-10-26).
  // Each labelled row of the strip, the receipts' bars and both tables
  // draws from one ladder row; it carries the tag exactly when ladder.json
  // marks that row post hoc, and the example count exactly when it is the
  // few-shot row. Each table lists every row in ladder order.
  const ladder = 'docs/results/sft-v1/ladder.json';
  const rows = resolver.resolve(['ptr', ladder, '/rows']) as readonly LadderRow[];
  const examples = JSON.stringify(examplesSource(ladder));
  await page.goto('training/');
  const section = page.locator('section[aria-labelledby="tr-steps"]');
  await expect(section.locator('h2 [data-tag="post-hoc"]')).toHaveCount(
    resolver.resolve(['ptr', ladder, '/post_hoc']) === true ? 1 : 0,
  );
  const items = await section
    .locator('.tr-flow > li, .tr-mix, table.tr-table tbody tr')
    .evaluateAll((all) =>
      all.map((item) => ({
        table: item.closest('table') !== null,
        tagged: item.querySelector('[data-tag="post-hoc"]') !== null,
        sources: Array.from(
          item.querySelectorAll('[data-src]'),
          (node) => node.getAttribute('data-src') ?? '',
        ),
      })),
    );
  const listed: number[] = [];
  for (const {table, tagged, sources} of items) {
    const drawn = new Set(
      sources.flatMap((source) => {
        const [, file, at] = JSON.parse(source) as [string, string, unknown];
        const found =
          file === ladder && typeof at === 'string' ? /^\/rows\/(\d+)\//.exec(at) : null;
        return found === null ? [] : [Number(found[1])];
      }),
    );
    expect(drawn.size, sources.join(' ')).toBeLessThanOrEqual(1);
    const [index] = [...drawn];
    const row = index === undefined ? undefined : rows[index];
    expect(tagged, sources.join(' ')).toBe(row?.post_hoc === true);
    expect(sources.includes(examples), sources.join(' ')).toBe(row?.row === 'few_shot');
    if (table && index !== undefined) {
      listed.push(index);
    }
  }
  const order = rows.map((_, index) => index);
  expect(listed).toEqual([...order, ...order]);
});

test("the training page's ledes and strip read each value in its place", async ({page}) => {
  // A value swapped with another of its kind passes every value check, and
  // the words beside it are fixed: the schema and few-shot rates could trade
  // places, and so could the first two steps' readings, which both read
  // inconclusive. Rows, steps and arms are found by their keys in the
  // committed files.
  const ladder = 'docs/results/sft-v1/ladder.json';
  const pool = 'docs/results/repair-pool/test-qwen3-1.7b-sft.json';
  const rows = resolver.resolve(['ptr', ladder, '/rows']) as readonly LadderRow[];
  const rungs = resolver.resolve(['ptr', ladder, '/rungs']) as readonly LadderRung[];
  const arms = resolver.resolve(['ptr', pool, '/arms']) as readonly {readonly arm: string}[];
  const at = (pointer: string) => ['ptr', ladder, pointer];
  const row = (name: string) => `/rows/${String(rows.findIndex((each) => each.row === name))}`;
  const rung = (name: string) =>
    `/rungs/${String(rungs.findIndex((each) => each.rung === name))}`;
  const arm = (code: string) => `/arms/${String(arms.findIndex((each) => each.arm === code))}`;
  const rate = (base: string) => ['value', 'low', 'high'].map((key) => at(`${base}/rate/${key}`));
  const step = (name: string) => [at(`${rung(name)}/difference/value`), at(`${rung(name)}/reading`)];
  const examples = examplesSource(ladder);
  const steps = ['schema_minus_base', 'few_shot_minus_schema', 'sft_mean_minus_few_shot'];
  await page.goto('training/');

  expect(await sourcesIn(page, 'section[aria-labelledby="tr-steps"] p.tr-sec-lede')).toEqual([
    at('/cases'),
    at('/condition'),
    at(`${row('base')}/rate/value`),
    at(`${row('schema')}/rate/value`),
    examples,
    at(`${row('few_shot')}/rate/value`),
    at('/sft_mean/rate/value'),
    ...steps.map((name) => at(`${rung(name)}/reading`)),
  ]);
  expect(await sourcesIn(page, 'ol.tr-flow')).toEqual([
    ...rate(row('base')),
    ...step('schema_minus_base'),
    ...rate(row('schema')),
    ...step('few_shot_minus_schema'),
    examples,
    ...rate(row('few_shot')),
    ...step('sft_mean_minus_few_shot'),
    ...rate('/sft_mean'),
  ]);
  expect(await sourcesIn(page, 'section[aria-labelledby="tr-repair"] p.tr-sec-lede')).toEqual([
    ['ptr', pool, `${arm('counterexample')}/triggered_items`],
    ...['counterexample', 'bare', 'resample'].map((code) => [
      'ptr',
      pool,
      `${arm(code)}/repaired`,
    ]),
  ]);
});

test("the training page's cost reads each amount in its place", async ({page}) => {
  // The section sets values of one kind beside fixed words: four USD amounts
  // in its lead and paragraph, and each session's requests, GPU hours and
  // bill. Swapped, each still passes every value check: the bill would read
  // as the cost per thousand requests. The table is read cell by cell under
  // its header words, so a value moved to another column fails too.
  const cost = 'docs/results/sft-v1/cost.json';
  const at = (pointer: string) => ['ptr', cost, pointer];
  const sessions = resolver.resolve(['ptr', cost, '/sessions']) as readonly {
    readonly unread: unknown;
  }[];
  const unread = sessions.findIndex((session) => session.unread !== null);
  const section = 'section[aria-labelledby="tr-cost"]';
  await page.goto('training/');

  expect(await sourcesIn(page, `${section} p.tr-cost-big`)).toEqual([
    at('/total/usd_per_1000_requests'),
  ]);
  expect(await sourcesIn(page, `${section} p.tr-sub`)).toEqual([
    at('/total/requests'),
    ['len', cost, '/sessions'],
    at('/total/bill_usd'),
    at('/total/gpu_hours'),
    at(`/sessions/${String(unread)}/unread/requests`),
    at('/total/gpu_usd'),
    at('/usd_per_gpu_hour'),
  ]);
  expect(await sourcesIn(page, `${section} p.tr-note`)).toEqual([
    at('/excluded/date'),
    at('/excluded/bill_usd'),
  ]);
  const table = await page.locator(`${section} table`).evaluate((element) => ({
    head: Array.from(element.querySelectorAll('thead th'), (cell) => cell.textContent),
    body: Array.from(element.querySelectorAll('tbody tr'), (row) =>
      Array.from(row.children, (cell) =>
        Array.from(cell.querySelectorAll('[data-src]'), (node): unknown =>
          JSON.parse(node.getAttribute('data-src') ?? 'null'),
        ),
      ),
    ),
  }));
  expect(table.head).toEqual(['Session', 'Requests', 'GPU hours', 'Bill', 'What it sent']);
  expect(table.body).toEqual(
    sessions.map((session, index) => {
      const of = (key: string) => `/sessions/${String(index)}/${key}`;
      return [
        [at(of('date'))],
        [at(of('requests'))],
        [at(of('gpu_hours'))],
        [at(of('bill_usd'))],
        [
          ['len', cost, of('runs')],
          ...(session.unread === null
            ? []
            : [['len', cost, of('unread/runs')], at(of('unread/requests'))]),
        ],
      ];
    }),
  );
});

test("the training page's tables and questions read each count under its words", async ({
  page,
}) => {
  // A count swapped with another of its row passes every value check, and
  // the words above or beside it are fixed: silent-wrong and invalid, the two
  // malformed parts, the two coverage strata, or a question's cases better
  // and worse could trade places, and a question could draw another step's
  // rows.
  const ladder = 'docs/results/sft-v1/ladder.json';
  const rows = resolver.resolve(['ptr', ladder, '/rows']) as readonly LadderRow[];
  const rungs = resolver.resolve(['ptr', ladder, '/rungs']) as readonly LadderRung[];
  const at = (pointer: string) => ['ptr', ladder, pointer];
  const strata = [
    ['every_gold_field_retrieved', 'Every gold field retrieved'],
    ['some_gold_field_missing', 'Some gold field missing'],
  ] as const;
  await page.goto('training/');
  const read = (labelledBy: string) =>
    page.locator(`table[aria-labelledby="${labelledBy}"]`).evaluate((element) => {
      const sources = (cell: Element) =>
        Array.from(cell.querySelectorAll('[data-src]'), (node): unknown =>
          JSON.parse(node.getAttribute('data-src') ?? 'null'),
        );
      return {
        head: Array.from(element.querySelectorAll('thead th'), (cell) => ({
          words: cell.textContent ?? '',
          sources: sources(cell),
        })),
        body: Array.from(element.querySelectorAll('tbody tr'), (row) =>
          Array.from(row.querySelectorAll('td'), sources),
        ),
      };
    });
  const outcomes = await read('tr-steps-outcomes');
  expect(outcomes.head).toEqual(
    ['Row', ...OUTCOME_COLUMNS.map(([words]) => words)].map((words) => ({words, sources: []})),
  );
  expect(outcomes.body).toEqual(
    rows.map((_, index) => OUTCOME_COLUMNS.map(([, key]) => [at(`/rows/${String(index)}/${key}`)])),
  );
  const coverage = await read('tr-steps-coverage');
  expect(coverage.head.map(({words, sources}) => ({words: words.split(',')[0], sources}))).toEqual([
    {words: 'Row', sources: []},
    ...strata.map(([key, words]) => ({words, sources: [at(`/coverage_items/${key}`)]})),
  ]);
  expect(coverage.body).toEqual(
    rows.map((_, index) =>
      strata.map(([key]) =>
        ['value', 'low', 'high'].map((bound) =>
          at(`/rows/${String(index)}/coverage/${key}/${bound}`),
        ),
      ),
    ),
  );
  // A question's bars draw its first row or rows, then its second.
  const rowsOf = (name: string) =>
    rows.flatMap((row, index) =>
      row.row === (name === 'sft_mean' ? 'sft' : name) ? [[index]] : [],
    );
  for (const [index, rung] of rungs.entries()) {
    const question = `li.tr-q[data-rung="${rung.rung}"]`;
    expect(await sourcesIn(page, `${question} .tr-of`), rung.rung).toEqual(
      ['first', 'second'].map((side) => at(`/rungs/${String(index)}/${side}_better_cases`)),
    );
    const bars = await page.locator(`${question} .tr-mix`).evaluateAll((all) =>
      all.map((mix) =>
        Array.from(
          mix.querySelectorAll('[data-src]'),
          (node) => node.getAttribute('data-src') ?? '',
        ),
      ),
    );
    expect(bars.map((sources) => ladderRows(ladder, sources)), rung.rung).toEqual([
      ...rowsOf(rung.first),
      ...rowsOf(rung.second),
    ]);
  }
});

test('the training page draws each mark from the counts and bounds it shows', async ({page}) => {
  // A square, a bar part's width and a scale's positions are geometry, which
  // no value check sees. Each arm draws one square per failed answer and
  // fills its repaired ones first, each part of a bar grows by the count it
  // hides, and each question's interval and value sit at the bounds and value
  // its summary shows. A style property left out reads as no number.
  const pool = 'docs/results/repair-pool/test-qwen3-1.7b-sft.json';
  const ladder = 'docs/results/sft-v1/ladder.json';
  await page.goto('training/');
  const arms = await page
    .locator('section[aria-labelledby="tr-repair"] .tr-arm')
    .evaluateAll((all) =>
      all.map((arm) => ({
        shown: Array.from(arm.querySelectorAll('[data-src]'), (node) => [
          node.getAttribute('data-src'),
          node.getAttribute('data-v'),
        ]),
        filled: Array.from(arm.querySelectorAll('.tr-sq'), (square) =>
          square.classList.contains('tr-sq-on'),
        ),
      })),
    );
  expect(arms).toHaveLength(resolver.resolve(['len', pool, '/arms']) as number);
  for (const {shown, filled} of arms) {
    const [triggered, repaired] = [valueAt(shown, 'triggered_items'), valueAt(shown, 'repaired')];
    expect(filled, `${String(repaired)} of ${String(triggered)}`).toEqual(
      Array.from({length: Number(triggered)}, (_, index) => index < Number(repaired)),
    );
  }

  const parts = await page.locator('.tr-mix .tr-seg').evaluateAll((all) =>
    all.map((part) => ({
      grow: part.style.flexGrow,
      count: part.querySelector('[data-src]')?.getAttribute('data-v') ?? 'null',
    })),
  );
  expect(parts.length).toBeGreaterThan(0);
  expect(parts.map(({grow}) => (grow === '' ? null : Number(grow)))).toEqual(
    parts.map(({count}): unknown => JSON.parse(count)),
  );

  const scales = await page.locator('li.tr-q').evaluateAll((items) =>
    items.map((item) => {
      const scale = item.querySelector<HTMLElement>('.tr-scale');
      return {
        drawn: ['--lo', '--hi', '--v'].map((name) => {
          const text = scale?.style.getPropertyValue(name) ?? '';
          return text === '' ? null : Number(text);
        }),
        shown: Array.from(item.querySelectorAll('.tr-val [data-src]'), (node) => [
          node.getAttribute('data-src'),
          node.getAttribute('data-v'),
        ]),
      };
    }),
  );
  expect(scales).toHaveLength(resolver.resolve(['len', ladder, '/rungs']) as number);
  for (const {drawn, shown} of scales) {
    expect(drawn).toEqual(
      ['low', 'high', 'value'].map((key) => valueAt(shown, `difference/${key}`)),
    );
  }
});

interface TracedProbe {
  readonly probe_id: string;
  readonly counterexample_frames: readonly number[];
  readonly candidate_predicates: readonly {readonly matched_frames: readonly number[]}[];
  readonly canonical_predicates: readonly {readonly matched_frames: readonly number[]}[];
}

test("the Reel's ladder and readout say what the receipt, packets and trace hold", async ({
  page,
}) => {
  // The readout says in fixed words whether the filter and the request
  // select each frame and what each traced leaf gave, and the ladder draws
  // each frame's direction: none of it is a sourced value, so no value
  // check sees it. Here every word and direction is derived again from the
  // pick's receipt, packets.json and the committed trace, for every frame
  // of every probe.
  const pick = resolver.reelPick();
  if (pick === null) {
    throw new Error('the committed pool has a pick');
  }
  const receipt = `docs/results/${pick.run}/scored/receipts/${pick.cond}/${pick.item}.json`;
  const probes = resolver.resolve(['ptr', receipt, '/probes']) as readonly {
    readonly probe_id: string;
    readonly expected_frames: readonly number[];
    readonly candidate_frames: readonly number[];
  }[];
  const packets = 'docs/decisions/evidence/web/packets.json';
  const lists = resolver.resolve(['ptr', packets, '/probes']) as readonly {
    readonly probe_id: string;
    readonly frames: readonly {readonly direction: string}[];
  }[];
  const trace = `docs/decisions/evidence/web/traces/${pick.run}/${pick.cond}/${pick.item}.json`;
  const traced = resolver.resolve(['ptr', trace, '/result/trace/probes']) as readonly TracedProbe[];

  await page.goto('./');
  const read = (selector: string, attribute: string) =>
    page.locator(selector).evaluateAll(
      (cells, name) =>
        cells.map((cell) => [cell.getAttribute('data-at'), cell.getAttribute(name), cell.textContent]),
      attribute,
    );
  const ladder = await read('.lad-tx .fr', 'data-dir');
  const results = await read('.tr2-res [data-state]', 'data-state');
  const roots = await read('.rt .at', 'data-at');
  const leaves = await read('[data-leaf]', 'data-leaf');

  const states = probes.map((probe) => {
    const list = lists.find((each) => each.probe_id === probe.probe_id);
    return (list?.frames ?? []).map((frame, row) => {
      const selected = probe.candidate_frames.includes(row + 1);
      const requested = probe.expected_frames.includes(row + 1);
      const state = selected ? (requested ? 'tp' : 'fp') : requested ? 'fn' : 'tn';
      return {at: `${probes.indexOf(probe)}-${row}`, state, selected, requested, dir: frame.direction};
    });
  });
  const frames = states.flat();
  expect(ladder.map(([at, dir]) => [at, dir])).toEqual(frames.map((f) => [f.at, f.dir]));
  expect(results).toEqual(
    frames.map((f) => [f.at, f.state, f.selected === f.requested ? 'agree' : 'disagree']),
  );
  // Each probe's request root, then its filter root.
  expect(roots).toEqual(
    states.flatMap((rows) => [
      ...rows.map((f) => [f.at, f.at, f.requested ? 'should match' : 'should not match']),
      ...rows.map((f) => [f.at, f.at, f.selected ? 'matched' : 'not matched']),
    ]),
  );
  // Each request leaf, then each filter leaf: true or false where traced.
  expect(leaves).toEqual(
    states.flatMap((rows, index) => {
      const probe = traced[index];
      const sides = [
        ['request', probe?.canonical_predicates ?? []],
        ['filter', probe?.candidate_predicates ?? []],
      ] as const;
      return sides.flatMap(([side, list]) =>
        list.flatMap((leaf, at) =>
          rows.map((f, row) => [
            f.at,
            `${side}-${at}`,
            probe?.counterexample_frames.includes(row + 1) === true
              ? String(leaf.matched_frames.includes(row + 1))
              : '-',
          ]),
        ),
      );
    }),
  );
  expect(frames.filter((f) => f.selected !== f.requested)).not.toEqual([]);
  expect(leaves.filter(([, , word]) => word === 'false')).not.toEqual([]);
});

interface Replayed {
  readonly run_id: string;
  readonly receipt: string;
  readonly v1: string;
  readonly v2: string;
}

interface ScoredProbe {
  readonly probe_id: string;
  readonly expected_frames: readonly number[];
  readonly candidate_frames: readonly number[];
  readonly candidate_only: readonly number[];
  readonly reference_only: readonly number[];
}

test('the exhibits page draws what the replay and the receipts hold', async ({page}) => {
  // A square's look, a tape's cells and the words beside a killing frame
  // are geometry and fixed words, which no value check sees. Here each is
  // derived again: every row's squares, as verdict pairs and rings, from
  // the committed replay and the Reel's pool; every turned answer's tapes
  // and killing frames from its receipt and the frame tables.
  const replay = 'docs/decisions/evidence/web/exhibits.json';
  const answers = resolver.resolve([
    'ptr',
    replay,
    '/sources/hosted_test/answers',
  ]) as readonly Replayed[];
  const letters: Readonly<Record<string, string>> = {
    strong_exact: 'e',
    shortcut: 's',
    silent_wrong: 'w',
    unscorable: 'u',
  };
  const turned = (each: Replayed) =>
    (each.v1 === 'strong_exact' || each.v1 === 'shortcut') && each.v2 === 'silent_wrong';
  const square = (each: Replayed) =>
    `${letters[each.v1] ?? '?'}${letters[each.v2] ?? '?'}${turned(each) ? ' ringed' : ''}`;
  const tables = resolver.resolve([
    'ptr',
    'docs/decisions/evidence/web/captures.json',
    '/probes',
  ]) as readonly {readonly probe_id: string; readonly frames: readonly unknown[]}[];
  const sides = {
    candidate_only: 'matched; the labels leave it out',
    reference_only: 'labelled; the answer misses it',
  };

  await page.goto('exhibits/');
  const rows = await page.locator('.xh-row').evaluateAll((all) =>
    all.map((row) =>
      Array.from(row.querySelectorAll('.xh-cells .xh-q'), (each) =>
        [
          `${each.getAttribute('data-a') ?? '?'}${each.getAttribute('data-t') ?? '?'}`,
          each.classList.contains('xh-q-k') ? ' ringed' : '',
        ].join(''),
      ).sort(),
    ),
  );
  expect(rows).toEqual(
    resolver
      .reelPool()
      .map((run) => answers.filter((each) => each.run_id === run).map(square).sort()),
  );

  // Each turned answer by its receipt digest: its tapes and its packet lists.
  const drawn = await page.locator('article.xh-ex').evaluateAll((cards) =>
    cards.flatMap((card) =>
      Array.from(card.querySelectorAll('.xh-rcpt [data-fmt="digest"]'), (digest) => {
        const at = digest.closest('[data-ans]')?.getAttribute('data-ans') ?? '';
        const source = JSON.parse(digest.getAttribute('data-src') ?? '[]') as unknown[];
        const tapes = card.querySelector(`.xh-tapes-in[data-ans~="${at}"]`);
        return {
          receipt: String(source[1]),
          states: Array.from(tapes?.querySelectorAll('[data-p]') ?? [], (tape) =>
            Array.from(tape.querySelectorAll('[data-s]'), (cell) => cell.getAttribute('data-s')),
          ),
          kills: Array.from(card.querySelectorAll(`[data-pr][data-ans~="${at}"]`), (list) =>
            Array.from(list.querySelectorAll('tbody tr'), (row) => [
              Number(row.querySelector('[data-fmt="int"]')?.getAttribute('data-v')),
              row.querySelector('.xh-pl-side')?.textContent ?? '',
            ]),
          ),
        };
      }),
    ),
  );
  expect(drawn.map(({receipt}) => receipt).sort()).toEqual(
    answers
      .filter(turned)
      .map((each) => each.receipt)
      .sort(),
  );
  for (const {receipt, states, kills} of drawn) {
    const probes = resolver.resolve(['ptr', receipt, '/probes']) as readonly ScoredProbe[];
    expect({states, kills}, receipt).toEqual({
      states: probes.map((probe) => {
        const frames = tables.find((table) => table.probe_id === probe.probe_id)?.frames ?? [];
        return frames.map((_, row) => {
          const selected = probe.candidate_frames.includes(row + 1);
          const requested = probe.expected_frames.includes(row + 1);
          return selected ? (requested ? 'tp' : 'fp') : requested ? 'fn' : 'tn';
        });
      }),
      kills: probes.map((probe) =>
        [
          ...probe.candidate_only.map((frame) => [frame, sides.candidate_only] as const),
          ...probe.reference_only.map((frame) => [frame, sides.reference_only] as const),
        ].sort(([first], [second]) => first - second),
      ),
    });
  }
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
      title: null,
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

test('a not_measured status is shown as fixed words and never as its key', () => {
  // The scorer's not_run means no round has measured it yet; shown as
  // written it would read as the protocol's "not run". Fixed words for any
  // other source would hide its value.
  const run = resolver.shownRuns()[0] ?? '';
  const status = ['ptr', `docs/results/${run}/scored/summary.json`, '/not_measured/repair_at_1'];
  const label = ['ptr', `docs/results/${run}/prepare.json`, '/conditions/0/label'];
  const shown = (source: readonly string[], kind: string, text: string): Sourced => ({
    src: JSON.stringify(source),
    v: JSON.stringify(resolver.resolve(source)),
    kind,
    cap: null,
    text,
    title: null,
  });
  const key = String(resolver.resolve(status));

  expect(key).toBe('not_run');
  expect(mismatches(shown(status, 'unmeasured', 'not measured yet'))).toEqual([]);
  expect(mismatches(shown(status, 'text', key))).toHaveLength(1);
  expect(mismatches(shown(status, 'unmeasured', key))).toHaveLength(1);
  expect(mismatches(shown(label, 'unmeasured', 'not measured yet'))).toHaveLength(1);
});

test("a comparison's inconclusive flag is shown as its verdict, and nothing else is", () => {
  // As yes or no the flag reads as the opposite of a conclusive reading;
  // the verdict words on another boolean would state a reading.
  const summary = 'docs/results/test-qwen3-32b-2026-09-26/scored/summary.json';
  const flag = ['ptr', 'docs/results/repair-pool/test.json', '/comparisons/0/inconclusive'];
  const setting = ['ptr', summary, '/effective_settings/json_mode'];
  const shown = (source: readonly string[], kind: 'bool' | 'verdict'): Sourced => {
    const value = resolver.resolve(source);
    return {
      src: JSON.stringify(source),
      v: JSON.stringify(value),
      kind,
      cap: null,
      text: fmt(value, kind),
      title: null,
    };
  };

  expect(resolver.resolve(flag)).toBe(false);
  expect(mismatches(shown(flag, 'verdict'))).toEqual([]);
  expect(mismatches(shown(flag, 'bool'))).toHaveLength(1);
  expect(mismatches(shown(setting, 'bool'))).toEqual([]);
  expect(mismatches(shown(setting, 'verdict'))).toHaveLength(1);
});

test('a SHA-256 digest shows its first twelve digits and keeps the whole digest', () => {
  // A page shows a digest short, so the check must see that the short text
  // is the start of the committed digest, that the whole digest is still in
  // the markup, and that no digest is shown whole or as another kind.
  const digest = ['ptr', 'src/dfilterforge/held_out_freeze.json', '/admitted_prepares/0'];
  const run = resolver.shownRuns()[0] ?? '';
  const label = ['ptr', `docs/results/${run}/prepare.json`, '/conditions/0/label'];
  const shown = (
    source: readonly string[],
    kind: string,
    text: string,
    title: string | null,
  ): Sourced => ({
    src: JSON.stringify(source),
    v: JSON.stringify(resolver.resolve(source)),
    kind,
    cap: null,
    text,
    title,
  });
  const full = String(resolver.resolve(digest));
  const short = full.slice(0, 12);
  const name = String(resolver.resolve(label));

  expect(full).toMatch(/^[0-9a-f]{64}$/);
  expect(mismatches(shown(digest, 'digest', short, full))).toEqual([]);
  expect(mismatches(shown(digest, 'text', full, null))).toHaveLength(1);
  expect(mismatches(shown(digest, 'digest', full, full))).toHaveLength(1);
  expect(mismatches(shown(digest, 'digest', full.slice(0, 11), full))).toHaveLength(1);
  expect(mismatches(shown(digest, 'digest', short, null))).toHaveLength(1);
  expect(mismatches(shown(digest, 'digest', short, short))).toHaveLength(1);
  expect(mismatches(shown(label, 'text', name, null))).toEqual([]);
  expect(mismatches(shown(label, 'digest', name, name))).toHaveLength(1);
});

test('a USD amount keeps the exact amount in its title', () => {
  // The title is what a pointer shows on hover. Another amount there, or the
  // amount rounded as the text shows it, would pass every other check.
  const cost = 'docs/results/sft-v1/cost.json';
  const bill = ['ptr', cost, '/total/bill_usd'];
  const amount = String(resolver.resolve(bill));
  const other = String(resolver.resolve(['ptr', cost, '/total/gpu_usd']));
  const shown = (title: string | null): Sourced => ({
    src: JSON.stringify(bill),
    v: JSON.stringify(amount),
    kind: 'usd',
    cap: null,
    text: fmt(amount, 'usd'),
    title,
  });

  expect(mismatches(shown(amount))).toEqual([]);
  expect(mismatches(shown(other))).toHaveLength(1);
  expect(mismatches(shown(fmt(amount, 'usd')))).toHaveLength(1);
  expect(mismatches(shown(null))).toHaveLength(1);
});

test('the sweep finds a number in any script, in a list start and outside the terms', async ({
  page,
}) => {
  // Fullwidth digits, a Roman numeral and a superscript are hand-written
  // numbers as much as ASCII digits; a list shows its start as a marker.
  await page.setContent(
    '<title>Plant</title>' +
    '<ol start="56"><li>first item</li></ol>' +
    '<p>\uff19\uff10 runs</p><p>Round \u2167</p><p>x\u00b2</p><p>Cases: 12</p>' +
    '<p><span data-src="[]">99</span></p>' +
    '<p><span data-term="">SHA-256</span> <span data-term="">SHA-512</span></p>',
  );

  expect(await page.evaluate(strayNumbers, SWEEP)).toEqual([
    'text in <p>: \uff19\uff10 runs',
    'text in <p>: Round \u2167',
    'text in <p>: x\u00b2',
    'text in <p>: Cases: 12',
    'text in <span>: SHA-512',
    'start on <ol>: 56',
  ]);
});

test('the server-rendered sweep finds a number that hydration removes', async ({
  browser,
  baseURL,
}) => {
  // The plant's HTML shows a hand-typed number and its script removes it,
  // as a client island that renders differently after hydration would.
  const plant =
    '<!doctype html><title>Plant</title>' +
    '<p id="before">Seventy-eight: 78 runs</p>' +
    "<script>document.getElementById('before').remove();</script>";

  const hydrated = await visit(browser, baseURL, 'plant/', true, plant);
  const server = await visit(browser, baseURL, 'plant/', false, plant);

  expect(hydrated.status).toBe(200);
  expect(hydrated.stray).toEqual([]);
  expect(server.stray).toEqual(['text in <p>: Seventy-eight: 78 runs']);
});
