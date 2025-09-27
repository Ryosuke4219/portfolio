import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { createFailureSignature } from '../classification.js';
import { loadConfig, resolveConfigPaths } from '../config.js';
import { ensureDir } from '../fs-utils.js';
import { parseJUnitFile, parseJUnitStream } from '../junit-parser.js';
import { appendAttempts } from '../store.js';
import { resolveConfigPath } from './utils.js';

function collectXmlFiles(targetPath) {
  const results = [];
  const stats = fs.statSync(targetPath);
  if (stats.isFile()) {
    if (targetPath.endsWith('.xml')) results.push(targetPath);
    return results;
  }
  if (stats.isDirectory()) {
    const entries = fs.readdirSync(targetPath);
    for (const entry of entries) {
      const full = path.join(targetPath, entry);
      const entryStats = fs.statSync(full);
      if (entryStats.isDirectory()) {
        results.push(...collectXmlFiles(full));
      } else if (entryStats.isFile() && entry.toLowerCase().endsWith('.xml')) {
        results.push(full);
      }
    }
  }
  return results;
}

function truncate(text, limit) {
  if (!text) return null;
  const str = String(text);
  if (str.length <= limit) return str;
  return `${str.slice(0, limit)}…`;
}

function sanitiseIdPart(text) {
  if (!text) return 'input';
  return String(text).replace(/[^a-z0-9._-]+/gi, '_');
}

function createParseErrorAttempt({
  source,
  error,
  runId,
  timestamp,
  branch,
  commit,
  actor,
  workflow,
  durationTotalMs,
}) {
  const relativeSource = source === '<stdin>' ? source : path.relative(process.cwd(), source);
  const suite = '__parser__';
  const className = 'ingest';
  const params = relativeSource === '<stdin>' ? null : relativeSource;
  const canonicalId = `${suite}.${className}.${sanitiseIdPart(relativeSource)}`;
  const message = `Failed to parse ${relativeSource}`;
  const details = error?.stack || error?.message || String(error);
  const signature = createFailureSignature(message, details) || sanitiseIdPart(relativeSource);
  return {
    suite,
    class: className,
    name: 'parse_error',
    params,
    canonical_id: canonicalId,
    status: 'error',
    duration_ms: 0,
    failure_kind: 'parsing',
    failure_signature: signature,
    failure_message: message,
    failure_details: details,
    system_out: [],
    system_err: [],
    retries: 0,
    source,
    run_id: runId,
    ts: timestamp,
    branch,
    commit,
    duration_total_ms: durationTotalMs,
    ci_meta: {
      actor,
      workflow,
    },
    failure_excerpt: truncate(details, 500),
  };
}

export async function runParse(args) {
  const configPath = resolveConfigPath(args.config);
  const { config } = loadConfig(configPath);
  const resolvedConfig = resolveConfigPaths(config, process.cwd());

  const inputTarget = args.input ? path.resolve(process.cwd(), args.input) : resolvedConfig.paths.input;
  const runId = args.run_id || `run_${Date.now()}`;
  const timestamp = args.timestamp || new Date().toISOString();
  const branch = args.branch || null;
  const commit = args.commit || null;
  const actor = args.actor || null;
  const workflow = args.workflow || null;
  const durationTotalMs = args.duration_total_ms != null ? Number(args.duration_total_ms) : null;
  const timeoutFactor = Number.isFinite(Number(args.timeout_factor)) ? Number(args.timeout_factor) : resolvedConfig.timeout_factor;

  const attempts = [];
  const parseErrors = [];
  if (args.input === '-' || args.stdin) {
    try {
      const { attempts: parsed } = await parseJUnitStream(process.stdin, { filename: '<stdin>', timeoutFactor });
      for (const attempt of parsed) {
        attempts.push({ ...attempt, source: '<stdin>' });
      }
    } catch (error) {
      parseErrors.push({ source: '<stdin>', error });
    }
  } else if (fs.existsSync(inputTarget)) {
    const files = collectXmlFiles(inputTarget);
    if (!files.length) {
      console.warn(`No JUnit XML files found under ${inputTarget}`);
    }
    for (const file of files) {
      try {
        const { attempts: parsed } = await parseJUnitFile(file, { timeoutFactor });
        for (const attempt of parsed) {
          attempts.push({ ...attempt, source: file });
        }
      } catch (error) {
        parseErrors.push({ source: file, error });
      }
    }
  } else {
    console.error(`Input path not found: ${inputTarget}`);
    process.exit(1);
  }

  for (const { source, error } of parseErrors) {
    console.warn(`Failed to parse JUnit XML at ${source}: ${error?.message || error}`);
    attempts.push(
      createParseErrorAttempt({
        source,
        error,
        runId,
        timestamp,
        branch,
        commit,
        actor,
        workflow,
        durationTotalMs,
      }),
    );
  }

  if (!attempts.length) {
    console.log('No test cases parsed.');
    return;
  }

  const enrichedAttempts = attempts.map((attempt) => ({
    ...attempt,
    run_id: runId,
    ts: timestamp,
    branch,
    commit,
    duration_total_ms: durationTotalMs,
    ci_meta: {
      actor,
      workflow,
    },
    failure_details: truncate(attempt.failure_details, 2000),
    failure_message: attempt.failure_message,
    failure_excerpt: truncate(attempt.failure_details, 500),
    system_out: (attempt.system_out || []).map((line) => truncate(line, 500)),
    system_err: (attempt.system_err || []).map((line) => truncate(line, 500)),
    source: attempt.source,
  }));

  ensureDir(resolvedConfig.paths.store);
  appendAttempts(resolvedConfig.paths.store, enrichedAttempts);

  const failCount = enrichedAttempts.filter((a) => a.status === 'fail' || a.status === 'error').length;
  const parseErrorCount = parseErrors.length;
  const parseSuffix = parseErrorCount ? `, parse_errors=${parseErrorCount}` : '';
  console.log(`Stored ${enrichedAttempts.length} attempts (fails=${failCount}${parseSuffix}).`);
  if (parseErrorCount) {
    console.log('Some inputs could not be parsed and were recorded as parsing failures.');
  }
  console.log(`Run ID: ${runId}`);
  console.log(`Store: ${resolvedConfig.paths.store}`);
}
