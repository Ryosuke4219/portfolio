import assert from 'node:assert';
import { test } from 'node:test';

import { parseSpecFile, validateCasesSchema } from '../projects/01-spec2cases-md2json/scripts/spec2cases.mjs';
import { parseSpecText } from '../projects/01-spec2cases-md2json/src/parse-spec.js';
import { SPEC2CASES_SAMPLE_SPEC_MD_PATH } from '../scripts/paths.mjs';

test('markdown specs with headings are parsed into cases', () => {
  const result = parseSpecFile(SPEC2CASES_SAMPLE_SPEC_MD_PATH);

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

test('markdown sections keep order and multiline entries', () => {
  const text = [
    'suite: Regression',
    'case: CASE-10',
    'title: Inline',
    'pre: inline pre',
    '  continues',
    'steps:',
    '- first',
    '  details',
    '- second',
    'expected:',
    '- result one',
    '  details',
    'case: CASE-11',
    'title: Reordered',
    'expected:',
    '- done',
    'steps:',
    '- first',
    'pre:',
    '- ready',
    '',
  ].join('\n');

  const result = parseSpecText(text);

  assert.equal(result.suite, 'Regression');
  assert.equal(result.cases.length, 2);

  const [first, second] = result.cases;
  assert.equal(first.id, 'CASE-10');
  assert.equal(first.title, 'Inline');
  assert.deepEqual(first.pre, ['inline pre continues']);
  assert.deepEqual(first.steps, ['first details', 'second']);
  assert.deepEqual(first.expected, ['result one details']);

  assert.equal(second.id, 'CASE-11');
  assert.equal(second.title, 'Reordered');
  assert.deepEqual(second.pre, ['ready']);
  assert.deepEqual(second.steps, ['first']);
  assert.deepEqual(second.expected, ['done']);
});
