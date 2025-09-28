import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import {
  loadWindowRuns,
  computeAggregates,
  determineFlaky,
  summarise,
  isFailureStatus,
} from '../analyzer.js';
import { loadConfig, resolveConfigPaths } from '../config.js';
import { ensureDir } from '../fs-utils.js';
import { resolveConfigPath } from './utils.js';

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

export function formatWeeklyMarkdown(summary, entries, sinceLabel, newEntries, resolvedEntries, failureKindTotals) {
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

export async function runWeekly(args) {
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
        if (isFailureStatus(status)) hadFailAfter = true;
        if (status.status !== 'skipped') executedAfter = true;
      } else if (isFailureStatus(status)) {
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
