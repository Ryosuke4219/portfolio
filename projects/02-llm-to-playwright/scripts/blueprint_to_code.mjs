#!/usr/bin/env node
import fs from 'fs';
import path from 'path';

function usage() {
  console.error('Usage: node blueprint_to_code.mjs <blueprint.json>');
}

function readJson(filePath) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    const message = error && typeof error.message === 'string' ? error.message : String(error);
    throw new Error(`Failed to read "${filePath}": ${message}`);
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new Error(`Invalid JSON in "${filePath}": ${(error && error.message) || error}`);
  }
}

function sanitiseFileName(id) {
  const base = (id || '').toString().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return base || 'scenario';
}

function toQuoted(value) {
  return JSON.stringify((value ?? '').toString());
}

function toUrlRegex(assertion) {
  const raw = assertion.split(':', 2)[1] ?? '';
  const trimmed = raw.replace(/^\/+/, '');
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return `/${escaped}/`;
}

function buildAssert(assertion) {
  if (typeof assertion !== 'string') {
    return '  // skipped: unsupported assertion';
  }
  if (assertion.startsWith('url:')) {
    return `  await expect(page).toHaveURL(${toUrlRegex(assertion)});`;
  }
  if (assertion.startsWith('text:')) {
    const raw = assertion.split(':', 2)[1] ?? '';
    return `  await expect(page.getByText(${JSON.stringify(raw)})).toBeVisible();`;
  }
  return `  // unsupported assert: ${assertion.replace(/\*\//g, '* /')}`;
}

function renderScenario(scenario) {
  const selectors = scenario.selectors || {};
  const data = scenario.data || {};
  const assertLines = Array.isArray(scenario.asserts)
    ? scenario.asserts.map((item) => buildAssert(item)).join('\n')
    : '';

  const lines = [
    "import { test, expect } from '@playwright/test';",
    '',
    `test('${scenario.id} ${scenario.title}', async ({ page }) => {`,
    "  await page.goto(process.env.BASE_URL || 'http://localhost:5173');",
  ];

  if (selectors.user && data.user !== undefined) {
    lines.push(`  await page.fill(${toQuoted(selectors.user)}, ${toQuoted(data.user)});`);
  }
  if (selectors.pass && data.pass !== undefined) {
    lines.push(`  await page.fill(${toQuoted(selectors.pass)}, ${toQuoted(data.pass)});`);
  }
  if (selectors.submit) {
    lines.push(`  await page.click(${toQuoted(selectors.submit)});`);
  }

  if (assertLines) {
    lines.push('', assertLines);
  }

  lines.push('});', '');

  return lines.join('\n');
}

export function generateTestsFromBlueprint(blueprint, outDir) {
  if (!blueprint || typeof blueprint !== 'object') {
    throw new Error('Blueprint must be an object');
  }
  if (!Array.isArray(blueprint.scenarios)) {
    throw new Error('Invalid blueprint: scenarios[] is required');
  }
  if (!outDir) {
    throw new Error('Output directory is required');
  }

  fs.mkdirSync(outDir, { recursive: true });
  const generatedFiles = [];

  for (const scenario of blueprint.scenarios) {
    if (!scenario || typeof scenario !== 'object') {
      continue;
    }
    const filename = `${sanitiseFileName(scenario.id)}.spec.ts`;
    const filePath = path.join(outDir, filename);
    const code = renderScenario(scenario);
    fs.writeFileSync(filePath, `${code}\n`, 'utf8');
    generatedFiles.push(filename);
  }

  return generatedFiles;
}

function main(argv) {
  const [, , inputPath] = argv;
  if (!inputPath) {
    usage();
    process.exit(2);
  }

  let blueprint;
  try {
    blueprint = readJson(inputPath);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }

  const outDir = path.join(process.cwd(), 'projects/02-llm-to-playwright/tests/generated');
  let generated;
  try {
    generated = generateTestsFromBlueprint(blueprint, outDir);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }

  for (const file of generated) {
    console.log('📝 generated:', file);
  }
  console.log('✅ done');
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv);
}
