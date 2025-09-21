#!/usr/bin/env node
// analyze-junit.mjs
import fs from 'node:fs';
import path from 'node:path';
import { XMLParser } from 'fast-xml-parser';

// ---- Utils ----
const toArray = (v) => (v == null ? [] : Array.isArray(v) ? v : [v]);

const collectFromSuite = (suite, out) => {
  if (!suite) return;
  const testcases = toArray(suite.testcase);
  for (const tc of testcases) {
    const classname = tc.classname || 'unknown';
    const name = tc.name || 'unknown';
    const timeMs = tc.time ? Number(tc.time) * 1000 : 0;
    const failed = Boolean(tc.failure || tc.error);
    const id = `${classname}::${name}`;
    out.push({
      id,               // main系のID
      name: id,         // codex互換（name）
      failed,
      timeMs,
    });
  }
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

const summarise = (events) => {
  const totalRuns = events.length;
  const failureCount = events.reduce((acc, e) => acc + (e.failed ? 1 : 0), 0);
  const avgTimeMs = totalRuns
    ? Math.round(events.reduce((s, e) => s + (e.timeMs || 0), 0) / totalRuns)
    : 0;
  return { totalRuns, failureCount, avgTimeMs };
};

// flaky判定：直近5件にP/F混在 かつ 直近2件が F→P（main準拠）
const isFlaky = (events) => {
  if (events.length < 2) return false;
  const recent = events.slice(-5);
  const hasFail = recent.some((e) => e.failed);
  const hasPass = recent.some((e) => !e.failed);
  if (!hasFail || !hasPass) return false;
  const [prev, last] = events.slice(-2);
  return Boolean(prev?.failed && last && !last.failed);
};

const ensureRecord = (value) => {
  if (!value) return { events: [], stats: { totalRuns: 0, failureCount: 0, avgTimeMs: 0 } };

  if (Array.isArray(value)) {
    const events = value
      .map((e) => ({ ts: e.ts, failed: e.failed, timeMs: e.timeMs || 0 }))
      .filter((e) => typeof e.ts === 'number');
    return { events, stats: summarise(events) };
  }
  const events = Array.isArray(value.events)
    ? value.events.map((e) => ({ ts: e.ts, failed: e.failed, timeMs: e.timeMs || 0 }))
      .filter((e) => typeof e.ts === 'number')
    : [];
  return { events, stats: value.stats || summarise(events) };
};

const loadDatabase = (databasePath) => {
  if (!fs.existsSync(databasePath)) return { history: {} };
  try {
    const raw = JSON.parse(fs.readFileSync(databasePath, 'utf8'));
    if (raw && typeof raw === 'object') return raw;
  } catch {
    // start fresh
  }
  return { history: {} };
};

// ---- Exported API (codex互換) ----
export function analyzeJUnitReport(junitPathArg, databasePathArg = 'database.json') {
  const junitPath = path.resolve(process.cwd(), junitPathArg);
  const databasePath = path.resolve(process.cwd(), databasePathArg);

  if (!fs.existsSync(junitPath)) {
    return { cases: [], flaky: [], databasePath };
  }

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
    throw new Error(`Failed to parse JUnit XML: ${e?.message || String(e)}`);
  }

  const cases = extractTestcases(root);
  const db = loadDatabase(databasePath);

  if (!db.history || typeof db.history !== 'object') db.history = {};
  const timestamp = Date.now();
  const maxHistory = 20;

  for (const tc of cases) {
    const rec = ensureRecord(db.history[tc.id] || db.history[tc.name]); // nameでも拾う
    rec.events.push({ ts: timestamp, failed: tc.failed, timeMs: tc.timeMs });
    rec.events = rec.events.slice(-maxHistory);
    rec.stats = summarise(rec.events);
    db.history[tc.id] = rec;
  }

  db.updatedAt = new Date(timestamp).toISOString();
  fs.writeFileSync(databasePath, JSON.stringify(db, null, 2));

  const flaky = Object.entries(db.history)
    .filter(([, rec]) => isFlaky(rec.events))
    .map(([id]) => id);

  return { cases, flaky, databasePath };
}

// ---- CLI ----
const [, , junitArg, dbArg] = process.argv;

if (import.meta.url === `file://${process.argv[1]}`) {
  const junitPath = path.resolve(process.cwd(), junitArg || 'junit-results.xml');
  const databasePath = path.resolve(process.cwd(), dbArg || 'database.json');

  if (!fs.existsSync(junitPath)) {
    console.warn(`No JUnit report found at ${junitPath}`);
    process.exit(0);
  }

  let result;
  try {
    result = analyzeJUnitReport(junitPath, databasePath);
  } catch (e) {
    console.error(e?.message || String(e));
    process.exit(1);
  }

  const totalFailed = result.cases.filter((t) => t.failed).length;
  console.log(`Analyzed ${result.cases.length} test cases (failed=${totalFailed}).`);
  console.log(`Updated database: ${result.databasePath}`);
  if (result.flaky.length) {
    console.log('Potential flaky tests detected:');
    for (const id of result.flaky) console.log(` - ${id}`);
  } else {
    console.log('No flaky tests detected in the latest run.');
  }
}
