import assert from 'node:assert';
import { test } from 'node:test';

import { computeAggregates, isFailureStatus } from '../../projects/03-ci-flaky/src/analyzer.js';

test('errored attempts are treated as failures', () => {
  assert.strictEqual(isFailureStatus({ status: 'errored' }), true);

  const runId = 'run-1';
  const attempt = {
    canonical_id: 'suite.class.test',
    suite: 'suite',
    class: 'class',
    name: 'test',
    status: 'errored',
    duration_ms: 10,
  };
  const runs = new Map([[runId, { attempts: [attempt] }]]);
  const runOrder = [runId];

  const { results } = computeAggregates(runs, runOrder, {});
  assert.equal(results.length, 1);
  assert.equal(results[0].fails, 1);
});
