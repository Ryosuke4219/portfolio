import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { validateSuite, formatValidationErrors } from './lib/suite-validator.mjs';

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

const { valid, errors } = validateSuite(data);
if (!valid) {
  console.error('Schema validation failed:');
  console.error(formatValidationErrors(errors));
  process.exit(1);
}

console.log(`✅ Valid cases: suite="${data.suite}", count=${data.cases.length}`);
process.exit(0);
