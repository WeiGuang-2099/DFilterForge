import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';

// Paths are relative so that they resolve under the configured base URL.
const PAGES = [
  {path: './', heading: 'Find the packet that disproves the filter.'},
  {path: 'methodology/', heading: 'Evidence has a boundary.'},
] as const;

for (const {path, heading} of PAGES) {
  test(`${path} renders its heading and shows no number`, async ({page}) => {
    await page.goto(path);

    await expect(page.getByRole('heading', {level: 1, name: heading})).toBeVisible();
    // No page may show a number until it is rendered from a committed file.
    expect(await page.title()).not.toMatch(/[0-9]/);
    expect(await page.locator('body').innerText()).not.toMatch(/[0-9]/);
  });

  test(`${path} has no serious accessibility violations`, async ({page}) => {
    await page.goto(path);

    const results = await new AxeBuilder({page}).analyze();
    const seriousOrCritical = results.violations.filter(
      (violation) => violation.impact === 'serious' || violation.impact === 'critical',
    );

    expect(seriousOrCritical).toEqual([]);
  });
}
