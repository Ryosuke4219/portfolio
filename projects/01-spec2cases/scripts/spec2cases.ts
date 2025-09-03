import fs from 'fs';
import path from 'path';
import Ajv from 'ajv';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const schema = JSON.parse(fs.readFileSync(path.join(__dirname, '../schema.json'), 'utf8'));
const ajv = new Ajv({ allErrors: true, allowUnionTypes: true });
const validate = ajv.compile(schema);

const input = process.argv[2];
if (!input) {
  console.error('Usage: ts-node spec2cases.ts <cases.json>');
  process.exit(2);
}

const data = JSON.parse(fs.readFileSync(input, 'utf8'));
const ok = validate(data);
if (!ok) {
  console.error('Schema validation failed:');
  console.error(validate.errors);
  process.exit(1);
}

console.log(`✅ Valid cases: suite="${data.suite}", count=${data.cases.length}`);
process.exit(0);
