import { listJsonlFiles, readJsonl } from './fs-utils.js';

function calculateImpact(avgDuration, baseline) {
  if (!avgDuration || !baseline) return 0;
  return Math.min(1, Math.log1p(avgDuration) / Math.log1p(baseline));
}

function calculateRecency(perRunStats, runOrderLength, lambda) {
  let numerator = 0;
  let denom = 0;
  for (const [runIndex, stats] of perRunStats) {
    if (!stats.attempts) continue;
    const age = runOrderLength - 1 - runIndex;
    const weight = Math.exp(-lambda * age);
    const pFail = stats.attempts ? stats.fails / stats.attempts : 0;
    numerator += pFail * weight;
    denom += weight;
  }
  return denom ? numerator / denom : 0;
}

export async function loadWindowRuns(storePath, windowSize) {
  const files = listJsonlFiles(storePath);
  if (!files.includes(storePath)) files.push(storePath);
  const uniqueFiles = [...new Set(files)];

  const runOrder = [];
  const runs = new Map();

  for (const file of uniqueFiles) {
    for await (const record of readJsonl(file)) {
      if (!record || !record.run_id) continue;
      let runEntry = runs.get(record.run_id);
      if (!runEntry) {
        runEntry = { attempts: [], meta: {} };
        runs.set(record.run_id, runEntry);
        runOrder.push(record.run_id);
        while (runOrder.length > windowSize) {
          const removed = runOrder.shift();
          runs.delete(removed);
        }
      }
      if (!runs.has(record.run_id)) continue; // dropped due to window overflow
      runEntry.attempts.push(record);
      if (record.ts && (!runEntry.meta.ts || record.ts > runEntry.meta.ts)) runEntry.meta.ts = record.ts;
      if (record.branch) runEntry.meta.branch = record.branch;
      if (record.commit) runEntry.meta.commit = record.commit;

      // merge CI meta (prefer explicit fields, fallback to ci_meta)
      const ciMeta = record.ci_meta || {};
      const actor = record.actor || ciMeta.actor;
      if (actor) runEntry.meta.actor = actor;
      const workflow = record.workflow || ciMeta.workflow;
      if (workflow) runEntry.meta.workflow = workflow;

      if (record.duration_total_ms) runEntry.meta.duration_total_ms = record.duration_total_ms;
    }
  }

  const runMeta = runOrder.map((runId) => ({
    run_id: runId,
    ...(runs.get(runId)?.meta ?? {}),
  }));

  return { runs, runOrder, runMeta };
}

export function computeAggregates(runs, runOrder, config) {
  const weights = config.weights || {};
  const lambda = config.recency_lambda ?? 0.1;
  const baseline = config.impact_baseline_ms ?? 600000;
  const entries = new Map();
  const failureKindTotals = new Map();

  runOrder.forEach((runId, idx) => {
    const run = runs.get(runId);
    if (!run) return;
    for (const attempt of run.attempts) {
      const key = attempt.canonical_id || `${attempt.suite}.${attempt.class}.${attempt.name}`;
      if (!entries.has(key)) {
        entries.set(key, {
          canonical_id: key,
          suite: attempt.suite,
          class: attempt.class,
          name: attempt.name,
          params: attempt.params ?? null,
          attempts: 0,
          passes: 0,
          fails: 0,
          skipped: 0,
          durationTotal: 0,
          failureKinds: new Map(),
          failureSignatures: new Map(),
          perRun: new Map(),
          statuses: [],
          latestFailure: null,
        });
      }
      const entry = entries.get(key);
      entry.suite = attempt.suite;
      entry.class = attempt.class;
      entry.name = attempt.name;
      entry.params = attempt.params ?? entry.params;

      entry.statuses.push({
        runIndex: idx,
        status: attempt.status,
        run_id: attempt.run_id,
        ts: attempt.ts || null,
      });

      if (attempt.status === 'skipped') {
        entry.skipped += 1;
      } else {
        entry.attempts += 1;
        entry.durationTotal += attempt.duration_ms || 0;
        if (attempt.status === 'pass') entry.passes += 1;
        else if (attempt.status === 'fail' || attempt.status === 'error') entry.fails += 1;
      }

      if (attempt.failure_kind) {
        const current = entry.failureKinds.get(attempt.failure_kind) || 0;
        entry.failureKinds.set(attempt.failure_kind, current + 1);
        failureKindTotals.set(
          attempt.failure_kind,
          (failureKindTotals.get(attempt.failure_kind) || 0) + 1,
        );
      }

      if (attempt.failure_signature) {
        const sig = entry.failureSignatures.get(attempt.failure_signature) || { count: 0, runs: new Set() };
        sig.count += 1;
        if (attempt.run_id) sig.runs.add(attempt.run_id);
        entry.failureSignatures.set(attempt.failure_signature, sig);
      }

      if (attempt.status === 'fail' || attempt.status === 'error') {
        const current = entry.latestFailure;
        if (!current || current.runIndex <= idx) {
          entry.latestFailure = {
            runIndex: idx,
            run_id: attempt.run_id,
            ts: attempt.ts,
            message: attempt.failure_message,
            details: attempt.failure_details,
            excerpt: attempt.failure_excerpt,
            failure_kind: attempt.failure_kind,
            failure_signature: attempt.failure_signature,
          };
        }
      }

      const perRun = entry.perRun.get(idx) || { attempts: 0, fails: 0, passes: 0 };
      if (attempt.status !== 'skipped') {
        perRun.attempts += 1;
        if (attempt.status === 'fail' || attempt.status === 'error') perRun.fails += 1;
        if (attempt.status === 'pass') perRun.passes += 1;
      }
      entry.perRun.set(idx, perRun);
    }
  });

  const results = [];
  for (const entry of entries.values()) {
    const attempts = entry.attempts;
    const fails = entry.fails;
    const passes = entry.passes;
    const pFail = attempts ? fails / attempts : 0;
    const intermittency = attempts ? (2 * Math.min(passes, fails)) / attempts : 0;
    const recency = calculateRecency(entry.perRun, runOrder.length, lambda);
    const avgDuration = attempts ? entry.durationTotal / attempts : 0;
    const impact = calculateImpact(avgDuration, baseline);
    const score = (weights.intermittency ?? 0.5) * intermittency
      + (weights.p_fail ?? 0.3) * pFail
      + (weights.recency ?? 0.15) * recency
      + (weights.impact ?? 0.05) * impact;
    const failureTop = [...entry.failureKinds.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([kind, count]) => `${kind}(${count})`)
      .join('|');
    const trend = runOrder.map((_, idx) => {
      const stats = entry.perRun.get(idx);
      if (!stats || !stats.attempts) return 0;
      return stats.fails / stats.attempts;
    });

    results.push({
      canonical_id: entry.canonical_id,
      suite: entry.suite,
      class: entry.class,
      name: entry.name,
      params: entry.params,
      attempts,
      passes,
      fails,
      skipped: entry.skipped,
      p_fail: pFail,
      intermittency,
      recency,
      impact,
      score,
      avg_duration_ms: Math.round(avgDuration),
      failure_top_k: failureTop,
      trend,
      failure_signatures: entry.failureSignatures,
      failure_kinds: entry.failureKinds,
      statuses: entry.statuses,
      latest_failure: entry.latestFailure,
    });
  }

  return { results, failureKindTotals };
}

export function determineFlaky(results, config, runOrder) {
  const threshold = config.threshold ?? 0.6;
  const newWindow = config.new_flaky_window ?? 5;
  const flaky = [];
  for (const entry of results) {
    if (entry.attempts === 0) continue;
    if (entry.passes === 0 || entry.fails === 0) continue;
    if (entry.score < threshold) continue;
    const failureRuns = entry.statuses
      .filter((status) => status.status === 'fail' || status === 'error' || status.status === 'error')
      .map((status) => status.runIndex);
    const firstFailure = failureRuns.length ? Math.min(...failureRuns) : Number.POSITIVE_INFINITY;
    const isNew = runOrder.length <= newWindow
      ? failureRuns.length > 0
      : firstFailure >= runOrder.length - newWindow;
    flaky.push({ ...entry, is_new: Boolean(isNew) });
  }
  flaky.sort((a, b) => b.score - a.score);
  return flaky;
}

export function summarise(results, flaky, failureKindTotals, runOrder) {
  const totalTests = results.length;
  const mostCommonFailure = [...failureKindTotals.entries()].sort((a, b) => b[1] - a[1])[0];
  const failureKindSummary = Object.fromEntries(
    [...failureKindTotals.entries()].sort((a, b) => b[1] - a[1]),
  );
  return {
    total_tests: totalTests,
    flaky_count: flaky.length,
    new_flaky_count: flaky.filter((item) => item.is_new).length,
    most_common_failure_kind: mostCommonFailure ? mostCommonFailure[0] : null,
    window_runs: runOrder.length,
    failure_kind_totals: failureKindSummary,
  };
}
