// Records the home page's Disproof Reel as PNG frames for the README GIF.
//
// Serves the built export (out/, after `pnpm build`), opens / at 960x540
// with a fake clock paused before the page loads, then steps the clock at
// a fixed rate and captures the masthead and the Reel's stage after each
// step. The Reel moves only by that clock (app/_components/reel/clock.ts),
// so the same build gives the same frames. Not part of test:e2e. Writes
// artifacts/reel/frames/ (git-ignored) and prints the ffmpeg command that
// encodes docs/media/reel.gif.
//
//   node apps/web/scripts/record_reel.mjs [light|dark]

import {spawn} from 'node:child_process';
import {mkdirSync, rmSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

import {chromium} from '@playwright/test';

import {basePath} from './base_path.mjs';

const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FRAMES = path.resolve(WEB, '..', '..', 'artifacts', 'reel', 'frames');
const PORT = 3150;
// Ten frames a second is ten centiseconds a frame, which a GIF keeps
// exactly. The Reel ends about twelve seconds in; the rest holds its end.
const FPS = 10;
const SECONDS = 15;
const scheme = process.argv[2] === 'dark' ? 'dark' : 'light';

const server = spawn(process.execPath, [path.join(WEB, 'scripts', 'serve.mjs')], {
  cwd: WEB,
  env: {...process.env, PORT: String(PORT)},
  stdio: 'ignore',
});
const browser = await chromium.launch();
try {
  rmSync(FRAMES, {recursive: true, force: true});
  mkdirSync(FRAMES, {recursive: true});
  const context = await browser.newContext({
    viewport: {width: 960, height: 540},
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
  const stage = await page.locator('.reel').boundingBox();
  if (stage === null) throw new Error('the home page has no Reel stage');
  const clip = {x: 0, y: 0, width: 960, height: Math.ceil(stage.y + stage.height + 16)};
  for (let frame = 0; frame < FPS * SECONDS; frame += 1) {
    const name = `frame-${String(frame).padStart(4, '0')}.png`;
    await page.screenshot({path: path.join(FRAMES, name), clip, fullPage: true});
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
  await browser.close();
  server.kill();
}
