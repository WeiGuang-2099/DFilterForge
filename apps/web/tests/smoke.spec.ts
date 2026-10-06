import {existsSync} from 'node:fs';
import {request as httpRequest} from 'node:http';
import {join} from 'node:path';

import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';

import {basePath} from '../scripts/base_path.mjs';

// Paths are relative so that they resolve under the base URL, which ends in
// the base path and a slash.
const PAGES = [
  {path: './', status: 200, heading: /^Frame [0-9]+ disproves \(/},
  {path: 'methodology/', status: 200, heading: 'Evidence has a boundary.'},
  {path: 'no-such-page/', status: 404, heading: 'This page does not exist.'},
] as const;

function requireBaseURL(baseURL: string | undefined): string {
  if (baseURL === undefined) {
    throw new Error('playwright.config.ts must set use.baseURL');
  }
  return baseURL;
}

const OUT = join(__dirname, '..', 'out');

// Next 16.3.4 writes a nested segment's prefetch file into a subdirectory
// when it exports on Windows (methodology/__next.methodology/__PAGE__.txt):
// export/index.js builds the name from path.relative, which joins with
// backslashes there. The client requests the flat name
// (methodology/__next.methodology.__PAGE__.txt), which a Linux build writes,
// so CI, Docker and Pages are unaffected. A 404 for a flat name whose
// Windows-layout file exists is that defect and nothing else.
function isWindowsSegmentFile(url: string): boolean {
  const relative = new URL(url).pathname.slice(basePath.length + 1);
  const match = /^((?:[^/]+\/)*)__next\.([^/]+)\.txt$/.exec(relative);
  if (match === null) {
    return false;
  }
  const [, directory = '', segmentPath = ''] = match;
  const parts = segmentPath.split('.');
  return parts.length > 1 && existsSync(join(OUT, directory, `__next.${parts.join('/')}.txt`));
}

// Sends a GET with the path exactly as given; Playwright's request API
// normalizes "." and ".." segments before they reach the server.
function rawGet(baseURL: string, path: string): Promise<{status: number; body: string}> {
  const {hostname, port} = new URL(baseURL);
  return new Promise((resolve, reject) => {
    const request = httpRequest({host: hostname, port, path, method: 'GET'}, (response) => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', (chunk: string) => {
        body += chunk;
      });
      response.on('end', () => resolve({status: response.statusCode ?? 0, body}));
    });
    request.on('error', reject);
    request.end();
  });
}

for (const {path, status, heading} of PAGES) {
  // tests/consistency.spec.ts checks every value and every stray digit.
  test(`${path} renders its heading`, async ({page}) => {
    const response = await page.goto(path);

    expect(response?.status()).toBe(status);
    await expect(page.getByRole('heading', {level: 1, name: heading})).toBeVisible();
  });

  test(`${path} links and loads only under the base path`, async ({page}) => {
    // Failed statuses only: the router's HEAD probe before a prefetch is
    // reported as aborted even when it gets its 200.
    const failures: string[] = [];
    page.on('response', (response) => {
      const url = response.url();
      if (
        response.status() >= 400 &&
        response.request().resourceType() !== 'document' &&
        !isWindowsSegmentFile(url)
      ) {
        failures.push(`${response.status()} ${url}`);
      }
    });

    await page.goto(path, {waitUntil: 'networkidle'});

    const urls = await page.evaluate(() => [
      ...Array.from(document.querySelectorAll('[href]'), (node) => node.getAttribute('href')),
      ...Array.from(document.querySelectorAll('[src]'), (node) => node.getAttribute('src')),
    ]);
    const rooted = urls.filter((url): url is string => url !== null && url.startsWith('/'));
    expect(rooted.length).toBeGreaterThan(0);
    expect(rooted.filter((url) => !url.startsWith(`${basePath}/`))).toEqual([]);
    expect(failures).toEqual([]);
  });

  test(`${path} has no serious accessibility violations`, async ({page}) => {
    await page.goto(path);

    const results = await new AxeBuilder({page}).analyze();
    const seriousOrCritical = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );

    expect(seriousOrCritical).toEqual([]);
  });
}

test('client navigation stays under the base path', async ({page}) => {
  await page.goto('./');

  await page
    .getByRole('navigation', {name: 'Primary navigation'})
    .getByRole('link', {name: 'Methodology'})
    .click();

  await expect(
    page.getByRole('heading', {level: 1, name: 'Evidence has a boundary.'}),
  ).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`${basePath}/methodology/`);
});

test('a directory path without its slash redirects to it', async ({request, baseURL}) => {
  const page = await request.get('methodology', {maxRedirects: 0});
  expect(page.status()).toBe(301);
  expect(page.headers()['location']).toBe(`${basePath}/methodology/`);

  if (basePath !== '') {
    const root = await request.get(new URL(basePath, requireBaseURL(baseURL)).href, {
      maxRedirects: 0,
    });
    expect(root.status()).toBe(301);
    expect(root.headers()['location']).toBe(`${basePath}/`);
  }
});

test('nothing outside the base path is served', async ({request, baseURL}) => {
  test.skip(basePath === '', 'the site is served at the root');

  const response = await request.get(new URL('/index.html', requireBaseURL(baseURL)).href);

  expect(response.status()).toBe(404);
});

test('a path that could leave the export directory is refused', async ({baseURL}) => {
  const site = requireBaseURL(baseURL);
  for (const path of [
    `${basePath}/../package.json`,
    `${basePath}/%2e%2e/package.json`,
    `${basePath}/..%2Fpackage.json`,
    `${basePath}/methodology/..%5C..%5Cpackage.json`,
    `${basePath}/C:%5CWindows`,
    `${basePath}//methodology/`,
  ]) {
    const response = await rawGet(site, path);

    expect(response.status, path).toBe(400);
    expect(response.body, path).not.toContain('@dfilterforge/web');
  }
});
