const ATTRIBUTE_REGEX = /([:\\w.-]+)(?:\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s'"=<>`]+)))?/g;

function parseAttributes(raw) {
  const attrs = {};
  let match;
  ATTRIBUTE_REGEX.lastIndex = 0;
  while ((match = ATTRIBUTE_REGEX.exec(raw)) !== null) {
    const [, key, , dbl, sgl, bare] = match;
    if (dbl !== undefined) attrs[key] = dbl;
    else if (sgl !== undefined) attrs[key] = sgl;
    else if (bare !== undefined) attrs[key] = bare;
    else attrs[key] = '';
  }
  return attrs;
}

export class JUnitStreamParser {
  constructor(options = {}) {
    const { filename = '<stdin>', onOpenTag, onCloseTag, onText } = options;
    this.filename = filename;
    this.handlers = { onOpenTag, onCloseTag, onText };
    this.tagStack = [];
    this.buffer = '';
  }

  async parse(readable) {
    for await (const chunk of readable) {
      this.buffer += chunk;
      let index = 0;
      while (index < this.buffer.length) {
        const next = this.buffer.indexOf('<', index);
        if (next === -1) {
          this.buffer = this.buffer.slice(index);
          break;
        }
        if (next > index) {
          this.emitText(this.buffer.slice(index, next));
        }
        if (this.buffer.startsWith('<!--', next)) {
          const end = this.buffer.indexOf('-->', next + 4);
          if (end === -1) {
            this.buffer = this.buffer.slice(next);
            break;
          }
          index = end + 3;
          continue;
        }
        if (this.buffer.startsWith('<![CDATA[', next)) {
          const end = this.buffer.indexOf(']]>', next + 9);
          if (end === -1) {
            this.buffer = this.buffer.slice(next);
            break;
          }
          const content = this.buffer.slice(next + 9, end);
          this.emitText(content, { isCData: true });
          index = end + 3;
          continue;
        }
        const tagEnd = this.buffer.indexOf('>', next + 1);
        if (tagEnd === -1) {
          this.buffer = this.buffer.slice(next);
          break;
        }
        const rawTag = this.buffer.slice(next + 1, tagEnd).trim();
        index = tagEnd + 1;
        if (!rawTag || rawTag.startsWith('?') || rawTag.startsWith('!')) continue;
        if (rawTag.startsWith('/')) {
          const name = rawTag.slice(1).trim();
          this.handleCloseTag(name, { selfClosing: false });
          continue;
        }
        const selfClosing = rawTag.endsWith('/');
        const body = selfClosing ? rawTag.slice(0, -1).trim() : rawTag;
        const spaceIndex = body.search(/\s/);
        const name = spaceIndex === -1 ? body : body.slice(0, spaceIndex);
        const attrString = spaceIndex === -1 ? '' : body.slice(spaceIndex + 1);
        const attrs = parseAttributes(attrString);
        this.handleOpenTag(name, attrs, { selfClosing });
      }
    }
    if (this.tagStack.length) {
      const last = this.tagStack[this.tagStack.length - 1];
      throw new Error(`Unclosed tag <${last}> detected while parsing ${this.filename}`);
    }
  }

  emitText(text, info = {}) {
    if (!text) return;
    if (!info.isCData && !text.trim()) return;
    const handler = this.handlers.onText;
    if (handler) handler(text, info);
  }

  handleOpenTag(name, attrs, meta) {
    if (!meta.selfClosing) this.tagStack.push(name);
    const handler = this.handlers.onOpenTag;
    if (handler) handler(name, attrs, meta);
    if (meta.selfClosing) {
      const closeHandler = this.handlers.onCloseTag;
      if (closeHandler) closeHandler(name, { selfClosing: true });
    }
  }

  handleCloseTag(name, meta) {
    if (!meta.selfClosing) {
      const current = this.tagStack.pop();
      if (current !== name) {
        throw new Error(`Unexpected closing tag </${name}> while parsing ${this.filename}`);
      }
    }
    const handler = this.handlers.onCloseTag;
    if (handler) handler(name, meta);
  }
}

export async function parseStream(readable, options = {}) {
  const parser = new JUnitStreamParser(options);
  await parser.parse(readable);
}
