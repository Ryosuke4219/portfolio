/**
 * @param {string} line
 * @returns {string}
 */
function stripInlineComment(line) {
  let escaped = false;
  let quote = null;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (escaped) {
      escaped = false;
      continue;
    }
    if (ch === '\\') {
      escaped = true;
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      continue;
    }
    if (ch === '#') {
      return line.slice(0, i).trimEnd();
    }
  }
  return line;
}

/**
 * @param {string} value
 * @returns {string | number | boolean | null}
 */
function parseScalar(value) {
  const trimmed = value.trim();
  if (trimmed === '') return '';
  if (trimmed === 'null') return null;
  if (trimmed === 'true') return true;
  if (trimmed === 'false') return false;
  if (/^[+-]?\d+(?:\.\d+)?$/u.test(trimmed)) return Number(trimmed);
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    const inner = trimmed.slice(1, -1);
    return inner.replace(/\\("|\\|n|r|t)/gu, (match, group) => {
      switch (group) {
        case '"':
          return '"';
        case '\\':
          return '\\';
        case 'n':
          return '\n';
        case 'r':
          return '\r';
        case 't':
          return '\t';
        default:
          return match;
      }
    });
  }
  return trimmed;
}

/**
 * @param {string} raw
 * @returns {unknown[]}
 */
function parseInlineArray(raw) {
  const inner = raw.slice(1, -1).trim();
  if (!inner) return [];
  const items = [];
  let current = '';
  let quote = null;
  let escaped = false;
  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }
    if (ch === '\\') {
      escaped = true;
      current += ch;
      continue;
    }
    if (quote) {
      current += ch;
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      current += ch;
      continue;
    }
    if (ch === ',') {
      items.push(parseValue(current.trim()));
      current = '';
      continue;
    }
    current += ch;
  }
  if (current.trim() !== '') items.push(parseValue(current.trim()));
  return items;
}

/**
 * @param {string} value
 * @returns {unknown}
 */
function parseValue(value) {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) return parseInlineArray(trimmed);
  return parseScalar(trimmed);
}

/**
 * @param {string} text
 * @returns {{ indent: number, content: string }[]}
 */
function preprocessLines(text) {
  const out = [];
  const rawLines = text.split(/\r?\n/u);
  for (const raw of rawLines) {
    const cleaned = stripInlineComment(raw);
    if (!cleaned.trim()) continue;
    const indentMatch = cleaned.match(/^(\s*)/u);
    const indent = indentMatch ? indentMatch[0].length : 0;
    out.push({
      indent,
      content: cleaned.trimStart(),
    });
  }
  return out;
}

/**
 * @param {{ indent: number, content: string }[]} lines
 * @param {number} start
 */
function findNextNonEmpty(lines, start) {
  for (let i = start; i < lines.length; i += 1) {
    if (lines[i].content.length > 0) return lines[i];
  }
  return null;
}

/**
 * @param {string} text
 * @returns {Record<string, unknown>}
 */
export function parseYAML(text) {
  const lines = preprocessLines(text);
  if (lines.length === 0) return {};

  const root = {};
  const stack = [{ indent: -1, value: root }];

  for (let i = 0; i < lines.length; i += 1) {
    const { indent, content } = lines[i];
    if (!content) continue;

    while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
      stack.pop();
    }

    const parentEntry = stack[stack.length - 1];
    const parent = parentEntry.value;

    if (content.startsWith('- ')) {
      if (!Array.isArray(parent)) {
        throw new Error('List item encountered outside of an array context');
      }
      const itemRaw = content.slice(2).trim();
      if (!itemRaw) {
        const next = findNextNonEmpty(lines, i + 1);
        const child = next && next.indent > indent && next.content.startsWith('- ') ? [] : {};
        parent.push(child);
        stack.push({ indent, value: child });
      } else if (itemRaw.includes(':')) {
        const [itemKeyRaw, ...rest] = itemRaw.split(':');
        const itemKey = itemKeyRaw.trim();
        const itemValuePart = rest.join(':').trim();
        const child = itemValuePart ? parseValue(itemValuePart) : {};
        const obj = { [itemKey]: child };
        parent.push(obj);
        if (!itemValuePart) {
          stack.push({ indent, value: child });
        }
      } else {
        parent.push(parseValue(itemRaw));
      }
      continue;
    }

    const colonIndex = content.indexOf(':');
    if (colonIndex === -1) {
      throw new Error(`Invalid YAML entry: ${content}`);
    }

    const key = content.slice(0, colonIndex).trim();
    const valuePart = content.slice(colonIndex + 1).trim();

    if (valuePart === '') {
      const next = findNextNonEmpty(lines, i + 1);
      const childIsArray = Boolean(next && next.indent > indent && next.content.startsWith('- '));
      const child = childIsArray ? [] : {};
      if (Array.isArray(parent)) {
        const obj = { [key]: child };
        parent.push(obj);
      } else {
        parent[key] = child;
      }
      stack.push({ indent, value: child });
    } else {
      const parsedValue = parseValue(valuePart);
      if (Array.isArray(parent)) {
        const obj = { [key]: parsedValue };
        parent.push(obj);
      } else {
        parent[key] = parsedValue;
      }
    }
  }

  return root;
}
