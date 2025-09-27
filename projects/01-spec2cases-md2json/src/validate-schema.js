export function ensureArrayOfStrings(value) {
  if (!Array.isArray(value)) return false;
  return value.every((item) => typeof item === 'string' && item.trim().length > 0);
}

export function validateCaseStructure(testCase, index, errors) {
  const prefix = `cases[${index}]`;
  if (!testCase || typeof testCase !== 'object') {
    errors.push(`${prefix} must be an object`);
    return;
  }

  if (typeof testCase.id !== 'string' || testCase.id.trim().length === 0) {
    errors.push(`${prefix}.id must be a non-empty string`);
  }
  if (typeof testCase.title !== 'string' || testCase.title.trim().length === 0) {
    errors.push(`${prefix}.title must be a non-empty string`);
  }
  if (!ensureArrayOfStrings(testCase.pre)) {
    errors.push(`${prefix}.pre must be an array of non-empty strings`);
  }
  if (!ensureArrayOfStrings(testCase.steps)) {
    errors.push(`${prefix}.steps must be an array of non-empty strings`);
  }
  if (!ensureArrayOfStrings(testCase.expected)) {
    errors.push(`${prefix}.expected must be an array of non-empty strings`);
  }
  if (!ensureArrayOfStrings(testCase.tags)) {
    errors.push(`${prefix}.tags must be an array of non-empty strings`);
  }
}

export function validateCasesSchema(data) {
  const errors = [];
  if (!data || typeof data !== 'object') {
    errors.push('root must be an object');
    return errors;
  }
  if (typeof data.suite !== 'string' || data.suite.trim().length === 0) {
    errors.push('suite must be a non-empty string');
  }
  if (!Array.isArray(data.cases)) {
    errors.push('cases must be an array');
  } else if (data.cases.length === 0) {
    errors.push('cases must contain at least one item');
  } else {
    data.cases.forEach((testCase, index) => {
      validateCaseStructure(testCase, index, errors);
    });
  }
  return errors;
}
