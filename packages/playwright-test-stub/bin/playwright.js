#!/usr/bin/env node
import path from 'node:path';
import process from 'node:process';

import { LLM2PW_DEMO_DIR } from '../../../scripts/paths.mjs';
import { runPlaywrightTests } from './runner.js';

const projectRoot = process.cwd();
const demoDir = LLM2PW_DEMO_DIR;
const generatedDir = path.resolve(projectRoot, 'projects/02-blueprint-to-playwright/tests/generated');
const snapshotDir = path.join(generatedDir, '__snapshots__');
const junitPath = path.resolve(projectRoot, 'junit-results.xml');
const resultsDir = path.resolve(projectRoot, 'test-results');
const screenshotDiffDir = path.join(resultsDir, 'snapshot-diffs');

const args = process.argv.slice(2);
const command = args.shift();

const printUsage = () => {
  console.log('[playwright-stub] Usage: playwright test [options]');
};

if (command == null || command === '' || command === '--help' || command === '-h') {
  printUsage();
  process.exit(0);
}

if (command === '--version' || command === '-v') {
  console.log('0.0.0-stub');
  process.exit(0);
}

const installCommands = new Set(['install', 'install-deps']);

if (installCommands.has(command)) {
  console.log(`[playwright-stub] Skipping "playwright ${command}" in stub environment.`);
  process.exit(0);
}

if (command !== 'test') {
  console.error('[playwright-stub] Only "playwright test" is supported.');
  process.exit(1);
}

for (let i = 0; i < args.length; i += 1) {
  const value = args[i];
  if (value === '-c' || value === '--config') {
    if (i + 1 < args.length) {
      i += 1;
    }
    continue;
  }
}

const baseURL = process.env.BASE_URL || 'http://127.0.0.1:4173';

try {
  const { exitCode } = await runPlaywrightTests({
    baseURL,
    projectRoot,
    demoDir,
    generatedDir,
    snapshotDir,
    resultsDir,
    screenshotDiffDir,
    junitPath,
  });
  process.exit(exitCode);
} catch (error) {
  console.error(error?.message || error);
  process.exit(1);
}
