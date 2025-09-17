#!/usr/bin/env node
import fs from 'fs';

function readXml(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch (error) {
    return null;
  }
}

function parseAttributes(segment) {
  const attributes = {};
  const regex = /(\w+)=("([^"]*)"|'([^']*)')/g;
  let match;
  while ((match = regex.exec(segment))) {
    attributes[match[1]] = match[3] ?? match[4] ?? '';
  }
  return attributes;
}

function collectTestCases(xml) {
  const cases = [];
  if (!xml) {
    return cases;
  }

  const pattern = /<testcase\b([^>]*?)(?:\/>|>([\s\S]*?)<\/testcase>)/g;
  let match;
  while ((match = pattern.exec(xml))) {
    const attrs = parseAttributes(match[1] || '');
    const body = match[2] || '';
    const hasFailure = /<(failure|error)\b/i.test(body);
    const classname = attrs.classname ? `${attrs.classname}::` : '';
    const name = attrs.name || 'unknown';
    cases.push({
      name: `${classname}${name}`,
      failed: hasFailure,
    });
  }
  return cases;
}

function loadDatabase(filePath) {
  if (!fs.existsSync(filePath)) {
    return { history: {} };
  }
  try {
    const raw = fs.readFileSync(filePath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || typeof parsed.history !== 'object') {
      return { history: {} };
    }
    return parsed;
  } catch (error) {
    return { history: {} };
  }
}

function saveDatabase(filePath, db) {
  const json = `${JSON.stringify(db, null, 2)}\n`;
  fs.writeFileSync(filePath, json, 'utf8');
}

function detectFlaky(history) {
  const entries = Object.entries(history);
  const flaky = [];
  for (const [name, records] of entries) {
    if (!Array.isArray(records)) {
      continue;
    }
    const lastTwo = records.slice(-2);
    if (lastTwo.length === 2 && lastTwo[0]?.failed && lastTwo[1] && lastTwo[1].failed === false) {
      flaky.push(name);
    }
  }
  return flaky;
}

export function analyzeJUnitReport(junitPath, databasePath = 'database.json') {
  if (!fs.existsSync(junitPath)) {
    return { cases: [], flaky: [], databasePath };
  }

  const xml = readXml(junitPath);
  if (!xml) {
    throw new Error(`Failed to read ${junitPath}`);
  }

  const cases = collectTestCases(xml);
  const db = loadDatabase(databasePath);

  for (const testCase of cases) {
    const history = Array.isArray(db.history[testCase.name]) ? db.history[testCase.name] : [];
    history.push({ ts: Date.now(), failed: testCase.failed });
    db.history[testCase.name] = history.slice(-10);
  }

  saveDatabase(databasePath, db);

  const flaky = detectFlaky(db.history);
  return { cases, flaky, databasePath };
}

function main(argv) {
  const [, , inputArg] = argv;
  const junitPath = inputArg || 'junit-results.xml';
  if (!fs.existsSync(junitPath)) {
    console.warn('No junit-results.xml');
    process.exit(0);
  }

  let result;
  try {
    result = analyzeJUnitReport(junitPath);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }

  console.log('Analyzed cases:', result.cases.length);
  console.log('Flaky detected:', result.flaky.length);
  if (result.flaky.length) {
    console.log(result.flaky.join('\n'));
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main(process.argv);
}
