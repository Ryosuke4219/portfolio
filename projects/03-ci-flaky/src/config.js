import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const DEFAULT_CONFIG = {
  window: 20,
  threshold: 0.6,
  new_flaky_window: 5,
  weights: {
    intermittency: 0.5,
    p_fail: 0.3,
    recency: 0.15,
    impact: 0.05,
  },
  timeout_factor: 3.0,
  impact_baseline_ms: 600000,
  recency_lambda: 0.1,
  output: {
    top_n: 50,
    formats: ['csv', 'json', 'html'],
  },
  issue: {
    enabled: true,
    dry_run: true,
    repo: '',
    labels: ['flaky', 'test'],
    assignees: [],
    dedupe_by: 'failure_signature',
  },
  paths: {
    input: './junit',
    store: './data/runs.jsonl',
    out: './out',
  },
};

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

function parseValue(value) {
  const trimmed = value.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) return parseInlineArray(trimmed);
  return parseScalar(trimmed);
}

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

function findNextNonEmpty(lines, start) {
  for (let i = start; i < lines.length; i += 1) {
    if (lines[i].content.length > 0) return lines[i];
  }
  return null;
}

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
    let parent = parentEntry.value;

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

function mergeDeep(target, source) {
  if (source == null) return target;
  const output = Array.isArray(target) ? [...target] : { ...target };
  for (const [key, value] of Object.entries(source)) {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const base = target && typeof target[key] === 'object' && !Array.isArray(target[key]) ? target[key] : {};
      output[key] = mergeDeep(base, value);
    } else if (Array.isArray(value)) {
      output[key] = [...value];
    } else {
      output[key] = value;
    }
  }
  return output;
}

export function loadConfig(configPath) {
  if (!configPath) return { config: { ...DEFAULT_CONFIG }, path: null };
  const resolvedPath = path.resolve(process.cwd(), configPath);
  if (!fs.existsSync(resolvedPath)) {
    return { config: { ...DEFAULT_CONFIG }, path: resolvedPath };
  }
  const raw = fs.readFileSync(resolvedPath, 'utf8');
  let parsed;
  try {
    parsed = parseYAML(raw);
  } catch (error) {
    throw new Error(`Failed to parse YAML config at ${resolvedPath}: ${error.message}`);
  }
  const config = mergeDeep(DEFAULT_CONFIG, parsed);
  return { config, path: resolvedPath };
}

export function resolveConfigPaths(config, baseDir = process.cwd()) {
  const resolved = { ...config };
  if (config.paths) {
    resolved.paths = {
      ...config.paths,
      input: path.resolve(baseDir, config.paths.input),
      store: path.resolve(baseDir, config.paths.store),
      out: path.resolve(baseDir, config.paths.out),
    };
  }
  return resolved;
}
