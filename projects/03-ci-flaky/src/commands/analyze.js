import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { loadWindowRuns, computeAggregates, determineFlaky, summarise } from '../analyzer.js';
import { loadConfig, resolveConfigPaths } from '../config.js';
import { ensureDir } from '../fs-utils.js';
import { writeCsv, writeJson, generateHtmlReport } from '../report.js';
import { determineFormats, resolveConfigPath } from './utils.js';

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

export function serialiseFlakyEntry(entry) {
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

export async function runAnalyze(args) {
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

  ensureDir(resolvedConfig.paths.out);

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
