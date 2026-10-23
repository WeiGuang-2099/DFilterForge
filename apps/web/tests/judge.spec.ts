import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';
import type {Locator, Page} from '@playwright/test';

// The methodology page's judge figure: one square per silent-wrong test
// answer. Every value it shows is in the HTML, and tests/consistency.spec.ts
// checks each one and re-derives every square's letters from the committed
// table. This file holds the island to what it shows: the mode switch fills
// exactly the squares the table counts for that mode, the page opens with the
// first false acceptance held, pointing reads out any square, a pressed
// square reads out its own answer and receipt whenever the pointer is off the
// squares, until Escape or a second press, the arrow keys move the figure's
// one tab stop, and the figure fits a phone with no accessibility violation.

test.use({contextOptions: {reducedMotion: 'reduce'}});

const TABLE = 'docs/results/judge-v2/table.json';
const SECTION = 'section[aria-labelledby="m-judge"]';

/** The sourced value of one table pointer on the page, as a number. */
async function tableValue(page: Page, pointer: string): Promise<number> {
  const node = page.locator(`[data-src='${JSON.stringify(['ptr', TABLE, pointer])}']`).first();
  return Number(await node.getAttribute('data-v'));
}

/** How many squares are filled as the false-acceptance swatch is. */
function filled(figure: Locator): Promise<number> {
  return figure.evaluate((root) => {
    const swatch = root.querySelector('.jd-sw-c');
    const fill = swatch === null ? 'none' : getComputedStyle(swatch).backgroundColor;
    return Array.from(root.querySelectorAll('.jd-q')).filter(
      (square) => getComputedStyle(square).backgroundColor === fill,
    ).length;
  });
}

/** The condition and item that label a square, from its detail block. */
async function named(page: Page, square: Locator): Promise<string[]> {
  const at = (await square.getAttribute('data-q')) ?? '';
  return page
    .locator(`#jd-n-${at} [data-src]`)
    .evaluateAll((nodes) =>
      nodes.map((node) => String(JSON.parse(node.getAttribute('data-v') ?? '""'))),
    );
}

test('the mode switch fills the squares each mode rates correct', async ({page}) => {
  await page.goto('methodology/');
  const figure = page.locator('.jd');
  const squares = figure.locator('.jd-q');
  await expect(squares).toHaveCount(await tableValue(page, '/modes/primary/headline/silent_wrong'));

  for (const mode of ['secondary', 'primary'] as const) {
    await page.locator(`#jd-mode-${mode}`).click();
    await expect(figure).toHaveAttribute('data-mode', mode);
    await expect(page.locator(`#jd-mode-${mode}`)).toHaveAttribute('aria-pressed', 'true');
    const counted = await tableValue(page, `/modes/${mode}/headline/silent_wrong_rated_correct`);
    expect(await filled(figure)).toBe(counted);
    const letter = mode === 'primary' ? 'data-p' : 'data-s';
    await expect(figure.locator(`.jd-q[${letter}="c"]`)).toHaveCount(counted);
    // A row shows one count, the active mode's.
    await expect(figure.locator('.jd-row').first().locator('.jd-n > :visible')).toHaveCount(1);
  }
});

test('a pressed square reads out its answer until a second press or Escape', async ({page}) => {
  await page.goto('methodology/');
  const figure = page.locator('.jd');
  const square = figure.locator('.jd-q[data-p="c"]').nth(2);
  const at = (await square.getAttribute('data-q')) ?? '';
  const detail = figure.locator(`.jd-d[data-d="${at}"]`);
  await expect(detail).toBeHidden();
  // The page opens with the first false acceptance held and read out.
  const opening = figure.locator('.jd-q[data-p="c"]').first();
  await expect(opening).toHaveAttribute('aria-pressed', 'true');
  const first = (await opening.getAttribute('data-q')) ?? '';
  await expect(figure.locator('.jd-d:visible')).toHaveCount(1);
  await expect(figure.locator(`.jd-d[data-d="${first}"]`)).toBeVisible();
  await expect(figure.locator('.jd-hint')).toBeHidden();

  await square.click();
  await expect(square).toHaveAttribute('aria-pressed', 'true');
  await expect(opening).toHaveAttribute('aria-pressed', 'false');
  await expect(detail).toBeVisible();
  await expect(figure.locator('.jd-d:visible')).toHaveCount(1);
  await expect(detail.locator('[data-line="primary"]')).toContainText(
    'Request alone: rated correct, a false acceptance',
  );
  const lettered = (await square.getAttribute('data-s')) === 'c';
  const secondary = lettered ? 'rated correct' : 'rated incorrect';
  await expect(detail.locator('[data-line="secondary"]')).toContainText(
    `With the reference filter: ${secondary}`,
  );
  const [condition = '', item = ''] = await named(page, square);
  const receipt = (await detail.getByRole('link').getAttribute('href')) ?? '';
  expect(receipt.endsWith(`/receipts/${condition}/${item}.json`), receipt).toBe(true);
  await expect(square).toHaveAccessibleName(
    `${condition} ${item} rated correct, a false acceptance`,
  );

  // Pointing at another square reads it out while the press holds this one,
  // and moving the pointer off the squares, on to the readout, brings the
  // held square back.
  const other = figure.locator(`.jd-q:not([data-q="${at}"])`).last();
  await other.hover();
  const elsewhere = (await other.getAttribute('data-q')) ?? '';
  await expect(figure.locator(`.jd-d[data-d="${elsewhere}"]`)).toBeVisible();
  await expect(detail).toBeHidden();
  await figure.locator('.jd-detail').hover();
  await expect(detail).toBeVisible();
  await expect(figure.locator('.jd-d:visible')).toHaveCount(1);

  // The pointer leaves and the press keeps the readout; a second press and
  // Escape each let it go.
  await page.mouse.move(0, 0);
  await expect(detail).toBeVisible();
  await square.click();
  await expect(square).toHaveAttribute('aria-pressed', 'false');
  await page.mouse.move(0, 0);
  await expect(figure.locator('.jd-hint')).toBeVisible();
  await square.click();
  await page.mouse.move(0, 0);
  await page.keyboard.press('Escape');
  await expect(square).toHaveAttribute('aria-pressed', 'false');
  await expect(detail).toBeHidden();
});

test('the squares are one tab stop and the arrow keys move along them', async ({page}) => {
  await page.goto('methodology/');
  const figure = page.locator('.jd');
  const focused = figure.locator('.jd-q:focus');
  const place = async () => Number(await focused.getAttribute('data-q'));

  await page.locator('#jd-mode-secondary').focus();
  await page.keyboard.press('Tab');
  expect(await place()).toBe(0);
  await expect(figure.locator('.jd-d[data-d="0"]')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  expect(await place()).toBe(1);
  await expect(figure.locator('.jd-d[data-d="1"]')).toBeVisible();
  // Down to the nearest square of the next line, and back up.
  const top = (await focused.boundingBox())?.y ?? 0;
  await page.keyboard.press('ArrowDown');
  expect(await place()).toBeGreaterThan(1);
  expect((await focused.boundingBox())?.y ?? 0).toBeGreaterThan(top);
  await page.keyboard.press('ArrowUp');
  expect(await place()).toBe(1);
  // End and Home keep to the row.
  const first = figure.locator('.jd-sqs').first().locator('.jd-q');
  await page.keyboard.press('End');
  await expect(first.last()).toBeFocused();
  await page.keyboard.press('Home');
  await expect(first.first()).toBeFocused();
  await expect(figure.locator('.jd-q[tabindex="0"]')).toHaveCount(1);

  // Escape lets go the square the page opens with, which a press on it
  // would let go too. Enter keeps the readout; Tab goes on to its receipt,
  // and back comes to the same square; Escape lets the readout go.
  await page.keyboard.press('Escape');
  await expect(figure.locator('.jd-q[aria-pressed="true"]')).toHaveCount(0);
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('Enter');
  await expect(figure.locator('.jd-q[data-q="1"]')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('Tab');
  await expect(figure.locator('.jd-d[data-d="1"]').getByRole('link')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  expect(await place()).toBe(1);
  await page.keyboard.press('Escape');
  await expect(figure.locator('.jd-q[data-q="1"]')).toHaveAttribute('aria-pressed', 'false');
});

test('the figure fits a phone, and axe finds no violation in it', async ({page}) => {
  for (const width of [320, 400]) {
    await page.setViewportSize({width, height: 900});
    await page.goto('methodology/');
    const figure = page.locator('.jd');
    // The answer with the longest filter, read out.
    const longest = await figure.evaluate((root) => {
      const blocks = Array.from(root.querySelectorAll('.jd-d'));
      const length = (block: Element) => block.querySelector('code')?.textContent?.length ?? 0;
      const block = blocks.reduce((best, each) => (length(each) > length(best) ? each : best));
      return block.getAttribute('data-d') ?? '';
    });
    // A press on the square the page opens with would let it go.
    const square = figure.locator(`.jd-q[data-q="${longest}"]`);
    if ((await square.getAttribute('aria-pressed')) !== 'true') {
      await square.click();
    }
    await expect(figure.locator(`.jd-d[data-d="${longest}"]`)).toBeVisible();
    const [scroll, client] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      document.documentElement.clientWidth,
    ]);
    expect(scroll, `${String(width)} px`).toBeLessThanOrEqual(client);
    if (width === 400) {
      const results = await new AxeBuilder({page}).include(SECTION).analyze();
      expect(
        results.violations.map(
          (violation) =>
            `${violation.id} (${violation.impact ?? 'no impact'}): ` +
            violation.nodes.map((node) => node.target.join(' ')).join(', '),
        ),
      ).toEqual([]);
    }
  }
});

test('at the default width axe finds no serious or critical violation in it', async ({page}) => {
  await page.goto('methodology/');
  await page.locator('.jd-q').nth(5).click();
  await page.locator('#jd-mode-secondary').click();
  const results = await new AxeBuilder({page}).include(SECTION).analyze();
  expect(
    results.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => violation.id),
  ).toEqual([]);
});
