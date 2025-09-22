#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { spawn } from 'node:child_process';

import { parseArgs } from '../src/cli-args.js';
import { loadConfig, resolveConfigPaths } from '../src/config.js';
import { parseJUnitFile, parseJUnitStream } from '../src/junit-parser.js';
import { createFailureSignature } from '../src/classification.js';
import { appendAttempts } from '../src/store.js';
import { ensureDir } from '../src/fs-utils.js';
import { loadWindowRuns, computeAggregates, determineFlaky, summarise } from '../src/analyzer.js';
import { writeCsv, writeJson, generateHtmlReport } from '../src/report.js';

const DEFAULT_CONFIG_PATHS = [
  'projects/03-ci-flaky/config/flaky.yml',
  'config/flaky.yml',
];

function parseBoolean(value, defaultValue = false) {
  if (value === undefined) return defaultValue;
  if (typeof value === 'boolean') return value;
  const normalized = String(value).trim().toLowerCase();
  if (['false', '0', 'off', 'no'].includes(normalized)) return false;
  if (['true', '1', 'on', 'yes'].includes(normalized)) return true;
  return defaultValue;
}

function parseList(value) {
  if (value === undefined || value === null) return [];
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value)
    .split(/[\s,]+/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

function determineFormats(args, resolvedConfig) {
  const requested = parseList(args.formats ?? args.format);
  if (requested.length) return [...new Set(requested.map((item) => item.toLowerCase()))];
  const configFormats = resolvedConfig.output?.formats;
  if (Array.isArray(configFormats) && configFormats.length) {
    return [...new Set(configFormats.map((item) => String(item).toLowerCase()))];
  }
  return ['csv', 'json', 'html'];
}

function openInBrowser(filePath) {
  if (!filePath) return;
  const resolved = path.resolve(filePath);
  let command;
  let commandArgs;
  if (process.platform === 'darwin') {
    command = 'open';
    commandArgs = [resolved];
  } else if (process.platform === 'win32') {
    command = 'cmd';
    commandArgs = ['/c', 'start', '""', resolved];
  } else {
    command = 'xdg-open';
    commandArgs = [resolved];
  }
  try {
    const child = spawn(command, commandArgs, { detached: true, stdio: 'ignore' });
    child.on('error', (error) => {
      console.warn(`Failed to open report in browser: ${error.message}`);
    });
    child.unref();
  } catch (error) {
    console.warn(`Unable to launch browser for ${resolved}: ${error.message}`);
  }
}

function resolveConfigPath(argPath) {
  if (argPath) return argPath;
  for (const candidate of DEFAULT_CONFIG_PATHS) {
    const resolved = path.resolve(process.cwd(), candidate);
    if (fs.existsSync(resolved)) return resolved;
  }
  return path.resolve(process.cwd(), DEFAULT_CONFIG_PATHS[0]);
}

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

function serialiseFlakyEntry(entry) {
  const failureSignatures = Object.fromEntries(
    [...(entry.failure_signatures?.entries?.() ?? [])].map(([sig, info]) => [sig, { count: info.count, runs: [...info.runs] }]),
  );
  const failureKinds = Object.fromEntries(entry.failure_kinds ?? []);
  const latestFailure = entry.latest_failure
    ? {
        run_id: entry.latest_failure.run_id,
        ts: entry.latest_failure.ts,
        message: entry.latest_failure.message,
        details: entry.latest_failure.details,
        excerpt: entry.latest_failure.excerpt,
        failure_kind: entry.latest_failure.failure_kind,
        failure_signature: entry.latest_failure.failure_signature,
      }
    : null;
  const statuses = (entry.statuses || []).map((status) => ({
    run_index: status.runIndex,
    run_id: status.run_id,
    status: status.status,
    ts: status.ts ?? null,
  }));
  return {
    canonical_id: entry.canonical_id,
    suite: entry.suite,
    class: entry.class,
    name: entry.name,
    params: entry.params,
    attempts: entry.attempts,
    passes: entry.passes,
    fails: entry.fails,
    skipped: entry.skipped,
    p_fail: entry.p_fail,
    intermittency: entry.intermittency,
    recency: entry.recency,
    impact: entry.impact,
    score: entry.score,
    avg_duration_ms: entry.avg_duration_ms,
    failure_top_k: entry.failure_top_k,
    trend: entry.trend,
    statuses,
    failure_signatures: failureSignatures,
    failure_kinds: failureKinds,
    latest_failure: latestFailure,
    is_new: entry.is_new,
  };
}

async function runParse(args) {
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
    attempts.push(createParseErrorAttempt({
      source,
      error,
      runId,
      timestamp,
      branch,
      commit,
      actor,
      workflow,
      durationTotalMs,
    }));
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

function ensureOutputsDir(outPath) {
  ensureDir(outPath);
}

function buildRankingRows(entries) {
  return entries.map((entry, index) => ({
    rank: index + 1,
    canonical_id: entry.canonical_id,
    suite: entry.suite,
    class: entry.class,
    name: entry.name,
    attempts: entry.attempts,
    passes: entry.passes,
    fails: entry.fails,
    p_fail: entry.p_fail.toFixed(3),
    intermittency: entry.intermittency.toFixed(3),
    recency: entry.recency.toFixed(3),
    impact: entry.impact.toFixed(3),
    score: entry.score.toFixed(3),
    avg_duration_ms: entry.avg_duration_ms,
    failure_top_k: entry.failure_top_k,
  }));
}

async function runAnalyze(args) {
  const configPath = resolveConfigPath(args.config);
  const { config } = loadConfig(configPath);
  const resolvedConfig = resolveConfigPaths(config, process.cwd());
  const windowSize = args.window ? Number(args.window) : resolvedConfig.window;
  const { runs, runOrder, runMeta } = await loadWindowRuns(resolvedConfig.paths.store, windowSize);

  if (!runOrder.length) {
    console.log('No run history available. Previous outputs retained.');
    return {
      summary: null,
      flaky: [],
      resolvedConfig,
      runMeta: [],
      runOrder: [],
      failureKindTotals: new Map(),
      htmlPath: null,
    };
  }

  const { results, failureKindTotals } = computeAggregates(runs, runOrder, resolvedConfig);
  const flaky = determineFlaky(results, resolvedConfig, runOrder);
  const topN = Number.isFinite(Number(args.top_n)) ? Number(args.top_n) : resolvedConfig.output.top_n;
  const topFlaky = flaky.slice(0, topN);
  const summary = summarise(results, flaky, failureKindTotals, runOrder);
  const formats = determineFormats(args, resolvedConfig);

  ensureOutputsDir(resolvedConfig.paths.out);

  const timestamp = new Date().toISOString();
  let htmlPath = null;

  if (formats.includes('json')) {
    const summaryJsonPath = path.join(resolvedConfig.paths.out, 'summary.json');
    writeJson(summaryJsonPath, { ...summary, generated_at: timestamp });
    const rankingJsonPath = path.join(resolvedConfig.paths.out, 'flaky_rank.json');
    writeJson(rankingJsonPath, topFlaky.map(serialiseFlakyEntry));
  }

  if (formats.includes('csv')) {
    const summaryRows = [
      { metric: 'total_tests', value: summary.total_tests },
      { metric: 'flaky_count', value: summary.flaky_count },
      { metric: 'new_flaky_count', value: summary.new_flaky_count },
      { metric: 'most_common_failure_kind', value: summary.most_common_failure_kind ?? '' },
      { metric: 'window_runs', value: summary.window_runs },
    ];
    for (const [kind, count] of Object.entries(summary.failure_kind_totals || {})) {
      summaryRows.push({ metric: `failure_kind_${kind}`, value: count });
    }
    const summaryCsvPath = path.join(resolvedConfig.paths.out, 'summary.csv');
    writeCsv(summaryCsvPath, summaryRows, ['metric', 'value']);

    const rankingCsvPath = path.join(resolvedConfig.paths.out, 'flaky_rank.csv');
    writeCsv(rankingCsvPath, buildRankingRows(topFlaky), [
      'rank',
      'canonical_id',
      'suite',
      'class',
      'name',
      'attempts',
      'passes',
      'fails',
      'p_fail',
      'intermittency',
      'recency',
      'impact',
      'score',
      'avg_duration_ms',
      'failure_top_k',
    ]);
  }

  if (formats.includes('html')) {
    htmlPath = path.join(resolvedConfig.paths.out, 'index.html');
    const html = generateHtmlReport(summary, topFlaky, runMeta, failureKindTotals);
    fs.writeFileSync(htmlPath, html, 'utf8');
  }

  console.log(`Analyzed ${results.length} unique tests. Flaky detected: ${flaky.length}`);
  console.log(`Outputs written to ${resolvedConfig.paths.out} (formats: ${formats.join(', ')})`);
  return {
    summary,
    flaky: topFlaky,
    runMeta,
    resolvedConfig,
    runOrder,
    failureKindTotals,
    htmlPath,
  };
}

function formatIssueMarkdown(entry, resolvedConfig, issueConfig, summary) {
  const signatureEntries = Object.entries(entry.failure_signatures || {});
  const primarySignature = signatureEntries.sort((a, b) => b[1].count - a[1].count)[0]?.[0] ?? 'unknown';
  const recentRuns = Array.from(new Set((entry.statuses || []).map((s) => s.run_id).filter(Boolean))).slice(-5).join(', ');
  const failureKinds = entry.failure_top_k || '';
  const avgDurationSec = (entry.avg_duration_ms / 1000).toFixed(2);
  const header = `# Flaky: ${entry.canonical_id}`;
  const body = [
    `- Score: ${entry.score.toFixed(2)} (T=${resolvedConfig.threshold ?? 0.6})`,
    `- Attempts: ${entry.attempts} (Pass ${entry.passes} / Fail ${entry.fails})`,
    `- p_fail=${entry.p_fail.toFixed(2)}, I=${entry.intermittency.toFixed(2)}`,
    `- Avg Duration: ${avgDurationSec}s`,
    `- Failure kinds: ${failureKinds || 'N/A'}`,
    `- Primary signature: ${primarySignature}`,
    `- Recent runs: ${recentRuns || 'N/A'}`,
  ];
  const details = entry.latest_failure?.excerpt || entry.latest_failure?.details || '';
  const snippet = details ? `\n\n\n\`\`\`\n${details}\n\`\`\`` : '';
  const labels = (issueConfig.labels || []).join(', ');
  return `${header}\n\n${body.join('\n')}\n${snippet}\n\n/label: ${labels || 'flaky, test'}\n`;
}

async function runIssue(args) {
  const { summary, flaky, resolvedConfig } = await runAnalyze(args);
  if (!summary) {
    console.log('No data available to generate issues.');
    return;
  }
  const issueConfig = {
    ...(resolvedConfig.issue || {}),
    labels: [...(resolvedConfig.issue?.labels || [])],
    assignees: [...(resolvedConfig.issue?.assignees || [])],
  };
  if (args.repo) issueConfig.repo = args.repo;
  const overrideLabels = parseList(args.labels);
  if (overrideLabels.length) issueConfig.labels = overrideLabels;
  const overrideAssignees = parseList(args.assignees);
  if (overrideAssignees.length) issueConfig.assignees = overrideAssignees;
  if (args.dedupe_by) issueConfig.dedupe_by = args.dedupe_by;
  if (args.enabled !== undefined) issueConfig.enabled = parseBoolean(args.enabled, issueConfig.enabled ?? true);
  if (args.dry_run !== undefined) issueConfig.dry_run = parseBoolean(args.dry_run, issueConfig.dry_run ?? true);
  issueConfig.enabled = parseBoolean(issueConfig.enabled, true);
  issueConfig.dry_run = parseBoolean(issueConfig.dry_run, true);
  if (!issueConfig.enabled) {
    console.log('Issue generation disabled via config/CLI.');
    return;
  }
  const topN = Number.isFinite(Number(args.top_n)) ? Number(args.top_n) : resolvedConfig.output.top_n;
  const entries = flaky.slice(0, topN);
  if (!entries.length) {
    console.log('No flaky tests above threshold.');
    return;
  }

  const dedupeKey = issueConfig.dedupe_by || 'failure_signature';
  const seen = new Set();
  const issuesDir = path.join(resolvedConfig.paths.out, 'issues');
  ensureDir(issuesDir);
  for (const entry of entries) {
    const serialized = serialiseFlakyEntry(entry);
    let key;
    if (dedupeKey === 'canonical_id') key = serialized.canonical_id;
    else {
      const signatures = Object.keys(serialized.failure_signatures || {});
      key = signatures[0] || serialized.canonical_id;
    }
    if (seen.has(key)) continue;
    seen.add(key);
    const markdown = formatIssueMarkdown(serialized, resolvedConfig, issueConfig, summary);
    if (issueConfig.dry_run) {
      const filename = `${serialized.canonical_id.replace(/[^a-z0-9-_]+/gi, '_')}.md`;
      const filePath = path.join(issuesDir, filename);
      fs.writeFileSync(filePath, markdown, 'utf8');
      console.log(`Generated issue draft: ${filePath}`);
    } else {
      console.log('Issue content:');
      console.log(markdown);
    }
  }
}

function describeWeeklyEntry(entry) {
  const failureKinds = entry.failure_top_k || 'N/A';
  const recentRuns = Array.from(new Set((entry.statuses || []).map((s) => s.run_id).filter(Boolean))).slice(-5).reverse();
  const latestFailRun = entry.latest_failure?.run_id ? `, last fail: ${entry.latest_failure.run_id}` : '';
  const latestFailTs = entry.latest_failure?.ts ? ` (${entry.latest_failure.ts})` : '';
  return `- **${entry.canonical_id}** — score ${entry.score?.toFixed?.(2) ?? '0.00'}, attempts ${entry.attempts}, failure kinds: ${failureKinds}${latestFailRun}${latestFailTs}. Recent runs: ${recentRuns.join(', ') || 'N/A'}`;
}

function describeResolvedEntry(entry) {
  const recentRuns = Array.from(new Set((entry.statuses || []).map((s) => s.run_id).filter(Boolean))).slice(-5).reverse();
  const latestFailRun = entry.latest_failure?.run_id ? `last fail: ${entry.latest_failure.run_id}` : 'last fail run unknown';
  const latestFailTs = entry.latest_failure?.ts ? ` (${entry.latest_failure.ts})` : '';
  return `- ~~${entry.canonical_id}~~ — ${latestFailRun}${latestFailTs}. Recent healthy runs: ${recentRuns.join(', ') || 'N/A'}`;
}

function formatWeeklyMarkdown(summary, entries, sinceLabel, newEntries, resolvedEntries, failureKindTotals) {
  const lines = [];
  lines.push(`# Weekly Flaky Summary (${sinceLabel})`);
  lines.push('');
  lines.push(`- Total tracked tests: ${summary.total_tests}`);
  lines.push(`- Flaky above threshold: ${summary.flaky_count}`);
  lines.push(`- Newly detected (window): ${summary.new_flaky_count}`);
  lines.push(`- New flaky this period: ${newEntries.length}`);
  lines.push(`- Resolved this period: ${resolvedEntries.length}`);
  lines.push('');
  if (failureKindTotals && Object.keys(failureKindTotals).length) {
    lines.push('## Failure kind distribution');
    lines.push('');
    for (const [kind, count] of Object.entries(failureKindTotals)) {
      lines.push(`- ${kind}: ${count}`);
    }
    lines.push('');
  }

  lines.push('## Highlights');
  lines.push('');
  lines.push('### New flaky tests');
  lines.push('');
  if (!newEntries.length) {
    lines.push('- None 🎉');
  } else {
    for (const entry of newEntries) {
      lines.push(describeWeeklyEntry(entry));
    }
  }
  lines.push('');
  lines.push('### Resolved flaky tests');
  lines.push('');
  if (!resolvedEntries.length) {
    lines.push('- None recorded this period.');
  } else {
    for (const entry of resolvedEntries) {
      lines.push(describeResolvedEntry(entry));
    }
  }
  lines.push('');
  if (!entries.length) {
    lines.push('No flaky tests met the threshold in this period.');
  } else {
    lines.push('## Top flaky tests (current window)');
    lines.push('');
    for (const entry of entries) {
      lines.push(describeWeeklyEntry(entry));
    }
    lines.push('');
  }
  lines.push(`Generated at ${new Date().toISOString()}`);
  return lines.join('\n');
}

async function runWeekly(args) {
  const configPath = resolveConfigPath(args.config);
  const { config } = loadConfig(configPath);
  const resolvedConfig = resolveConfigPaths(config, process.cwd());
  const windowSize = resolvedConfig.window;
  const { runs, runOrder, runMeta } = await loadWindowRuns(resolvedConfig.paths.store, windowSize);
  if (!runOrder.length) {
    console.log('No run data available for weekly summary.');
    return;
  }
  const { results, failureKindTotals } = computeAggregates(runs, runOrder, resolvedConfig);
  const flaky = determineFlaky(results, resolvedConfig, runOrder);
  const summary = summarise(results, flaky, failureKindTotals, runOrder);
  const topN = Number.isFinite(Number(args.top_n)) ? Number(args.top_n) : resolvedConfig.output.top_n;
  const entries = flaky.slice(0, topN);

  const sinceArg = args.since || '7d';
  const match = /^([0-9]+)d$/u.exec(sinceArg);
  const days = match ? Number(match[1]) : 7;
  const cutoff = Date.now() - days * 86400000;
  const filteredEntries = entries.filter((entry) => {
    const latest = entry.latest_failure?.ts ? Date.parse(entry.latest_failure.ts) : null;
    return latest ? latest >= cutoff : true;
  });

  const newEntries = filteredEntries.filter((entry) => entry.is_new);
  const flakySet = new Set(flaky.map((entry) => entry.canonical_id));
  const resolvedEntries = [];
  const indexTs = runMeta.map((meta) => (meta.ts ? Date.parse(meta.ts) : null));
  for (const entry of results) {
    if (flakySet.has(entry.canonical_id)) continue;
    const statuses = entry.statuses || [];
    let hadFailBefore = false;
    let hadFailAfter = false;
    let executedAfter = false;
    for (const status of statuses) {
      const tsValue = status.ts ? Date.parse(status.ts) : indexTs[status.runIndex] ?? null;
      if (!Number.isFinite(tsValue)) continue;
      if (tsValue >= cutoff) {
        if (status.status === 'fail' || status.status === 'error') hadFailAfter = true;
        if (status.status !== 'skipped') executedAfter = true;
      } else if (status.status === 'fail' || status.status === 'error') {
        hadFailBefore = true;
      }
    }
    const latestFailTs = entry.latest_failure?.ts ? Date.parse(entry.latest_failure.ts) : null;
    if (hadFailBefore && !hadFailAfter && executedAfter && latestFailTs && latestFailTs < cutoff) {
      resolvedEntries.push(entry);
    }
  }
  resolvedEntries.sort((a, b) => {
    const tsA = a.latest_failure?.ts ? Date.parse(a.latest_failure.ts) : 0;
    const tsB = b.latest_failure?.ts ? Date.parse(b.latest_failure.ts) : 0;
    return tsB - tsA;
  });
  const resolvedLimited = resolvedEntries.slice(0, 10);

  const markdown = formatWeeklyMarkdown(
    summary,
    filteredEntries,
    sinceArg,
    newEntries,
    resolvedLimited,
    summary.failure_kind_totals || {},
  );
  const docPath = path.join(process.cwd(), 'projects/03-ci-flaky/docs/weekly-summary.md');
  ensureDir(path.dirname(docPath));
  fs.appendFileSync(docPath, `${markdown}\n\n`, 'utf8');
  console.log(`Weekly summary appended to ${docPath}`);
}

async function main() {
  const [, , command, ...rest] = process.argv;
  const args = parseArgs(rest);

  switch (command) {
    case 'parse':
      await runParse(args);
      break;
    case 'analyze':
      await runAnalyze(args);
      break;
    case 'report':
      if (!args.format && !args.formats) args.format = 'html';
      {
        const { htmlPath } = await runAnalyze({ ...args, top_n: args.top_n ?? undefined });
        if (parseBoolean(args.open, false)) {
          openInBrowser(htmlPath);
        }
      }
      break;
    case 'issue':
      await runIssue(args);
      break;
    case 'weekly':
      await runWeekly(args);
      break;
    default:
      console.log('Usage: flaky <parse|analyze|report|issue|weekly> [options]');
      process.exit(1);
  }
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exit(1);
});
