#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

import { SPEC2CASES_SAMPLE_CASES_PATH } from '../../../scripts/paths.mjs';
import { parseSpecText } from '../src/parse-spec.js';

function usage() {
  console.error('Usage: node spec2cases.mjs <input.(json|txt|md)> [output.json]');
  console.error(`       (no args) -> defaults to ${SPEC2CASES_SAMPLE_CASES_PATH}`);
}

function readFile(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    const message = error && typeof error.message === 'string' ? error.message : String(error);
    throw new Error(`Failed to read "${filePath}": ${message}`);
  }
}

function ensureArrayOfStrings(value) {
  if (!Array.isArray(value)) return false;
  return value.every((item) => typeof item === 'string' && item.trim().length > 0);
}

function validateCaseStructure(testCase, index, errors) {
  const prefix = `cases[${index}]`;
  if (!testCase || typeof testCase !== 'object') {
    errors.push(`${prefix} must be an object`);
    return;
  }

  if (typeof testCase.id !== 'string' || testCase.id.trim().length === 0) {
    errors.push(`${prefix}.id must be a non-empty string`);
  }
  if (typeof testCase.title !== 'string' || testCase.title.trim().length === 0) {
    errors.push(`${prefix}.title must be a non-empty string`);
  }
  if (!ensureArrayOfStrings(testCase.pre)) {
    errors.push(`${prefix}.pre must be an array of non-empty strings`);
  }
  if (!ensureArrayOfStrings(testCase.steps)) {
    errors.push(`${prefix}.steps must be an array of non-empty strings`);
  }
  if (!ensureArrayOfStrings(testCase.expected)) {
    errors.push(`${prefix}.expected must be an array of non-empty strings`);
  }
  if (!ensureArrayOfStrings(testCase.tags)) {
    errors.push(`${prefix}.tags must be an array of non-empty strings`);
  }
}

export function validateCasesSchema(data) {
  const errors = [];
  if (!data || typeof data !== 'object') {
    errors.push('root must be an object');
    return errors;
  }
  if (typeof data.suite !== 'string' || data.suite.trim().length === 0) {
    errors.push('suite must be a non-empty string');
  }
  if (!Array.isArray(data.cases)) {
    errors.push('cases must be an array');
  } else if (data.cases.length === 0) {
    errors.push('cases must contain at least one item');
  } else {
    data.cases.forEach((testCase, index) => {
      validateCaseStructure(testCase, index, errors);
    });
  }
  return errors;
}

export function parseSpecFile(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const raw = readFile(filePath);
  if (ext === '.json') {
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      throw new Error(`Invalid JSON: ${(error && error.message) || error}`);
    }
    return parsed;
  }
  if (ext === '.txt' || ext === '.md') {
    return parseSpecText(raw);
  }
  throw new Error(`Unsupported file extension for "${filePath}"`);
}

export function saveCases(result, outputPath) {
  const json = `${JSON.stringify(result, null, 2)}\n`;
  fs.writeFileSync(outputPath, json, 'utf8');
}

function main(argv) {
  let [, , inputPath, outputPath] = argv;

  // Default to sample file if no input provided (retains main-branch behavior)
  if (!inputPath) {
    if (fs.existsSync(SPEC2CASES_SAMPLE_CASES_PATH)) {
      console.log(
        `ℹ️  No path provided. Defaulting to sample cases: ${SPEC2CASES_SAMPLE_CASES_PATH}`,
      );
      inputPath = SPEC2CASES_SAMPLE_CASES_PATH;
    } else {
      usage();
      process.exit(2);
    }
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
    // When parsing from text/markdown and no output is specified, print the JSON to stdout
    console.log(JSON.stringify(parsed, null, 2));
  }

  console.log(`✅ Valid cases: suite="${parsed.suite}", count=${parsed.cases.length}`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv);
}
