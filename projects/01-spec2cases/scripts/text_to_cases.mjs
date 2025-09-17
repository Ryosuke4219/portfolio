import fs from 'node:fs';

import { parseSpec } from './lib/spec-parser.mjs';
import { validateSuite, formatValidationErrors } from './lib/suite-validator.mjs';

const [, , inputPath, outputPath] = process.argv;
if (!inputPath || !outputPath) {
  console.error('Usage: node text_to_cases.mjs <spec.md> <output.json>');
  process.exit(2);
}

const rawSpec = fs.readFileSync(inputPath, 'utf8').replace(/^\uFEFF/, '');

let suiteDef;
try {
  suiteDef = parseSpec(rawSpec, {
    onWarning: (message) => {
      console.warn('WARN:', message);
    },
  });
} catch (error) {
  console.error(`Failed to parse specification: ${error.message}`);
  process.exit(1);
}

const { valid, errors } = validateSuite(suiteDef);
if (!valid) {
  console.error('Generated test cases did not pass validation:');
  console.error(formatValidationErrors(errors));
  process.exit(1);
}

fs.writeFileSync(outputPath, JSON.stringify(suiteDef, null, 2), 'utf8');
console.log(`✅ Generated ${suiteDef.cases.length} cases for suite "${suiteDef.suite}" → ${outputPath}`);
