#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { parseJUnitFile } from '../src/junit-parser.js';
import { appendAttempts } from '../src/store.js';

function requireString(value, name) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${name} is required`);
  }
  return value;
}

function resolvePath(targetPath) {
  return path.resolve(process.cwd(), targetPath);
}

function sanitiseRunIdPart(text) {
  if (!text) return 'run';
  return String(text).replace(/[^a-zA-Z0-9_.-]+/g, '_');
}

function createRunId(junitPath, timestampIso) {
  const baseName = path.basename(junitPath, path.extname(junitPath));
  const prefix = sanitiseRunIdPart(baseName) || 'run';
  const timePart = timestampIso.replace(/[-:TZ.]/g, '').slice(0, 14);
  return `${prefix}_${timePart}`;
}

function toRelativeOrAbsolute(filePath) {
  const relative = path.relative(process.cwd(), filePath);
  if (!relative || relative.startsWith('..')) return filePath;
  return relative;
}

function truncate(text, limit = 500) {
  if (text === undefined || text === null) return null;
  const str = String(text);
  if (str.length <= limit) return str;
  return `${str.slice(0, limit)}…`;
}

export async function analyzeJUnitReport(junitPath, dbPath) {
  const junitArg = requireString(junitPath, 'junitPath');
  const dbArg = requireString(dbPath, 'dbPath');

  const resolvedJUnit = resolvePath(junitArg);
  const resolvedDb = resolvePath(dbArg);

  if (!fs.existsSync(resolvedJUnit) || !fs.statSync(resolvedJUnit).isFile()) {
    throw new Error(`JUnit report not found: ${junitArg}`);
  }

  const timestamp = new Date();
  const timestampIso = timestamp.toISOString();
  const runId = createRunId(resolvedJUnit, timestampIso);
  const source = toRelativeOrAbsolute(resolvedJUnit);

  const { attempts } = await parseJUnitFile(resolvedJUnit);
  const enrichedAttempts = attempts.map((attempt) => {
    const excerptSource = attempt.failure_details || attempt.failure_message || null;
    return {
      ...attempt,
      run_id: runId,
      ts: timestampIso,
      source,
      failure_excerpt: excerptSource ? truncate(excerptSource) : null,
    };
  });

  appendAttempts(resolvedDb, enrichedAttempts);

  return {
    runId,
    attemptsCount: enrichedAttempts.length,
    outputPath: resolvedDb,
  };
}

function printUsage() {
  console.error('Usage: node analyze-junit.mjs <junitPath> <dbPath>');
}

const isMainModule = (() => {
  if (!process.argv[1]) return false;
  try {
    return path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
  } catch {
    return false;
  }
})();

if (isMainModule) {
  (async () => {
    try {
      const [, , junitArg, dbArg] = process.argv;
      if (!junitArg || !dbArg) {
        printUsage();
        process.exitCode = 1;
        return;
      }
      const result = await analyzeJUnitReport(junitArg, dbArg);
      const junitDisplay = toRelativeOrAbsolute(resolvePath(junitArg));
      const outputDisplay = toRelativeOrAbsolute(result.outputPath);
      console.log(`Analyzed ${result.attemptsCount} test cases from ${junitDisplay}`);
      console.log(`Appended results to ${outputDisplay}`);
    } catch (error) {
      const message = error && typeof error.message === 'string'
        ? error.message
        : String(error);
      console.error(`Error: ${message}`);
      process.exitCode = 1;
    }
  })();
}
