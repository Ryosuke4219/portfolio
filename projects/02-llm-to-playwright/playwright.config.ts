import { defineConfig } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const serverScript = path.resolve(__dirname, 'server.mjs');
const baseURL = process.env.BASE_URL || 'http://127.0.0.1:4173';

let serverPort = 4173;
try {
  const parsed = new URL(baseURL);
  const inferredPort = Number(parsed.port);
  if (!Number.isNaN(inferredPort) && inferredPort > 0) {
    serverPort = inferredPort;
  }
} catch {
  // Fallback to default port when BASE_URL is malformed.
  serverPort = 4173;
}

const outputDir = path.resolve(process.cwd(), 'test-results');

export default defineConfig({
  testDir: './tests',
  reporter: [
    ['list'],
    ['junit', { outputFile: path.resolve(process.cwd(), 'junit-results.xml') }],
  ],
  outputDir,
  use: {
    headless: true,
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: `node ${JSON.stringify(serverScript)}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
    env: {
      PORT: String(serverPort),
    },
  },
});
