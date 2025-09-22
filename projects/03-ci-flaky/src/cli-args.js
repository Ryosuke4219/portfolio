import { fileURLToPath } from 'node:url';

const FLAG_REGEX = /^--([^=]+)(?:=(.*))?$/u;

export function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      args._.push(token);
      continue;
    }
    const match = FLAG_REGEX.exec(token);
    if (!match) {
      args._.push(token);
      continue;
    }
    const [, rawKey, inlineValue] = match;
    const key = rawKey.replace(/-/g, '_');
    if (inlineValue !== undefined) {
      args[key] = inlineValue;
      continue;
    }
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      args[key] = next;
      i += 1;
    } else {
      args[key] = true;
    }
  }
  return args;
}

export function ensureCommand(invokedAs) {
  const scriptPath = fileURLToPath(import.meta.url);
  return invokedAs.endsWith(scriptPath);
}
