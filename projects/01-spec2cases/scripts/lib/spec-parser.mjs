const BULLET_KEYS = new Map([
  ['pre', 'pre'],
  ['given', 'pre'],
  ['step', 'steps'],
  ['when', 'steps'],
  ['expected', 'expected'],
  ['then', 'expected'],
  ['expect', 'expected'],
  ['tag', 'tags'],
  ['tags', 'tags'],
]);

const BULLET_PREFIX_PATTERN = /^([-*]|\d+[.)])\s+(.*)$/;

const splitTags = (value) =>
  value
    .split(/[,、]/)
    .map((item) => item.trim())
    .filter(Boolean);

export function parseSpec(text, options = {}) {
  const { onWarning } = options;
  const lines = text.split(/\r?\n/);
  let suite = '';
  const cases = [];
  let current = null;
  const warnings = [];

  const emitWarning = (message) => {
    warnings.push(message);
    if (typeof onWarning === 'function') {
      onWarning(message);
    }
  };

  const pushCurrent = () => {
    if (current) {
      if (!current.title) {
        throw new Error(`Test case "${current.id}" is missing a title.`);
      }
      cases.push(current);
      current = null;
    }
  };

  const ensureCurrent = () => {
    if (!current) {
      throw new Error('Specification format error: bullet section defined before any test case heading.');
    }
    return current;
  };

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      return;
    }

    if (line.startsWith('# ')) {
      suite = line.slice(2).trim();
      return;
    }

    if (line.startsWith('Suite:')) {
      suite = line.slice('Suite:'.length).trim();
      return;
    }

    if (line.startsWith('## ')) {
      pushCurrent();
      const body = line.slice(3).trim();
      if (!body) {
        throw new Error('Test case heading "##" must include id and title.');
      }
      const match = body.match(/^([^\s]+)\s+(.+)$/);
      if (!match) {
        throw new Error(`Unable to parse test case heading: "${body}"`);
      }
      current = {
        id: match[1].trim(),
        title: match[2].trim(),
        pre: [],
        steps: [],
        expected: [],
        tags: [],
      };
      return;
    }

    const prefixMatch = line.match(BULLET_PREFIX_PATTERN);
    if (prefixMatch) {
      const bulletBody = prefixMatch[2].trim();
      const bulletMatch = bulletBody.match(/^([A-Za-z]+):\s*(.+)$/);
      if (!bulletMatch) {
        emitWarning(`Skip bullet (unrecognized format): ${line}`);
        return;
      }

      const key = bulletMatch[1].toLowerCase();
      const value = bulletMatch[2].trim();
      const target = ensureCurrent();

      const normalizedKey = BULLET_KEYS.get(key);
      if (!normalizedKey) {
        emitWarning(`Skip bullet (unknown key "${key}"): ${line}`);
        return;
      }

      if (normalizedKey === 'tags') {
        target.tags.push(...splitTags(value));
        return;
      }

      target[normalizedKey].push(value);
      return;
    }

    emitWarning(`Skip line: ${line}`);
  });

  pushCurrent();

  if (!suite) {
    throw new Error('Suite name was not specified. Use "# <suite>" or "Suite: <suite>".');
  }
  if (!cases.length) {
    throw new Error('No test cases were parsed. Ensure "## <id> <title>" blocks exist.');
  }

  const uniqueIds = new Set();
  cases.forEach((testCase) => {
    if (uniqueIds.has(testCase.id)) {
      throw new Error(`Duplicate test case id detected: ${testCase.id}`);
    }
    uniqueIds.add(testCase.id);
  });

  return { suite, cases, warnings };
}
