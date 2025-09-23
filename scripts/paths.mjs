import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const REPO_ROOT = path.resolve(__dirname, '..');
export const DOCS_DIR = path.join(REPO_ROOT, 'docs');
export const DOCS_EXAMPLES_DIR = path.join(DOCS_DIR, 'examples');
export const SPEC2CASES_EXAMPLES_DIR = path.join(DOCS_EXAMPLES_DIR, 'spec2cases');
export const LLM2PW_EXAMPLES_DIR = path.join(DOCS_EXAMPLES_DIR, 'llm2pw');

export const SPEC2CASES_SAMPLE_SPEC_MD_PATH = path.join(
  SPEC2CASES_EXAMPLES_DIR,
  'spec.sample.md',
);
export const SPEC2CASES_SAMPLE_SPEC_TXT_PATH = path.join(
  SPEC2CASES_EXAMPLES_DIR,
  'spec.sample.txt',
);
export const SPEC2CASES_SAMPLE_CASES_PATH = path.join(
  SPEC2CASES_EXAMPLES_DIR,
  'cases.sample.json',
);

export const LLM2PW_SAMPLE_BLUEPRINT_PATH = path.join(
  LLM2PW_EXAMPLES_DIR,
  'blueprint.sample.json',
);
export const LLM2PW_DEMO_DIR = path.join(LLM2PW_EXAMPLES_DIR, 'demo');
