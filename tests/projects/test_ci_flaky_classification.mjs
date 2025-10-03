import assert from 'node:assert';
import { test } from 'node:test';

import { applyTimeoutClassification } from '../../projects/03-ci-flaky/src/classification.js';

test('timeout classification upgrades errored attempts', () => {
  const attempts = [
    {
      suite: 'suite-a',
      status: 'errored',
      duration_ms: 5000,
      failure_kind: 'nondeterministic',
    },
  ];
  const suiteDurations = new Map([
    ['suite-a', [1000, 2000, 3000, 4000, 4500]],
  ]);

  applyTimeoutClassification(attempts, suiteDurations, 1.1);

  assert.strictEqual(attempts[0].failure_kind, 'timeout');
});
