import { test } from 'node:test';
import assert from 'node:assert/strict';

import { XMLParser } from 'fast-xml-parser';

test('XMLParser parses basic junit suite with attributes and text content', () => {
  const xml =
    `<?xml version="1.0" encoding="UTF-8"?>` +
    `<testsuite name="Example" tests="1">` +
    `<testcase classname="Login" name="HappyPath" time="0.42"><failure>boom</failure></testcase>` +
    `</testsuite>`;

  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '',
    allowBooleanAttributes: true,
  });
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

test('XMLParser parses junit-like suites with attributes and text content (multiple cases)', () => {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '',
    allowBooleanAttributes: true,
  });

  const xml = `
    <testsuite name="Login" tests="2">
      <testcase classname="Login" name="HappyPath">
        <failure>boom</failure>
      </testcase>
      <testcase classname="Login" name="Retry" skipped/>
    </testsuite>
  `;

  const result = parser.parse(xml);

  assert.ok(result.testsuite, 'testsuite element is present');
  assert.equal(result.testsuite.name, 'Login');
  assert.equal(result.testsuite.tests, '2');

  const cases = Array.isArray(result.testsuite.testcase)
    ? result.testsuite.testcase
    : [result.testsuite.testcase];

  assert.equal(cases.length, 2);

  const [first, second] = cases;
  assert.deepEqual(first, {
    classname: 'Login',
    name: 'HappyPath',
    failure: 'boom',
  });
  assert.deepEqual(second, {
    classname: 'Login',
    name: 'Retry',
    skipped: true,
  });
});

test('XMLParser groups repeated elements into arrays and honours boolean attributes', () => {
  const xml =
    `<testsuite>` +
    `<testcase classname="Login" name="HappyPath"/>` +
    `<testcase classname="Login" name="Retry" flaky/>` +
    `</testsuite>`;

  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '',
    allowBooleanAttributes: true,
  });
  const result = parser.parse(xml);

  assert.deepEqual(result, {
    testsuite: {
      testcase: [
        { classname: 'Login', name: 'HappyPath' },
        { classname: 'Login', name: 'Retry', flaky: true },
      ],
    },
  });
});

test('XMLParser groups repeated suite nodes into arrays', () => {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '',
  });

  const xml = `
    <testsuites>
      <testsuite name="A"/>
      <testsuite name="B"/>
    </testsuites>
  `;

  const result = parser.parse(xml);

  assert.ok(Array.isArray(result.testsuites.testsuite));
  assert.deepEqual(result.testsuites.testsuite, [{ name: 'A' }, { name: 'B' }]);
});
