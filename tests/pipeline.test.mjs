import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { spawnSync } from 'child_process';

import { parseSpecFile, validateCasesSchema } from '../projects/01-spec2cases/scripts/spec2cases.mjs';
import { generateTestsFromBlueprint } from '../projects/02-llm-to-playwright/scripts/blueprint_to_code.mjs';
import { analyzeJUnitReport } from '../projects/03-ci-flaky/scripts/analyze-junit.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

test('spec text is converted into structured cases', () => {
  const specPath = path.join(rootDir, 'projects/01-spec2cases/spec.sample.txt');
  const result = parseSpecFile(specPath);
  assert.equal(result.suite, 'ログイン機能');
  assert.equal(result.cases.length, 2);
  assert.deepEqual(result.cases[0].steps, ['ログイン画面にアクセス', 'ID/PWを入力', 'ログインを押下']);
  const errors = validateCasesSchema(result);
  assert.deepEqual(errors, []);
});

test('blueprint is rendered into playwright spec files', () => {
  const blueprint = readJson(path.join(rootDir, 'projects/02-llm-to-playwright/blueprint.sample.json'));
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'playwright-gen-'));
  const files = generateTestsFromBlueprint(blueprint, tmpDir);
  assert.equal(files.length, blueprint.scenarios.length);
  const firstFile = path.join(tmpDir, files[0]);
  const content = fs.readFileSync(firstFile, 'utf8');
  assert.ok(content.includes("test('LGN-001 正常ログイン'"));
  assert.ok(content.includes("await expect(page).toHaveURL(/dashboard/);"));
});

test('junit analysis tracks flaky transitions', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'junit-db-'));
  const junitPath = path.join(tmpDir, 'junit-results.xml');
  const dbPath = path.join(tmpDir, 'database.json');

  const failing = `<testsuite><testcase classname="Login" name="HappyPath"><failure>boom</failure></testcase></testsuite>`;
  fs.writeFileSync(junitPath, failing, 'utf8');
  const first = analyzeJUnitReport(junitPath, dbPath);
  assert.equal(first.flaky.length, 0);

  const passing = `<testsuite><testcase classname="Login" name="HappyPath"/></testsuite>`;
  fs.writeFileSync(junitPath, passing, 'utf8');
  const second = analyzeJUnitReport(junitPath, dbPath);
  assert.ok(second.flaky.includes('Login::HappyPath'));
});

test('playwright stub gracefully handles no-arg invocation', () => {
  const cliPath = path.join(rootDir, 'node_modules', '.bin', 'playwright');
  assert.ok(fs.existsSync(cliPath), 'playwright CLI should be installed via npm ci');

  const result = spawnSync(process.execPath, [cliPath], { encoding: 'utf8' });
  assert.equal(result.status, 0, `expected exit code 0, received ${result.status}`);
  assert.match(result.stdout, /Usage: playwright test/);
});
