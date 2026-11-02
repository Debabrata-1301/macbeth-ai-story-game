import { defineConfig, devices } from '@playwright/test';

const localMode = process.env.PLAYWRIGHT_MODE === 'local';
const viteUrl = process.env.PLAYWRIGHT_VITE_URL || 'http://127.0.0.1:5173';

export default defineConfig({
  globalSetup: './e2e/global-setup.ts',
  testDir: './e2e',
  testMatch: localMode ? '**/*.local.e2e.ts' : '**/*.ui.e2e.ts',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 2,
  timeout: localMode ? 180_000 : 30_000,
  expect: { timeout: localMode ? 150_000 : 10_000 },
  outputDir: 'test-results',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: viteUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  projects: [{ name: localMode ? 'local-ollama-smoke' : 'mocked-ui', use: { ...devices['Desktop Chrome'] } }],
});
