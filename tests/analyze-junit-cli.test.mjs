import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { computeAggregates, determineFlaky } from '../projects/03-ci-flaky/src/analyzer.js';

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

test('computeAggregates preserves scoring and ranking', () => {
  const runs = new Map([
    ['run1', {
      attempts: [
        {
          canonical_id: 'suite.class.test',
          suite: 'suite',
          class: 'class',
          name: 'test',
          status: 'fail',
          duration_ms: 1000,
          failure_kind: 'assert',
          failure_signature: 'sig1',
          failure_message: 'boom',
          failure_details: 'trace',
          failure_excerpt: 'boom',
          run_id: 'run1',
          ts: '2024-01-01T00:00:00Z',
        },
      ],
      meta: {},
    }],
    ['run2', {
      attempts: [
        {
          canonical_id: 'suite.class.test',
          suite: 'suite',
          class: 'class',
          name: 'test',
          status: 'pass',
          duration_ms: 500,
          run_id: 'run2',
          ts: '2024-01-02T00:00:00Z',
        },
        {
          canonical_id: 'suite.class.other',
          suite: 'suite',
          class: 'class',
          name: 'other',
          status: 'pass',
          duration_ms: 200,
          run_id: 'run2',
          ts: '2024-01-02T00:00:00Z',
        },
      ],
      meta: {},
    }],
  ]);

  const config = {
    weights: { intermittency: 0.5, p_fail: 0.3, recency: 0.15, impact: 0.05 },
    recency_lambda: 0.1,
    impact_baseline_ms: 600000,
  };

  const { results, failureKindTotals } = computeAggregates(runs, ['run1', 'run2'], config);
  assert.equal(results.length, 2);
  const [first, second] = [...results].sort((a, b) => b.score - a.score);

  assert.equal(first.canonical_id, 'suite.class.test');
  assert.equal(first.attempts, 2);
  assert.equal(first.p_fail, 0.5);
  assert.equal(first.intermittency, 1);
  assert.ok(Math.abs(first.recency - 0.47502081252106) < 1e-12);
  assert.ok(Math.abs(first.score - 0.7461368558976224) < 1e-12);
  assert.deepEqual(first.trend, [1, 0]);
  assert.equal(first.latest_failure?.run_id, 'run1');
  const failureSignature = first.failure_signatures.get('sig1');
  assert.equal(failureSignature.count, 1);
  assert.deepEqual([...failureSignature.runs], ['run1']);

  assert.equal(second.canonical_id, 'suite.class.other');
  assert.equal(second.attempts, 1);
  assert.ok(second.score < first.score);
  assert.deepEqual(second.trend, [0, 0]);

  assert.deepEqual([...failureKindTotals.entries()], [['assert', 1]]);
});

test('determineFlaky keeps entries with error attempts', () => {
  const runOrder = ['run1', 'run2'];
  const results = [
    {
      canonical_id: 'suite.class.error',
      attempts: 2,
      passes: 1,
      fails: 1,
      score: 0.9,
      statuses: [
        { runIndex: 0, status: 'error', run_id: 'run1', ts: '2024-01-01T00:00:00Z' },
        { runIndex: 1, status: 'pass', run_id: 'run2', ts: '2024-01-02T00:00:00Z' },
      ],
    },
  ];

  const flaky = determineFlaky(results, {}, runOrder);
  assert.equal(flaky.length, 1);
  const [entry] = flaky;
  assert.equal(entry.canonical_id, 'suite.class.error');
  assert.ok(entry.is_new);
});
