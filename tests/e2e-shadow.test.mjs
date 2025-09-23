import assert from 'node:assert';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { parseSpecFile } from '../projects/01-spec2cases/scripts/spec2cases.mjs';
import { generateTestsFromBlueprint } from '../projects/02-llm-to-playwright/scripts/blueprint_to_code.mjs';
import { analyzeJUnitReport } from '../projects/03-ci-flaky/scripts/analyze-junit.mjs';
import {
  LLM2PW_SAMPLE_BLUEPRINT_PATH,
  SPEC2CASES_SAMPLE_SPEC_TXT_PATH,
} from '../scripts/paths.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..');

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

async function waitForFile(targetPath, { timeoutMs = 1000, intervalMs = 25 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(targetPath)) return;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  assert.fail(`expected file to exist within ${timeoutMs}ms: ${targetPath}`);
}

test('spec → playwright → junit → python metrics pipeline', async () => {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'shadow-pipeline-'));
  const generatedDir = path.join(tmpRoot, 'projects', '02-llm-to-playwright', 'tests', 'generated');
  fs.mkdirSync(generatedDir, { recursive: true });

  const cases = parseSpecFile(SPEC2CASES_SAMPLE_SPEC_TXT_PATH);
  const casesPath = path.join(tmpRoot, 'cases.json');
  fs.writeFileSync(casesPath, JSON.stringify(cases, null, 2), 'utf8');

  const blueprint = readJson(LLM2PW_SAMPLE_BLUEPRINT_PATH);
  const generatedFiles = generateTestsFromBlueprint(blueprint, generatedDir);
  assert.equal(
    generatedFiles.length,
    blueprint.scenarios.length,
    'expected one generated spec file per scenario',
  );

  const playwrightCli = path.join(repoRoot, 'node_modules', '.bin', 'playwright');
  assert.ok(fs.existsSync(playwrightCli), 'playwright CLI stub should exist');

  const runResult = spawnSync(process.execPath, [playwrightCli, 'test'], {
    cwd: tmpRoot,
    encoding: 'utf8',
    env: { ...process.env },
  });
  if (runResult.status !== 0) {
    const stderr = runResult.stderr || '<no stderr>';
    const stdout = runResult.stdout || '<no stdout>';
    assert.fail(`playwright stub failed (status=${runResult.status})\nSTDOUT:\n${stdout}\nSTDERR:\n${stderr}`);
  }

  const junitPath = path.join(tmpRoot, 'junit-results.xml');
  assert.ok(fs.existsSync(junitPath), 'junit-results.xml should be produced by the stub');

  const dbPath = path.join(tmpRoot, 'artifacts', 'junit-attempts.jsonl');
  const analysis = await analyzeJUnitReport(junitPath, dbPath);
  assert.equal(analysis.attemptsCount, blueprint.scenarios.length);
  await waitForFile(analysis.outputPath);

  const pythonExe = process.env.PYTHON || 'python3';
  const adapterScript = path.join(
    repoRoot,
    'projects',
    '04-llm-adapter-shadow',
    'tools',
    'consume_cases.py',
  );
  assert.ok(fs.existsSync(adapterScript), 'adapter metrics script should exist');

  const pythonResult = spawnSync(
    pythonExe,
    [
      adapterScript,
      '--cases',
      casesPath,
      '--attempts',
      analysis.outputPath,
      '--format',
      'json',
    ],
    {
      encoding: 'utf8',
    },
  );

  if (pythonResult.status !== 0) {
    assert.fail(`consume_cases.py failed: ${pythonResult.stderr || pythonResult.stdout}`);
  }

  const trimmed = pythonResult.stdout.trim();
  assert.ok(trimmed, 'adapter script should emit metrics');
  const metrics = JSON.parse(trimmed);
  assert.equal(metrics.suite, cases.suite);
  assert.equal(metrics.case_count, cases.cases.length);
  assert.equal(metrics.attempt_count, blueprint.scenarios.length);
  assert.deepEqual(metrics.missing_case_ids, []);
  assert.deepEqual(metrics.failed_case_ids, []);
  assert.equal(metrics.status_breakdown.pass, blueprint.scenarios.length);
  assert.equal(metrics.all_green, true);
});
