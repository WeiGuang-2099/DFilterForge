import {existsSync, readdirSync, readFileSync} from 'node:fs';
import path from 'node:path';

import {expect, test} from '@playwright/test';
import type {Browser} from '@playwright/test';

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
 * flag with the verdict kind, and a SHA-256 digest with the digest kind.
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
  const doc = new DOMParser().parseFromString(html, 'text/html');
  return Array.from(doc.querySelectorAll('[data-src]'), (element) =>
    decodeEntities(element.getAttribute('data-src') ?? ''),
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

test('the board shows the pool in its order and repair numbers from the allowed files', () => {
  // A value read from another file passes the value checks. The board's
  // passes must be the Reel's pool in pool order, never ranked, both as
  // counted rows and as repair rounds, and a repair number may come only
  // from the pool file or a pool pass's repair/summary.json, never from an
  // arm run's scored summary (docs/decisions/web-site.md, Sourced values).
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

  expect(runsOf('/scored/summary.json')).toEqual(pool);
  expect(runsOf('/repair/summary.json')).toEqual(pool);
  expect([...files].filter((file) => /-(?:cx|bare|res)(?:-r2)?-[0-9]{4}-/.test(file))).toEqual([]);
  expect([...files].filter((file) => file.includes('/repair')).sort()).toEqual(
    ['docs/results/repair-pool/test.json', ...rounds].sort(),
  );
});

test('the board labels only the registered primary comparison primary', async ({page}) => {
  // The label is fixed words, which no value check sees. Per model,
  // counterexample against bare is primary (docs/protocol.md, Repair);
  // pooled, every comparison is secondary.
  await page.goto('board/');
  const labelled = await page.locator('tr[data-label]').evaluateAll((rows) =>
    rows.map((row) => [
      row.getAttribute('data-label'),
      ...Array.from(row.querySelectorAll('th [data-fmt="text"]'), (cell) => cell.textContent),
      row.querySelector('.bd-tag')?.textContent ?? 'none',
    ]),
  );
  const models = resolver.reelPool().length;
  const pooled = ['secondary', 'secondary', 'secondary'];
  const perModel = ['primary', 'none', 'none'];

  expect(labelled.map(([label]) => label)).toEqual([
    ...pooled,
    ...Array.from({length: models}, () => perModel).flat(),
  ]);
  for (const [label, first, second, tag] of labelled) {
    expect(tag).toBe(label);
    expect(label === 'primary', `${first} - ${second}`).toBe(
      first === 'counterexample' && second === 'bare' && label !== 'secondary',
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
