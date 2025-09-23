#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import url from 'node:url';
import vm from 'node:vm';

import { LLM2PW_DEMO_DIR } from '../../../scripts/paths.mjs';

const projectRoot = process.cwd();
const demoDir = LLM2PW_DEMO_DIR;
const generatedDir = path.resolve(projectRoot, 'projects/02-llm-to-playwright/tests/generated');
const snapshotDir = path.join(generatedDir, '__snapshots__');
const junitPath = path.resolve(projectRoot, 'junit-results.xml');
const resultsDir = path.resolve(projectRoot, 'test-results');
const screenshotDiffDir = path.join(resultsDir, 'snapshot-diffs');

const axeCoreStub = {
  async run(input) {
    const html = typeof input === 'string' ? input : input?.html || '';
    if (typeof html !== 'string') {
      throw new Error('[axe-core:run] Expected HTML string input in stub environment.');
    }
    const violations = [];

    const imgRegex = /<img\b[^>]*>/gi;
    let match;
    while ((match = imgRegex.exec(html)) !== null) {
      if (!/\balt=/.test(match[0])) {
        violations.push({
          id: 'image-alt',
          help: 'Images must have alternate text',
          impact: 'serious',
          nodes: [{ html: match[0] }],
        });
      }
    }

    const hasLandmark = /<(main|nav|header|footer)\b/i.test(html);
    if (!hasLandmark) {
      violations.push({
        id: 'landmark-structure',
        help: 'Page should expose at least one landmark region',
        impact: 'moderate',
        nodes: [],
      });
    }

    return {
      violations,
      passes: [],
      inapplicable: [],
    };
  },
};

const args = process.argv.slice(2);
const command = args.shift();

const printUsage = () => {
  console.log('[playwright-stub] Usage: playwright test [options]');
};

if (command == null || command === '' || command === '--help' || command === '-h') {
  printUsage();
  process.exit(0);
}

if (command === '--version' || command === '-v') {
  console.log('0.0.0-stub');
  process.exit(0);
}

const installCommands = new Set(['install', 'install-deps']);

if (installCommands.has(command)) {
  console.log(`[playwright-stub] Skipping "playwright ${command}" in stub environment.`);
  process.exit(0);
}

if (command !== 'test') {
  console.error('[playwright-stub] Only "playwright test" is supported.');
  process.exit(1);
}

// consume simple flags (-c/--config) without processing for compatibility
for (let i = 0; i < args.length; i += 1) {
  const value = args[i];
  if (value === '-c' || value === '--config') {
    // skip config path argument if present
    if (i + 1 < args.length) {
      i += 1;
    }
    continue;
  }
  // ignore other args for now
}

const baseURL = process.env.BASE_URL || 'http://127.0.0.1:4173';
const base = new url.URL(baseURL);

const escapeXml = (value) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

const isRegExp = (value) => Object.prototype.toString.call(value) === '[object RegExp]';

const urlMatches = (actualUrl, expected) => {
  if (!actualUrl) {
    return false;
  }
  if (isRegExp(expected)) {
    return expected.test(actualUrl);
  }
  if (typeof expected === 'string') {
    if (actualUrl === expected) {
      return true;
    }
    if (/^\/.+\/$/.test(expected)) {
      try {
        const pattern = new RegExp(expected.slice(1, -1));
        return pattern.test(actualUrl);
      } catch (error) {
        return false;
      }
    }
  }
  return false;
};

const ensureDir = (target) => {
  fs.mkdirSync(path.dirname(target), { recursive: true });
};

const readPage = (targetUrl) => {
  const parsed = new url.URL(targetUrl, base.origin);
  let pathname = parsed.pathname || '/';
  if (pathname === '/') {
    pathname = '/index.html';
  }
  const filePath = path.resolve(demoDir, `.${pathname}`);
  const normalizedRoot = demoDir.endsWith(path.sep) ? demoDir : `${demoDir}${path.sep}`;
  if (!filePath.startsWith(normalizedRoot)) {
    throw new Error(`Blocked file access outside demo directory: ${filePath}`);
  }
  if (!fs.existsSync(filePath)) {
    throw new Error(`Demo page not found: ${filePath}`);
  }
  return fs.readFileSync(filePath, 'utf8');
};

const sanitiseForFile = (value) =>
  value
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/[\s]+/g, ' ')
    .trim()
    .slice(0, 80) || 'snapshot';

const normaliseSnapshotContent = (value) => value.replace(/\r\n/g, '\n');

const createPage = () => {
  const state = {
    url: '',
    content: '',
    fields: new Map(),
  };

  const normalise = (target) => new url.URL(target, `${base.protocol}//${base.host}`).toString();
  const selectorForTestId = (testId) => `[data-testid="${testId}"]`;
  const hasTestId = (testId) => new RegExp(`data-testid=["']${testId}["']`).test(state.content);

  return {
    async goto(target) {
      const absolute = normalise(target);
      state.url = absolute;
      state.content = readPage(absolute);
      state.fields.clear();
    },
    async fill(selector, value) {
      state.fields.set(selector, value);
    },
    async click(selector) {
      const normalizedSelector = selector.startsWith('[data-testid="') ? selector : selector.trim();
      const submitSelectors = new Set(['button[type=submit]', selectorForTestId('login-submit')]);
      if (!submitSelectors.has(normalizedSelector)) {
        throw new Error(`Unsupported selector for click(): ${selector}`);
      }
      const pass =
        state.fields.get(selectorForTestId('login-password')) || state.fields.get('#pass') || state.fields.get('pass') || '';
      const destination = pass === 'wrong' ? '/invalid.html' : '/dashboard.html';
      const absolute = new url.URL(destination, `${base.protocol}//${base.host}`).toString();
      await this.goto(absolute);
    },
    async waitForLoadState(state = 'load') {
      const allowed = new Set(['load', 'domcontentloaded', 'networkidle']);
      if (!allowed.has(state)) {
        throw new Error(`[playwright-stub] waitForLoadState("${state}") is not supported in the stub environment.`);
      }
      // no-op: HTML is loaded synchronously in the stub
    },
    async waitForURL(expected) {
      const currentUrl = state.url;
      if (!urlMatches(currentUrl, expected)) {
        throw new Error(`Expected navigation to match ${expected}, current URL ${currentUrl}`);
      }
    },
    getByText(text) {
      return {
        __kind: 'text-locator',
        text,
        check() {
          if (!state.content.includes(text)) {
            throw new Error(`Expected to find text "${text}" in ${state.url}`);
          }
        },
      };
    },
    getByTestId(testId) {
      const selector = selectorForTestId(testId);
      return {
        __kind: 'test-id-locator',
        testId,
        selector,
        async fill(value) {
          if (!hasTestId(testId)) {
            throw new Error(`Expected to find data-testid="${testId}" before fill()`);
          }
          await this.page.fill(selector, value);
        },
        async click() {
          if (!hasTestId(testId)) {
            throw new Error(`Expected to find data-testid="${testId}" before click()`);
          }
          await this.page.click(selector);
        },
        check() {
          if (!hasTestId(testId)) {
            throw new Error(`Expected element with data-testid="${testId}" in ${state.url}`);
          }
        },
        page: null,
      };
    },
    async content() {
      return state.content;
    },
    _getURL() {
      return state.url;
    },
    _attach(locator) {
      if (locator && typeof locator === 'object') {
        locator.page = this;
      }
      return locator;
    },
  };
};

let currentTest = null;

const recordSnapshotMismatch = (name, expected, actual) => {
  const safeTitle = currentTest ? sanitiseForFile(currentTest.title) : 'snapshot';
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

const expect = (actual) => ({
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

const tests = [];

const registerTest = (title, fn) => {
  tests.push({ title, fn });
};

if (!fs.existsSync(generatedDir)) {
  console.warn('[playwright-stub] No generated tests found. Did you run npm run e2e:gen?');
}

const requireFromContext = (specifier) => {
  if (specifier === 'node:fs' || specifier === 'fs') {
    return fs;
  }
  if (specifier === 'node:path' || specifier === 'path') {
    return path;
  }
  if (specifier === 'node:url' || specifier === 'url') {
    return url;
  }
  if (specifier === 'axe-core') {
    return axeCoreStub;
  }
  throw new Error(`[playwright-stub] Unsupported require("${specifier}") in generated test.`);
};

const contextGlobals = {
  console,
  test: registerTest,
  expect,
  process: {
    env: { ...process.env },
    cwd: () => projectRoot,
  },
  require: requireFromContext,
};

const vmContext = vm.createContext(contextGlobals);

if (fs.existsSync(generatedDir)) {
  const files = fs.readdirSync(generatedDir).filter((file) => file.endsWith('.spec.ts'));
  for (const file of files) {
    const filePath = path.join(generatedDir, file);
    const raw = fs.readFileSync(filePath, 'utf8');
    const sanitised = raw.replace(/import\s+\{[^}]*\}\s+from\s+['"]@playwright\/test['"];?\s*/g, '');
    try {
      const script = new vm.Script(sanitised, { filename: filePath });
      script.runInContext(vmContext);
    } catch (error) {
      console.error(`[playwright-stub] Failed to load ${file}:`, error);
      process.exit(1);
    }
  }
}

if (!tests.length) {
  console.log('[playwright-stub] No tests collected. Exiting.');
  fs.writeFileSync(junitPath, '<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="playwright-stub" tests="0" failures="0" time="0"/>\n');
  process.exit(0);
}

const results = [];
let hasFailure = false;

const run = async () => {
  console.log(`[playwright-stub] Running ${tests.length} test(s) with base URL ${baseURL}`);
  for (const { title, fn } of tests) {
    const page = createPage();
    const start = Date.now();
    try {
      currentTest = { title };
      await fn({
        page: new Proxy(page, {
          get(target, prop) {
            const value = target[prop];
            if (prop === 'getByTestId' && typeof value === 'function') {
              return (testId) => target._attach(value.call(target, testId));
            }
            if (typeof value === 'function') {
              return value.bind(target);
            }
            return value;
          },
        }),
      });
      currentTest = null;
      const durationMs = Date.now() - start;
      results.push({ title, status: 'passed', durationMs });
      console.log(`  ✓ ${title}`);
    } catch (error) {
      const durationMs = Date.now() - start;
      hasFailure = true;
      results.push({ title, status: 'failed', durationMs, error });
      console.error(`  ✗ ${title}`);
      console.error(`    ${error?.message || error}`);
      currentTest = null;
    }
  }
};

await run();

fs.mkdirSync(resultsDir, { recursive: true });
fs.writeFileSync(path.join(resultsDir, 'results.json'), JSON.stringify(results.map((entry) => ({
  title: entry.title,
  status: entry.status,
  durationMs: entry.durationMs,
  error: entry.error ? { message: entry.error.message } : undefined,
})), null, 2));

const totalTime = results.reduce((sum, entry) => sum + entry.durationMs, 0) / 1000;
const xmlBody = results
  .map((entry) => {
    const timeSec = (entry.durationMs / 1000).toFixed(3);
    if (entry.status === 'failed') {
      const message = escapeXml(entry.error?.message || 'Test failed');
      return `  <testcase classname="generated" name="${escapeXml(entry.title)}" time="${timeSec}">\n    <failure message="${message}"/>\n  </testcase>`;
    }
    return `  <testcase classname="generated" name="${escapeXml(entry.title)}" time="${timeSec}"/>`;
  })
  .join('\n');
const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="playwright-stub" tests="${results.length}" failures="${results.filter((r) => r.status === 'failed').length}" time="${totalTime.toFixed(3)}">\n${xmlBody}\n</testsuite>\n`;

ensureDir(junitPath);
fs.writeFileSync(junitPath, xml);

if (hasFailure) {
  process.exit(1);
}
