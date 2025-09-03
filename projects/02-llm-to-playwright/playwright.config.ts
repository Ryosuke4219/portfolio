import { defineConfig } from '@playwright/test';
import path from 'path';

export default defineConfig({
  testDir: './tests',
  reporter: [
    ['list'],
    ['junit', { outputFile: path.resolve(process.cwd(), 'junit-results.xml') }], // ルート直下に固定
  ],
  use: { headless: true },
});
