const REQUIRED_ARRAY_FIELDS = ['pre', 'steps', 'expected', 'tags'];

const ensureArray = (value) => (Array.isArray(value) ? value : []);

export function validateSuite(definition, options = {}) {
  const { requireContent = false } = options;
  const errors = [];

  if (!definition || typeof definition !== 'object') {
    errors.push('Definition must be an object.');
    return { valid: false, errors };
  }

  if (typeof definition.suite !== 'string' || !definition.suite.trim()) {
    errors.push('suite must be a non-empty string.');
  }

  if (!Array.isArray(definition.cases) || definition.cases.length === 0) {
    errors.push('cases must be a non-empty array.');
    return { valid: errors.length === 0, errors };
  }

  const seenIds = new Set();

  definition.cases.forEach((testCase, index) => {
    const prefix = `cases[${index}]`;
    if (!testCase || typeof testCase !== 'object') {
      errors.push(`${prefix} must be an object.`);
      return;
    }

    if (typeof testCase.id !== 'string' || !testCase.id.trim()) {
      errors.push(`${prefix}.id must be a non-empty string.`);
    } else {
      const normalizedId = testCase.id.trim();
      if (seenIds.has(normalizedId)) {
        errors.push(`${prefix}.id duplicates an existing test id: ${normalizedId}`);
      }
      seenIds.add(normalizedId);
    }

    if (typeof testCase.title !== 'string' || !testCase.title.trim()) {
      errors.push(`${prefix}.title must be a non-empty string.`);
    }

    for (const field of REQUIRED_ARRAY_FIELDS) {
      const value = ensureArray(testCase[field]);
      if (!Array.isArray(testCase[field])) {
        errors.push(`${prefix}.${field} must be an array.`);
        continue;
      }

      if (requireContent && value.length === 0) {
        errors.push(`${prefix}.${field} must include at least one item.`);
      }

      value.forEach((item, itemIndex) => {
        if (typeof item !== 'string' || !item.trim()) {
          errors.push(`${prefix}.${field}[${itemIndex}] must be a non-empty string.`);
        }
      });
    }
  });

  return { valid: errors.length === 0, errors };
}

export function assertValidSuite(definition, options = {}) {
  const { valid, errors } = validateSuite(definition, options);
  if (!valid) {
    const error = new Error('Suite definition failed validation.');
    error.details = errors;
    throw error;
  }
  return definition;
}

export function formatValidationErrors(errors) {
  return errors.map((message) => `- ${message}`).join('\n');
}
