import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { summariseJUnit } from '../../scripts/build-ci-reports.mjs';

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
