import assert from 'node:assert';
import { Readable } from 'node:stream';
import { test } from 'node:test';

import { isFailureStatus } from '../../projects/03-ci-flaky/src/analyzer.js';
import { parseJUnitStream } from '../../projects/03-ci-flaky/src/junit-parser.js';

test('parseJUnitStream treats errored status attribute as a failure', async () => {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="suite">
  <testcase name="test" classname="Class" status="errored" time="0.1" />
</testsuite>`;

  const { attempts } = await parseJUnitStream(Readable.from([xml]), { filename: '<stdin>' });

  assert.strictEqual(attempts.length, 1);
  const [attempt] = attempts;
  assert.strictEqual(attempt.status, 'errored');
  assert.strictEqual(isFailureStatus(attempt), true);
});
