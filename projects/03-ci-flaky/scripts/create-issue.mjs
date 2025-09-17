#!/usr/bin/env node
import fs from 'fs';

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

function detectFlaky(history) {
  const flaky = [];
  for (const [name, records] of Object.entries(history)) {
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

function main() {
  const dbPath = 'database.json';
  const db = loadDatabase(dbPath);
  const flaky = detectFlaky(db.history);
  if (!flaky.length) {
    console.log('No flaky tests');
    process.exit(0);
  }

  const lines = ['# Flaky tests detected', ...flaky.map((name) => `- ${name}`)];
  console.log(lines.join('\n'));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
