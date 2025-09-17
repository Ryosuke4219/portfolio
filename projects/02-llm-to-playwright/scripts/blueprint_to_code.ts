import fs from 'fs';
import path from 'path';
import Handlebars from 'handlebars';

// Helpers
Handlebars.registerHelper('startsWith', function (value: string, prefix: string) {
  return typeof value === 'string' && value.startsWith(prefix);
});

Handlebars.registerHelper('toRegex', function (value: string) {
  // "url:/dashboard" → "/dashboard/" に変換（先頭の "/" を剥がしてからエスケープ）
  const v = (value ?? '').toString();
  const raw = v.split(':', 2)[1] ?? '';
  const trimmed = raw.replace(/^\/+/, ''); // 先頭 "/" を全部削除
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // 正規表現メタをエスケープ（"/"は含めない）
  return `/${escaped}/`;
});

Handlebars.registerHelper('toText', function (value: string) {
  // "text:Welcome Alice" → "\"Welcome Alice\""（JSON文字列）
  const v = (value ?? '').toString();
  const raw = v.split(':', 2)[1] ?? '';
  return JSON.stringify(raw);
});

const input = process.argv[2];
if (!input) {
  console.error('Usage: ts-node blueprint_to_code.ts <blueprint.json>');
  process.exit(2);
}

const outDir = path.join(process.cwd(), 'projects/02-llm-to-playwright/tests/generated');
fs.mkdirSync(outDir, { recursive: true });

const tplPath = path.join(process.cwd(), 'projects/02-llm-to-playwright/templates/playwright.test.ts.hbs');
const tplSrc = fs.readFileSync(tplPath, 'utf8');
const template = Handlebars.compile(tplSrc);

const blueprint = JSON.parse(fs.readFileSync(input, 'utf8'));
if (!Array.isArray(blueprint.scenarios)) {
  console.error('Invalid blueprint: scenarios[] is required');
  process.exit(1);
}

const generated: string[] = [];

for (const scenario of blueprint.scenarios) {
  if (!scenario?.id || !scenario?.title) {
    console.error('Scenario must include id and title:', scenario);
    process.exit(1);
  }
  if (!scenario.selectors || !scenario.selectors.user || !scenario.selectors.pass || !scenario.selectors.submit) {
    console.error(`Scenario ${scenario.id} is missing selectors.user/pass/submit`);
    process.exit(1);
  }
  if (!scenario.data || typeof scenario.data.user !== 'string' || typeof scenario.data.pass !== 'string') {
    console.error(`Scenario ${scenario.id} is missing data.user or data.pass`);
    process.exit(1);
  }
  if (!Array.isArray(scenario.asserts)) {
    console.error(`Scenario ${scenario.id} has invalid asserts. Expected an array.`);
    process.exit(1);
  }

  const filename = `${scenario.id.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.spec.ts`;
  const code = template(scenario);
  fs.writeFileSync(path.join(outDir, filename), code, 'utf8');
  generated.push(filename);
  console.log('📝 generated:', filename);
}

console.log(`✅ done (files: ${generated.join(', ')})`);
