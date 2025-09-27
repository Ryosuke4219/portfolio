#!/usr/bin/env node
import process from 'node:process';

import { parseArgs } from '../src/cli-args.js';
import { runAnalyze } from '../src/commands/analyze.js';
import { runIssue } from '../src/commands/issue.js';
import { runParse } from '../src/commands/parse.js';
import { openInBrowser, parseBoolean } from '../src/commands/utils.js';
import { runWeekly } from '../src/commands/weekly.js';

async function main() {
  const [, , command, ...rest] = process.argv;
  const args = parseArgs(rest);

  switch (command) {
    case 'parse':
      await runParse(args);
      break;
    case 'analyze':
      await runAnalyze(args);
      break;
    case 'report':
      if (!args.format && !args.formats) args.format = 'html';
      {
        const { htmlPath } = await runAnalyze({ ...args, top_n: args.top_n ?? undefined });
        if (parseBoolean(args.open, false)) {
          openInBrowser(htmlPath);
        }
      }
      break;
    case 'issue':
      await runIssue(args);
      break;
    case 'weekly':
      await runWeekly(args);
      break;
    default:
      console.log('Usage: flaky <parse|analyze|report|issue|weekly> [options]');
      process.exit(1);
  }
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exit(1);
});
