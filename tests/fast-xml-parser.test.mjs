import { test } from 'node:test';
import assert from 'node:assert';

import { XMLParser } from 'fast-xml-parser';

test('XMLParser parses junit-like suites with attributes and text content', () => {
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

test('XMLParser groups repeated nodes into arrays', () => {
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
  assert.deepEqual(result.testsuites.testsuite, [
    { name: 'A' },
    { name: 'B' },
  ]);
});
