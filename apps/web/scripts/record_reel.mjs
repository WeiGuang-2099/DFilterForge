// Records the home page's Disproof Reel as PNG frames for the README GIF.
//
// Serves the built export (out/, after `pnpm build`), opens / at 1280x1100
// with a fake clock paused before the page loads, presses "Play the sweep",
// scrolls the ladder to the top of the window, then steps the clock at a
// fixed rate and captures the ladder and the readout after each step. The
// Reel moves only by that clock (app/_components/reel/clock.ts), and its
// sweep starts at the first animation frame after the press, so the same
// build gives the same frames. Not part of test:e2e. Writes
// artifacts/reel/frames/ (git-ignored), or the directory given, and prints
// the ffmpeg command that encodes docs/media/reel.gif.
//
//   node apps/web/scripts/record_reel.mjs [light|dark] [frames directory]

import {spawn} from 'node:child_process';
import {mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {chromium} from '@playwright/test';

import {basePath} from './base_path.mjs';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FRAMES = path.resolve(process.argv[3] ?? path.join(WEB, '..', '..', 'artifacts', 'reel', 'frames'));
const PORT = 3150;
// Ten frames a second is ten centiseconds a frame, which a GIF keeps
// exactly. The sweep ends about six seconds in; the rest holds its end.
const FPS = 10;
const SECONDS = 8;
// The window holds the opening probe's whole ladder, at 24 px a row, down
// to its footer, with 12 px above and below it.
const HEIGHT = 1100;
const scheme = process.argv[2] === 'dark' ? 'dark' : 'light';

const server = spawn(process.execPath, [path.join(WEB, 'scripts', 'serve.mjs')], {
  cwd: WEB,
  env: {...process.env, PORT: String(PORT)},
  stdio: 'ignore',
});
let browser;
try {
  // One raster thread and no GPU, so text and blending rasterize alike on
  // every run.
  browser = await chromium.launch({
    args: [
      '--disable-gpu',
      '--num-raster-threads=1',
      '--disable-partial-raster',
      '--force-color-profile=srgb',
    ],
  });
  rmSync(FRAMES, {recursive: true, force: true});
  mkdirSync(FRAMES, {recursive: true});
  const context = await browser.newContext({
    viewport: {width: 1280, height: HEIGHT},
    deviceScaleFactor: 1,
    colorScheme: scheme,
    reducedMotion: 'no-preference',
  });
  const page = await context.newPage();
  await page.clock.install({time: 0});
  await page.clock.pauseAt(1000);
  for (let tries = 0; ; tries += 1) {
    try {
      await page.goto(`http://127.0.0.1:${PORT}${basePath}/`);
      break;
    } catch (error) {
      if (tries > 20) throw error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.getByRole('button', {name: 'Play the sweep'}).click();
  const ladder = await page.locator('.lad').boundingBox();
  if (ladder === null) throw new Error('the home page has no ladder');
  const top = Math.floor(ladder.y + (await page.evaluate(() => window.scrollY)) - 12);
  await page.evaluate((y) => window.scrollTo(0, y), top);
  const readout = await page.locator('.ro').boundingBox();
  if (readout === null) throw new Error('the home page has no readout');
  const left = Math.floor(ladder.x - 12);
  const clip = {
    x: left,
    y: 0,
    width: Math.ceil(readout.x + readout.width + 12 - left),
    height: Math.min(HEIGHT, Math.ceil(ladder.height + 24)),
  };
  for (let frame = 0; frame < FPS * SECONDS; frame += 1) {
    const name = `frame-${String(frame).padStart(4, '0')}.png`;
    await page.screenshot({path: path.join(FRAMES, name), clip});
    await page.clock.runFor(1000 / FPS);
  }
  const relative = path.relative(process.cwd(), FRAMES).split(path.sep).join('/');
  console.log(`${FPS * SECONDS} frames of ${clip.width}x${clip.height} in ${relative}`);
  console.log('Encode them (at most 5 MB; drop to 64 colours if larger):');
  console.log(
    `ffmpeg -y -framerate ${FPS} -i ${relative}/frame-%04d.png -vf ` +
      '"scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];' +
      '[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" -loop 0 docs/media/reel.gif',
  );
} finally {
  await browser?.close();
  server.kill();
}
