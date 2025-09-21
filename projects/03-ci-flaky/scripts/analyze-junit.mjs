// analyze-junit.mjs
import fs from 'node:fs';
import path from 'node:path';
import { XMLParser } from 'fast-xml-parser';

// ---- CLI ----
const [, , junitArg, dbArg] = process.argv;
const junitPath = path.resolve(process.cwd(), junitArg || 'junit-results.xml');
const databasePath = path.resolve(process.cwd(), dbArg || 'database.json');

// ---- Guards ----
if (!fs.existsSync(junitPath)) {
  console.warn(`No JUnit report found at ${junitPath}`);
  process.exit(0);
}

// ---- Parse XML ----
const xmlText = fs.readFileSync(junitPath, 'utf8');
const parser = new XMLParser({
  ignoreAttributes: false,
  attributeNamePrefix: '',
  allowBooleanAttributes: true,
});
let root;
try {
  root = parser.parse(xmlText);
} catch (e) {
  console.error('Failed to parse JUnit XML:', e);
  process.exit(1);
}

// ---- Helpers ----
const toArray = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

const collectFromSuite = (suite, out) => {
  if (!suite) return;
  const testcases = toArray(suite.testcase);
  for (const tc of testcases) {
    const classname = tc.classname || 'unknown';
    const name = tc.name || 'unknown';
    const timeMs = tc.time ? Number(tc.time) * 1000 : 0;
    const failed = Boolean(tc.failure || tc.error);

    out.push({
      id: `${classname}::${name}`,
      failed,
      timeMs,
    });
  }
  // nested testsuite(s) fallback
  if (suite.testsuite) {
    for (const s of toArray(suite.testsuite)) collectFromSuite(s, out);
  }
};

const extractTestcases = (doc) => {
  const results = [];
  if (doc.testsuite) collectFromSuite(doc.testsuite, results);
  if (doc.testsuites) {
    const suites = toArray(doc.testsuites.testsuite ?? doc.testsuites);
    for (const s of suites) collectFromSuite(s, results);
  }
  return results;
};

// ---- Extract ----
const testcases = extractTestcases(root);
if (!testcases.length) {
  console.warn('JUnit report did not contain any <testcase> elements.');
  process.exit(0);
}

// ---- DB IO ----
const loadDatabase = () => {
  if (!fs.existsSync(databasePath)) return { history: {} };
  try {
    const raw = JSON.parse(fs.readFileSync(databasePath, 'utf8'));
    if (raw && typeof raw === 'object') return raw;
  } catch (e) {
    console.warn('Failed to read database.json, starting fresh.', e);
  }
  return { history: {} };
};

const summarise = (events) => {
  const totalRuns = events.length;
  const failureCount = events.reduce((acc, e) => acc + (e.failed ? 1 : 0), 0);
  const avgTimeMs = totalRuns
    ? Math.round(events.reduce((s, e) => s + (e.timeMs || 0), 0) / totalRuns)
    : 0;
  return { totalRuns, failureCount, avgTimeMs };
};

// flaky: 直近5回にP/Fが混在 & 直近2回で「F→P」転換
const isFlaky = (events) => {
  if (events.length < 2) return false;
  const recent = events.slice(-5);
  const hasFail = recent.some((e) => e.failed);
  const hasPass = recent.some((e) => !e.failed);
  if (!hasFail || !hasPass) return false;
  const [prev, last] = events.slice(-2);
  return Boolean(prev?.failed && last && !last.failed);
};

// DB後方互換（旧: 配列のみ保存 → 新: {events, stats}）
const ensureRecord = (value) => {
  if (!value) return { events: [], stats: { totalRuns: 0, failureCount: 0, avgTimeMs: 0 } };

  if (Array.isArray(value)) {
    const events = value
      .map((e) => ({ ts: e.ts, failed: e.failed, timeMs: e.timeMs || 0 }))
      .filter((e) => typeof e.ts === 'number');
    return { events, stats: summarise(events) };
  }

  const events = Array.isArray(value.events)
    ? value.events
        .map((e) => ({ ts: e.ts, failed: e.failed, timeMs: e.timeMs || 0 }))
        .filter((e) => typeof e.ts === 'number')
    : [];
  return { events, stats: value.stats || summarise(events) };
};

// ---- Update DB ----
const db = loadDatabase();
if (!db.history || typeof db.history !== 'object') db.history = {};

const timestamp = Date.now();
const maxHistory = 20;
const flakyTests = [];

for (const tc of testcases) {
  const rec = ensureRecord(db.history[tc.id]);
  rec.events.push({ ts: timestamp, failed: tc.failed, timeMs: tc.timeMs });
  rec.events = rec.events.slice(-maxHistory);
  rec.stats = summarise(rec.events);
  db.history[tc.id] = rec;

  if (isFlaky(rec.events)) {
    flakyTests.push({ id: tc.id, stats: rec.stats, events: rec.events });
  }
}

db.updatedAt = new Date(timestamp).toISOString();

fs.writeFileSync(databasePath, JSON.stringify(db, null, 2));

// ---- Report ----
const totalFailed = testcases.filter((t) => t.failed).length;
console.log(`Analyzed ${testcases.length} test cases (failed=${totalFailed}).`);
console.log(`Updated database: ${databasePath}`);

if (flakyTests.length) {
  console.log('Potential flaky tests detected:');
  for (const f of flakyTests) {
    const timeline = f.events.slice(-5).map((e) => (e.failed ? 'F' : 'P')).join(' ');
    console.log(` - ${f.id} (runs=${f.stats.totalRuns}, failures=${f.stats.failureCount}, avgTimeMs=${f.stats.avgTimeMs}) :: ${timeline}`);
  }
} else {
  console.log('No flaky tests detected in the latest run.');
}
