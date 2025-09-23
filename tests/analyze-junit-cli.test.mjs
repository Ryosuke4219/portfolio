import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('ci analyzer CLI succeeds without external fast-xml-parser dependency', () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-analyze-cli-'));
  const junitPath = path.join(tmpDir, 'junit-results.xml');
  const dbPath = path.join(tmpDir, 'database.json');

  fs.writeFileSync(
    junitPath,
    '<testsuite><testcase classname="Smoke" name="Happy"/></testsuite>',
    'utf8',
  );

  const scriptPath = path.join(rootDir, 'projects/03-ci-flaky/scripts/analyze-junit.mjs');
  const result = spawnSync(process.execPath, [scriptPath, junitPath, dbPath], {
    cwd: rootDir,
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout, /Analyzed 1 test cases/);
  assert.ok(fs.existsSync(dbPath), 'database file should be created');
  assert.ok(
    !/Cannot find package 'fast-xml-parser'/i.test(result.stderr),
    'should not complain about missing fast-xml-parser package',
  );
});
