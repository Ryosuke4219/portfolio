import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

import { DEFAULT_CONFIG, mergeDeep } from './defaults.js';
import { parseYAML } from './parser.js';

/**
 * @param {Partial<Record<string, unknown>>} [overrides]
 * @returns {Record<string, unknown>}
 */
function buildConfigBase(overrides = undefined) {
  const base = mergeDeep({}, DEFAULT_CONFIG);
  return overrides ? mergeDeep(base, overrides) : base;
}

/**
 * @param {string | null | undefined} configPath
 * @returns {{ config: Record<string, unknown>, path: string | null }}
 */
export function loadConfig(configPath) {
  if (!configPath) {
    return { config: buildConfigBase(), path: null };
  }
  const resolvedPath = path.resolve(process.cwd(), configPath);
  if (!fs.existsSync(resolvedPath)) {
    return { config: buildConfigBase(), path: resolvedPath };
  }
  const raw = fs.readFileSync(resolvedPath, 'utf8');
  let parsed;
  try {
    parsed = parseYAML(raw);
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to parse YAML config at ${resolvedPath}: ${error.message}`);
    }
    throw error;
  }
  const config = buildConfigBase(parsed);
  return { config, path: resolvedPath };
}
