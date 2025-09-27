import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const DEFAULT_CONFIG_PATHS = [
  'projects/03-ci-flaky/config/flaky.yml',
  'config/flaky.yml',
];

export function parseBoolean(value, defaultValue = false) {
  if (value === undefined) return defaultValue;
  if (typeof value === 'boolean') return value;
  const normalized = String(value).trim().toLowerCase();
  if (['false', '0', 'off', 'no'].includes(normalized)) return false;
  if (['true', '1', 'on', 'yes'].includes(normalized)) return true;
  return defaultValue;
}

export function parseList(value) {
  if (value === undefined || value === null) return [];
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value)
    .split(/[\s,]+/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function determineFormats(args, resolvedConfig) {
  const requested = parseList(args.formats ?? args.format);
  if (requested.length) return [...new Set(requested.map((item) => item.toLowerCase()))];
  const configFormats = resolvedConfig.output?.formats;
  if (Array.isArray(configFormats) && configFormats.length) {
    return [...new Set(configFormats.map((item) => String(item).toLowerCase()))];
  }
  return ['csv', 'json', 'html'];
}

export function resolveConfigPath(argPath) {
  if (argPath) return argPath;
  for (const candidate of DEFAULT_CONFIG_PATHS) {
    const resolved = path.resolve(process.cwd(), candidate);
    if (fs.existsSync(resolved)) return resolved;
  }
  return path.resolve(process.cwd(), DEFAULT_CONFIG_PATHS[0]);
}

export function openInBrowser(filePath) {
  if (!filePath) return;
  const resolved = path.resolve(filePath);
  let command;
  let commandArgs;
  if (process.platform === 'darwin') {
    command = 'open';
    commandArgs = [resolved];
  } else if (process.platform === 'win32') {
    command = 'cmd';
    commandArgs = ['/c', 'start', '""', resolved];
  } else {
    command = 'xdg-open';
    commandArgs = [resolved];
  }
  try {
    const child = spawn(command, commandArgs, { detached: true, stdio: 'ignore' });
    child.on('error', (error) => {
      console.warn(`Failed to open report in browser: ${error.message}`);
    });
    child.unref();
  } catch (error) {
    console.warn(`Unable to launch browser for ${resolved}: ${error.message}`);
  }
}
