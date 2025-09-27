#!/usr/bin/env node
import path from 'node:path';

import {
  parseSpecFile,
  saveCases,
  resolveInputPath,
} from '../src/index.js';
import { validateCasesSchema } from '../src/validate-schema.js';
import { SPEC2CASES_SAMPLE_CASES_PATH } from '../../../scripts/paths.mjs';

function usage() {
  console.error('Usage: node spec2cases.mjs <input.(json|txt|md)> [output.json]');
  console.error(`       (no args) -> defaults to ${SPEC2CASES_SAMPLE_CASES_PATH}`);
}

function main(argv) {
  let [, , rawInputPath, outputPath] = argv;

  let resolution;
  try {
    resolution = resolveInputPath(rawInputPath, SPEC2CASES_SAMPLE_CASES_PATH);
  } catch (error) {
    usage();
    console.error(error.message);
    process.exit(2);
  }

  const { path: inputPath, usedDefault } = resolution;
  if (usedDefault) {
    console.log(`ℹ️  No path provided. Defaulting to sample cases: ${SPEC2CASES_SAMPLE_CASES_PATH}`);
  }

  let parsed;
  try {
    parsed = parseSpecFile(inputPath);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }

  const errors = validateCasesSchema(parsed);
  if (errors.length > 0) {
    console.error('Schema validation failed:');
    for (const err of errors) console.error(`- ${err}`);
    process.exit(1);
  }

  if (outputPath) {
    saveCases(parsed, outputPath);
    console.log(`📝 Wrote ${parsed.cases.length} cases to ${outputPath}`);
  } else if (path.extname(inputPath).toLowerCase() !== '.json') {
    console.log(JSON.stringify(parsed, null, 2));
  }

  console.log(`✅ Valid cases: suite="${parsed.suite}", count=${parsed.cases.length}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv);
}
