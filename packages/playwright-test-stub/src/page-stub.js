import url from 'node:url';

export const isRegExp = (value) => Object.prototype.toString.call(value) === '[object RegExp]';

export const urlMatches = (actualUrl, expected) => {
  if (!actualUrl) return false;
  if (isRegExp(expected)) return expected.test(actualUrl);
  if (typeof expected === 'string') {
    if (actualUrl === expected) return true;
    if (/^\/.+\/$/.test(expected)) {
      try {
        return new RegExp(expected.slice(1, -1)).test(actualUrl);
      } catch {
        return false;
      }
    }
  }
  return false;
};

const selectorForTestId = (testId) => `[data-testid="${testId}"]`;
const hasTestId = (html, testId) => new RegExp(`data-testid=["']${testId}["']`).test(html);
const allowedLoadStates = new Set(['load', 'domcontentloaded', 'networkidle']);

export const createPageFactory = ({ base, readPage }) => {
  const baseUrl = base instanceof url.URL ? base : new url.URL(base);
  const origin = `${baseUrl.protocol}//${baseUrl.host}`;
  const normalise = (target) => new url.URL(target, origin).toString();
  const submitSelectors = new Set(['button[type=submit]', selectorForTestId('login-submit')]);

  return () => {
    const state = { url: '', content: '', fields: new Map() };

    const page = {
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
        if (!submitSelectors.has(normalizedSelector)) {
          throw new Error(`Unsupported selector for click(): ${selector}`);
        }
        const pass =
          state.fields.get(selectorForTestId('login-password')) ||
          state.fields.get('#pass') ||
          state.fields.get('pass') ||
          '';
        const destination = pass === 'wrong' ? '/invalid.html' : '/dashboard.html';
        await page.goto(destination);
      },
      async waitForLoadState(stateName = 'load') {
        if (!allowedLoadStates.has(stateName)) {
          throw new Error(
            `[playwright-stub] waitForLoadState("${stateName}") is not supported in the stub environment.`,
          );
        }
      },
      async waitForURL(expected) {
        if (!urlMatches(state.url, expected)) {
          throw new Error(`Expected navigation to match ${expected}, current URL ${state.url}`);
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
        const locator = {
          __kind: 'test-id-locator',
          testId,
          selector,
          async fill(value) {
            if (!hasTestId(state.content, testId)) {
              throw new Error(`Expected to find data-testid="${testId}" before fill()`);
            }
            await page.fill(selector, value);
          },
          async click() {
            if (!hasTestId(state.content, testId)) {
              throw new Error(`Expected to find data-testid="${testId}" before click()`);
            }
            await page.click(selector);
          },
          check() {
            if (!hasTestId(state.content, testId)) {
              throw new Error(`Expected element with data-testid="${testId}" in ${state.url}`);
            }
          },
          page: null,
        };
        return locator;
      },
      async content() {
        return state.content;
      },
      _getURL() {
        return state.url;
      },
      _attach(locator) {
        if (locator && typeof locator === 'object') {
          locator.page = page;
        }
        return locator;
      },
    };

    return page;
  };
};
