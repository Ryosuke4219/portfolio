import fs from 'node:fs';
import path from 'node:path';

import { ensureDir } from '../fs-utils.js';
import { runAnalyze, serialiseFlakyEntry } from './analyze.js';
import { parseBoolean, parseList } from './utils.js';

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

export async function runIssue(args) {
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
