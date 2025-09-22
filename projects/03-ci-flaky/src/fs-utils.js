import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';

export function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

export async function * readJsonl(filePath) {
  if (!fs.existsSync(filePath)) return;
  const stream = fs.createReadStream(filePath, { encoding: 'utf8' });
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      yield JSON.parse(trimmed);
    } catch {
      // ignore malformed lines but continue
    }
  }
}

export function listJsonlFiles(primaryPath) {
  const files = [];
  const dir = path.dirname(primaryPath);
  const baseName = path.basename(primaryPath);
  if (!fs.existsSync(dir)) return files;
  const entries = fs.readdirSync(dir);
  for (const entry of entries) {
    if (!entry.startsWith(path.parse(baseName).name)) continue;
    if (!entry.endsWith('.jsonl')) continue;
    files.push(path.join(dir, entry));
  }
  files.sort((a, b) => fs.statSync(a).mtimeMs - fs.statSync(b).mtimeMs);
  return files;
}

export function getFileSize(filePath) {
  try {
    return fs.statSync(filePath).size;
  } catch {
    return 0;
  }
}

export function appendJsonl(filePath, records) {
  if (!records.length) return;
  ensureDir(path.dirname(filePath));
  const stream = fs.createWriteStream(filePath, { flags: 'a', encoding: 'utf8' });
  for (const record of records) {
    stream.write(`${JSON.stringify(record)}\n`);
  }
  stream.end();
}
