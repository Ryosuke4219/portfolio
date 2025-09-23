import fs from 'node:fs';
import path from 'node:path';

import { classifyFailureByMessage, createFailureSignature, applyTimeoutClassification } from './classification.js';

const ATTRIBUTE_REGEX = /([:\w.-]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s'"=<>`]+)))?/g;

function parseAttributes(raw) {
  const attrs = {};
  let match;
  while ((match = ATTRIBUTE_REGEX.exec(raw)) !== null) {
    const [, key, , dbl, sgl, bare] = match;
    if (dbl !== undefined) attrs[key] = dbl;
    else if (sgl !== undefined) attrs[key] = sgl;
    else if (bare !== undefined) attrs[key] = bare;
    else attrs[key] = '';
  }
  return attrs;
}

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

export async function parseJUnitStream(readable, options = {}) {
  const {
    onTestcase,
    filename = '<stdin>',
  } = options;

  const suiteStack = [];
  const nodeStack = [];
  const attempts = [];
  const suiteDurations = new Map();

  const pushSuite = (attrs) => {
    const parent = suiteStack[suiteStack.length - 1];
    const baseName = attrs.name || attrs.id || attrs.package || attrs.file || 'suite';
    const fullName = parent && parent.fullName ? `${parent.fullName}.${baseName}` : baseName;
    const entry = { name: baseName, fullName, attrs };
    suiteStack.push(entry);
  };

  const popSuite = () => {
    suiteStack.pop();
  };

  const attachChildNode = (node) => {
    const parent = nodeStack[nodeStack.length - 1];
    if (!parent) return;
    const textContent = decodeEntities(node.text || '').trim();
    if (parent.type === 'testcase') {
      if (node.type === 'failure') parent.failures.push({ ...node, text: textContent });
      else if (node.type === 'error') parent.errors.push({ ...node, text: textContent });
      else if (node.type === 'skipped') parent.skipped = { ...node, text: textContent };
      else if (node.type === 'system-out') parent.systemOut.push({ ...node, text: textContent });
      else if (node.type === 'system-err') parent.systemErr.push({ ...node, text: textContent });
    }
  };

  const finaliseTestcase = (node) => {
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
        const message = failure.attrs.message || failure.attrs.type || '';
        if (message) messages.push(message);
        const text = decodeEntities(failure.text || '');
        if (text) texts.push(text.trim());
      }
      failureMessage = messages.join(' | ') || null;
      failureDetails = texts.join('\n\n') || null;
    }

    const signature = createFailureSignature(failureMessage, failureDetails);
    const failureKind = failureNodes.length
      ? classifyFailureByMessage(failureMessage, failureDetails) || 'nondeterministic'
      : null;

    const attempt = {
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
      system_out: node.systemOut.map((item) => item.text).filter(Boolean),
      system_err: node.systemErr.map((item) => item.text).filter(Boolean),
      retries: Number.parseInt(node.attrs.retries ?? node.attrs.retry ?? node.attrs.rerun ?? '0', 10) || 0,
    };

    attempts.push(attempt);
    if (typeof onTestcase === 'function') onTestcase(attempt);
  };

  const processClosingTag = (name) => {
    const node = nodeStack.pop();
    if (!node || node.name !== name) {
      throw new Error(`Unexpected closing tag </${name}> while parsing ${filename}`);
    }
    if (node.type === 'testsuite') {
      popSuite();
    } else if (node.type === 'testcase') {
      finaliseTestcase(node);
    } else {
      attachChildNode(node);
    }
  };

  const processOpeningTag = (name, attrs, selfClosing) => {
    if (name === 'testsuite') {
      pushSuite(attrs);
      const node = { type: 'testsuite', name, attrs, text: '' };
      nodeStack.push(node);
      if (selfClosing) processClosingTag(name);
      return;
    }
    if (name === 'testcase') {
      const node = {
        type: 'testcase',
        name,
        attrs,
        text: '',
        failures: [],
        errors: [],
        skipped: null,
        systemOut: [],
        systemErr: [],
      };
      nodeStack.push(node);
      if (selfClosing) processClosingTag(name);
      return;
    }

    const typeMap = {
      failure: 'failure',
      error: 'error',
      skipped: 'skipped',
      'system-out': 'system-out',
      'system-err': 'system-err',
    };
    const mapped = typeMap[name] || 'generic';
    const node = { type: mapped, name, attrs, text: '' };
    nodeStack.push(node);
    if (selfClosing) processClosingTag(name);
  };

  let buffer = '';
  for await (const chunk of readable) {
    buffer += chunk;
    let index = 0;
    while (index < buffer.length) {
      const next = buffer.indexOf('<', index);
      if (next === -1) {
        buffer = buffer.slice(index);
        break;
      }
      if (next > index) {
        const text = buffer.slice(index, next);
        if (text.trim()) {
          const current = nodeStack[nodeStack.length - 1];
          if (current && typeof current.text === 'string') {
            current.text += text;
          }
        }
      }
      if (buffer.startsWith('<!--', next)) {
        const end = buffer.indexOf('-->', next + 4);
        if (end === -1) {
          buffer = buffer.slice(next);
          break;
        }
        index = end + 3;
        continue;
      }
      if (buffer.startsWith('<![CDATA[', next)) {
        const end = buffer.indexOf(']]>', next + 9);
        if (end === -1) {
          buffer = buffer.slice(next);
          break;
        }
        const content = buffer.slice(next + 9, end);
        const current = nodeStack[nodeStack.length - 1];
        if (current && typeof current.text === 'string') {
          current.text += content;
        }
        index = end + 3;
        continue;
      }
      const tagEnd = buffer.indexOf('>', next + 1);
      if (tagEnd === -1) {
        buffer = buffer.slice(next);
        break;
      }
      const rawTag = buffer.slice(next + 1, tagEnd).trim();
      index = tagEnd + 1;
      if (!rawTag) continue;
      if (rawTag.startsWith('?') || rawTag.startsWith('!')) continue;
      if (rawTag.startsWith('/')) {
        const name = rawTag.slice(1).trim();
        processClosingTag(name);
        continue;
      }
      const selfClosing = rawTag.endsWith('/');
      const body = selfClosing ? rawTag.slice(0, -1).trim() : rawTag;
      const spaceIndex = body.search(/\s/);
      const name = spaceIndex === -1 ? body : body.slice(0, spaceIndex);
      const attrString = spaceIndex === -1 ? '' : body.slice(spaceIndex + 1);
      const attrs = parseAttributes(attrString);
      processOpeningTag(name, attrs, selfClosing);
    }
  }

  if (nodeStack.length) {
    const last = nodeStack[nodeStack.length - 1];
    throw new Error(`Unclosed tag <${last.name}> detected while parsing ${filename}`);
  }

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
