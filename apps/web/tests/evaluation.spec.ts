import AxeBuilder from '@axe-core/playwright';
import {expect, test} from '@playwright/test';

test('illustrative evaluation exposes the evidence chain', async ({page}) => {
  await page.goto('/evaluate');

  await expect(
    page.getByRole('heading', {
      name: 'Find the packet that disproves the filter.',
    }),
  ).toBeVisible();
  await expect(
    page
      .getByRole('region', {name: 'Execution environment'})
      .getByText('Illustrative mock', {exact: true}),
  ).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Typed Intent IR'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Compiled filter'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Counterexamples'})).toBeVisible();

  await page.getByRole('button', {name: '113'}).click();
  await expect(page.getByRole('heading', {name: 'Frame 113'})).toBeVisible();
  await expect(page.getByText('Observed: true')).toBeVisible();
});

test('evaluation page has no serious accessibility violations', async ({page}) => {
  await page.goto('/evaluate');

  const results = await new AxeBuilder({page}).analyze();
  const seriousOrCritical = results.violations.filter((violation) =>
    violation.impact === 'serious' || violation.impact === 'critical',
  );

  expect(seriousOrCritical).toEqual([]);
});
