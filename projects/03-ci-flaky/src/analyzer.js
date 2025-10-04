import { listJsonlFiles, readJsonl } from './fs-utils.js';

const FAILURE_STATUSES = new Set(['fail', 'error', 'errored', 'failure']);

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

export function isFailureStatus(status) {
  const value = typeof status === 'string' ? status : status?.status;
  if (!value) return false;
  return FAILURE_STATUSES.has(value.toLowerCase());
}

class AggregatedEntry {
  constructor(key) {
    this.canonical_id = key;
    this.suite = null;
    this.class = null;
    this.name = null;
    this.params = null;
    this.attempts = 0;
    this.passes = 0;
    this.fails = 0;
    this.skipped = 0;
    this.durationTotal = 0;
    this.failureKinds = new Map();
    this.failureSignatures = new Map();
    this.perRun = new Map();
    this.statuses = [];
    this.latestFailure = null;
  }

  addAttempt(attempt, runIndex) {
    this.suite = attempt.suite;
    this.class = attempt.class;
    this.name = attempt.name;
    if (attempt.params !== undefined && attempt.params !== null) this.params = attempt.params;

    this.statuses.push({
      runIndex,
      status: attempt.status,
      run_id: attempt.run_id,
      ts: attempt.ts ?? null,
    });

    if (attempt.status === 'skipped') {
      this.skipped += 1;
      return;
    }

    this.attempts += 1;
    this.durationTotal += attempt.duration_ms || 0;
    if (attempt.status === 'pass') this.passes += 1;
    else if (isFailureStatus(attempt)) this.fails += 1;

    if (attempt.failure_kind) {
      const next = (this.failureKinds.get(attempt.failure_kind) || 0) + 1;
      this.failureKinds.set(attempt.failure_kind, next);
    }

    if (attempt.failure_signature) {
      const sig = this.failureSignatures.get(attempt.failure_signature) || { count: 0, runs: new Set() };
      sig.count += 1;
      if (attempt.run_id) sig.runs.add(attempt.run_id);
      this.failureSignatures.set(attempt.failure_signature, sig);
    }

    if (isFailureStatus(attempt)) {
      const current = this.latestFailure;
      if (!current || current.runIndex <= runIndex) {
        this.latestFailure = {
          runIndex,
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

    const perRun = this.perRun.get(runIndex) || { attempts: 0, fails: 0, passes: 0 };
    perRun.attempts += 1;
    if (isFailureStatus(attempt)) perRun.fails += 1;
    if (attempt.status === 'pass') perRun.passes += 1;
    this.perRun.set(runIndex, perRun);
  }

  toResult(runOrder, weights, baseline, lambda) {
    const attempts = this.attempts;
    const fails = this.fails;
    const passes = this.passes;
    const pFail = attempts ? fails / attempts : 0;
    const intermittency = attempts ? (2 * Math.min(passes, fails)) / attempts : 0;
    const recency = calculateRecency(this.perRun, runOrder.length, lambda);
    const avgDuration = attempts ? this.durationTotal / attempts : 0;
    const impact = calculateImpact(avgDuration, baseline);
    const score = (weights.intermittency ?? 0.5) * intermittency
      + (weights.p_fail ?? 0.3) * pFail
      + (weights.recency ?? 0.15) * recency
      + (weights.impact ?? 0.05) * impact;
    const failureTop = [...this.failureKinds.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([kind, count]) => `${kind}(${count})`)
      .join('|');
    const trend = runOrder.map((_, idx) => {
      const stats = this.perRun.get(idx);
      if (!stats || !stats.attempts) return 0;
      return stats.fails / stats.attempts;
    });

    return {
      canonical_id: this.canonical_id,
      suite: this.suite,
      class: this.class,
      name: this.name,
      params: this.params,
      attempts,
      passes,
      fails,
      skipped: this.skipped,
      p_fail: pFail,
      intermittency,
      recency,
      impact,
      score,
      avg_duration_ms: Math.round(avgDuration),
      failure_top_k: failureTop,
      trend,
      failure_signatures: this.failureSignatures,
      failure_kinds: this.failureKinds,
      statuses: this.statuses,
      latest_failure: this.latestFailure,
    };
  }
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

  runOrder.forEach((runId, idx) => {
    const run = runs.get(runId);
    if (!run) return;
    for (const attempt of run.attempts) {
      const key = attempt.canonical_id || `${attempt.suite}.${attempt.class}.${attempt.name}`;
      let entry = entries.get(key);
      if (!entry) {
        entry = new AggregatedEntry(key);
        entries.set(key, entry);
      }
      entry.addAttempt(attempt, idx);
    }
  });

  const results = [];
  const failureKindTotals = new Map();
  for (const entry of entries.values()) {
    const result = entry.toResult(runOrder, weights, baseline, lambda);
    results.push(result);
    for (const [kind, count] of entry.failureKinds.entries()) {
      failureKindTotals.set(kind, (failureKindTotals.get(kind) || 0) + count);
    }
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
      .filter((status) => isFailureStatus(status))
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
