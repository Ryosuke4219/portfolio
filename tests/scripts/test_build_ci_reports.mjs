import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { summariseJUnit } from '../../scripts/build-ci-reports.mjs';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, '..', '..');
const scriptPath = path.resolve(repoRoot, 'scripts/build-ci-reports.mjs');
const scriptSource = fs.readFileSync(scriptPath, 'utf8');

test('summariseJUnit counts errored status as error', (t) => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-reports-'));
  t.after(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  const inputPath = path.join(tmpDir, 'junit.xml');
  const outputDir = path.join(tmpDir, 'out');

  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="Dummy">\n  <testcase classname="Example" name="errored case" status="errored" time="0.1" />\n</testsuite>\n`;
  fs.writeFileSync(inputPath, xml, 'utf8');

  const summary = summariseJUnit(inputPath, outputDir);

  assert.equal(summary.errors, 1);
});

test('coverage paths target main project directory', () => {
  const expectedHtmlPath = "path.resolve(rootDir, 'projects/04-llm-adapter/htmlcov')";
  const expectedXmlPath = "path.resolve(rootDir, 'projects/04-llm-adapter/coverage.xml')";

  if (!scriptSource.includes(expectedHtmlPath)) {
    throw new Error(`coverageHtmlDir は ${expectedHtmlPath} を参照していません`);
  }

  if (!scriptSource.includes(expectedXmlPath)) {
    throw new Error(`coverageXmlPath は ${expectedXmlPath} を参照していません`);
  }
});
