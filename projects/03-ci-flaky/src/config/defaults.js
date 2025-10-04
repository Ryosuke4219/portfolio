import { isPlainObject } from './utils.js';

/** @typedef {Record<string, unknown>} PlainObject */

/** @type {PlainObject} */
export const DEFAULT_CONFIG = {
  window: 20,
  threshold: 0.6,
  new_flaky_window: 5,
  weights: {
    intermittency: 0.5,
    p_fail: 0.3,
    recency: 0.15,
    impact: 0.05,
  },
  timeout_factor: 3.0,
  impact_baseline_ms: 600000,
  recency_lambda: 0.1,
  output: {
    top_n: 50,
    formats: ['csv', 'json', 'html'],
  },
  issue: {
    enabled: true,
    dry_run: true,
    repo: '',
    labels: ['flaky', 'test'],
    assignees: [],
    dedupe_by: 'failure_signature',
  },
  paths: {
    input: './junit',
    store: './data/runs.jsonl',
    out: './out',
  },
};

/**
 * @template T extends PlainObject
 * @param {T} target
 * @param {unknown} source
 * @returns {T}
 */
export function mergeDeep(target, source) {
  if (source == null || typeof source !== 'object') return target;
  if (Array.isArray(target)) {
    return Array.isArray(source) ? /** @type {T} */ (source.slice()) : target;
  }

  /** @type {PlainObject} */
  const output = { ...target };
  for (const [key, value] of Object.entries(/** @type {PlainObject} */ (source))) {
    const current = output[key];
    if (Array.isArray(value)) {
      output[key] = value.slice();
    } else if (isPlainObject(value) && isPlainObject(current)) {
      output[key] = mergeDeep(current, value);
    } else if (isPlainObject(value)) {
      output[key] = mergeDeep({}, value);
    } else {
      output[key] = value;
    }
  }
  return /** @type {T} */ (output);
}
