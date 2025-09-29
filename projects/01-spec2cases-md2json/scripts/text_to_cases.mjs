import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node text_to_cases.mjs <spec.md> <output.json>');
  process.exit(2);
}

const rawSpec = fs.readFileSync(inputPath, 'utf8').replace(/^\uFEFF/, '');

function parseSpec(text) {
  const lines = text.split(/\r?\n/);
  let suite = '';
  const cases = [];
  let current = null;
  const warnings = [];

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

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }

    if (line.startsWith('# ')) {
      suite = line.slice(2).trim();
      continue;
    }

    if (line.startsWith('Suite:')) {
      suite = line.slice('Suite:'.length).trim();
      continue;
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
      continue;
    }

    if (line.startsWith('- ')) {
      const itemMatch = line.match(/^-\s*([A-Za-z]+):\s*(.+)$/);
      if (!itemMatch) {
        warnings.push(`Skip bullet (unrecognized format): ${line}`);
        continue;
      }
      const key = itemMatch[1].toLowerCase();
      const value = itemMatch[2].trim();
      const target = ensureCurrent();

      switch (key) {
        case 'pre':
        case 'given':
          target.pre.push(value);
          break;
        case 'step':
        case 'when':
          target.steps.push(value);
          break;
        case 'expected':
        case 'then':
        case 'expect':
          target.expected.push(value);
          break;
        case 'tag':
        case 'tags': {
          const tags = value
            .split(/[,、]/)
            .map((t) => t.trim())
            .filter(Boolean);
          target.tags.push(...tags);
          break;
        }
        default:
          warnings.push(`Skip bullet (unknown key "${key}"): ${line}`);
      }
      continue;
    }

    warnings.push(`Skip line: ${line}`);
  }

  pushCurrent();

  if (!suite) {
    throw new Error('Suite name was not specified. Use "# <suite>" or "Suite: <suite>".');
  }
  if (!cases.length) {
    throw new Error('No test cases were parsed. Ensure "## <id> <title>" blocks exist.');
  }

  const uniqueIds = new Set();
  for (const testCase of cases) {
    if (uniqueIds.has(testCase.id)) {
      throw new Error(`Duplicate test case id detected: ${testCase.id}`);
    }
    uniqueIds.add(testCase.id);
  }

  if (warnings.length) {
    for (const warning of warnings) {
      console.warn('WARN:', warning);
    }
  }

  return { suite, cases };
}

function validateSuite(definition) {
  const errors = [];
  if (!definition || typeof definition !== 'object') {
    errors.push('Definition must be an object.');
    return { valid: false, errors };
  }
  if (typeof definition.suite !== 'string' || !definition.suite.trim()) {
    errors.push('suite must be a non-empty string.');
  }
  if (!Array.isArray(definition.cases) || definition.cases.length === 0) {
    errors.push('cases must be a non-empty array.');
  } else {
    definition.cases.forEach((testCase, index) => {
      const prefix = `cases[${index}]`;
      if (!testCase || typeof testCase !== 'object') {
        errors.push(`${prefix} must be an object.`);
        return;
      }
      if (typeof testCase.id !== 'string' || !testCase.id.trim()) {
        errors.push(`${prefix}.id must be a non-empty string.`);
      }
      if (typeof testCase.title !== 'string' || !testCase.title.trim()) {
        errors.push(`${prefix}.title must be a non-empty string.`);
      }
      ['pre', 'steps', 'expected', 'tags'].forEach((field) => {
        const value = testCase[field];
        if (!Array.isArray(value)) {
          errors.push(`${prefix}.${field} must be an array.`);
          return;
        }
        value.forEach((item, itemIndex) => {
          if (typeof item !== 'string' || !item.trim()) {
            errors.push(`${prefix}.${field}[${itemIndex}] must be a non-empty string.`);
          }
        });
      });
    });
  }

  return { valid: errors.length === 0, errors };
}

const suiteDef = parseSpec(rawSpec);
const { valid, errors } = validateSuite(suiteDef);
if (!valid) {
  console.error('Generated test cases did not pass validation:');
  for (const error of errors) {
    console.error('-', error);
  }
  process.exit(1);
}

fs.writeFileSync(outputPath, JSON.stringify(suiteDef, null, 2), 'utf8');
console.log(`✅ Generated ${suiteDef.cases.length} cases for suite "${suiteDef.suite}" → ${outputPath}`);
