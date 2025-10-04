import assert from 'node:assert';
import { test } from 'node:test';

import { computeAggregates, isFailureStatus } from '../../projects/03-ci-flaky/src/analyzer.js';

test('failure-like attempts are treated as failures', () => {
  for (const status of ['errored', 'failure']) {
    assert.strictEqual(isFailureStatus({ status }), true);

    const runId = `run-${status}`;
    const attempt = {
      canonical_id: 'suite.class.test',
      suite: 'suite',
      class: 'class',
      name: 'test',
      status,
      duration_ms: 10,
    };
    const runs = new Map([[runId, { attempts: [attempt] }]]);
    const runOrder = [runId];

    const { results } = computeAggregates(runs, runOrder, {});
    assert.equal(results.length, 1);
    assert.equal(results[0].fails, 1);
  }
});
