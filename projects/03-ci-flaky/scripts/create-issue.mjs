import fs from 'fs';
import path from 'path';

const [, , dbArg] = process.argv;
const databasePath = path.resolve(process.cwd(), dbArg || 'database.json');

if (!fs.existsSync(databasePath)) {
  console.log(`No database found at ${databasePath}`);
  process.exit(0);
}

const db = JSON.parse(fs.readFileSync(databasePath, 'utf8'));
if (!db.history || typeof db.history !== 'object') {
  console.log('Database does not include any history data.');
  process.exit(0);
}

const isFlaky = (events) => {
  if (!Array.isArray(events) || events.length < 2) {
    return false;
  }
  const recent = events.slice(-5);
  const hasFail = recent.some((event) => event.failed);
  const hasPass = recent.some((event) => !event.failed);
  if (!hasFail || !hasPass) {
    return false;
  }
  const [prev, last] = events.slice(-2);
  return Boolean(prev?.failed && last && !last.failed);
};

const formatTimeline = (events) => {
  return events
    .slice(-10)
    .map((event) => (event.failed ? '❌' : '✅'))
    .join(' ');
};

const flakyEntries = Object.entries(db.history)
  .map(([id, record]) => {
    if (!record) return null;
    const events = Array.isArray(record.events) ? record.events : Array.isArray(record) ? record : [];
    const stats = record.stats || {
      totalRuns: events.length,
      failureCount: events.filter((event) => event.failed).length,
      avgTimeMs: events.length
        ? Math.round(events.reduce((sum, event) => sum + (event.timeMs || 0), 0) / events.length)
        : 0,
    };
    return { id, events, stats };
  })
  .filter(Boolean)
  .filter((entry) => isFlaky(entry.events));

if (!flakyEntries.length) {
  console.log('No flaky tests');
  process.exit(0);
}

let output = `# Flaky tests detected (${flakyEntries.length})\n\n`;
output += 'The following tests recently flipped from fail ➜ pass. Investigate their stability.\n\n';

for (const entry of flakyEntries) {
  const lastFailure = [...entry.events].reverse().find((event) => event.failed);
  const lastPass = [...entry.events].reverse().find((event) => !event.failed);
  const failureRate = entry.stats.totalRuns
    ? ((entry.stats.failureCount / entry.stats.totalRuns) * 100).toFixed(1)
    : '0.0';
  output += `## ${entry.id}\n`;
  output += `- Runs tracked: ${entry.stats.totalRuns}\n`;
  output += `- Failure rate: ${failureRate}%\n`;
  output += `- Avg duration: ${entry.stats.avgTimeMs} ms\n`;
  output += `- Recent runs: ${formatTimeline(entry.events)}\n`;
  if (lastFailure) {
    output += `- Last failure: ${new Date(lastFailure.ts).toISOString()}\n`;
  }
  if (lastPass) {
    output += `- Last success: ${new Date(lastPass.ts).toISOString()}\n`;
  }
  output += '\n';
}

output += `Database: ${databasePath}\n`;
if (db.updatedAt) {
  output += `Updated at: ${db.updatedAt}\n`;
}

console.log(output.trim());
