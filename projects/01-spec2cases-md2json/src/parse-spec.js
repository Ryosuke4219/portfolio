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

export function applySectionLine(
  sectionName,
  current,
  inlineValue,
  listResult,
  currentIndex,
) {
  const targetArray = current[sectionName];
  if (inlineValue) {
    targetArray.push(inlineValue);
  }
  if (listResult) {
    targetArray.push(...listResult.values);
  }
  return {
    section: sectionName,
    nextIndex: listResult ? listResult.nextIndex : currentIndex,
  };
}

const SECTION_PATTERNS = {
  pre: /^pre\s*:\s*/i,
  steps: /^steps?\s*:\s*/i,
  expected: /^expected\s*:\s*/i,
};

export function handleSectionLine(sectionName, normalisedLine, lines, index, current) {
  const pattern = SECTION_PATTERNS[sectionName];
  if (!pattern?.test(normalisedLine)) return null;

  const inlineValue = normalisedLine.replace(pattern, '').trim();
  if (inlineValue) {
    return applySectionLine(sectionName, current, inlineValue, null, index);
  }

  const listResult = parseListSection(lines, index + 1);
  return applySectionLine(sectionName, current, null, listResult, index);
}

export function handleSectionDispatch(normalisedLine, lines, index, current) {
  for (const sectionName of ['pre', 'steps', 'expected']) {
    const result = handleSectionLine(sectionName, normalisedLine, lines, index, current);
    if (result) {
      return { handled: true, ...result };
    }
  }
  return { handled: false, section: null, nextIndex: index };
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

    const sectionState = handleSectionDispatch(normalisedLine, lines, i, current);
    if (sectionState.handled) {
      currentSection = sectionState.section;
      i = sectionState.nextIndex;
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
