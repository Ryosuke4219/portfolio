import fs from 'node:fs';
import path from 'node:path';
import { appendJsonl, ensureDir, getFileSize } from './fs-utils.js';

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

function formatDate(ts = new Date()) {
  const year = ts.getUTCFullYear();
  const month = String(ts.getUTCMonth() + 1).padStart(2, '0');
  const day = String(ts.getUTCDate()).padStart(2, '0');
  return `${year}${month}${day}`;
}

function rotateFile(storePath) {
  const dir = path.dirname(storePath);
  const baseName = path.basename(storePath, '.jsonl');
  const suffix = formatDate();
  let candidate = path.join(dir, `${baseName}_${suffix}.jsonl`);
  let counter = 1;
  while (fs.existsSync(candidate)) {
    counter += 1;
    candidate = path.join(dir, `${baseName}_${suffix}_${counter}.jsonl`);
  }
  fs.renameSync(storePath, candidate);
}

export function appendAttempts(storePath, attempts) {
  if (!attempts.length) return;
  ensureDir(path.dirname(storePath));
  if (fs.existsSync(storePath) && getFileSize(storePath) >= MAX_FILE_SIZE) {
    rotateFile(storePath);
  }
  appendJsonl(storePath, attempts);
}
