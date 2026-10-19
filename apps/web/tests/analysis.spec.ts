import {expect, test} from '@playwright/test';

// The analysis page's islands show one seed's figure, one ribbon's answers,
// one class's receipt and one case at a time. Every value is in the HTML
// whatever they show, and tests/consistency.spec.ts checks each one; this
// checks that the controls change what is shown.

test('the analysis page shows the seed, ribbon, class and case a visitor picks', async ({
  page,
}) => {
  await page.goto('training/analysis/');

  const flow = page.locator('.an-flow');
  const seeds = flow.getByRole('group', {name: 'Fine-tuned seed'}).getByRole('button');
  const detail = flow.locator('.an-detail:visible .an-detail-t');
  await expect(seeds).toHaveCount(3);
  await expect(seeds.first()).toHaveAttribute('aria-pressed', 'true');
  // A seed opens on the base model's refused answers that now run wrongly.
  await expect(detail).toHaveCount(1);
  await expect(detail).toContainText('refused answers are silently wrong under seed');

  await seeds.nth(1).click();
  const second = (await seeds.nth(1).innerText()).toLowerCase();
  await expect(seeds.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(detail).toContainText(`under ${second}.`);

  // Pointing at another ribbon only marks it: the list stays put while the
  // reader moves down to it.
  const ribbon = flow.locator('.an-rib:visible').first();
  const listed = await detail.innerText();
  await ribbon.hover();
  await expect(detail).toHaveText(listed);
  await expect(ribbon).toHaveAttribute('aria-pressed', 'false');

  // Focusing a ribbon lists its answers; its name is that list's opening.
  await ribbon.focus();
  await expect(ribbon).toHaveAttribute('aria-pressed', 'true');
  await expect(ribbon).toHaveAccessibleName(await detail.innerText());
  await ribbon.press('Enter');
  await expect(ribbon).toHaveAttribute('aria-pressed', 'true');

  const kinds = page.locator('section[aria-labelledby="an-kinds-h"]');
  const count = kinds.getByRole('button', {name: /^Missing field Base model [0-9]+$/});
  await count.click();
  await expect(count).toHaveAttribute('aria-pressed', 'true');
  await expect(kinds.locator('.an-receipt:visible')).toHaveCount(1);
  await expect(kinds.locator('.an-receipt:visible h3')).toContainText('Missing field Base model');

  const near = page.locator('section[aria-labelledby="an-near-h"]');
  const square = near.locator('.an-sq[aria-pressed]').nth(1);
  await square.click();
  await expect(square).toHaveAttribute('aria-pressed', 'true');
  await expect(near.locator('.an-receipt:visible')).toHaveCount(1);
  await expect(square).toHaveAccessibleName(await near.locator('.an-receipt:visible h3').innerText());
});
