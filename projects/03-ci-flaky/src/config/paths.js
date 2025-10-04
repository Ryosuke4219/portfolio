import path from 'node:path';
import process from 'node:process';

/**
 * @param {Record<string, any>} config
 * @param {string} [baseDir]
 * @returns {Record<string, any>}
 */
export function resolveConfigPaths(config, baseDir = process.cwd()) {
  const resolved = { ...config };
  if (config.paths) {
    resolved.paths = {
      ...config.paths,
      input: path.resolve(baseDir, config.paths.input),
      store: path.resolve(baseDir, config.paths.store),
      out: path.resolve(baseDir, config.paths.out),
    };
  }
  return resolved;
}
