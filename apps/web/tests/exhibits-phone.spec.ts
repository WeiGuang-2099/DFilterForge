import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';
import type {Locator} from '@playwright/test';

// The exhibits page 400 px wide, a phone held upright inside the site's
// 16 px gutters. Nothing may scroll sideways there: not the page, not a
// frame tape, a packet list or a table, whichever answer and probe an
// exhibit shows, and every cell of a table keeps its value on screen.
// Each probe's tape puts its name above two rows, the benchmark frames
// and then the witness tail, where every disagreeing frame sits, so the
// tail is on screen whenever its tapes are. A tap reads a frame out, and
// axe finds no violation at all.

test.use({viewport: {width: 400, height: 900}, contextOptions: {reducedMotion: 'reduce'}});

/**
 * Lists what does not fit the screen under a root: a shown tape or table
 * box that scrolls sideways, or a shown table cell with no width or with
 * an edge off the screen.
 */
function unfit(root: Locator): Promise<string[]> {
  return root.evaluate((scope) => {
    const width = document.documentElement.clientWidth;
    const shown = (each: Element) => each.getClientRects().length > 0;
    const boxes = Array.from(scope.querySelectorAll('.xh-tapes, .xh-tw')).filter(shown);
    const cells = Array.from(scope.querySelectorAll('.xh-pl td, .xh-t tbody th, .xh-t td'));
    return [
      ...boxes
        .filter((box) => box.scrollWidth > box.clientWidth)
        .map((box) => `${box.className} scrolls ${box.scrollWidth} px in ${box.clientWidth}`),
      ...cells.filter(shown).flatMap((cell) => {
        const {left, right} = cell.getBoundingClientRect();
        return right > left && left >= 0 && right <= width
          ? []
          : [`${cell.getAttribute('data-h') ?? 'a cell'} at ${left} to ${right}`];
      }),
    ];
  });
}

/** A part's top and bottom on the page, in px. */
async function span(part: Locator): Promise<readonly [number, number]> {
  const box = await part.boundingBox();
  expect(box, 'the part is laid out').not.toBeNull();
  return box === null ? [0, 0] : [box.y, box.y + box.height];
}

test('nothing scrolls sideways, whichever answer and probe an exhibit shows', async ({page}) => {
  await page.goto('exhibits/');
  const [scroll, client] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(scroll).toBeLessThanOrEqual(client);
  expect(await unfit(page.locator('main'))).toEqual([]);

  const cards = await page.locator('article.xh-ex').all();
  expect(cards.length).toBeGreaterThan(1);
  for (const card of cards) {
    const picks = card.getByRole('group', {name: 'Answers'}).getByRole('button');
    const probes = card.getByRole('group', {name: 'Probe'}).getByRole('button');
    const answers = Math.max(await picks.count(), 1);
    expect(await probes.count()).toBeGreaterThan(1);
    for (let answer = 0; answer < answers; answer += 1) {
      if (answers > 1) {
        await picks.nth(answer).click();
      }
      for (const probe of await probes.all()) {
        await probe.click();
        await expect(probe).toHaveAttribute('aria-pressed', 'true');
        expect(await unfit(card), `${await probe.innerText()}, answer ${String(answer)}`).toEqual(
          [],
        );
      }
    }
  }
});

test("each probe's name sits above its two rows, and its tail is on screen", async ({page}) => {
  await page.goto('exhibits/');
  for (const card of await page.locator('article.xh-ex').all()) {
    await card.locator('.xh-tapes').scrollIntoViewIfNeeded();
    const tapes = await card.locator('.xh-tapes-in:visible .xh-tape').all();
    expect(tapes.length).toBeGreaterThan(1);
    for (const tape of tapes) {
      const tail = tape.locator('.xh-seg-t');
      await expect(tail).toBeInViewport({ratio: 1});
      const [, nameBottom] = await span(tape.locator('.xh-tape-l'));
      const [benchTop, benchBottom] = await span(tape.locator('.xh-seg-b'));
      const [tailTop] = await span(tail);
      expect(nameBottom, 'the name above the benchmark frames').toBeLessThanOrEqual(benchTop);
      expect(benchBottom, 'the tail under the benchmark frames').toBeLessThanOrEqual(tailTop);
    }
  }
});

test.describe('on a touch screen', () => {
  test.use({hasTouch: true, isMobile: true});

  test('a tap on a frame reads it out', async ({page}) => {
    await page.goto('exhibits/');
    const card = page.locator('article.xh-ex').first();
    const tape = card.locator('.xh-tapes-in:visible [data-p="1"]');

    for (const cell of [tape.locator('.xh-f').nth(3), tape.locator('.xh-seg-t .xh-f').last()]) {
      await cell.tap();
      const probe = (await tape.locator('.xh-tape-l b').textContent()) ?? '';
      await expect(card.locator('.xh-fd b [data-fmt="int"]')).toHaveText(
        (await cell.getAttribute('data-n')) ?? '',
      );
      await expect(card.locator('.xh-fd b [data-fmt="text"]')).toHaveText(probe);
    }
  });
});

test('axe finds no violation', async ({page}) => {
  await page.goto('exhibits/');
  const results = await new AxeBuilder({page}).analyze();
  expect(
    results.violations.map(
      (violation) =>
        `${violation.id} (${violation.impact ?? 'no impact'}): ` +
        violation.nodes.map((node) => node.target.join(' ')).join(', '),
    ),
  ).toEqual([]);
});
