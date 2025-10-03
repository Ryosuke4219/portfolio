import assert from 'node:assert';
import { test, mock } from 'node:test';

const CONFIG = {
  paths: {
    input: '<stdin>',
    store: '/tmp/store.jsonl',
  },
  timeout_factor: 1,
};

test('runParse counts errored attempts as failures', async (t) => {
  const logs = [];
  const warnings = [];
  const errors = [];

  t.after(() => {
    mock.restoreAll();
  });

  mock.method(console, 'log', (message) => {
    logs.push(String(message));
  });
  mock.method(console, 'warn', (message) => {
    warnings.push(String(message));
  });
  mock.method(console, 'error', (message) => {
    errors.push(String(message));
  });

  const appendAttempts = mock.fn(() => {});

  const { runParse } = await import('../../projects/03-ci-flaky/src/commands/parse.js');

  await runParse(
    { stdin: true, run_id: 'run-123', timestamp: '2024-01-01T00:00:00.000Z' },
    {
      resolveConfigPath: () => '/tmp/config.json',
      loadConfig: () => ({ config: CONFIG }),
      resolveConfigPaths: () => CONFIG,
      ensureDir: () => {},
      parseJUnitStream: async () => ({
        attempts: [
          {
            canonical_id: 'suite.class.test',
            suite: 'suite',
            class: 'class',
            name: 'test',
            status: 'errored',
            duration_ms: 25,
            failure_details: 'stack',
            failure_message: 'boom',
            system_out: ['out'],
            system_err: ['err'],
          },
        ],
      }),
      parseJUnitFile: async () => ({ attempts: [] }),
      appendAttempts,
    },
  );

  assert.strictEqual(appendAttempts.mock.callCount(), 1);
  assert.ok(
    logs.some((line) => /Stored 1 attempts \(fails=1\)\./.test(line)),
    `Expected stored output to include fails=1, got: ${logs.join('\n')}`,
  );
  assert.deepStrictEqual(warnings, []);
  assert.deepStrictEqual(errors, []);
});
