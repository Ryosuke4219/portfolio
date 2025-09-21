#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

// ---- CLI / Paths ----
function usage() {
  console.error('Usage: node blueprint_to_code.mjs <blueprint.json>');
}

const [, , inputPath] = process.argv;
if (!inputPath) {
  usage();
  process.exit(2);
}

const outDir = path.join(process.cwd(), 'projects/02-llm-to-playwright/tests/generated');

// ---- IO Helpers ----
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

// ---- Validation ----
function validateBlueprint(blueprint) {
  if (!blueprint || typeof blueprint !== 'object') {
    throw new Error('Blueprint must be an object.');
  }
  if (!Array.isArray(blueprint.scenarios)) {
    throw new Error('Invalid blueprint: scenarios[] is required');
  }
}

function validateScenario(scenario) {
  if (!scenario || typeof scenario !== 'object') {
    throw new Error('Scenario must be an object.');
  }
  if (!scenario.id || !scenario.title) {
    throw new Error('Scenario must include non-empty id and title.');
  }
  if (!scenario.selectors || !scenario.selectors.user || !scenario.selectors.pass || !scenario.selectors.submit) {
    throw new Error(`Scenario ${scenario.id} is missing selectors.user/pass/submit`);
  }
  if (!scenario.data || typeof scenario.data.user !== 'string' || typeof scenario.data.pass !== 'string') {
    throw new Error(`Scenario ${scenario.id} is missing data.user or data.pass (string).`);
  }
  if (!Array.isArray(scenario.asserts)) {
    throw new Error(`Scenario ${scenario.id} has invalid asserts. Expected an array.`);
  }
}

// ---- Utilities for codegen ----
function sanitiseFileName(id) {
  const base = (id || '').toString().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return base || 'scenario';
}

function toQuoted(value) {
  // Safe JS string literal via JSON
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

// ---- Rendering ----
function renderScenario(scenario) {
  const selectors = scenario.selectors || {};
  const data = scenario.data || {};
  const assertLines = Array.isArray(scenario.asserts)
    ? scenario.asserts.map((a) => [`  // assert: ${String(a)}`, buildAssert(a)].join('\n')).join('\n')
    : '';

  const lines = [];
  lines.push("import { test, expect } from '@playwright/test';");
  lines.push('');
  lines.push(`test('${scenario.id} ${scenario.title}', async ({ page }) => {`);
  lines.push("  await page.goto(process.env.BASE_URL || 'http://127.0.0.1:4173');");

  // Inputs
  lines.push(`  await page.fill(${toQuoted(selectors.user)}, ${toQuoted(data.user)});`);
  lines.push(`  await page.fill(${toQuoted(selectors.pass)}, ${toQuoted(data.pass)});`);
  lines.push(`  await page.click(${toQuoted(selectors.submit)});`);

  if (assertLines) {
    lines.push('');
    lines.push(assertLines);
  }

  lines.push('});');
  lines.push('');
  return lines.join('\n');
}

// ---- Public API (used by script & importers) ----
export function generateTestsFromBlueprint(blueprint, outputDirectory) {
  validateBlueprint(blueprint);
  if (!outputDirectory) throw new Error('Output directory is required');

  fs.mkdirSync(outputDirectory, { recursive: true });
  const generatedFiles = [];

  for (const scenario of blueprint.scenarios) {
    validateScenario(scenario);
    const filename = `${sanitiseFileName(scenario.id)}.spec.ts`;
    const filePath = path.join(outputDirectory, filename);
    const code = renderScenario(scenario);
    fs.writeFileSync(filePath, `${code}\n`, 'utf8');
    generatedFiles.push(filename);
  }

  return generatedFiles;
}

// ---- CLI main ----
function main() {
  let blueprint;
  try {
    blueprint = readJson(inputPath);
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }

  let generated;
  try {
    generated = generateTestsFromBlueprint(blueprint, outDir);
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }

  for (const f of generated) {
    console.log('📝 generated:', f);
  }
  console.log(`✅ done (files: ${generated.join(', ')})`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
