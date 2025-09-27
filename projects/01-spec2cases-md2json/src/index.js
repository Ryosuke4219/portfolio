import fs from 'node:fs';
import path from 'node:path';

import { parseSpecText } from './parse-spec.js';

function readFile(filePath, fsModule = fs) {
  try {
    return fsModule.readFileSync(filePath, 'utf8');
  } catch (error) {
    const message = error && typeof error.message === 'string' ? error.message : String(error);
    throw new Error(`Failed to read "${filePath}": ${message}`);
  }
}

export function parseSpecFile(filePath, fsModule = fs) {
  const ext = path.extname(filePath).toLowerCase();
  const raw = readFile(filePath, fsModule);
  if (ext === '.json') {
    try {
      return JSON.parse(raw);
    } catch (error) {
      throw new Error(`Invalid JSON: ${(error && error.message) || error}`);
    }
  }
  if (ext === '.txt' || ext === '.md') {
    return parseSpecText(raw);
  }
  throw new Error(`Unsupported file extension for "${filePath}"`);
}

export function saveCases(result, outputPath, fsModule = fs) {
  const json = `${JSON.stringify(result, null, 2)}\n`;
  fsModule.writeFileSync(outputPath, json, 'utf8');
}

export function resolveInputPath(inputPath, fallbackPath, fsModule = fs) {
  if (inputPath) {
    return { path: inputPath, usedDefault: false };
  }
  if (fallbackPath && fsModule.existsSync(fallbackPath)) {
    return { path: fallbackPath, usedDefault: true };
  }
  throw new Error('Input path is required and no default sample was found');
}

export { parseSpecText } from './parse-spec.js';
