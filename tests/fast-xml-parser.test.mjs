import { test } from 'node:test';
import assert from 'node:assert/strict';

import { XMLParser } from '../projects/03-ci-flaky/lib/fast-xml-parser.js';

test('XMLParser parses basic junit suite with attributes and text content', () => {
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<testsuite name="Example" tests="1">` +
    `<testcase classname="Login" name="HappyPath" time="0.42"><failure>boom</failure></testcase>` +
    `</testsuite>`;

  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '', allowBooleanAttributes: true });
  const result = parser.parse(xml);

  assert.deepEqual(result, {
    testsuite: {
      name: 'Example',
      tests: '1',
      testcase: {
        classname: 'Login',
        name: 'HappyPath',
        time: '0.42',
        failure: 'boom',
      },
    },
  });
});

test('XMLParser groups repeated elements into arrays and honours boolean attributes', () => {
  const xml =
    `<testsuite>` +
    `<testcase classname="Login" name="HappyPath"/>` +
    `<testcase classname="Login" name="Retry" flaky/>` +
    `</testsuite>`;

  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '', allowBooleanAttributes: true });
  const result = parser.parse(xml);

  assert.deepEqual(result, {
    testsuite: {
      testcase: [
        {
          classname: 'Login',
          name: 'HappyPath',
        },
        {
          classname: 'Login',
          name: 'Retry',
          flaky: true,
        },
      ],
    },
  });
});
