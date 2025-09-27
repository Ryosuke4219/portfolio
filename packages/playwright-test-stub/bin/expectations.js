import fs from 'node:fs';
import path from 'node:path';

const sanitiseForFile = (value) =>
  value
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/[\s]+/g, ' ')
    .trim()
    .slice(0, 80) || 'snapshot';

const normaliseSnapshotContent = (value) => value.replace(/\r\n/g, '\n');

const deepEqual = (a, b) => {
  if (a === b) {
    return true;
  }
  if (typeof a !== typeof b) {
    return false;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) {
      return false;
    }
    for (let i = 0; i < a.length; i += 1) {
      if (!deepEqual(a[i], b[i])) {
        return false;
      }
    }
    return true;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const keysA = Object.keys(a);
    const keysB = Object.keys(b);
    if (keysA.length !== keysB.length) {
      return false;
    }
    for (const key of keysA) {
      if (!deepEqual(a[key], b[key])) {
        return false;
      }
    }
    return true;
  }
  return false;
};

export const createExpect = ({
  snapshotDir,
  screenshotDiffDir,
  getCurrentTestTitle,
  urlMatches,
  isRegExp,
}) => {
  const recordSnapshotMismatch = (name, expected, actual) => {
    const safeTitle = sanitiseForFile(getCurrentTestTitle() || 'snapshot');
    fs.mkdirSync(screenshotDiffDir, { recursive: true });
    const diffPath = path.join(screenshotDiffDir, `${safeTitle}-${sanitiseForFile(name)}.diff.txt`);
    const diffBody = [
      `Snapshot mismatch for ${name}`,
      '--- expected',
      expected,
      '--- actual',
      actual,
    ].join('\n');
    fs.writeFileSync(diffPath, diffBody, 'utf8');
    return diffPath;
  };

  const compareSnapshot = (name, value) => {
    if (!name || typeof name !== 'string') {
      throw new Error('[expect] Snapshot name must be a non-empty string.');
    }
    const baselinePath = path.join(snapshotDir, name);
    if (!fs.existsSync(baselinePath)) {
      throw new Error(
        `[expect] Snapshot baseline not found for "${name}". Create ${baselinePath} to update the golden image.`,
      );
    }
    const expected = normaliseSnapshotContent(fs.readFileSync(baselinePath, 'utf8'));
    const actual = normaliseSnapshotContent(value);
    if (expected !== actual) {
      const diffPath = recordSnapshotMismatch(name, expected, actual);
      throw new Error(`Snapshot mismatch for "${name}". See ${diffPath}`);
    }
  };

  const expectFn = (actual) => ({
    async toHaveURL(expected) {
      const urlValue = typeof actual?._getURL === 'function' ? actual._getURL() : actual;
      if (process.env.DEBUG_PLAYWRIGHT_STUB === '1') {
        console.log('[expect.toHaveURL]', {
          urlValue,
          expectedType: typeof expected,
          isRegex: isRegExp(expected),
          expected: String(expected),
          match: urlMatches(urlValue, expected),
        });
      }
      if (!urlMatches(urlValue, expected)) {
        throw new Error(`Expected URL to match ${expected}, received ${urlValue}`);
      }
    },
    async toBeVisible() {
      if (actual && typeof actual.check === 'function') {
        actual.check();
        return;
      }
      throw new Error('toBeVisible() is only supported on getByText() locators in the stub');
    },
    async toHaveScreenshot(name) {
      if (!actual || typeof actual.content !== 'function') {
        throw new Error('toHaveScreenshot() expects a page-like object with content().');
      }
      const html = await actual.content();
      compareSnapshot(name, html);
    },
    async toMatchSnapshot(name) {
      if (typeof actual !== 'string') {
        throw new Error('toMatchSnapshot() expects a string value in the stub environment.');
      }
      compareSnapshot(name, actual);
    },
    async toBe(expected) {
      if (actual !== expected) {
        throw new Error(`Expected ${actual} to be ${expected}`);
      }
    },
    async toEqual(expected) {
      if (!deepEqual(actual, expected)) {
        throw new Error(`Expected ${JSON.stringify(actual)} to equal ${JSON.stringify(expected)}`);
      }
    },
  });

  return { expect: expectFn };
};
