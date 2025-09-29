import assert from 'node:assert';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { Readable } from 'node:stream';
import { test } from 'node:test';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

import { parseSpecFile, validateCasesSchema } from '../projects/01-spec2cases-md2json/scripts/spec2cases.mjs';
import { generateTestsFromBlueprint } from '../projects/02-blueprint-to-playwright/scripts/blueprint_to_code.mjs';
import { analyzeJUnitReport } from '../projects/03-ci-flaky/scripts/analyze-junit.mjs';
import { parseJUnitStream } from '../projects/03-ci-flaky/src/junit-parser.js';
import {
  LLM2PW_SAMPLE_BLUEPRINT_PATH,
  SPEC2CASES_SAMPLE_SPEC_TXT_PATH,
} from '../scripts/paths.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

test('spec text is converted into structured cases', () => {
  const result = parseSpecFile(SPEC2CASES_SAMPLE_SPEC_TXT_PATH);
  assert.equal(result.suite, 'ログイン機能');
  assert.equal(result.cases.length, 2);
  assert.deepEqual(result.cases[0].steps, ['ログイン画面にアクセス', 'ID/PWを入力', 'ログインを押下']);
  const errors = validateCasesSchema(result);
  assert.deepEqual(errors, []);
});

test('blueprint is rendered into playwright spec files', () => {
  const blueprint = readJson(LLM2PW_SAMPLE_BLUEPRINT_PATH);
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'playwright-gen-'));
  const files = generateTestsFromBlueprint(blueprint, tmpDir);
  assert.equal(files.length, blueprint.scenarios.length);
  const firstFile = path.join(tmpDir, files[0]);
  const content = fs.readFileSync(firstFile, 'utf8');
  assert.ok(content.includes("test('LGN-001 正常ログイン'"));
  assert.ok(content.includes("await expect(page).toHaveURL(/dashboard/);"));
});

test('blueprint generation fails when scenario IDs would create duplicate filenames', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'playwright-gen-duplicate-'));
  const duplicateBlueprint = {
    scenarios: [
      {
        id: 'DUP-001',
        title: 'first',
        selectors: { user: '#user', pass: '#pass', submit: '#submit' },
        data: { user: 'alice', pass: 'secret' },
        asserts: [],
      },
      {
        id: 'dup 001',
        title: 'second',
        selectors: { user: '#user', pass: '#pass', submit: '#submit' },
        data: { user: 'bob', pass: 'hunter2' },
        asserts: [],
      },
    ],
  };

  assert.throws(
    () => {
      generateTestsFromBlueprint(duplicateBlueprint, tmpDir);
    },
    (error) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /duplicate scenario file name/i);
      assert.match(error.message, /DUP-001/);
      assert.match(error.message, /dup 001/);
      return true;
    },
  );
});

test('junit analysis tracks flaky transitions', async () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'junit-db-'));
  const junitPath = path.join(tmpDir, 'junit-results.xml');
  const dbPath = path.join(tmpDir, 'database.json');

  const failing = `<testsuite><testcase classname="Login" name="HappyPath"><failure>boom</failure></testcase></testsuite>`;
  fs.writeFileSync(junitPath, failing, 'utf8');
  const first = await analyzeJUnitReport(junitPath, dbPath);
  assert.equal(first.attemptsCount, 1);

  const passing = `<testsuite><testcase classname="Login" name="HappyPath"/></testsuite>`;
  fs.writeFileSync(junitPath, passing, 'utf8');
  const second = await analyzeJUnitReport(junitPath, dbPath);
  assert.equal(second.attemptsCount, 1);

  const readEntries = async (expected) => {
    const deadline = Date.now() + 1000;
    while (Date.now() < deadline) {
      if (fs.existsSync(dbPath)) {
        const text = fs.readFileSync(dbPath, 'utf8').trim();
        if (text) {
          const entries = text.split('\n').map((line) => JSON.parse(line));
          if (!expected || entries.length === expected) return entries;
        }
      }
      await delay(10);
    }
    throw new Error('timed out waiting for junit log entries');
  };

  const [firstEntry, secondEntry] = await readEntries(2);
  assert.equal(firstEntry.status, 'fail');
  assert.equal(secondEntry.status, 'pass');
  assert.equal(firstEntry.canonical_id, secondEntry.canonical_id);
});

test('parseJUnitStream aggregates attempts and classifies timeouts', async () => {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
    <testsuite name="Top">
      <testcase classname="Login" name="Fast" time="0.2" />
      <testcase classname="Login" name="Slow" time="4">
        <failure message="unexpected"/>
      </testcase>
    </testsuite>`;

  const stream = Readable.from([xml]);
  const { attempts, suiteDurations } = await parseJUnitStream(stream, { timeoutFactor: 0.1 });

  assert.equal(attempts.length, 2);
  const slow = attempts.find((item) => item.name === 'Slow');
  assert.ok(slow, 'expected slow testcase to be parsed');
  assert.equal(slow.status, 'fail');
  assert.equal(slow.failure_kind, 'timeout');

  const durations = suiteDurations.get('Top');
  assert.deepEqual([...durations].sort((a, b) => a - b), [200, 4000]);
});

test('playwright stub gracefully handles no-arg invocation', () => {
  const cliPath = path.join(rootDir, 'node_modules', '.bin', 'playwright');
  assert.ok(fs.existsSync(cliPath), 'playwright CLI should be installed via npm ci');

  const result = spawnSync(process.execPath, [cliPath], { encoding: 'utf8' });
  assert.equal(result.status, 0, `expected exit code 0, received ${result.status}`);
  assert.match(result.stdout, /Usage: playwright test/);
});

test('playwright stub treats install commands as no-ops', () => {
  const cliPath = path.join(rootDir, 'node_modules', '.bin', 'playwright');
  assert.ok(fs.existsSync(cliPath), 'playwright CLI should be installed via npm ci');

  const result = spawnSync(process.execPath, [cliPath, 'install'], { encoding: 'utf8' });
  assert.equal(result.status, 0, `expected exit code 0, received ${result.status}`);
  assert.match(result.stdout, /Skipping "playwright install"/);
});

function extractRunCommands(yamlText) {
  const lines = yamlText.split(/\r?\n/);
  const commands = [];

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const match = line.match(/^(\s*)run:\s*(.*)$/);
    if (!match) continue;

    const [, indent, value] = match;
    if (value === '|' || value === '>') {
      const blockIndent = indent.length + 2;
      const blockLines = [];
      let cursor = index + 1;
      while (cursor < lines.length) {
        const current = lines[cursor];
        const currentIndent = current.match(/^\s*/)[0].length;
        if (currentIndent <= indent.length && current.trim() !== '') break;
        if (currentIndent < blockIndent && current.trim() === '') {
          blockLines.push('');
          cursor += 1;
          continue;
        }
        if (currentIndent < blockIndent) break;
        blockLines.push(current.slice(blockIndent));
        cursor += 1;
      }
      commands.push(blockLines.join('\n'));
      index = cursor - 1;
      continue;
    }

    commands.push(value.trim());
  }

  return commands;
}

function extractExecutableLines(command) {
  return command
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));
}

function isPytestExecutionLine(line) {
  const executionPatterns = [
    /\bpytest\.main\b/, // python -c "... pytest.main(..." pattern
    /(^|\s)python[\d.]*\b[^\n]*\b-m\s+pytest\b/, // python -m pytest ...
  ];

  return executionPatterns.some((pattern) => pattern.test(line));
}

function collectPytestExecutionCommands(commands) {
  return commands.filter((command) =>
    extractExecutableLines(command).some(isPytestExecutionLine),
  );
}

test('python pytest runs exactly once in CI workflow', () => {
  const ciWorkflowPath = path.join(rootDir, '.github', 'workflows', 'ci.yml');
  const workflow = fs.readFileSync(ciWorkflowPath, 'utf8');
  const runCommands = extractRunCommands(workflow);
  const executions = collectPytestExecutionCommands(runCommands);
  assert.equal(executions.length, 1);
});
