import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

import { createExpect } from './expectations.js';

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

const escapeXml = (value) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

const ensureDir = (target) => {
  fs.mkdirSync(path.dirname(target), { recursive: true });
};

const isRegExp = (value) => Object.prototype.toString.call(value) === '[object RegExp]';

export const runPlaywrightTests = async ({
  baseURL,
  projectRoot,
  demoDir,
  generatedDir,
  snapshotDir,
  resultsDir,
  screenshotDiffDir,
  junitPath,
}) => {
  const base = new url.URL(baseURL);

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
          state.fields.get(selectorForTestId('login-password')) ||
          state.fields.get('#pass') ||
          state.fields.get('pass') ||
          '';
        const destination = pass === 'wrong' ? '/invalid.html' : '/dashboard.html';
        const absolute = new url.URL(destination, `${base.protocol}//${base.host}`).toString();
        await this.goto(absolute);
      },
      async waitForLoadState(state = 'load') {
        const allowed = new Set(['load', 'domcontentloaded', 'networkidle']);
        if (!allowed.has(state)) {
          throw new Error(`[playwright-stub] waitForLoadState("${state}") is not supported in the stub environment.`);
        }
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

  const tests = [];
  let currentTestTitle = null;

  const { expect } = createExpect({
    snapshotDir,
    screenshotDiffDir,
    getCurrentTestTitle: () => currentTestTitle,
    urlMatches,
    isRegExp,
  });

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
        throw new Error(`[playwright-stub] Failed to load ${file}: ${error?.message || error}`);
      }
    }
  }

  if (!tests.length) {
    console.log('[playwright-stub] No tests collected. Exiting.');
    ensureDir(junitPath);
    fs.writeFileSync(
      junitPath,
      '<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="playwright-stub" tests="0" failures="0" time="0"/>\n',
    );
    return { exitCode: 0 };
  }

  const results = [];
  let hasFailure = false;

  console.log(`[playwright-stub] Running ${tests.length} test(s) with base URL ${baseURL}`);
  for (const { title, fn } of tests) {
    const page = createPage();
    const start = Date.now();
    try {
      currentTestTitle = title;
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
      currentTestTitle = null;
      const durationMs = Date.now() - start;
      results.push({ title, status: 'passed', durationMs });
      console.log(`  ✓ ${title}`);
    } catch (error) {
      const durationMs = Date.now() - start;
      hasFailure = true;
      results.push({ title, status: 'failed', durationMs, error });
      console.error(`  ✗ ${title}`);
      console.error(`    ${error?.message || error}`);
      currentTestTitle = null;
    }
  }

  fs.mkdirSync(resultsDir, { recursive: true });
  fs.writeFileSync(
    path.join(resultsDir, 'results.json'),
    JSON.stringify(
      results.map((entry) => ({
        title: entry.title,
        status: entry.status,
        durationMs: entry.durationMs,
        error: entry.error ? { message: entry.error.message } : undefined,
      })),
      null,
      2,
    ),
  );

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

  return { exitCode: hasFailure ? 1 : 0 };
};
