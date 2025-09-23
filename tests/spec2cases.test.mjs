import { test } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { parseSpecFile, validateCasesSchema } from '../projects/01-spec2cases/scripts/spec2cases.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

test('markdown specs with headings are parsed into cases', () => {
  const specPath = path.join(rootDir, 'docs/examples/spec2cases/spec.sample.md');
  const result = parseSpecFile(specPath);

  assert.equal(result.suite, 'ログイン機能');
  assert.equal(result.cases.length, 2);

  const [first, second] = result.cases;

  assert.equal(first.id, 'LGN-001');
  assert.equal(first.title, '正常ログイン');
  assert.deepEqual(first.pre, ['ユーザー alice が存在する']);
  assert.deepEqual(first.steps, ['ログイン画面にアクセス', 'ID/PWを入力', 'ログインを押下']);
  assert.deepEqual(first.expected, ['ダッシュボードに遷移', 'Welcome Alice が表示']);
  assert.deepEqual(first.tags, ['happy-path', 'smoke']);

  assert.equal(second.id, 'LGN-002');
  assert.equal(second.title, 'パスワード誤り');
  assert.deepEqual(second.pre, ['ユーザー alice が存在する']);
  assert.deepEqual(second.steps, [
    'ログイン画面にアクセス',
    'ID=alice, PW=wrong を入力',
    'ログインを押下',
  ]);
  assert.deepEqual(second.expected, ["エラートースト 'Invalid credentials'"]);
  assert.deepEqual(second.tags, ['negative']);

  const errors = validateCasesSchema(result);
  assert.deepEqual(errors, []);
});
