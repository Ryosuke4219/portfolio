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

const bp = JSON.parse(fs.readFileSync(input, 'utf8'));
if (!Array.isArray(bp.scenarios)) {
  console.error('Invalid blueprint: scenarios[] is required');
  process.exit(1);
}

for (const s of bp.scenarios) {
  const code = template(s);
  const filename = `${s.id.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.spec.ts`;
  fs.writeFileSync(path.join(outDir, filename), code, 'utf8');
  console.log('📝 generated:', filename);
}
console.log('✅ done');
