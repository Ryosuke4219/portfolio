import test from 'node:test';
import assert from 'node:assert/strict';

const MODULE_BASE = '../../projects/03-ci-flaky/src/config';

async function importModule(name) {
  return import(`${MODULE_BASE}/${name}.js`);
}

test('config defaults exposes DEFAULT_CONFIG and mergeDeep', async () => {
  const { DEFAULT_CONFIG, mergeDeep } = await importModule('defaults');
  assert.ok(DEFAULT_CONFIG.paths);
  const merged = mergeDeep(
    { nested: { value: 1 }, arr: [1, 2] },
    { nested: { other: 2 }, arr: [3], top: true },
  );
  assert.deepEqual(merged, {
    nested: { value: 1, other: 2 },
    arr: [3],
    top: true,
  });
});

test('config parser exposes parseYAML compatible behaviour', async () => {
  const { parseYAML } = await importModule('parser');
  const parsed = parseYAML(`
name: example
items:
  - key: value # comment
  - 'text'
`);
  assert.deepEqual(parsed, {
    name: 'example',
    items: [{ key: 'value' }, 'text'],
  });
});

test('config paths resolves relative directories against base', async () => {
  const { DEFAULT_CONFIG } = await importModule('defaults');
  const { resolveConfigPaths } = await importModule('paths');
  const base = process.cwd();
  const resolved = resolveConfigPaths(DEFAULT_CONFIG, base);
  assert.equal(resolved.paths.input, `${base}/junit`);
  assert.equal(resolved.paths.store.endsWith('data/runs.jsonl'), true);
});
