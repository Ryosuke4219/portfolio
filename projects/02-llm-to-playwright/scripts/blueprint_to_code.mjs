import fs from 'node:fs';
import path from 'node:path';

const input = process.argv[2];
if (!input) {
  console.error('Usage: node blueprint_to_code.mjs <blueprint.json>');
  process.exit(2);
}

const outDir = path.join(process.cwd(), 'projects/02-llm-to-playwright/tests/generated');
fs.mkdirSync(outDir, { recursive: true });

const blueprint = JSON.parse(fs.readFileSync(input, 'utf8'));
if (!Array.isArray(blueprint.scenarios)) {
  console.error('Invalid blueprint: scenarios[] is required');
  process.exit(1);
}

const escapeJs = (value) =>
  (value ?? '')
    .toString()
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'");

const toRegex = (value) => {
  const v = (value ?? '').toString();
  const raw = v.split(':', 2)[1] ?? '';
  const trimmed = raw.replace(/^\/+/, '');
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return `/${escaped}/`;
};

const toText = (value) => {
  const v = (value ?? '').toString();
  const raw = v.split(':', 2)[1] ?? '';
  return JSON.stringify(raw);
};

const renderTest = (scenario) => {
  const lines = [];
  lines.push("import { test, expect } from '@playwright/test';");
  lines.push('');
  lines.push(`test('${scenario.id} ${scenario.title}', async ({ page }) => {`);
  lines.push("  await page.goto(process.env.BASE_URL || 'http://127.0.0.1:4173');");
  lines.push(
    `  await page.fill('${escapeJs(scenario.selectors.user)}', '${escapeJs(scenario.data.user)}');`,
  );
  lines.push(
    `  await page.fill('${escapeJs(scenario.selectors.pass)}', '${escapeJs(scenario.data.pass)}');`,
  );
  lines.push(`  await page.click('${escapeJs(scenario.selectors.submit)}');`);
  lines.push('');
  for (const assert of scenario.asserts) {
    lines.push(`  // assert: ${assert}`);
    if (typeof assert === 'string' && assert.startsWith('url:')) {
      lines.push(`  await expect(page).toHaveURL(${toRegex(assert)});`);
    } else if (typeof assert === 'string' && assert.startsWith('text:')) {
      lines.push(`  await expect(page.getByText(${toText(assert)})).toBeVisible();`);
    } else {
      lines.push("  // Unsupported assert type");
    }
    lines.push('');
  }
  if (lines[lines.length - 1] === '') {
    lines.pop();
  }
  lines.push('});');
  lines.push('');
  return lines.join('\n');
};

const generated = [];

for (const scenario of blueprint.scenarios) {
  if (!scenario?.id || !scenario?.title) {
    console.error('Scenario must include id and title:', scenario);
    process.exit(1);
  }
  if (!scenario.selectors || !scenario.selectors.user || !scenario.selectors.pass || !scenario.selectors.submit) {
    console.error(`Scenario ${scenario.id} is missing selectors.user/pass/submit`);
    process.exit(1);
  }
  if (!scenario.data || typeof scenario.data.user !== 'string' || typeof scenario.data.pass !== 'string') {
    console.error(`Scenario ${scenario.id} is missing data.user or data.pass`);
    process.exit(1);
  }
  if (!Array.isArray(scenario.asserts)) {
    console.error(`Scenario ${scenario.id} has invalid asserts. Expected an array.`);
    process.exit(1);
  }

  const filename = `${scenario.id.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.spec.mjs`;
  const code = renderTest(scenario);
  fs.writeFileSync(path.join(outDir, filename), code, 'utf8');
  generated.push(filename);
  console.log('📝 generated:', filename);
}

console.log(`✅ done (files: ${generated.join(', ')})`);
