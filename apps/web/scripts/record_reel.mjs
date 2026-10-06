// Records the home page as PNG frames for the README GIF, in three scenes
// of one size: the opening, the Disproof Reel's sweep and the repair turn.
//
// Serves the built export (out/, after `pnpm build`) and opens / with a fake
// clock paused before the page loads. The sweep is shot in a window 1280 px
// wide, where the readout sits beside the ladder; the opening and the repair
// turn in one 1024 px wide, where the page's column fits the same frame:
//   opening      the top of the page: the answer, its request and the start
//                of the ladder, held still;
//   sweep        "Play the sweep" pressed, the ladder scrolled to the top of
//                the window, then the clock stepped at a fixed rate with the
//                ladder and the readout captured after each step;
//   repair turn  the foot of the page: the end of the readout, the card sent
//                back and the second answer, held still.
// The Reel moves only by that clock (app/_components/reel/clock.ts), and its
// sweep starts at the first animation frame after the press, so the same
// build gives the same frames. Not part of test:e2e. Writes
// artifacts/reel/frames/ (git-ignored), or the directory given, and prints
// the ffmpeg command that encodes docs/media/reel.gif.
//
//   node apps/web/scripts/record_reel.mjs [light|dark] [frames directory]

import {spawn} from 'node:child_process';
import {copyFileSync, mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {chromium} from '@playwright/test';

import {basePath} from './base_path.mjs';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FRAMES = path.resolve(process.argv[3] ?? path.join(WEB, '..', '..', 'artifacts', 'reel', 'frames'));
const PORT = 3150;
// Ten frames a second is ten centiseconds a frame, which a GIF keeps
// exactly. Each scene's length in seconds: the sweep reaches frame 60 about
// five seconds in and holds it for the rest.
const FPS = 10;
const [OPENING, SWEEP, REPAIR] = [3, 6.5, 4];
// The sweep's window holds the highlighted probe's whole ladder, at 24 px
// a row, down to its footer, with 12 px above and below it. The narrow
// window is under 1280 px, so the page runs in one column, and wide enough
// for the repair turn and the pool to stay side by side.
const [WIDE, NARROW, HEIGHT] = [1280, 1024, 1100];
const scheme = process.argv[2] === 'dark' ? 'dark' : 'light';

const server = spawn(process.execPath, [path.join(WEB, 'scripts', 'serve.mjs')], {
  cwd: WEB,
  env: {...process.env, PORT: String(PORT)},
  stdio: 'ignore',
});
let browser;
let count = 0;

/** The path of frame `n`. */
function frame(n) {
  return path.join(FRAMES, `frame-${String(n).padStart(4, '0')}.png`);
}

/** Captures one frame and repeats it for the rest of a still scene. */
async function hold(page, clip, seconds) {
  await page.screenshot({path: frame(count), clip});
  for (let copy = 1; copy < seconds * FPS; copy += 1) {
    copyFileSync(frame(count), frame(count + copy));
  }
  count += seconds * FPS;
}

/** The box of the first element `selector` matches, in page pixels. */
async function box(page, selector) {
  const found = await page.locator(selector).first().boundingBox();
  if (found === null) throw new Error(`the home page has no ${selector}`);
  const scrollY = await page.evaluate(() => window.scrollY);
  return {...found, y: found.y + scrollY};
}

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
    viewport: {width: WIDE, height: HEIGHT},
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

  // The frame: the ladder and the readout of the wide window.
  const [ladder, readout] = [await box(page, '.lad'), await box(page, '.ro')];
  const left = Math.floor(ladder.x - 12);
  const size = {
    width: Math.ceil(readout.x + readout.width + 12 - left),
    height: Math.min(HEIGHT, Math.ceil(ladder.height + 24)),
  };
  // The narrow window's frame, centred; its column must fit inside.
  const centred = {x: Math.floor((NARROW - size.width) / 2), ...size};
  await page.setViewportSize({width: NARROW, height: HEIGHT});
  const column = await box(page, '.top');
  if (column.x < centred.x || column.x + column.width > centred.x + size.width) {
    throw new Error(`the ${NARROW} px column does not fit a ${size.width} px frame`);
  }

  // The opening: the top of the page.
  await hold(page, {...centred, y: 0}, OPENING);

  // The sweep. Its first animation frame moves the cursor to row 1, so the
  // clock steps once before the first capture.
  await page.setViewportSize({width: WIDE, height: HEIGHT});
  await page.getByRole('button', {name: 'Play the sweep'}).click();
  await page.evaluate((y) => window.scrollTo(0, y), Math.floor((await box(page, '.lad')).y - 12));
  for (let step = 0; step < SWEEP * FPS; step += 1) {
    await page.clock.runFor(1000 / FPS);
    await page.screenshot({path: frame(count), clip: {x: left, y: 0, ...size}});
    count += 1;
  }

  // The repair turn: from the readout's leaf table down past the card.
  await page.setViewportSize({width: NARROW, height: HEIGHT});
  const [leaves, repair] = [await box(page, '.tr2:visible'), await box(page, '.act-repair')];
  const top = Math.floor(leaves.y - 8);
  if (top + size.height < repair.y + repair.height + 12) {
    throw new Error('the repair turn does not fit the frame');
  }
  await page.evaluate((y) => window.scrollTo(0, y), top);
  const y = top - (await page.evaluate(() => window.scrollY));
  if (y < 0 || y + size.height > HEIGHT) throw new Error('the repair turn does not fit the window');
  await hold(page, {...centred, y}, REPAIR);

  const relative = path.relative(process.cwd(), FRAMES).split(path.sep).join('/');
  console.log(`${count} frames of ${size.width}x${size.height} in ${relative}`);
  // The page draws no gradient, so dithering only adds noise to flat fills.
  console.log('Encode them (at most 5 MB; drop to 64 colours if larger):');
  console.log(
    `ffmpeg -y -framerate ${FPS} -i ${relative}/frame-%04d.png -vf ` +
      '"scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];' +
      '[b][p]paletteuse=dither=none:diff_mode=rectangle" -loop 0 docs/media/reel.gif',
  );
} finally {
  await browser?.close();
  server.kill();
}
