#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ---- CLI / Paths ----
function usage() {
  console.error('Usage: node blueprint_to_code.mjs <blueprint.json> [outputDir]');
}

const defaultOutputDir = path.join(process.cwd(), 'projects/02-blueprint-to-playwright/tests/generated');

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
  const base = (id || '')
    .toString()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return base || 'scenario';
}

function toQuoted(value) {
  // Safe JS string literal via JSON
  return JSON.stringify((value ?? '').toString());
}

function toSingleQuoted(value) {
  const raw = (value ?? '').toString();
  const escaped = raw.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  return `'${escaped}'`;
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
    const urlRegex = toUrlRegex(assertion);
    return [
      "  if (typeof page.waitForURL === 'function') {",
      `    await page.waitForURL(${urlRegex});`,
      '  }',
      `  await expect(page).toHaveURL(${urlRegex});`,
    ].join('\n');
  }
  if (assertion.startsWith('text:')) {
    const raw = assertion.split(':', 2)[1] ?? '';
    return `  await expect(page.getByText(${JSON.stringify(raw)})).toBeVisible();`;
  }
  return `  // unsupported assert: ${assertion.replace(/\*\//g, '* /')}`;
}

// ---- Rendering ----
function renderScenario(scenario) {
  validateScenario(scenario);
  const selectors = scenario.selectors || {};
  const data = scenario.data || {};
  const assertLines = Array.isArray(scenario.asserts) ? scenario.asserts.map((assertion) => buildAssert(assertion)) : [];
  const startUrl = typeof scenario.url === 'string' && scenario.url.trim().length > 0 ? scenario.url : '/';

  const lines = [
    "import { test, expect } from '@playwright/test';",
    '',
    `test(${toSingleQuoted(`${scenario.id} ${scenario.title}`)}, async ({ page }) => {`,
    `  await page.goto(${toQuoted(startUrl)});`,
    "  if (typeof page.waitForLoadState === 'function') {",
    "    await page.waitForLoadState('networkidle');",
    '  }',
    `  await page.fill(${toQuoted(selectors.user)}, ${toQuoted(data.user)});`,
    `  await page.fill(${toQuoted(selectors.pass)}, ${toQuoted(data.pass)});`,
    `  await page.click(${toQuoted(selectors.submit)});`,
    "  if (typeof page.waitForLoadState === 'function') {",
    "    await page.waitForLoadState('networkidle');",
    '  }',
  ];

  if (assertLines.length > 0) {
    lines.push('');
    lines.push(...assertLines);
  }

  lines.push('});', '');

  return lines.join('\n');
}

// ---- Generation ----
function generateTestsFromBlueprint(blueprint, outputDir = defaultOutputDir) {
  validateBlueprint(blueprint);
  const targetDir = outputDir ? path.resolve(outputDir) : defaultOutputDir;
  fs.mkdirSync(targetDir, { recursive: true });

  const seenFileNames = new Set();
  const fileNameSources = new Map();
  const written = [];

  for (const scenario of blueprint.scenarios) {
    validateScenario(scenario);
    const fileNameBase = sanitiseFileName(scenario.id);

    if (seenFileNames.has(fileNameBase)) {
      const previousId = fileNameSources.get(fileNameBase);
      throw new Error(
        `Duplicate scenario file name "${fileNameBase}" generated from scenario IDs "${previousId}" and "${scenario.id}".`,
      );
    }

    seenFileNames.add(fileNameBase);
    fileNameSources.set(fileNameBase, scenario.id);

    const fileName = `${fileNameBase}.spec.ts`;
    const filePath = path.join(targetDir, fileName);
    const fileContents = renderScenario(scenario);
    fs.writeFileSync(filePath, fileContents, 'utf8');
    written.push(fileName);
  }

  return written;
}

// ---- CLI Entrypoint ----
const isMainModule = process.argv[1]
  ? path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))
  : false;

if (isMainModule) {
  const [, , blueprintPath, outputDirArg] = process.argv;

  if (!blueprintPath) {
    usage();
    process.exit(1);
  }

  const resolvedBlueprintPath = path.resolve(process.cwd(), blueprintPath);
  const resolvedOutputDir = outputDirArg ? path.resolve(process.cwd(), outputDirArg) : defaultOutputDir;

  try {
    const blueprint = readJson(resolvedBlueprintPath);
    fs.mkdirSync(resolvedOutputDir, { recursive: true });
    const generated = generateTestsFromBlueprint(blueprint, resolvedOutputDir);
    const count = generated.length;
    const suffix = count === 1 ? '' : 's';
    console.log(`Generated ${count} Playwright test file${suffix} in ${resolvedOutputDir}`);
  } catch (error) {
    const message = error && typeof error.message === 'string' ? error.message : String(error);
    console.error(message);
    process.exit(1);
  }
}

export { generateTestsFromBlueprint, renderScenario, sanitiseFileName };
