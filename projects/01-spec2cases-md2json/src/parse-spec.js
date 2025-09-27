export function normaliseBullet(line) {
  return line
    .replace(/^[-*\d.\)\s]+/, '')
    .trim();
}

export function parseListSection(lines, startIndex) {
  const values = [];
  let index = startIndex;
  for (; index < lines.length; index += 1) {
    const raw = lines[index];
    const trimmed = raw.trim();
    if (!trimmed) continue;

    if (/^(suite|case|title|pre|steps?|expected|tags)\s*:/i.test(trimmed)) {
      break;
    }
    if (/^[-*\d]/.test(trimmed)) {
      const normalised = normaliseBullet(trimmed);
      if (normalised) values.push(normalised);
      continue;
    }
    if (values.length) {
      const merged = `${values[values.length - 1]} ${trimmed}`.trim();
      values[values.length - 1] = merged;
      continue;
    }
    values.push(trimmed);
  }
  return { values, nextIndex: index - 1 };
}

export function parseSpecText(text) {
  const lines = text.split(/\r?\n/);
  let suite = '';
  const cases = [];
  let current = null;
  let currentSection = null;

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) continue;

    const suiteMatch =
      trimmed.match(/^suite\s*:\s*(.+)$/i) || trimmed.match(/^#\s+(.+)$/);
    if (suiteMatch) {
      suite = suiteMatch[1].trim();
      continue;
    }

    const caseHeadingMatch = trimmed.match(/^##\s+(\S+)(?:\s+(.+))?$/);
    if (caseHeadingMatch) {
      if (current) cases.push(current);
      const [, headingId, headingTitle = ''] = caseHeadingMatch;
      current = {
        id: headingId.trim(),
        title: headingTitle.trim(),
        pre: [],
        steps: [],
        expected: [],
        tags: [],
      };
      currentSection = null;
      continue;
    }

    const caseMatch = trimmed.match(/^case\s*:\s*(.+)$/i);
    if (caseMatch) {
      if (current) cases.push(current);
      current = {
        id: caseMatch[1].trim(),
        title: '',
        pre: [],
        steps: [],
        expected: [],
        tags: [],
      };
      currentSection = null;
      continue;
    }

    if (!current) continue;

    const normalisedLine = normaliseBullet(trimmed);

    const titleMatch = normalisedLine.match(/^title\s*:\s*(.+)$/i);
    if (titleMatch) {
      current.title = titleMatch[1].trim();
      currentSection = null;
      continue;
    }

    if (/^pre\s*:/i.test(normalisedLine)) {
      currentSection = 'pre';
      const inlineValue = normalisedLine.replace(/^pre\s*:\s*/i, '').trim();
      if (inlineValue) {
        current.pre.push(inlineValue);
      } else {
        const { values, nextIndex } = parseListSection(lines, i + 1);
        current.pre.push(...values);
        i = nextIndex;
      }
      continue;
    }

    if (/^steps?\s*:/i.test(normalisedLine)) {
      currentSection = 'steps';
      const inlineValue = normalisedLine.replace(/^steps?\s*:\s*/i, '').trim();
      if (inlineValue) {
        current.steps.push(inlineValue);
      } else {
        const { values, nextIndex } = parseListSection(lines, i + 1);
        current.steps.push(...values);
        i = nextIndex;
      }
      continue;
    }

    if (/^expected\s*:/i.test(normalisedLine)) {
      currentSection = 'expected';
      const inlineValue = normalisedLine.replace(/^expected\s*:\s*/i, '').trim();
      if (inlineValue) {
        current.expected.push(inlineValue);
      } else {
        const { values, nextIndex } = parseListSection(lines, i + 1);
        current.expected.push(...values);
        i = nextIndex;
      }
      continue;
    }

    const tagsMatch = normalisedLine.match(/^(tags?)\s*:\s*(.+)$/i);
    if (tagsMatch) {
      const [, label, value] = tagsMatch;
      const tokens = value
        .split(/[\s,\u3001]+/)
        .map((token) => token.trim())
        .filter(Boolean);
      if (label.toLowerCase() === 'tag') {
        current.tags.push(...tokens);
      } else {
        current.tags = tokens;
      }
      currentSection = null;
      continue;
    }

    if (currentSection) {
      const targetArray = current[currentSection];
      const normalised = normalisedLine;
      if (!normalised) continue;

      if (targetArray.length) {
        const merged = `${targetArray[targetArray.length - 1]} ${normalised}`.trim();
        targetArray[targetArray.length - 1] = merged;
      } else {
        targetArray.push(normalised);
      }
    }
  }

  if (current) cases.push(current);
  return { suite: suite.trim(), cases };
}
