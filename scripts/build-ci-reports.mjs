#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { XMLParser } from '../packages/fast-xml-parser/index.js';

const rootDir = process.cwd();
const junitInputPath = path.resolve(rootDir, 'junit-results.xml');
const flakyOutputDir = path.resolve(rootDir, 'projects/03-ci-flaky/out');
const coverageHtmlDir = path.resolve(rootDir, 'projects/04-llm-adapter-shadow/htmlcov');
const coverageXmlPath = path.resolve(rootDir, 'projects/04-llm-adapter-shadow/coverage.xml');
const reportsDir = path.resolve(rootDir, 'reports');

function ensureCleanDir(target) {
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(target, { recursive: true });
}

function toArray(value) {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function extractText(node) {
  if (node == null) return '';
  if (typeof node === 'string') return node;
  if (typeof node === 'number' || typeof node === 'boolean') return String(node);
  if (Array.isArray(node)) return node.map(extractText).filter(Boolean).join('\n');
  if (typeof node === 'object') {
    const text = [];
    if (typeof node['#text'] === 'string') text.push(node['#text']);
    for (const value of Object.values(node)) {
      if (typeof value === 'object' || Array.isArray(value)) {
        text.push(extractText(value));
      }
    }
    return text.filter(Boolean).join('\n');
  }
  return '';
}

function summariseJUnit(inputPath, outputDir) {
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_', textNodeName: '#text' });
  const xml = fs.readFileSync(inputPath, 'utf8');
  const parsed = parser.parse(xml) ?? {};

  const suiteNodes = [];
  if (parsed.testsuite) suiteNodes.push(parsed.testsuite);
  if (parsed.testsuites) {
    const suites = parsed.testsuites.testsuite ?? parsed.testsuites;
    suiteNodes.push(...toArray(suites));
  }

  const tests = [];
  for (const suite of suiteNodes) {
    if (!suite) continue;
    const suiteName = suite['@_name'] ?? suite.name ?? 'Suite';
    const cases = toArray(suite.testcase);
    for (const testCase of cases) {
      if (!testCase) continue;
      const className = testCase['@_classname'] ?? suiteName;
      const name = testCase['@_name'] ?? 'Unnamed test';
      const timeSeconds = Number.parseFloat(testCase['@_time'] ?? '0') || 0;
      let status = 'passed';
      let detail = '';
      if (testCase.failure !== undefined) {
        status = 'failed';
        detail = extractText(testCase.failure);
      } else if (testCase.error !== undefined) {
        status = 'error';
        detail = extractText(testCase.error);
      } else if (testCase.skipped !== undefined) {
        status = 'skipped';
        detail = extractText(testCase.skipped);
      }
      tests.push({ suite: suiteName, className, name, status, timeSeconds, detail });
    }
  }

  const summary = {
    suites: suiteNodes.length,
    tests: tests.length,
    failures: tests.filter((item) => item.status === 'failed').length,
    errors: tests.filter((item) => item.status === 'error').length,
    skipped: tests.filter((item) => item.status === 'skipped').length,
    passed: tests.filter((item) => item.status === 'passed').length,
    duration_seconds: Number.parseFloat(
      tests.reduce((total, item) => total + item.timeSeconds, 0).toFixed(3),
    ),
    generated_at: new Date().toISOString(),
  };

  fs.mkdirSync(outputDir, { recursive: true });
  fs.copyFileSync(inputPath, path.join(outputDir, 'junit-results.xml'));
  fs.writeFileSync(path.join(outputDir, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`, 'utf8');

  const rows = tests
    .map((test) => {
      const durationMs = Math.round(test.timeSeconds * 1000);
      const detail = test.detail ? `<pre>${escapeHtml(test.detail)}</pre>` : '';
      return `        <tr class="status-${test.status}">\n          <td>${escapeHtml(test.suite)}</td>\n          <td>${escapeHtml(test.className)}</td>\n          <td>${escapeHtml(test.name)}</td>\n          <td>${escapeHtml(test.status)}</td>\n          <td class="numeric">${durationMs}</td>\n          <td>${detail}</td>\n        </tr>`;
    })
    .join('\n');

  const html = `<!DOCTYPE html>\n<html lang="ja">\n  <head>\n    <meta charset="utf-8" />\n    <title>JUnit Summary</title>\n    <style>\n      body {\n        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;\n        margin: 2rem;\n        color: #1f2933;\n        background: #f8fafc;\n      }\n      h1 {\n        margin-bottom: 0.5rem;\n      }\n      .summary {\n        display: grid;\n        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));\n        gap: 0.75rem;\n        margin-bottom: 2rem;\n      }\n      .metric {\n        background: #fff;\n        border-radius: 0.75rem;\n        padding: 1rem;\n        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);\n      }\n      .metric__label {\n        font-size: 0.75rem;\n        text-transform: uppercase;\n        letter-spacing: 0.08em;\n        color: #64748b;\n        margin-bottom: 0.25rem;\n      }\n      .metric__value {\n        font-size: 1.75rem;\n        font-weight: 600;\n      }\n      table {\n        width: 100%;\n        border-collapse: collapse;\n        background: #fff;\n        border-radius: 0.75rem;\n        overflow: hidden;\n        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);\n      }\n      thead {\n        background: #0f172a;\n        color: #f8fafc;\n      }\n      th, td {\n        padding: 0.75rem 1rem;\n        text-align: left;\n        vertical-align: top;\n      }\n      tr:nth-child(even) {\n        background: #f1f5f9;\n      }\n      tr:hover {\n        background: #e2e8f0;\n      }\n      .status-passed { color: #0f766e; }\n      .status-failed { color: #b91c1c; }\n      .status-error { color: #b45309; }\n      .status-skipped { color: #475569; }\n      pre {\n        margin: 0;\n        white-space: pre-wrap;\n        word-break: break-word;\n        font-family: ui-monospace, SFMono-Regular, SFMono, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;\n        font-size: 0.75rem;\n        color: #334155;\n        background: #e2e8f0;\n        padding: 0.5rem;\n        border-radius: 0.5rem;\n      }\n      .numeric { text-align: right; }\n      .meta {\n        color: #475569;\n        margin-top: 1rem;\n        font-size: 0.85rem;\n      }\n    </style>\n  </head>\n  <body>\n    <h1>JUnit Summary</h1>\n    <p class="meta">生成日時: ${escapeHtml(summary.generated_at)} / 実行時間合計: ${summary.duration_seconds.toFixed(3)} 秒</p>\n    <section class="summary">\n      <div class="metric"><p class="metric__label">Total</p><p class="metric__value">${summary.tests}</p></div>\n      <div class="metric"><p class="metric__label">Passed</p><p class="metric__value">${summary.passed}</p></div>\n      <div class="metric"><p class="metric__label">Failed</p><p class="metric__value">${summary.failures}</p></div>\n      <div class="metric"><p class="metric__label">Errors</p><p class="metric__value">${summary.errors}</p></div>\n      <div class="metric"><p class="metric__label">Skipped</p><p class="metric__value">${summary.skipped}</p></div>\n      <div class="metric"><p class="metric__label">Suites</p><p class="metric__value">${summary.suites}</p></div>\n    </section>\n    <table>\n      <thead>\n        <tr>\n          <th>Suite</th>\n          <th>Class</th>\n          <th>Name</th>\n          <th>Status</th>\n          <th class="numeric">Duration (ms)</th>\n          <th>Details</th>\n        </tr>\n      </thead>\n      <tbody>\n${rows || '        <tr><td colspan="6">No testcases found.</td></tr>'}\n      </tbody>\n    </table>\n  </body>\n</html>\n`;

  fs.writeFileSync(path.join(outputDir, 'index.html'), html, 'utf8');
  return summary;
}

function hasDirectoryContent(target) {
  if (!fs.existsSync(target)) return false;
  const entries = fs.readdirSync(target);
  return entries.length > 0;
}

function summariseCoverage(xmlPath) {
  if (!fs.existsSync(xmlPath)) return null;
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_', textNodeName: '#text' });
  const xml = fs.readFileSync(xmlPath, 'utf8');
  const parsed = parser.parse(xml) ?? {};
  const coverage = parsed.coverage ?? {};
  const toNumber = (value) => {
    const num = Number.parseFloat(value ?? '0');
    return Number.isFinite(num) ? num : 0;
  };
  return {
    line_rate: toNumber(coverage['@_line-rate']) * 100,
    branch_rate: toNumber(coverage['@_branch-rate']) * 100,
    lines_valid: toNumber(coverage['@_lines-valid']),
    lines_covered: toNumber(coverage['@_lines-covered']),
    branches_valid: toNumber(coverage['@_branches-valid']),
    branches_covered: toNumber(coverage['@_branches-covered']),
    timestamp: coverage['@_timestamp'] ?? new Date().toISOString(),
  };
}

function renderIndex(targetDir, sections) {
  const cards = sections
    .map((section) => {
      const description =
        section.id === 'junit'
          ? `テスト件数 ${section.meta.tests} 件 / 成功 ${section.meta.passed} 件`
          : section.id === 'coverage' && section.meta
            ? `ライン網羅率 ${section.meta.line_rate.toFixed(1)}%`
            : section.id === 'flaky'
              ? 'flaky スコアの HTML レポート'
              : '';
      return `      <article class="card">\n        <h2><a href="${escapeHtml(section.href)}">${escapeHtml(section.title)}</a></h2>\n        <p>${escapeHtml(description)}</p>\n      </article>`;
    })
    .join('\n');

  const html = `<!DOCTYPE html>\n<html lang="ja">\n  <head>\n    <meta charset="utf-8" />\n    <title>CI Reports</title>\n    <style>\n      body {\n        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;\n        margin: 2rem;\n        color: #0f172a;\n        background: #f8fafc;\n      }\n      h1 {\n        margin-bottom: 0.5rem;\n      }\n      p.lead {\n        color: #475569;\n        margin-bottom: 2rem;\n      }\n      .cards {\n        display: grid;\n        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));\n        gap: 1rem;\n      }\n      .card {\n        background: #fff;\n        border-radius: 0.75rem;\n        padding: 1.25rem;\n        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.12);\n      }\n      .card h2 {\n        margin-top: 0;\n        margin-bottom: 0.5rem;\n        font-size: 1.1rem;\n      }\n      .card a {\n        color: #2563eb;\n        text-decoration: none;\n      }\n      .card a:hover {\n        text-decoration: underline;\n      }\n    </style>\n  </head>\n  <body>\n    <h1>CI Reports</h1>\n    <p class="lead">Playwright E2E / flaky 解析 / Python カバレッジの最新 CI レポート。</p>\n    <section class="cards">\n${cards || '      <p>レポートはまだ生成されていません。</p>'}\n    </section>\n  </body>\n</html>\n`;

  fs.writeFileSync(path.join(targetDir, 'index.html'), html, 'utf8');
}

function main() {
  ensureCleanDir(reportsDir);
  const sections = [];

  if (fs.existsSync(junitInputPath)) {
    const junitSummary = summariseJUnit(junitInputPath, path.join(reportsDir, 'junit'));
    sections.push({ id: 'junit', title: 'JUnit Summary', href: 'junit/index.html', meta: junitSummary });
  }

  if (hasDirectoryContent(flakyOutputDir)) {
    const target = path.join(reportsDir, 'flaky');
    fs.mkdirSync(target, { recursive: true });
    fs.cpSync(flakyOutputDir, target, { recursive: true });
    sections.push({ id: 'flaky', title: 'Flaky Ranking', href: 'flaky/index.html' });
  }

  if (hasDirectoryContent(coverageHtmlDir)) {
    const target = path.join(reportsDir, 'coverage');
    fs.mkdirSync(target, { recursive: true });
    fs.cpSync(coverageHtmlDir, target, { recursive: true });
    const coverageSummary = summariseCoverage(coverageXmlPath);
    if (coverageSummary) {
      fs.writeFileSync(
        path.join(target, 'summary.json'),
        `${JSON.stringify({ ...coverageSummary, generated_at: new Date().toISOString() }, null, 2)}\n`,
        'utf8',
      );
    }
    sections.push({ id: 'coverage', title: 'Coverage HTML', href: 'coverage/index.html', meta: coverageSummary });
  }

  renderIndex(reportsDir, sections);
}

main();
