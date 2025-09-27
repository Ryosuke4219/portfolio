import fs from 'node:fs';
import path from 'node:path';

import { createJUnitStreamParser } from './junit/stream-parser.js';
import { classifyFailureByMessage, createFailureSignature, applyTimeoutClassification } from './classification.js';

function buildSuiteName(stack) {
  const names = stack.map((entry) => entry.fullName).filter(Boolean);
  if (names.length === 0) return 'unknown-suite';
  return names[names.length - 1];
}

function buildClassName(testcaseAttrs, suiteStack) {
  if (testcaseAttrs.classname) return testcaseAttrs.classname;
  if (testcaseAttrs.class) return testcaseAttrs.class;
  const suiteAttr = suiteStack.length ? suiteStack[suiteStack.length - 1].attrs : {};
  if (suiteAttr?.classname) return suiteAttr.classname;
  if (suiteAttr?.package) return suiteAttr.package;
  if (testcaseAttrs.file) return path.basename(testcaseAttrs.file).replace(/\.\w+$/u, '');
  return 'unknown-class';
}

function buildCanonicalId({ suite, className, testName, params }) {
  const safeSuite = suite || 'suite';
  const safeClass = className || 'class';
  const safeName = testName || 'test';
  if (params && !/\[.*\]$/u.test(safeName)) {
    return `${safeSuite}.${safeClass}.${safeName}[${params}]`;
  }
  return `${safeSuite}.${safeClass}.${safeName}`;
}

function decodeEntities(text) {
  if (!text || !text.includes('&')) return text || '';
  const entities = {
    amp: '&',
    lt: '<',
    gt: '>',
    quot: '"',
    apos: "'",
  };
  return text.replace(/&([^;]+);/g, (match, entity) => {
    if (Object.prototype.hasOwnProperty.call(entities, entity)) {
      return entities[entity];
    }
    if (entity.startsWith('#x') || entity.startsWith('#X')) {
      const code = Number.parseInt(entity.slice(2), 16);
      return Number.isNaN(code) ? match : String.fromCodePoint(code);
    }
    if (entity.startsWith('#')) {
      const code = Number.parseInt(entity.slice(1), 10);
      return Number.isNaN(code) ? match : String.fromCodePoint(code);
    }
    return match;
  });
}

function normaliseText(node) {
  if (!node) return node;
  const text = decodeEntities(node.text || '').trim();
  return { ...node, text };
}

function mapOutput(nodes) {
  return nodes
    .map((item) => decodeEntities(item.text || '').trim())
    .filter(Boolean);
}

function finaliseTestcase(node, suiteStack, suiteDurations) {
  const suiteName = buildSuiteName(suiteStack);
  const className = buildClassName(node.attrs, suiteStack);
  const params = node.attrs.parameters || node.attrs.params || node.attrs.param || null;
  const testName = node.attrs.name || node.attrs.id || 'unknown-test';
  const canonicalId = buildCanonicalId({ suite: suiteName, className, testName, params });
  const durationMs = node.attrs.time ? Number(node.attrs.time) * 1000 : 0;
  const status = node.skipped
    ? 'skipped'
    : node.errors.length
      ? 'error'
      : node.failures.length
        ? 'fail'
        : 'pass';

  if (!suiteDurations.has(suiteName)) suiteDurations.set(suiteName, []);
  if (status !== 'skipped') suiteDurations.get(suiteName).push(durationMs);

  const failureNodes = status === 'fail' ? node.failures : status === 'error' ? node.errors : [];
  let failureMessage = null;
  let failureDetails = null;
  if (failureNodes.length) {
    const texts = [];
    const messages = [];
    for (const failure of failureNodes) {
      const normalised = normaliseText(failure);
      const message = normalised.attrs.message || normalised.attrs.type || '';
      if (message) messages.push(message);
      if (normalised.text) texts.push(normalised.text);
    }
    failureMessage = messages.join(' | ') || null;
    failureDetails = texts.join('\n\n') || null;
  }

  const signature = createFailureSignature(failureMessage, failureDetails);
  const failureKind = failureNodes.length
    ? classifyFailureByMessage(failureMessage, failureDetails) || 'nondeterministic'
    : null;

  return {
    suite: suiteName,
    class: className,
    name: testName,
    params: params || null,
    canonical_id: canonicalId,
    status,
    duration_ms: Number.isFinite(durationMs) ? Math.round(durationMs) : 0,
    failure_kind: failureKind,
    failure_signature: signature,
    failure_message: failureMessage,
    failure_details: failureDetails,
    system_out: mapOutput(node.systemOut),
    system_err: mapOutput(node.systemErr),
    retries: Number.parseInt(node.attrs.retries ?? node.attrs.retry ?? node.attrs.rerun ?? '0', 10) || 0,
  };
}

export async function parseJUnitStream(readable, options = {}) {
  const {
    onTestcase,
    filename = '<stdin>',
  } = options;

  const attempts = [];
  const suiteDurations = new Map();

  const parser = createJUnitStreamParser({
    filename,
    onTestcase: ({ node, suiteStack }) => {
      const testcaseNode = {
        ...node,
        failures: node.failures.map(normaliseText),
        errors: node.errors.map(normaliseText),
        skipped: normaliseText(node.skipped),
        systemOut: node.systemOut.map(normaliseText),
        systemErr: node.systemErr.map(normaliseText),
      };
      const attempt = finaliseTestcase(testcaseNode, suiteStack, suiteDurations);
      attempts.push(attempt);
      if (typeof onTestcase === 'function') onTestcase(attempt);
    },
  });

  for await (const chunk of readable) {
    parser.consume(chunk);
  }

  parser.finish();

  applyTimeoutClassification(attempts, suiteDurations, options.timeoutFactor ?? 3.0);

  return { attempts, suiteDurations };
}

export async function parseJUnitFile(filePath, options = {}) {
  const stream = fs.createReadStream(filePath, { encoding: 'utf8' });
  try {
    return await parseJUnitStream(stream, { ...options, filename: filePath });
  } finally {
    stream.close();
  }
}
