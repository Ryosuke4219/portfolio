#!/usr/bin/env node
import process from 'node:process';

const args = process.argv.slice(2);
if (args.includes('--version') || args.includes('-v')) {
  console.log('0.0.0-stub');
  process.exit(0);
}

const mode = args.includes('--write') ? 'write' : args.includes('--check') ? 'check' : 'format';
const targets = args.filter((arg) => !arg.startsWith('-'));

if (mode === 'check') {
  console.log(`prettier-stub: ${targets.length} file(s) assumed to be formatted.`);
} else if (mode === 'write') {
  console.log(`prettier-stub: skipping write for ${targets.length} target(s).`);
} else {
  console.log('prettier-stub: no formatting performed.');
}
