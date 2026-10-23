// Records the link-preview cards lib/preview.ts names: the top of each page,
// 1200 by 630 px, in the light scheme, as the page first renders.
//
// Serves the built export (out/, after `pnpm build`) the way record_reel.mjs
// does, with the clock paused before the page loads so the Reel holds its
// opening, and writes public/, which the next build copies to the site's
// root. Re-record after changing the top of a recorded page and rebuild; the
// smoke test checks that each card a page names is served at this size, not
// what it shows. Not part of test:e2e.
//
//   node apps/web/scripts/record_previews.mjs

import {spawn} from 'node:child_process';
import {mkdirSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {chromium} from '@playwright/test';

import {basePath} from './base_path.mjs';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC = path.join(WEB, 'public');
const PORT = 3151;
// lib/preview.ts: CARD, and the card each page's metadata names.
const [WIDTH, HEIGHT] = [1200, 630];
const CARDS = [
  {page: '/', file: 'og.png'},
  {page: '/training/', file: 'og-training.png'},
  {page: '/training/analysis/', file: 'og-analysis.png'},
  {page: '/exhibits/', file: 'og-exhibits.png'},
];

const server = spawn(process.execPath, [path.join(WEB, 'scripts', 'serve.mjs')], {
  cwd: WEB,
  env: {...process.env, PORT: String(PORT)},
  stdio: 'ignore',
});
let browser;

try {
  // As record_reel.mjs: one raster thread and no GPU.
  browser = await chromium.launch({
    args: [
      '--disable-gpu',
      '--num-raster-threads=1',
      '--disable-partial-raster',
      '--force-color-profile=srgb',
    ],
  });
  mkdirSync(PUBLIC, {recursive: true});
  for (const {page: route, file} of CARDS) {
    const context = await browser.newContext({
      viewport: {width: WIDTH, height: HEIGHT},
      deviceScaleFactor: 1,
      colorScheme: 'light',
    });
    const page = await context.newPage();
    await page.clock.install({time: 0});
    await page.clock.pauseAt(1000);
    for (let tries = 0; ; tries += 1) {
      try {
        await page.goto(`http://127.0.0.1:${PORT}${basePath}${route}`);
        break;
      } catch (error) {
        if (tries > 20) throw error;
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
    }
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    const target = path.join(PUBLIC, file);
    await page.screenshot({path: target});
    console.log(`${route} -> ${path.relative(process.cwd(), target).split(path.sep).join('/')}`);
    await context.close();
  }
} finally {
  await browser?.close();
  server.kill();
}
