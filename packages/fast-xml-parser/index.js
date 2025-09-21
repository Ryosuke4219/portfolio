const DEFAULT_OPTIONS = {
  ignoreAttributes: true,
  attributeNamePrefix: '@_',
  allowBooleanAttributes: false,
  trimValues: true,
};

function mergeOptions(options = {}) {
  return {
    ...DEFAULT_OPTIONS,
    ...options,
  };
}

function normaliseText(text, trim) {
  if (!trim) return text;
  return text.trim();
}

function hasOwnEnumerableKeys(obj) {
  // Used to detect whether we should collapse an element into a text value.
  for (const key in obj) {
    if (Object.prototype.hasOwnProperty.call(obj, key)) {
      return true;
    }
  }
  return false;
}

function assignChild(container, name, value) {
  const existing = container[name];
  if (existing === undefined) {
    container[name] = value;
    return { parent: container, key: name };
  }
  if (Array.isArray(existing)) {
    existing.push(value);
    return { parent: existing, key: existing.length - 1 };
  }
  container[name] = [existing, value];
  const arr = container[name];
  return { parent: arr, key: arr.length - 1 };
}

function parseAttributes(text, options) {
  if (!text) return {};
  const attrs = {};
  const attrPattern = /([^\s/=><"']+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>/]+)))?/g;
  let match;
  while ((match = attrPattern.exec(text)) !== null) {
    const [, rawName, , doubleQuoted, singleQuoted, bare] = match;
    const name = options.attributeNamePrefix + rawName;
    let value;
    if (doubleQuoted !== undefined) {
      value = doubleQuoted;
    } else if (singleQuoted !== undefined) {
      value = singleQuoted;
    } else if (bare !== undefined) {
      value = bare;
    } else if (options.allowBooleanAttributes) {
      value = true;
    } else {
      value = '';
    }
    if (typeof value === 'string' && options.trimValues) {
      value = value.trim();
    }
    if (!options.ignoreAttributes) {
      attrs[name] = value;
    }
  }
  return attrs;
}

function appendText(stack, text, options) {
  const normalised = normaliseText(text, options.trimValues);
  if (!normalised) return;
  if (!stack.length) return;
  const frame = stack[stack.length - 1];
  const target = frame.parent[frame.key];
  if (target == null) {
    frame.parent[frame.key] = normalised;
    return;
  }
  if (typeof target === 'string') {
    const combined = options.trimValues ? `${target}${normalised}`.trim() : target + normalised;
    frame.parent[frame.key] = combined;
    return;
  }
  if (typeof target === 'object') {
    if (!hasOwnEnumerableKeys(target)) {
      frame.parent[frame.key] = normalised;
      return;
    }
    if (target.__text) {
      target.__text = options.trimValues
        ? `${target.__text}${normalised}`.trim()
        : target.__text + normalised;
    } else {
      target.__text = normalised;
    }
  }
}

function handleStartTag(body, stack, root, options) {
  let tagBody = body;
  const selfClosing = tagBody.endsWith('/');
  if (selfClosing) {
    tagBody = tagBody.slice(0, -1).trim();
  }
  const nameMatch = tagBody.match(/^([^\s/>]+)/);
  if (!nameMatch) return;
  const tagName = nameMatch[1];
  const attrText = tagBody.slice(nameMatch[0].length).trim();
  const attrs = parseAttributes(attrText, options);

  const parentFrame = stack.length
    ? stack[stack.length - 1]
    : { parent: root, key: null };
  const parentContainer = parentFrame.key == null ? parentFrame.parent : parentFrame.parent[parentFrame.key];
  if (parentContainer == null || typeof parentContainer !== 'object') {
    throw new Error(`Invalid parent for <${tagName}> element`);
  }

  const child = options.ignoreAttributes ? {} : { ...attrs };
  const ref = assignChild(parentContainer, tagName, child);
  if (!selfClosing) {
    stack.push(ref);
  }
}

function handleEndTag(body, stack) {
  const tagName = body.replace(/^\//, '').trim();
  if (!stack.length) return;
  stack.pop();
}

export class XMLParser {
  constructor(options = {}) {
    this.options = mergeOptions(options);
  }

  parse(xmlText) {
    if (typeof xmlText !== 'string') {
      throw new Error('XMLParser.parse expects a string input');
    }
    const xml = xmlText.trim();
    const root = {};
    const stack = [];
    const tagPattern = /<([^>]+)>/g;
    let lastIndex = 0;
    let match;

    while ((match = tagPattern.exec(xml)) !== null) {
      const [raw, body] = match;
      const textChunk = xml.slice(lastIndex, match.index);
      appendText(stack, textChunk, this.options);
      lastIndex = match.index + raw.length;

      const trimmedBody = body.trim();
      if (!trimmedBody) continue;
      if (trimmedBody.startsWith('!--')) {
        // Skip comments
        const endIdx = xml.indexOf('-->', match.index + raw.length);
        if (endIdx !== -1) {
          tagPattern.lastIndex = endIdx + 3;
          lastIndex = endIdx + 3;
        }
        continue;
      }
      if (trimmedBody.startsWith('?') || trimmedBody.startsWith('!')) {
        // Skip declarations and doctypes
        continue;
      }
      if (trimmedBody.startsWith('/')) {
        handleEndTag(trimmedBody, stack);
        continue;
      }
      handleStartTag(trimmedBody, stack, root, this.options);
    }

    const tail = xml.slice(lastIndex);
    appendText(stack, tail, this.options);

    if (stack.length) {
      throw new Error('Malformed XML: unbalanced tags');
    }

    return root;
  }
}

export default {
  XMLParser,
};
