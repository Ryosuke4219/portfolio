import test from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import {
  parseSpecText,
  parseSpecFile,
} from '../projects/01-spec2cases-md2json/src/index.js';
import {
  ensureArrayOfStrings,
  validateCasesSchema,
} from '../projects/01-spec2cases-md2json/src/validate-schema.js';
import {
  SPEC2CASES_SAMPLE_CASES_PATH,
  SPEC2CASES_SAMPLE_SPEC_MD_PATH,
} from '../scripts/paths.mjs';

const CLI_PATH = fileURLToPath(
  new URL('../projects/01-spec2cases-md2json/scripts/spec2cases.mjs', import.meta.url),
);

const SAMPLE_SPEC_TEXT = fs.readFileSync(SPEC2CASES_SAMPLE_SPEC_MD_PATH, 'utf8');

test('parseSpecText transforms markdown specs into structured cases', () => {
  const result = parseSpecText(SAMPLE_SPEC_TEXT);

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
});

test('parseSpecFile reads json and markdown formats', () => {
  const markdownResult = parseSpecFile(SPEC2CASES_SAMPLE_SPEC_MD_PATH);
  assert.equal(markdownResult.cases.length, 2);

  const jsonResult = parseSpecFile(SPEC2CASES_SAMPLE_CASES_PATH);
  assert.equal(jsonResult.cases.length, 2);
});

test('validateCasesSchema reports detailed errors', () => {
  const invalid = {
    suite: '',
    cases: [
      {
        id: '',
        title: ' ',
        pre: [''],
        steps: null,
        expected: [' '],
        tags: [1],
      },
      'not-object',
    ],
  };

  const errors = validateCasesSchema(invalid);
  assert(errors.includes('suite must be a non-empty string'));
  assert(errors.includes('cases[0].id must be a non-empty string'));
  assert(errors.includes('cases[0].steps must be an array of non-empty strings'));
  assert(errors.includes('cases[0].expected must be an array of non-empty strings'));
  assert(errors.includes('cases[0].tags must be an array of non-empty strings'));
  assert(errors.includes('cases[1] must be an object'));

  assert.equal(ensureArrayOfStrings(['a', 'b']), true);
  assert.equal(ensureArrayOfStrings(['a', '']), false);
  assert.equal(ensureArrayOfStrings('nope'), false);
});

test('CLI validates inputs and prints summary', () => {
  const result = spawnSync(process.execPath, [CLI_PATH, SPEC2CASES_SAMPLE_SPEC_MD_PATH], {
    encoding: 'utf8',
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /✅ Valid cases/);
  assert.match(result.stdout, /"ログイン機能"/);
});
