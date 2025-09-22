import fs from 'node:fs';
import path from 'node:path';
import { ensureDir } from './fs-utils.js';

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatCsvValue(value) {
  if (value == null) return '';
  const str = String(value);
  if (/[",\n]/u.test(str)) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

export function writeCsv(filePath, rows, headers) {
  ensureDir(path.dirname(filePath));
  const csv = [headers.join(',')]
    .concat(rows.map((row) => headers.map((header) => formatCsvValue(row[header])).join(',')))
    .join('\n');
  fs.writeFileSync(filePath, `${csv}\n`, 'utf8');
}

export function writeJson(filePath, data) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
}

function formatPercentage(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function buildSparkline(values) {
  if (!values.length) return '';
  const width = 120;
  const height = 40;
  const max = Math.max(0.001, ...values);
  const step = values.length === 1 ? width : width / (values.length - 1);
  const points = values
    .map((v, idx) => {
      const x = idx * step;
      const y = height - (v / max) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" class="spark"><polyline points="${points}" /></svg>`;
}

export function generateHtmlReport(summary, flaky, runMeta) {
  const rows = flaky
    .map((entry, index) => {
      const trend = buildSparkline(entry.trend || []);
      const recentRuns = Array.from(new Set(entry.statuses.map((s) => s.run_id).filter(Boolean))).slice(-5).reverse();
      return `
        <tr>
          <td>${index + 1}</td>
          <td><code>${escapeHtml(entry.canonical_id)}</code>${entry.is_new ? ' <span class="badge">New</span>' : ''}</td>
          <td>${entry.attempts}</td>
          <td>${entry.passes}</td>
          <td>${entry.fails}</td>
          <td>${formatPercentage(entry.p_fail)}</td>
          <td>${entry.intermittency.toFixed(2)}</td>
          <td>${entry.recency.toFixed(2)}</td>
          <td>${entry.impact.toFixed(2)}</td>
          <td>${entry.score.toFixed(2)}</td>
          <td>${entry.avg_duration_ms}</td>
          <td>${escapeHtml(entry.failure_top_k || '')}</td>
          <td>${trend}</td>
          <td>${recentRuns.map((run) => `<span class="run">${escapeHtml(run)}</span>`).join(' ')}</td>
        </tr>`;
    })
    .join('\n');

  const summaryList = [
    `<li>Total Tests: <strong>${summary.total_tests}</strong></li>`,
    `<li>Flaky Tests: <strong>${summary.flaky_count}</strong></li>`,
    `<li>Newly Detected (last ${summary.window_runs} runs window): <strong>${summary.new_flaky_count}</strong></li>`,
    `<li>Most common failure kind: <strong>${summary.most_common_failure_kind ?? 'N/A'}</strong></li>`,
  ].join('\n');

  const runList = runMeta
    .map((meta) => `<li>${escapeHtml(meta.run_id)} — ${meta.ts ? escapeHtml(meta.ts) : 'unknown'}</li>`)
    .join('\n');

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Flaky Analyzer Report</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem; background: #f9fafb; color: #1f2933; }
    h1 { font-size: 1.8rem; margin-bottom: 0.5rem; }
    h2 { margin-top: 2rem; }
    .overview { display: flex; gap: 2rem; flex-wrap: wrap; }
    .card { background: #fff; padding: 1rem 1.5rem; border-radius: 0.75rem; box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08); }
    table { width: 100%; border-collapse: collapse; margin-top: 1.5rem; background: #fff; }
    th, td { padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 0.9rem; vertical-align: middle; }
    th { background: #f1f5f9; position: sticky; top: 0; z-index: 1; }
    tr:hover { background: #f8fafc; }
    code { font-family: 'SFMono-Regular', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; font-size: 0.85rem; }
    .badge { background: #16a34a; color: #fff; padding: 0.2rem 0.4rem; border-radius: 0.4rem; font-size: 0.7rem; margin-left: 0.3rem; }
    .spark { width: 120px; height: 40px; stroke: #3b82f6; stroke-width: 2; fill: none; }
    .run { background: #e2e8f0; border-radius: 0.4rem; padding: 0.1rem 0.4rem; margin: 0 0.1rem; display: inline-block; font-size: 0.75rem; }
    footer { margin-top: 3rem; font-size: 0.85rem; color: #64748b; }
  </style>
</head>
<body>
  <h1>Flaky Analyzer Report</h1>
  <section class="overview">
    <div class="card">
      <h2>Overview</h2>
      <ul>
        ${summaryList}
      </ul>
    </div>
    <div class="card">
      <h2>Runs (latest first)</h2>
      <ol>
        ${runList}
      </ol>
    </div>
  </section>

  <section>
    <h2>Top Flaky Tests</h2>
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Test</th>
          <th>Attempts</th>
          <th>Pass</th>
          <th>Fail</th>
          <th>p_fail</th>
          <th>Intermittency</th>
          <th>Recency</th>
          <th>Impact</th>
          <th>Score</th>
          <th>Avg Dur (ms)</th>
          <th>Failure kinds</th>
          <th>Trend</th>
          <th>Recent runs</th>
        </tr>
      </thead>
      <tbody>
        ${rows}
      </tbody>
    </table>
  </section>
  <footer>Generated on ${escapeHtml(new Date().toISOString())}</footer>
</body>
</html>`;
}
