import { test, expect } from '@playwright/test';

const { readFileSync } = require('node:fs');
const path = require('node:path');
const axe = require('axe-core');

const projectRoot = process.cwd();
const dataDir = path.resolve(projectRoot, 'projects/02-llm-to-playwright/tests/generated/data');

const loginCases = JSON.parse(readFileSync(path.join(dataDir, 'login-cases.json'), 'utf8'));
const a11yCsv = readFileSync(path.join(dataDir, 'a11y-pages.csv'), 'utf8');
const accessibilityTargets = parseCsv(a11yCsv);

for (const scenario of loginCases) {
  test(`data-driven login — ${scenario.name}`, async ({ page }) => {
    await page.goto('/index.html');
    if (typeof page.waitForLoadState === 'function') {
      await page.waitForLoadState('networkidle');
    }

    const usernameField = page.getByTestId('login-username');
    const passwordField = page.getByTestId('login-password');
    const submitButton = page.getByTestId('login-submit');
    await usernameField.fill(scenario.username);
    await passwordField.fill(scenario.password);
    await submitButton.click();

    if (typeof page.waitForLoadState === 'function') {
      await page.waitForLoadState('networkidle');
    }

    const expectedUrlPattern = new RegExp(scenario.expected.urlPattern);
    if (typeof page.waitForURL === 'function') {
      await page.waitForURL(expectedUrlPattern);
    }
    await expect(page).toHaveURL(expectedUrlPattern);

    const banner = page.getByTestId(scenario.expected.bannerTestId);
    await expect(banner).toBeVisible();
  });
}

test('dashboard visual smoke snapshot', async ({ page }) => {
  await page.goto('/dashboard.html');
  await expect(page).toHaveScreenshot('auth/dashboard.html');
});

for (const target of accessibilityTargets) {
  test(`axe accessibility scan — ${target.label}`, async ({ page }) => {
    await page.goto(target.path);
    const html = await page.content();
    const results = await axe.run(html);
    await expect(results.violations).toEqual([]);
  });
}

function parseCsv(raw) {
  return raw
    .split(/\r?\n/)
    .slice(1)
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      const [pathValue, label] = line.split(',');
      return {
        path: (pathValue || '').trim(),
        label: (label || '').trim(),
      };
    });
}
