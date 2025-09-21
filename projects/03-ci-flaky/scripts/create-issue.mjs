#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

// -------- Helpers --------
const readJson = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));

const getEvents = (record) => {
  if (!record) return [];
  if (Array.isArray(record.events)) return record.events;
  if (Array.isArray(record)) return record; // backward compatibility
  return [];
};

const summarise = (events) => {
  const totalRuns = events.length;
  const failureCount = events.filter((e) => e.failed).length;
  const avgTimeMs = totalRuns
    ? Math.round(events.reduce((s, e) => s + (e.timeMs || 0), 0) / totalRuns)
    : 0;
  return { totalRuns, failureCount, avgTimeMs };
};

// flaky: recent(<=5) にP/F混在 かつ 直近2件が F→P
const isFlaky = (events) => {
  if (!Array.isArray(events) || events.length < 2) return false;
  const recent = events.slice(-5);
  const hasFail = recent.some((e) => e.failed);
  const hasPass = recent.some((e) => !e.failed);
  if (!hasFail || !hasPass) return false;
  const [prev, last] = events.slice(-2);
  return Boolean(prev?.failed && last && !last.failed);
};

const formatTimeline = (events) =>
  events.slice(-10).map((e) => (e.failed ? '❌' : '✅')).join(' ');

// -------- Core --------
export function generateFlakyMarkdown(databasePath) {
  if (!fs.existsSync(databasePath)) {
    return { hasReport: false, message: `No database found at ${databasePath}` };
  }

  let db;
  try {
    db = readJson(databasePath);
  } catch (e) {
    return { hasReport: false, message: `Failed to parse database: ${e?.message || String(e)}` };
  }

  if (!db.history || typeof db.history !== 'object') {
    return { hasReport: false, message: 'Database does not include any history data.' };
  }

  const entries = Object.entries(db.history)
    .map(([id, rec]) => {
      const events = getEvents(rec);
      const stats = rec?.stats || summarise(events);
      return { id, events, stats };
    })
    .filter((e) => e.events.length > 0 && isFlaky(e.events));

  if (!entries.length) {
    return { hasReport: false, message: 'No flaky tests' };
  }

  let md = `# Flaky tests detected (${entries.length})\n\n`;
  md += 'The following tests recently flipped from **fail ➜ pass**. Investigate their stability.\n\n';

  for (const entry of entries) {
    const lastFailure = [...entry.events].reverse().find((ev) => ev.failed);
    const lastPass = [...entry.events].reverse().find((ev) => !ev.failed);
    const failureRate = entry.stats.totalRuns
      ? ((entry.stats.failureCount / entry.stats.totalRuns) * 100).toFixed(1)
      : '0.0';

    md += `## ${entry.id}\n`;
    md += `- Runs tracked: ${entry.stats.totalRuns}\n`;
    md += `- Failure rate: ${failureRate}%\n`;
    md += `- Avg duration: ${entry.stats.avgTimeMs} ms\n`;
    md += `- Recent runs: ${formatTimeline(entry.events)}\n`;
    if (lastFailure) md += `- Last failure: ${new Date(lastFailure.ts).toISOString()}\n`;
    if (lastPass) md += `- Last success: ${new Date(lastPass.ts).toISOString()}\n`;
    md += '\n';
  }

  md += `Database: ${databasePath}\n`;
  if (db.updatedAt) md += `Updated at: ${db.updatedAt}\n`;

  return { hasReport: true, markdown: md.trim() };
}

// -------- CLI --------
const [, , dbArg] = process.argv;
if (import.meta.url === `file://${process.argv[1]}`) {
  const databasePath = path.resolve(process.cwd(), dbArg || 'database.json');
  const result = generateFlakyMarkdown(databasePath);

  if (!result.hasReport) {
    console.log(result.message);
    process.exit(0);
  }

  console.log(result.markdown);
}
