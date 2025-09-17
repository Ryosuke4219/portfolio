import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { validateSuite } from '../lib/suite-validator.mjs';

const BASE_SUITE = {
  suite: 'Example',
  cases: [
    {
      id: 'CASE-1',
      title: 'Title',
      pre: ['given'],
      steps: ['when'],
      expected: ['then'],
      tags: ['tag'],
    },
  ],
};

describe('validateSuite', () => {
  test('accepts a minimal valid suite', () => {
    const result = validateSuite(BASE_SUITE);
    assert.equal(result.valid, true);
    assert.deepEqual(result.errors, []);
  });

  test('detects duplicate ids and missing arrays', () => {
    const invalid = {
      suite: 'Example',
      cases: [
        {
          id: 'CASE-1',
          title: 'Title',
          pre: 'not-array',
          steps: [],
          expected: [''],
          tags: [],
        },
        {
          id: 'CASE-1',
          title: '',
          pre: [],
          steps: [],
          expected: [],
          tags: [],
        },
      ],
    };
    const result = validateSuite(invalid, { requireContent: true });
    assert.equal(result.valid, false);
    assert.ok(result.errors.some((message) => message.includes('duplicates an existing test id')));
    assert.ok(result.errors.some((message) => message.includes('must be an array')));
    assert.ok(result.errors.some((message) => message.includes('must include at least one item')));
  });

  test('rejects missing suite name', () => {
    const result = validateSuite({ cases: [] });
    assert.equal(result.valid, false);
    assert.ok(result.errors.some((message) => message.includes('suite must be a non-empty string')));
  });
});
