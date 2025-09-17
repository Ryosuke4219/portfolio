import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const inputArg = process.argv[2];
const input = inputArg ?? path.join(__dirname, '../cases.sample.json');

if (!inputArg) {
  console.log(`ℹ️  No path provided. Defaulting to sample cases: ${input}`);
}

if (!fs.existsSync(input)) {
  console.error(`Could not find cases file: ${input}`);
  process.exit(2);
}

const data = JSON.parse(fs.readFileSync(input, 'utf8'));

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

const { valid, errors } = validateSuite(data);
if (!valid) {
  console.error('Schema validation failed:');
  for (const error of errors) {
    console.error('-', error);
  }
  process.exit(1);
}

console.log(`✅ Valid cases: suite="${data.suite}", count=${data.cases.length}`);
process.exit(0);
