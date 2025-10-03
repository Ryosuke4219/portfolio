import crypto from 'node:crypto';

import { isFailureStatus } from './analyzer.js';

const MESSAGE_PATTERNS = {
  timeout: /timeout|timed out|Exceeded.*time|Time limit/i,
  parsing: /syntax error|unexpected token|parse error|JSON\.parse|invalid json|xml parse/i,
  guard_violation: /assertion failed|expect\(|element (?:is )?not found|no such element|precondition|guard/i,
  provider_error: /ECONN|ENOTFOUND|EHOST|connection (?:reset|refused)|socket hang up|503|502|timeout awaiting 'request'/i,
  infra: /worker lost|infrastructure|out of memory|failed to start|ci runner/i,
};

export function createFailureSignature(message, text) {
  const normalized = `${message || ''}\n${(text || '').split(/\r?\n/u).slice(0, 20).join('\n')}`.trim();
  if (!normalized) return null;
  return crypto.createHash('sha1').update(normalized).digest('hex').slice(0, 16);
}

export function classifyFailureByMessage(message, text) {
  const haystack = `${message || ''}\n${text || ''}`;
  if (!haystack) return null;
  for (const [kind, pattern] of Object.entries(MESSAGE_PATTERNS)) {
    if (pattern.test(haystack)) {
      return kind;
    }
  }
  return 'nondeterministic';
}

export function applyTimeoutClassification(attempts, suiteDurations, factor) {
  if (!Number.isFinite(factor) || factor <= 0) return;
  const thresholds = new Map();
  for (const [suite, durations] of suiteDurations.entries()) {
    if (!durations.length) continue;
    const sorted = [...durations].sort((a, b) => a - b);
    const idx = Math.max(0, Math.floor(sorted.length * 0.95) - 1);
    const pct95 = sorted[idx] ?? sorted[sorted.length - 1];
    thresholds.set(suite, pct95 * factor);
  }
  for (const attempt of attempts) {
    if (!isFailureStatus(attempt)) continue;
    if (attempt.failure_kind && attempt.failure_kind !== 'nondeterministic') continue;
    const threshold = thresholds.get(attempt.suite);
    if (!threshold) continue;
    if (attempt.duration_ms && attempt.duration_ms > threshold) {
      attempt.failure_kind = 'timeout';
    }
  }
}
