const defaultOptions = {
  attributeNamePrefix: '',
  ignoreAttributes: true,
  allowBooleanAttributes: false,
  textNodeName: '#text',
  trimValues: true,
};

export class XMLParser {
  constructor(options = {}) {
    this.options = { ...defaultOptions, ...options };
  }

  parse(xmlData) {
    if (typeof xmlData !== 'string') {
      throw new TypeError('XML data must be a string');
    }

    const tokens = this.#tokenize(xmlData);
    const stack = [];
    let root = null;

    for (const token of tokens) {
      if (token.type === 'text') {
        if (!stack.length) continue;
        stack[stack.length - 1].text.push(token.value);
        continue;
      }

      if (token.type === 'open') {
        const node = this.#createNode(token.value);
        stack.push(node);
        continue;
      }

      if (token.type === 'self') {
        const node = this.#createNode(token.value);
        const data = this.#buildNode(node);
        if (!stack.length) {
          root = { name: node.name, value: data };
        } else {
          stack[stack.length - 1].children.push({ name: node.name, value: data });
        }
        continue;
      }

      if (token.type === 'close') {
        const node = stack.pop();
        if (!node) continue;
        const data = this.#buildNode(node);
        if (!stack.length) {
          root = { name: node.name, value: data };
        } else {
          stack[stack.length - 1].children.push({ name: node.name, value: data });
        }
      }
    }

    if (!root) {
      return {};
    }

    if (stack.length) {
      throw new Error('Malformed XML: unbalanced tags');
    }

    return { [root.name]: root.value };
  }

  #createNode(source) {
    const nameMatch = /^([^\s/>]+)/.exec(source);
    if (!nameMatch) {
      throw new Error(`Invalid tag: <${source}>`);
    }
    const name = nameMatch[1];
    const attrs = {};
    const rest = source.slice(name.length).trim();
    if (rest) {
      const attrRegex = /([^\s=]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>=]+)))?/g;
      let match;
      while ((match = attrRegex.exec(rest))) {
        const key = match[1];
        let value = match[3];
        if (value == null) value = match[4];
        if (value == null) value = match[5];
        if (value == null) {
          value = this.options.allowBooleanAttributes ? true : '';
        } else if (this.options.trimValues !== false) {
          value = value.trim();
        }
        attrs[key] = value;
      }
    }
    return { name, attrs, children: [], text: [] };
  }

  #buildNode(node) {
    const prefix = this.options.attributeNamePrefix ?? '';
    const textNodeName = this.options.textNodeName ?? '#text';
    const rawText = node.text.join('');
    const textValue = this.options.trimValues === false ? rawText : rawText.trim();
    const hasText = textValue.length > 0;
    const hasChildren = node.children.length > 0;
    const hasAttributes = !this.options.ignoreAttributes && Object.keys(node.attrs).length > 0;

    if (!hasAttributes && !hasChildren) {
      if (hasText) return textValue;
      return {};
    }

    const data = {};

    if (!this.options.ignoreAttributes) {
      for (const [key, value] of Object.entries(node.attrs)) {
        data[`${prefix}${key}`] = value;
      }
    }

    for (const child of node.children) {
      const existing = data[child.name];
      if (existing === undefined) {
        data[child.name] = child.value;
      } else if (Array.isArray(existing)) {
        existing.push(child.value);
      } else {
        data[child.name] = [existing, child.value];
      }
    }

    if (hasText) {
      data[textNodeName] = textValue;
    }

    return data;
  }

  #tokenize(xml) {
    const tokens = [];
    const regex = /<!\[CDATA\[[\s\S]*?\]\]>|<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<\/?[^>]+>|[^<]+/g;
    let match;
    while ((match = regex.exec(xml)) !== null) {
      const value = match[0];
      if (!value) continue;
      if (value.startsWith('<?')) continue;
      if (value.startsWith('<!--')) continue;
      if (value.startsWith('<![CDATA[')) {
        tokens.push({ type: 'text', value: value.slice(9, -3) });
        continue;
      }
      if (value.startsWith('</')) {
        tokens.push({ type: 'close', value: value.slice(2, -1).trim() });
        continue;
      }
      if (value.startsWith('<')) {
        const selfClosing = /\/>$/.test(value.trim());
        const inner = value.slice(1, value.length - (selfClosing ? 2 : 1)).trim();
        if (!inner) continue;
        tokens.push({ type: selfClosing ? 'self' : 'open', value: inner });
        continue;
      }
      if (value.trim().length) {
        tokens.push({ type: 'text', value });
      }
    }
    return tokens;
  }
}

export default { XMLParser };
