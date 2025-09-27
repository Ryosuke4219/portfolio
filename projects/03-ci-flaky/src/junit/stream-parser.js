const ATTRIBUTE_REGEX = /([:\\w.-]+)(?:\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s'"=<>`]+)))?/g;

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

function createSuiteEntry(attrs, parent) {
  const baseName = attrs.name || attrs.id || attrs.package || attrs.file || 'suite';
  const fullName = parent && parent.fullName ? `${parent.fullName}.${baseName}` : baseName;
  return { name: baseName, fullName, attrs };
}

export function createJUnitStreamParser({
  filename = '<stdin>',
  onSuiteStart,
  onSuiteEnd,
  onTestcase,
} = {}) {
  const suiteStack = [];
  const nodeStack = [];
  let buffer = '';

  const emitSuiteStart = (entry) => {
    if (typeof onSuiteStart === 'function') onSuiteStart(entry, suiteStack.slice());
  };

  const emitSuiteEnd = (entry) => {
    if (typeof onSuiteEnd === 'function') onSuiteEnd(entry, suiteStack.slice());
  };

  const emitTestcase = (node) => {
    if (typeof onTestcase === 'function') {
      onTestcase({ node, suiteStack: suiteStack.slice() });
    }
  };

  const attachChildNode = (node) => {
    const parent = nodeStack[nodeStack.length - 1];
    if (!parent) return;
    const textContent = (node.text || '').trim();
    if (parent.type === 'testcase') {
      if (node.type === 'failure') parent.failures.push({ ...node, text: textContent });
      else if (node.type === 'error') parent.errors.push({ ...node, text: textContent });
      else if (node.type === 'skipped') parent.skipped = { ...node, text: textContent };
      else if (node.type === 'system-out') parent.systemOut.push({ ...node, text: textContent });
      else if (node.type === 'system-err') parent.systemErr.push({ ...node, text: textContent });
    }
  };

  const processClosingTag = (name) => {
    const node = nodeStack.pop();
    if (!node || node.name !== name) {
      throw new Error(`Unexpected closing tag </${name}> while parsing ${filename}`);
    }
    if (node.type === 'testsuite') {
      suiteStack.pop();
      emitSuiteEnd(node);
    } else if (node.type === 'testcase') {
      emitTestcase(node);
    } else {
      attachChildNode(node);
    }
  };

  const processOpeningTag = (name, attrs, selfClosing) => {
    if (name === 'testsuite') {
      const parent = suiteStack[suiteStack.length - 1];
      const entry = createSuiteEntry(attrs, parent);
      suiteStack.push(entry);
      emitSuiteStart(entry);
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

  const consume = (chunk) => {
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
  };

  const finish = () => {
    if (nodeStack.length) {
      const last = nodeStack[nodeStack.length - 1];
      throw new Error(`Unclosed tag <${last.name}> detected while parsing ${filename}`);
    }
  };

  return {
    consume,
    finish,
  };
}
