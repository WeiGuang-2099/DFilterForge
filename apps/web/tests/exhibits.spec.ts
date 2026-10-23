import {expect, test} from '@playwright/test';
import type {Locator, Page} from '@playwright/test';

// The exhibits page's islands show one verifier, one answer and one probe
// at a time. Every value they switch between is in the HTML, and
// tests/consistency.spec.ts checks each one and re-derives the squares,
// tapes and killing frames. The two readouts are not in the HTML: the
// overview's line names a square's model, condition, item and case with
// its verdicts, exhibit and receipt, and an exhibit's frame line gives a
// frame's number, kind, name, packet-list columns and state. They render
// only while a square or frame is pointed at, focused or tapped, which the
// consistency test never does, so this file holds each line to what it
// reads out. A ringed square's line must name the answer its link label
// names and link its exhibit, answer and receipt; any square's line must
// give the verdict words of its letters. A frame's line must give its
// cell's number and state words and its tape's probe, and its number must
// come from that frame's row of the probe's table; the row's other
// columns are the same row's nodes and are not compared one by one. This
// file also checks that each control changes only what is shown, the
// captures alone folding each tail to no width and no height; that every
// square is drawn as the key draws its verdict; and that a ringed square
// opens its exhibit on its answer. exhibits-phone.spec.ts checks the page
// 400 px wide, a tap on a frame included.

test.use({contextOptions: {reducedMotion: 'reduce'}});

// What a readout says for a square's verdict letter and a frame's state.
const VERDICTS: Readonly<Record<string, string>> = {
  e: 'strong exact',
  s: 'shortcut',
  w: 'silent-wrong',
  u: 'not scorable',
};
const STATES: Readonly<Record<string, string>> = {
  tp: 'labelled and matched',
  tn: 'neither labelled nor matched',
  fp: 'matched; the labels leave it out',
  fn: 'labelled; the answer misses it',
};

/** Every sourced value of the page, shown or not, in order. */
function sources(page: Page): Promise<string[]> {
  return page
    .locator('[data-src]')
    .evaluateAll((all) => all.map((each) => each.getAttribute('data-src') ?? '').sort());
}

function verifier(root: Locator, name: string): Locator {
  return root.getByRole('group', {name: 'Verifier'}).getByRole('button', {name, exact: true});
}

/** Each shown tape's height, and its tail's width and height, in px. */
function tapeSizes(card: Locator): Promise<{tape: number; tail: number[]}[]> {
  return card.locator('.xh-tapes-in:visible .xh-tape').evaluateAll((tapes) =>
    tapes.map((tape) => {
      const tail = tape.querySelector('.xh-seg-t')?.getBoundingClientRect();
      return {
        tape: tape.getBoundingClientRect().height,
        tail: tail === undefined ? [] : [tail.width, tail.height],
      };
    }),
  );
}

/**
 * Lists what the overview does not draw as its key does under the view:
 * two verdicts' swatches alike, or a square not filled and edged as the
 * swatch of its letter (data-t with the tail, data-a on the captures
 * alone), or not ringed as the ringed swatch exactly when it is ringed.
 */
function offKey(overview: Locator, letter: 'data-t' | 'data-a'): Promise<string[]> {
  return overview.evaluate((root, name) => {
    const swatch = (key: string) => root.querySelector(`.xh-key [data-k="${key}"]`);
    const fill = (each: Element | null) => {
      const css = each === null ? null : getComputedStyle(each);
      return css === null
        ? 'no swatch'
        : [css.backgroundColor, css.backgroundImage, css.borderTopStyle, css.borderTopColor].join(' ');
    };
    const ring = (each: Element | null) =>
      each === null ? 'no swatch' : getComputedStyle(each).boxShadow;
    const keys = ['e', 's', 'w', 'u'].map((key) => fill(swatch(key)));
    const alike = new Set(keys).size === keys.length ? [] : [`swatches alike: ${keys.join(', ')}`];
    return alike.concat(
      Array.from(root.querySelectorAll('.xh-cells .xh-q')).flatMap((square) => {
        const own = swatch(square.getAttribute(name) ?? '');
        const ringed = square.classList.contains('xh-q-k') ? swatch('k') : own;
        return fill(square) === fill(own) && ring(square) === ring(ringed)
          ? []
          : [`square ${square.getAttribute('data-q') ?? '?'}: ${fill(square)} ${ring(square)}`];
      }),
    );
  }, letter);
}

/** Expects a readout to say a square's verdicts in the words for its letters. */
async function expectVerdicts(line: Locator, square: Locator): Promise<void> {
  const alone = VERDICTS[(await square.getAttribute('data-a')) ?? ''] ?? '?';
  const tail = VERDICTS[(await square.getAttribute('data-t')) ?? ''] ?? '?';
  await expect(line).toContainText(`Captures alone: ${alone}; with the tail: ${tail}.`);
}

/**
 * Expects the overview's line to read out a ringed square: the model,
 * condition and item its label names, its verdicts, its exhibit and its
 * receipt.
 */
async function expectReadout(line: Locator, square: Locator): Promise<void> {
  const [answer = ''] = ((await square.textContent()) ?? '').split(', ');
  const [, condition = '', item = ''] = answer.split(' ');
  await expect(line).toContainText(`${answer}, case `);
  await expectVerdicts(line, square);
  const open = line.getByRole('link', {name: 'Open its exhibit'});
  for (const name of ['data-exhibit', 'data-answer']) {
    await expect(open).toHaveAttribute(name, (await square.getAttribute(name)) ?? '');
  }
  const receipt = (await line.getByRole('link', {name: 'Receipt'}).getAttribute('href')) ?? '';
  expect(receipt.endsWith(`/receipts/${condition}/${item}.json`), receipt).toBe(true);
}

test('the verifier switch draws every square as the key draws its verdict', async ({page}) => {
  await page.goto('exhibits/');
  const overview = page.locator('.xh-ov');
  const line = overview.locator('.xh-detail-t:visible');
  const before = await sources(page);

  await expect(overview).toHaveAttribute('data-view', 'tail');
  await expect(verifier(overview, 'With the witness tail')).toHaveAttribute('aria-pressed', 'true');
  await expect(line).toContainText('With the tail:');
  expect(await offKey(overview, 'data-t')).toEqual([]);

  await verifier(overview, 'Captures alone').click();
  await expect(overview).toHaveAttribute('data-view', 'alone');
  await expect(verifier(overview, 'Captures alone')).toHaveAttribute('aria-pressed', 'true');
  await expect(line).toContainText('On the captures alone:');
  expect(await offKey(overview, 'data-a')).toEqual([]);
  expect(await sources(page)).toEqual(before);
});

test('each ringed square reads out its own answer, and Tab goes on to its links', async ({
  page,
}) => {
  await page.goto('exhibits/');
  const overview = page.locator('.xh-ov');
  const line = overview.locator('.xh-detail-t:visible');
  const ringed = overview.locator('.xh-cells a.xh-q-k');
  const focused = overview.locator('.xh-cells a.xh-q-k:focus');
  const total = await ringed.count();
  expect(total).toBeGreaterThan(0);

  await verifier(overview, 'Captures alone').focus();
  for (let read = 0, step = 0; read < total; step += 1) {
    expect(step, 'Tab reaches every ringed square').toBeLessThan(total * 8);
    await page.keyboard.press('Tab');
    if ((await focused.count()) === 1) {
      await expectReadout(line, focused);
      read += 1;
    }
  }
  // From the last ringed square, Tab takes the line's links; the line stays.
  for (const name of ['Open its exhibit', 'Receipt']) {
    await page.keyboard.press('Tab');
    await expect(line.getByRole('link', {name})).toBeFocused();
    await expectReadout(line, ringed.last());
  }
  await page.keyboard.press('Tab');
  await expect(line).toContainText('With the tail:');
});

test('a pointed square stays read out while the pointer moves to its links', async ({page}) => {
  await page.goto('exhibits/');
  const overview = page.locator('.xh-ov');
  const line = overview.locator('.xh-detail-t:visible');
  const square = overview.locator('.xh-cells a.xh-q-k:not([data-answer="0"])').first();
  const exhibit = (await square.getAttribute('data-exhibit')) ?? '';
  const answer = Number(await square.getAttribute('data-answer'));

  await overview.locator('.xh-detail').scrollIntoViewIfNeeded();
  await square.hover();
  await expectReadout(line, square);
  // In one move from the square onto the line, passing no other square.
  const detail = await overview.locator('.xh-detail').boundingBox();
  await page.mouse.move((detail?.x ?? 0) + 2, (detail?.y ?? 0) + 2);
  await expectReadout(line, square);
  await line.getByRole('link', {name: 'Open its exhibit'}).click();
  await expect(page).toHaveURL(new RegExp(`#${exhibit}$`));
  const picks = page.locator(`article[data-xh="${exhibit}"]`).getByRole('group', {name: 'Answers'});
  await expect(picks.getByRole('button').nth(answer)).toHaveAttribute('aria-pressed', 'true');

  // Leaving the overview brings the summary back; a press keeps a square.
  await page.mouse.move(0, 0);
  await expect(line).toContainText('With the tail:');
  const plain = overview.locator('.xh-cells span.xh-q').first();
  await plain.click();
  await page.mouse.move(0, 0);
  await expectVerdicts(line, plain);
  await page.keyboard.press('Escape');
  await expect(line).toContainText('With the tail:');
});

test('a ringed square and a turned answer open their exhibit on that answer', async ({page}) => {
  await page.goto('exhibits/');
  const links = [
    page.locator('.xh-cells a.xh-q-k:not([data-answer="0"])').last(),
    page.locator('.xh-turned a:not([data-answer="0"])').first(),
  ];
  for (const link of links) {
    const exhibit = (await link.getAttribute('data-exhibit')) ?? '';
    const answer = Number(await link.getAttribute('data-answer'));
    const card = page.locator(`article[data-xh="${exhibit}"]`);
    await verifier(card, 'Captures alone').click();
    await expect(card).toHaveAttribute('data-view', 'alone');

    await link.click();
    await expect(page).toHaveURL(new RegExp(`#${exhibit}$`));
    await expect(card).toHaveAttribute('data-view', 'tail');
    const picks = card.getByRole('group', {name: 'Answers'}).getByRole('button');
    await expect(picks.nth(answer)).toHaveAttribute('aria-pressed', 'true');
    await expect(card.locator('.xh-ex-answer:visible')).toHaveAttribute('data-ans', String(answer));
    await expect(card.getByRole('heading', {level: 3})).toBeInViewport();
  }
});

test("an exhibit's switch, picks and probes change only what is shown", async ({page}) => {
  await page.goto('exhibits/');
  const card = page.locator('article.xh-ex').first();
  const picks = card.getByRole('group', {name: 'Answers'}).getByRole('button');
  const before = await sources(page);

  await expect(card.locator('.xh-ex-answer:visible')).toHaveAttribute('data-ans', '0');
  await picks.nth(1).click();
  await expect(picks.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(card.locator('.xh-ex-answer:visible')).toHaveAttribute('data-ans', '1');
  await expect(card.locator('.xh-tapes-in:visible')).toHaveCount(1);

  // Captures alone: the tail folds away to no width and no height, so no
  // tape grows for it; the stamp reads the verdict alone and the killing
  // frames give way to the message.
  const stamp = card.locator('.xh-stamp:visible [data-fmt="outcome"]:visible');
  await expect(stamp).toHaveAttribute('data-v', '"silent_wrong"');
  const shown = await tapeSizes(card);
  expect(shown.length).toBeGreaterThan(1);
  await verifier(card, 'Captures alone').click();
  await expect(card).toHaveAttribute('data-view', 'alone');
  await expect(stamp).not.toHaveAttribute('data-v', '"silent_wrong"');
  const folded = await tapeSizes(card);
  expect(folded.map(({tail}) => tail)).toEqual(shown.map(() => [0, 0]));
  folded.forEach(({tape}, at) => {
    expect(tape, `tape ${String(at)}`).toBeLessThanOrEqual(shown[at]?.tape ?? 0);
  });
  await expect(card.locator('.xh-pl:visible')).toHaveCount(0);
  await expect(card.locator('.xh-quiet:visible')).toHaveCount(1);

  await verifier(card, 'With the witness tail').click();
  const probes = card.getByRole('group', {name: 'Probe'}).getByRole('button');
  await probes.last().click();
  await expect(probes.last()).toHaveAttribute('aria-pressed', 'true');
  await expect(card.locator('.xh-pl:visible')).toHaveCount(1);
  const probe = await probes.last().innerText();
  await expect(card.locator('.xh-pl:visible caption')).toContainText(probe);
  expect(await sources(page)).toEqual(before);
});

test("pointing at a frame of each probe's tape reads out that frame", async ({page}) => {
  await page.goto('exhibits/');
  const card = page.locator('article.xh-ex').first();
  const readout = card.locator('.xh-fd');
  const tapes = await card.locator('.xh-tapes-in:visible .xh-tape').all();
  expect(tapes.length).toBeGreaterThan(1);

  for (const tape of tapes) {
    const cell = tape.locator('.xh-seg-t .xh-f').last();
    await cell.hover();
    const frame = Number(await cell.getAttribute('data-n'));
    const number = readout.locator('b [data-fmt="int"]');
    const probe = readout.locator('b [data-fmt="text"]');
    await expect(number).toHaveText(String(frame));
    await expect(probe).toHaveText((await tape.locator('.xh-tape-l b').textContent()) ?? '');
    await expect(readout).toContainText(STATES[(await cell.getAttribute('data-s')) ?? ''] ?? '?');
    // The frame's row is that probe's, at the frame's place in its table.
    const [op, file, at = ''] = JSON.parse((await probe.getAttribute('data-src')) ?? '[]') as string[];
    const row = at.replace(/\/probe_id$/, `/frames/${String(frame - 1)}/n`);
    expect(JSON.parse((await number.getAttribute('data-src')) ?? '[]')).toEqual([op, file, row]);
  }
  await page.mouse.move(0, 0);
  await expect(readout).toContainText('Point at a frame to read it.');
});
