import {expect, test} from '@playwright/test';
import type {Page} from '@playwright/test';

// The Reel's demo behaviours on the built home page: the clock plays it to
// the highlighted frame, reduced motion shows that final state at once, and
// the measurement cursor answers keys and stops a drag on each frame that
// disproves the filter. tests/consistency.spec.ts checks every value.

const flag = (page: Page) => page.getByRole('slider', {name: 'Frame cursor'});
const heading = (page: Page) => page.locator('.ro-h .at:visible');

// The figures below are the committed tree's: the pick disagrees with its
// labels on frame 59 of semantic-31, 60 of semantic-37 and 66 of
// semantic-43, and the highlight is frame 60.

/** Installs the fake clock paused, so time moves only by runFor. */
async function freeze(page: Page): Promise<void> {
  await page.clock.install({time: 0});
  await page.clock.pauseAt(1000);
}

test.describe('with reduced motion', () => {
  test.use({contextOptions: {reducedMotion: 'reduce'}});

  test('shows the final state and rests on the highlighted frame', async ({page}) => {
    await page.goto('./');

    await expect(page.getByRole('heading', {level: 1, name: /^Frame 60 disproves/})).toBeVisible();
    await expect(flag(page)).toHaveText('60');
    await expect(heading(page)).toHaveText('60');
    await expect(page.getByRole('button', {name: 'Play the reel'})).toBeVisible();
    await expect(page.locator('.act-pool')).toHaveCSS('opacity', '1');
  });

  test('the keys step the cursor one frame and a page to the next disproof', async ({page}) => {
    await page.goto('./');
    await flag(page).focus();

    await page.keyboard.press('ArrowLeft');
    await expect(flag(page)).toHaveText('59');
    await expect(heading(page)).toHaveText('59');
    await page.keyboard.press('Home');
    await expect(flag(page)).toHaveText('1');
    // No frame before 59 disproves the filter, so a page moves ten frames.
    await page.keyboard.press('PageUp');
    await expect(flag(page)).toHaveText('11');
    await page.keyboard.press('End');
    await expect(flag(page)).toHaveText('66');
  });
});

test('the clock plays the reel to the frame that disproves the filter', async ({page}) => {
  await freeze(page);
  await page.goto('./');

  await page.clock.runFor(1000);
  await expect(flag(page)).toHaveText(/^[0-9]$/);
  await expect(page.locator('.act-repair')).toHaveCSS('opacity', '0');
  await page.clock.runFor(15_000);
  await expect(flag(page)).toHaveText('60');
  await expect(page.locator('.act-pool')).toHaveCSS('opacity', '1');
  await expect(page.getByRole('button', {name: 'Play the reel'})).toBeVisible();
});

test('a drag across the strips holds on each frame that disproves', async ({page}) => {
  await freeze(page);
  await page.goto('./');
  await page.clock.runFor(500);
  const strips = await page.locator('.cur').boundingBox();
  if (strips === null) {
    throw new Error('the cursor overlay is not laid out');
  }
  const y = strips.y + strips.height - 8;

  await page.mouse.move(strips.x + 2, y);
  await page.mouse.down();
  await page.clock.runFor(300);
  // Each disproving frame holds the cursor for the detent before it moves on.
  await page.mouse.move(strips.x + strips.width - 2, y);
  await page.clock.runFor(220);
  await expect(flag(page)).toHaveText('59');
  await page.clock.runFor(200);
  await expect(flag(page)).toHaveText('60');
  await page.clock.runFor(300);
  await expect(flag(page)).toHaveText('66');
  await page.mouse.up();
});
