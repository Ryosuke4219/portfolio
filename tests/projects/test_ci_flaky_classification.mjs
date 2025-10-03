import test from 'node:test';
import assert from 'node:assert/strict';

import { applyTimeoutClassification } from '../../projects/03-ci-flaky/src/classification.js';

test('applyTimeoutClassification marks errored attempts as timeout when exceeding threshold', () => {
  const attempts = [
    {
      status: 'errored',
      suite: 'ci-suite',
      duration_ms: 5_000,
      failure_kind: 'nondeterministic',
    },
  ];

  const suiteDurations = new Map([
    ['ci-suite', [1_000, 1_100, 1_200, 1_300, 1_400]],
  ]);

  applyTimeoutClassification(attempts, suiteDurations, 2);

  assert.equal(attempts[0].failure_kind, 'timeout');
});
