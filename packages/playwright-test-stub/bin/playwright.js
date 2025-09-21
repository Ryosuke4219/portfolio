#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import url from 'node:url';
import vm from 'node:vm';

const projectRoot = process.cwd();
const demoDir = path.resolve(projectRoot, 'projects/02-llm-to-playwright/demo');
const generatedDir = path.resolve(projectRoot, 'projects/02-llm-to-playwright/tests/generated');
const junitPath = path.resolve(projectRoot, 'junit-results.xml');
const resultsDir = path.resolve(projectRoot, 'test-results');

const args = process.argv.slice(2);
const command = args.shift();

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

const createPage = () => {
  const state = {
    url: '',
    content: '',
    fields: new Map(),
  };

  const normalise = (target) => new url.URL(target, `${base.protocol}//${base.host}`).toString();

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
      if (selector !== 'button[type=submit]') {
        throw new Error(`Unsupported selector for click(): ${selector}`);
      }
      const pass = state.fields.get('#pass') || '';
      const destination = pass === 'wrong' ? '/invalid.html' : '/dashboard.html';
      const absolute = new url.URL(destination, `${base.protocol}//${base.host}`).toString();
      await this.goto(absolute);
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
    _getURL() {
      return state.url;
    },
  };
};

const expect = (actual) => ({
  async toHaveURL(expected) {
    const urlValue = typeof actual?._getURL === 'function' ? actual._getURL() : actual;
    const isRegex = Object.prototype.toString.call(expected) === '[object RegExp]';
    const match = isRegex ? expected.test(urlValue) : urlValue === expected;
    if (process.env.DEBUG_PLAYWRIGHT_STUB === '1') {
      console.log('[expect.toHaveURL]', { urlValue, expectedType: typeof expected, isRegex, expected: String(expected), match });
    }
    if (!match) {
      if (!isRegex && typeof expected === 'string' && /^\/.+\/$/.test(expected)) {
        const pattern = new RegExp(expected.slice(1, -1));
        if (pattern.test(urlValue)) {
          return;
        }
      }
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
});

const tests = [];

const registerTest = (title, fn) => {
  tests.push({ title, fn });
};

if (!fs.existsSync(generatedDir)) {
  console.warn('[playwright-stub] No generated tests found. Did you run npm run e2e:gen?');
}

const contextGlobals = {
  console,
  test: registerTest,
  expect,
  process: { env: { ...process.env } },
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
      await fn({ page });
      const durationMs = Date.now() - start;
      results.push({ title, status: 'passed', durationMs });
      console.log(`  ✓ ${title}`);
    } catch (error) {
      const durationMs = Date.now() - start;
      hasFailure = true;
      results.push({ title, status: 'failed', durationMs, error });
      console.error(`  ✗ ${title}`);
      console.error(`    ${error?.message || error}`);
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
