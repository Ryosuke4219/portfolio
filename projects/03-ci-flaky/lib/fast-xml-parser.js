const defaultOptions = {
  ignoreAttributes: true,
  attributeNamePrefix: '',
  allowBooleanAttributes: false,
  trimValues: true,
  textNodeName: '#text',
};

const entityMap = {
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
};

function decodeEntity(match, entity) {
  if (entity.startsWith('#x') || entity.startsWith('#X')) {
    const code = Number.parseInt(entity.slice(2), 16);
    return Number.isNaN(code) ? match : String.fromCodePoint(code);
  }
  if (entity.startsWith('#')) {
    const code = Number.parseInt(entity.slice(1), 10);
    return Number.isNaN(code) ? match : String.fromCodePoint(code);
  }
  return Object.prototype.hasOwnProperty.call(entityMap, entity) ? entityMap[entity] : match;
}

function decode(text) {
  if (text == null || text === '') return '';
  return text.replace(/&([^;]+);/g, decodeEntity);
}

function parseAttributes(raw, options) {
  const attrs = {};
  const attrRegex = /([:\w.-]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s'"=<>`]+)))?/g;
  let match;
  while ((match = attrRegex.exec(raw)) !== null) {
    const [, key, , dbl, sgl, bare] = match;
    let value = dbl ?? sgl ?? bare;
    if (value === undefined) {
      if (options.allowBooleanAttributes) {
        attrs[key] = true;
      } else {
        attrs[key] = '';
      }
    } else {
      attrs[key] = decode(value);
    }
  }
  return attrs;
}

function createNode(name, attributes = {}) {
  return { name, attributes, children: [], text: '' };
}

function isWhitespace(text) {
  return /^(?:\s*)$/.test(text);
}

function normaliseText(text, options) {
  if (!text) return '';
  const decoded = decode(text);
  if (options.trimValues !== false) {
    return decoded.trim();
  }
  return decoded;
}

function mergeChildren(children, options, convert) {
  const grouped = new Map();
  for (const child of children) {
    const value = convert(child, options);
    const list = grouped.get(child.name);
    if (list) {
      list.push(value);
    } else {
      grouped.set(child.name, [value]);
    }
  }
  const result = {};
  for (const [name, values] of grouped) {
    result[name] = values.length === 1 ? values[0] : values;
  }
  return { result, hasChildren: grouped.size > 0 };
}

function convertNode(node, options) {
  const { ignoreAttributes, attributeNamePrefix, textNodeName } = options;
  const attrs = ignoreAttributes ? {} : Object.fromEntries(
    Object.entries(node.attributes).map(([key, value]) => [attributeNamePrefix + key, value]),
  );
  const { result: childValues, hasChildren } = mergeChildren(node.children, options, convertNode);
  const textValue = normaliseText(node.text, options);
  const hasText = textValue !== '';
  const hasAttrs = Object.keys(attrs).length > 0;

  if (!hasAttrs && !hasChildren) {
    return hasText ? textValue : '';
  }

  const out = { ...attrs, ...childValues };
  if (hasText) {
    if (!hasChildren && !hasAttrs) {
      return textValue;
    }
    out[textNodeName] = textValue;
  }
  return out;
}

function parseTokens(xml, options) {
  const root = createNode('#document');
  const stack = [root];
  let index = 0;
  const length = xml.length;

  const pushNode = (node, selfClosing) => {
    const parent = stack[stack.length - 1];
    parent.children.push(node);
    if (!selfClosing) {
      stack.push(node);
    }
  };

  while (index < length) {
    const next = xml.indexOf('<', index);
    if (next === -1) {
      const text = xml.slice(index);
      if (!isWhitespace(text)) {
        stack[stack.length - 1].text += text;
      }
      break;
    }
    if (next > index) {
      const text = xml.slice(index, next);
      if (!isWhitespace(text)) {
        stack[stack.length - 1].text += text;
      }
    }
    if (xml.startsWith('<!--', next)) {
      const end = xml.indexOf('-->', next + 4);
      if (end === -1) throw new Error('Unterminated comment in XML input');
      index = end + 3;
      continue;
    }
    if (xml.startsWith('<![CDATA[', next)) {
      const end = xml.indexOf(']]>', next + 9);
      if (end === -1) throw new Error('Unterminated CDATA section in XML input');
      const content = xml.slice(next + 9, end);
      if (content) stack[stack.length - 1].text += content;
      index = end + 3;
      continue;
    }
    const tagEnd = xml.indexOf('>', next + 1);
    if (tagEnd === -1) throw new Error('Unterminated tag in XML input');
    const rawTag = xml.slice(next + 1, tagEnd).trim();
    index = tagEnd + 1;

    if (!rawTag) continue;
    if (rawTag.startsWith('?')) {
      continue; // XML declaration or PI
    }
    if (rawTag.startsWith('!')) {
      continue; // doctype etc.
    }
    if (rawTag.startsWith('/')) {
      const name = rawTag.slice(1).trim();
      const node = stack.pop();
      if (!node || node.name !== name) {
        throw new Error(`Unexpected closing tag </${name}>`);
      }
      continue;
    }

    const selfClosing = rawTag.endsWith('/');
    const tagBody = selfClosing ? rawTag.slice(0, -1).trim() : rawTag;
    const spaceIndex = tagBody.search(/\s/);
    const name = spaceIndex === -1 ? tagBody : tagBody.slice(0, spaceIndex);
    const attrString = spaceIndex === -1 ? '' : tagBody.slice(spaceIndex + 1).trim();
    const attributes = parseAttributes(attrString, options);
    const node = createNode(name, attributes);
    pushNode(node, selfClosing);
    if (selfClosing) {
      // ensure stack is unchanged
    } else {
      node.text = '';
    }
  }

  if (stack.length !== 1) {
    const unclosed = stack.pop();
    throw new Error(`Unclosed tag <${unclosed.name}> in XML input`);
  }

  return root.children;
}

export class XMLParser {
  constructor(options = {}) {
    this.options = { ...defaultOptions, ...options };
  }

  parse(xml) {
    if (typeof xml !== 'string') {
      throw new TypeError('XMLParser.parse expects a string input');
    }
    const tokens = parseTokens(xml, this.options);
    const grouped = mergeChildren(tokens, this.options, convertNode);
    return grouped.result;
  }
}

export default { XMLParser };
