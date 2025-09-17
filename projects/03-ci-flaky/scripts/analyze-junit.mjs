import fs from 'fs';
import path from 'path';
import { XMLParser } from 'fast-xml-parser';

const [, , junitArg, dbArg] = process.argv;
const junitPath = path.resolve(process.cwd(), junitArg || 'junit-results.xml');
const databasePath = path.resolve(process.cwd(), dbArg || 'database.json');

if (!fs.existsSync(junitPath)) {
  console.warn(`No JUnit report found at ${junitPath}`);
  process.exit(0);
}

const xml = fs.readFileSync(junitPath, 'utf8');
const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '' });
const parsed = parser.parse(xml);

const toArray = (value) => {
  if (!value) return [];
  return Array.isArray(value) ? value : [value];
};

const collectTestcases = (node) => {
  const results = [];
  if (!node) {
    return results;
  }
  const suites = [];
  if (Array.isArray(node)) {
    suites.push(...node);
  } else {
    suites.push(node);
  }

  for (const suite of suites) {
    if (!suite) continue;
    results.push(
      ...toArray(suite.testcase).map((testcase) => {
        const classname = testcase.classname || 'unknown';
        const name = testcase.name || 'unknown';
        const id = `${classname}::${name}`;
        const failed = Boolean(testcase.failure || testcase.error);
        const timeMs = testcase.time ? Number(testcase.time) * 1000 : 0;
        return { id, failed, timeMs };
      }),
    );

    if (suite.testsuite) {
      results.push(...collectTestcases(suite.testsuite));
    }
  }

  return results;
};

let testcases = collectTestcases(parsed.testsuite);
if (parsed.testsuites) {
  testcases = testcases.concat(collectTestcases(parsed.testsuites.testsuite));
}

if (!testcases.length) {
  console.warn('JUnit report did not contain any <testcase> elements.');
  process.exit(0);
}

const loadDatabase = () => {
  if (!fs.existsSync(databasePath)) {
    return { history: {} };
  }
  try {
    const raw = JSON.parse(fs.readFileSync(databasePath, 'utf8'));
    if (raw && typeof raw === 'object') {
      return raw;
    }
  } catch (error) {
    console.warn('Failed to read database.json, starting fresh.', error);
  }
  return { history: {} };
};

const db = loadDatabase();
if (!db.history) {
  db.history = {};
}

const ensureRecord = (value) => {
  if (!value) {
    return { events: [], stats: { totalRuns: 0, failureCount: 0, avgTimeMs: 0 } };
  }
  if (Array.isArray(value)) {
    const events = value.map((entry) => ({ ts: entry.ts, failed: entry.failed, timeMs: entry.timeMs || 0 })).filter((entry) => typeof entry.ts === 'number');
    return {
      events,
      stats: summarise(events),
    };
  }
  const events = Array.isArray(value.events)
    ? value.events.map((entry) => ({ ts: entry.ts, failed: entry.failed, timeMs: entry.timeMs || 0 })).filter((entry) => typeof entry.ts === 'number')
    : [];
  return {
    events,
    stats: value.stats || summarise(events),
  };
};

function summarise(events) {
  const totalRuns = events.length;
  const failureCount = events.filter((event) => event.failed).length;
  const avgTimeMs = totalRuns ? Math.round(events.reduce((sum, event) => sum + (event.timeMs || 0), 0) / totalRuns) : 0;
  return { totalRuns, failureCount, avgTimeMs };
}

const isFlaky = (events) => {
  if (events.length < 2) {
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

const timestamp = Date.now();
const maxHistory = 20;
const flakyTests = [];

for (const testcase of testcases) {
  const record = ensureRecord(db.history[testcase.id]);
  record.events.push({ ts: timestamp, failed: testcase.failed, timeMs: testcase.timeMs });
  record.events = record.events.slice(-maxHistory);
  record.stats = summarise(record.events);
  db.history[testcase.id] = record;
  if (isFlaky(record.events)) {
    flakyTests.push({ id: testcase.id, stats: record.stats, events: record.events });
  }
}

db.updatedAt = new Date(timestamp).toISOString();

fs.writeFileSync(databasePath, JSON.stringify(db, null, 2));

console.log(`Analyzed ${testcases.length} test cases.`);
console.log(`Updated database: ${databasePath}`);
if (flakyTests.length) {
  console.log('Potential flaky tests detected:');
  for (const flaky of flakyTests) {
    const timeline = flaky.events.slice(-5).map((event) => (event.failed ? 'F' : 'P')).join(' ');
    console.log(` - ${flaky.id} (runs=${flaky.stats.totalRuns}, failures=${flaky.stats.failureCount}) :: ${timeline}`);
  }
} else {
  console.log('No flaky tests detected in the latest run.');
}
