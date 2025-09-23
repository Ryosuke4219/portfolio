#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { builtinModules } from 'node:module';

const cwd = process.cwd();
const builtinSet = new Set(
  builtinModules.flatMap((name) => {
    if (name.startsWith('node:')) {
      return [name, name.slice(5)];
    }
    return [name, `node:${name}`];
  }),
);

const IGNORED_DIR_NAMES = new Set([
  '.git',
  'node_modules',
  'packages',
  'dist',
  'coverage',
]);

const IGNORED_PATH_PATTERNS = [
  `${path.sep}projects${path.sep}04-llm-adapter-shadow${path.sep}`,
  `${path.sep}projects${path.sep}02-llm-to-playwright${path.sep}tests${path.sep}generated${path.sep}`,
  `${path.sep}tests${path.sep}playwright-report${path.sep}`,
];

function parseArgs(argv) {
  const args = argv.slice(2);
  const roots = [];
  const extensions = ['.js'];
  for (let i = 0; i < args.length; i += 1) {
    const arg = args[i];
    if (arg === '--ext') {
      const value = args[i + 1];
      if (value) {
        extensions.length = 0;
        for (const ext of value.split(',')) {
          const trimmed = ext.trim();
          if (trimmed) extensions.push(trimmed.startsWith('.') ? trimmed : `.${trimmed}`);
        }
        i += 1;
      }
      continue;
    }
    if (arg.startsWith('-')) {
      continue;
    }
    roots.push(arg);
  }
  if (roots.length === 0) {
    roots.push('.');
  }
  return { roots, extensions };
}

function shouldIgnore(relPath) {
  if (!relPath) return false;
  const segments = relPath.split(path.sep);
  if (segments.some((segment) => IGNORED_DIR_NAMES.has(segment))) {
    return true;
  }
  return IGNORED_PATH_PATTERNS.some((pattern) => relPath.includes(pattern));
}

function collectFiles(roots, extensions) {
  const files = [];
  for (const root of roots) {
    const absoluteRoot = path.resolve(cwd, root);
    traverse(absoluteRoot, extensions, files);
  }
  return files;
}

function traverse(targetPath, extensions, files) {
  let stats;
  try {
    stats = fs.statSync(targetPath);
  } catch {
    return;
  }
  const rel = path.relative(cwd, targetPath);
  if (shouldIgnore(rel)) return;

  if (stats.isDirectory()) {
    let entries;
    try {
      entries = fs.readdirSync(targetPath, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      traverse(path.join(targetPath, entry.name), extensions, files);
    }
    return;
  }

  if (!stats.isFile()) return;

  if (!extensions.some((ext) => targetPath.endsWith(ext))) {
    return;
  }

  files.push(path.resolve(targetPath));
}

function classifySource(specifier) {
  if (!specifier) return 'external';
  if (specifier.startsWith('node:')) return 'builtin';
  if (specifier.startsWith('.') || specifier.startsWith('/')) return 'relative';
  if (builtinSet.has(specifier)) return 'builtin';
  const [head] = specifier.split('/');
  if (builtinSet.has(head) || builtinSet.has(`node:${head}`)) return 'builtin';
  return 'external';
}

function gatherImports(content) {
  const lines = content.split(/\r?\n/u);
  const imports = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trimStart();
    if (
      !(
        trimmed.startsWith('import ') ||
        trimmed.startsWith('import{') ||
        trimmed.startsWith('import*') ||
        trimmed.startsWith('import(') ||
        trimmed.startsWith("import'") ||
        trimmed.startsWith('import"')
      )
    ) {
      continue;
    }
    let statement = line;
    let endLine = i;
    while (!statement.includes(';') && endLine + 1 < lines.length) {
      endLine += 1;
      statement += `\n${lines[endLine]}`;
      if (/;\s*$/u.test(lines[endLine])) break;
    }
    const fromMatch = statement.match(/from\s+['"]([^'"]+)['"]/u);
    const sideEffectMatch = statement.match(/import\s+['"]([^'"]+)['"]/u);
    const specifier = fromMatch ? fromMatch[1] : sideEffectMatch ? sideEffectMatch[1] : '';
    imports.push({
      specifier,
      group: classifySource(specifier),
      startLine: i,
      endLine,
    });
    i = endLine;
  }
  return imports;
}

function lintFile(filePath) {
  let content;
  try {
    content = fs.readFileSync(filePath, 'utf8');
  } catch {
    return [];
  }
  const imports = gatherImports(content);
  if (imports.length === 0) return [];

  const issues = [];
  let previous = null;
  const lastSeen = new Map();

  for (const entry of imports) {
    const normalized = entry.specifier.replace(/^node:/u, '').toLowerCase();
    if (previous) {
      if (entry.group !== previous.group) {
        const hasBlankLine = entry.startLine - previous.endLine > 1;
        if (!hasBlankLine) {
          issues.push({
            line: entry.startLine + 1,
            message: `expected blank line between ${previous.group} and ${entry.group} imports`,
          });
        }
      }
    }
    const last = lastSeen.get(entry.group);
    if (last && normalized.localeCompare(last, undefined, { sensitivity: 'base' }) < 0) {
      issues.push({
        line: entry.startLine + 1,
        message: `${entry.group} imports should be sorted alphabetically`,
      });
    }
    lastSeen.set(entry.group, normalized);
    previous = entry;
  }

  return issues;
}

function main() {
  const { roots, extensions } = parseArgs(process.argv);
  const files = collectFiles(roots, extensions);
  const results = [];
  for (const file of files) {
    const relPath = path.relative(cwd, file) || path.basename(file);
    const issues = lintFile(file);
    if (issues.length) {
      results.push({ file: relPath, issues });
    }
  }

  if (results.length === 0) {
    console.log('✅  No lint issues found by the ESLint stub.');
    return;
  }

  let total = 0;
  for (const result of results) {
    console.error(result.file);
    for (const issue of result.issues) {
      total += 1;
      console.error(`  ${issue.line}: ${issue.message}`);
    }
  }
  console.error(`\n${total} problem(s) detected.`);
  process.exitCode = 1;
}

main();
