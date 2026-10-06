import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';
import type {Page} from '@playwright/test';

// The Reel's demo behaviours on the built home page: it opens on the
// highlighted frame, the sweep plays to it on the clock, the cursor answers
// keys and drags, and the mini-map switches the ladder.
// tests/consistency.spec.ts checks every value.

const flag = (page: Page) => page.getByRole('slider', {name: 'Frame cursor'});
const heading = (page: Page) => page.locator('.ro-h');
const shown = {useInnerText: true};

// The figures below are the committed tree's: the pick disagrees with its
// labels on frame 59 of semantic-31, 60 of semantic-37 and 66 of
// semantic-43, and the highlight is frame 60 of semantic-37.

/** Installs the fake clock paused, so time moves only by runFor. */
async function freeze(page: Page): Promise<void> {
  await page.clock.install({time: 0});
  await page.clock.pauseAt(1000);
}

test.describe('with reduced motion', () => {
  test.use({contextOptions: {reducedMotion: 'reduce'}});

  test('opens on the highlighted frame, its packet and its trace', async ({page}) => {
    await page.goto('./');

    await expect(page.getByRole('heading', {level: 1, name: /^Frame 60 disproves/})).toBeVisible();
    await expect(flag(page)).toHaveText('60');
    await expect(heading(page)).toHaveText('Frame 60 of semantic-37', shown);
    await expect(page.locator('.pl-t tbody:visible td').first()).toHaveText('60');
    await expect(page.locator('.tr2-res .at:visible')).toHaveText('disagree');
    await expect(page.locator('[data-leaf="filter-1"]:visible')).toHaveText('false');
    await expect(page.getByRole('button', {name: 'Play the sweep'})).toBeHidden();
  });

  test('the mini-map draws another probe and the buttons step disproofs', async ({page}) => {
    await page.goto('./');

    await page.getByRole('button', {name: /^semantic-43/}).click();
    await expect(heading(page)).toHaveText('Frame 60 of semantic-43', shown);
    await expect(page.locator('.tr2-res .at:visible')).toHaveText('agree');
    await page.getByRole('button', {name: 'Next disproof'}).click();
    await expect(heading(page)).toHaveText('Frame 66 of semantic-43', shown);
    await page.getByRole('button', {name: 'Next disproof'}).click();
    await expect(heading(page)).toHaveText('Frame 59 of semantic-31', shown);
  });

  for (const scheme of ['light', 'dark'] as const) {
    test(`has no serious accessibility violations at phone width, ${scheme}`, async ({page}) => {
      await page.emulateMedia({colorScheme: scheme});
      await page.setViewportSize({width: 390, height: 844});
      await page.goto('./');

      const results = await new AxeBuilder({page})
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        .analyze();
      const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      expect(serious.map((v) => v.id)).toEqual([]);
    });
  }
});

test('keys step from where the cursor is headed, so fast presses add up', async ({page}) => {
  await page.goto('./');
  await flag(page).focus();

  for (let press = 0; press < 10; press += 1) {
    await page.keyboard.press('ArrowUp');
  }
  await expect(flag(page)).toHaveText('50');
  await expect(heading(page)).toHaveText('Frame 50 of semantic-37', shown);
  await page.keyboard.press('Home');
  await expect(flag(page)).toHaveText('1');
  // No frame before 60 disproves the filter, so a page moves ten frames.
  await page.keyboard.press('PageDown');
  await expect(flag(page)).toHaveText('11');
  await page.keyboard.press('End');
  await expect(flag(page)).toHaveText('60');
});

test('the clock sweeps the ladder down to the frame that disproves', async ({page}) => {
  await freeze(page);
  await page.goto('./');

  await page.getByRole('button', {name: 'Play the sweep'}).click();
  await page.clock.runFor(1500);
  await expect(flag(page)).toHaveText(/^[0-9]{1,2}$/);
  await expect(flag(page)).not.toHaveText('60');
  await expect(page.locator('.reel')).toHaveAttribute('data-mode', 'sweep');
  await page.clock.runFor(8000);
  await expect(flag(page)).toHaveText('60');
  await expect(page.locator('.reel')).toHaveAttribute('data-mode', 'pinned');
  await expect(page.getByRole('button', {name: 'Play the sweep'})).toBeVisible();
});

test('labels on neighbouring ladder rows do not overlap, on any probe, wide or narrow', async ({
  page,
}) => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({width, height: 900});
    await page.goto('./');
    const probes = page.locator('.ps');
    const count = await probes.count();
    for (let probe = 0; probe < count; probe += 1) {
      await probes.nth(probe).click();
      const ladder = page.locator(`.lad-p[data-p="${probe}"]`);
      await expect(ladder).toBeVisible();
      // Each row's label bounds, which hold a tilted label whole, or null
      // for a collapsed witness row, which has no label.
      const boxes = await ladder.locator('.lad-tx .fr').evaluateAll((rows) =>
        rows.map((row) => {
          const box = row.querySelector('.l-lab')?.getBoundingClientRect();
          return box === undefined
            ? null
            : {left: box.left, right: box.right, top: box.top, bottom: box.bottom};
        }),
      );
      const overlaps = boxes.flatMap((box, row) => {
        const next = boxes[row + 1] ?? null;
        const hit =
          box !== null &&
          next !== null &&
          box.left < next.right &&
          next.left < box.right &&
          box.top < next.bottom &&
          next.top < box.bottom;
        return hit ? [`probe ${probe}, frames ${row + 1} and ${row + 2}, ${width} px wide`] : [];
      });
      expect(overlaps).toEqual([]);
    }
  }
});

test('a drag of the flag moves the cursor and the readout with it', async ({page}) => {
  // Tall enough that the whole ladder is in view.
  await page.setViewportSize({width: 1280, height: 1500});
  await freeze(page);
  await page.goto('./');
  const box = await flag(page).boundingBox();
  const body = await page.locator('.lad-body').boundingBox();
  if (box === null || body === null) {
    throw new Error('the cursor is not laid out');
  }

  await page.mouse.move(box.x + 20, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 20, body.y + 120, {steps: 8});
  await page.clock.runFor(500);
  await page.mouse.up();
  await page.clock.runFor(200);
  const frame = Number(await flag(page).textContent());
  expect(frame).toBeGreaterThan(1);
  expect(frame).toBeLessThan(10);
  await expect(heading(page)).toHaveText(`Frame ${frame} of semantic-37`, shown);
});
