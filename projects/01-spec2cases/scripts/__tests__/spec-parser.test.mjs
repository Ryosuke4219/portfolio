import assert from 'node:assert/strict';
import { test, describe } from 'node:test';

import { parseSpec } from '../lib/spec-parser.mjs';

const SAMPLE_SPEC = `# ログイン機能\n\n## LGN-001 正常ログイン\n- pre: 事前条件\n- step: 操作1\n- expected: 結果1\n- tag: smoke, happy\n\n## LGN-002 代替動作\n- given: 事前条件\n- when: 操作2\n- then: 結果2\n- tags: regression\n`;

describe('parseSpec', () => {
  test('parses suite and cases with synonym bullets', () => {
    const { suite, cases, warnings } = parseSpec(SAMPLE_SPEC);
    assert.equal(suite, 'ログイン機能');
    assert.equal(cases.length, 2);
    assert.deepEqual(cases[0], {
      id: 'LGN-001',
      title: '正常ログイン',
      pre: ['事前条件'],
      steps: ['操作1'],
      expected: ['結果1'],
      tags: ['smoke', 'happy'],
    });
    assert.deepEqual(cases[1], {
      id: 'LGN-002',
      title: '代替動作',
      pre: ['事前条件'],
      steps: ['操作2'],
      expected: ['結果2'],
      tags: ['regression'],
    });
    assert.deepEqual(warnings, []);
  });

  test('collects warnings for unknown lines', () => {
    const { warnings } = parseSpec(`# Suite\n\n## CASE-1 Title\n- foo: bar\ntext\n- step: ok\n`);
    assert.ok(warnings.some((message) => message.includes('unknown key')));
    assert.ok(warnings.some((message) => message.startsWith('Skip line')));
  });

  test('supports numbered bullet syntax without misreading numeric text', () => {
    const spec = `# Suite\n\n## CASE-1 Title\n1. pre: 数字で始まる\n2) step: 2FAコードを入力\n3. expected: ダッシュボード表示\nただの文章 2FA を含む\n`;
    const { cases, warnings } = parseSpec(spec);
    assert.equal(cases[0].pre[0], '数字で始まる');
    assert.equal(cases[0].steps[0], '2FAコードを入力');
    assert.equal(cases[0].expected[0], 'ダッシュボード表示');
    assert.ok(warnings.some((message) => message.startsWith('Skip line:')));
  });

  test('throws when suite heading missing', () => {
    assert.throws(() => parseSpec('## ID Title\n- step: a'), /Suite name was not specified/);
  });

  test('throws when bullet appears before case heading', () => {
    const spec = '# Suite\n- step: invalid\n';
    assert.throws(() => parseSpec(spec), /bullet section defined before any test case heading/);
  });

  test('throws when duplicate ids exist', () => {
    const spec = '# Suite\n\n## CASE-1 Title\n- step: a\n- expected: b\n\n## CASE-1 Duplicate\n- step: c\n- expected: d\n';
    assert.throws(() => parseSpec(spec), /Duplicate test case id/);
  });
});
