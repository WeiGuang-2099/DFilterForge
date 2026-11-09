import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';
import type {Page} from '@playwright/test';

// The training page's three sections on the cheaper fixes, the repair turn
// and the cost. Their receipts and tables sit in closed details, whose
// content smoke.spec.ts's axe run at load does not evaluate, and that run
// never sees the dark scheme. So here every details is opened, axe runs on
// the three sections in light and in dark at smoke's bar, serious and
// critical findings, and the open page fits a phone held upright, 320 and
// 400 px wide, with nothing scrolling sideways. tests/consistency.spec.ts
// holds every value in them to the committed files and re-derives the
// receipts' marks, the tags, the primary labels, the questions' scales, the
// bars' parts and the pooled arms' squares; it does not re-derive the
// seeds' arm bars or the comparisons' interval marks.

test.use({contextOptions: {reducedMotion: 'reduce'}});

const SECTIONS = [
  'section[aria-labelledby="tr-steps"]',
  'section[aria-labelledby="tr-repair"]',
  'section[aria-labelledby="tr-cost"]',
];

/** Opens the training page with every details on it open. */
async function openAll(page: Page): Promise<void> {
  await page.goto('training/');
  const opened = await page.locator('details').evaluateAll((all: HTMLDetailsElement[]) => {
    for (const details of all) {
      details.open = true;
    }
    return all.length;
  });
  expect(opened).toBeGreaterThan(0);
  for (const section of SECTIONS) {
    await expect(page.locator(section)).toHaveCount(1);
  }
}

for (const colorScheme of ['light', 'dark'] as const) {
  test.describe(`in the ${colorScheme} scheme`, () => {
    test.use({colorScheme});

    test('with every receipt and table open, axe finds no serious violation in the new sections', async ({
      page,
    }) => {
      await openAll(page);
      const results = await SECTIONS.reduce(
        (builder, section) => builder.include(section),
        new AxeBuilder({page}),
      ).analyze();
      expect(
        results.violations
          .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
          .map(
            (violation) =>
              `${violation.id} (${violation.impact ?? 'no impact'}): ` +
              violation.nodes.map((node) => node.target.join(' ')).join(', '),
          ),
      ).toEqual([]);
    });
  });
}

test('with every receipt open, nothing scrolls sideways at 320 or 400 px', async ({page}) => {
  for (const width of [320, 400]) {
    await page.setViewportSize({width, height: 900});
    await openAll(page);
    const [scroll, client] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      document.documentElement.clientWidth,
    ]);
    expect(scroll, `${String(width)} px`).toBeLessThanOrEqual(client);
  }
});
