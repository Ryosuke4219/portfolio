import fs from 'node:fs';
import path from 'node:path';
import { SPEC2CASES_SAMPLE_CASES_PATH } from '../../../scripts/paths.mjs';

const args = process.argv.slice(2);
if (!args.length) {
  console.log('ℹ️  No cases file specified. Defaulting to sample cases.');
}

const options = {};
let casesPath;

for (let i = 0; i < args.length; i += 1) {
  const arg = args[i];
  if (arg === '--tag') {
    options.tag = args[i + 1];
    i += 1;
    continue;
  }
  if (arg === '--id') {
    options.id = args[i + 1];
    i += 1;
    continue;
  }
  if (!casesPath && !arg.startsWith('--')) {
    casesPath = arg;
    continue;
  }
  console.error(`Unknown argument: ${arg}`);
  process.exit(2);
}

const defaultCasesPath = SPEC2CASES_SAMPLE_CASES_PATH;
const resolvedCasesPath = casesPath ? path.resolve(process.cwd(), casesPath) : defaultCasesPath;

if (!fs.existsSync(resolvedCasesPath)) {
  console.error(`Cases file not found: ${resolvedCasesPath}`);
  process.exit(2);
}

const content = fs.readFileSync(resolvedCasesPath, 'utf8');
const suiteDef = JSON.parse(content);

const filterByTag = (testCase) => {
  if (!options.tag) {
    return true;
  }
  return Array.isArray(testCase.tags) && testCase.tags.includes(options.tag);
};

const filterById = (testCase) => {
  if (!options.id) {
    return true;
  }
  return testCase.id === options.id;
};

const targetCases = (Array.isArray(suiteDef.cases) ? suiteDef.cases : []).filter(
  (testCase) => filterByTag(testCase) && filterById(testCase),
);

if (!targetCases.length) {
  console.warn('No test cases matched the provided filters.');
  process.exit(0);
}

console.log(`Suite: ${suiteDef.suite}`);
console.log(`Source: ${resolvedCasesPath}`);
if (options.tag) {
  console.log(`Filter tag: ${options.tag}`);
}
if (options.id) {
  console.log(`Filter id: ${options.id}`);
}
console.log('---');

let passed = 0;
let failed = 0;

for (const testCase of targetCases) {
  console.log(`Running ${testCase.id} ${testCase.title}`);
  if (Array.isArray(testCase.pre) && testCase.pre.length) {
    console.log('  Preconditions:');
    for (const item of testCase.pre) {
      console.log(`   - ${item}`);
    }
  }
  console.log('  Steps:');
  for (const step of testCase.steps || []) {
    console.log(`   → ${step}`);
  }
  console.log('  Expected:');
  for (const expected of testCase.expected || []) {
    console.log(`   ☆ ${expected}`);
  }

  const issues = [];
  if (!Array.isArray(testCase.steps) || !testCase.steps.length) {
    issues.push('steps are missing');
  }
  if (!Array.isArray(testCase.expected) || !testCase.expected.length) {
    issues.push('expected results are missing');
  }

  if (issues.length) {
    failed += 1;
    console.log(`  ✖ FAILED (${issues.join(', ')})`);
  } else {
    passed += 1;
    console.log('  ✔ PASSED');
  }
  console.log('');
}

const total = passed + failed;
console.log(`Summary: total=${total}, passed=${passed}, failed=${failed}`);

if (failed > 0) {
  process.exit(1);
}
