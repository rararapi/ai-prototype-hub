import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 100_000 },
  outputDir: '/evidence/browser',
  reporter: [['list'], ['junit', { outputFile: '/evidence/playwright.xml' }], ['html', { outputFolder: '/evidence/html', open: 'never' }]],
  use: {
    baseURL: process.env.PROTOHUB_CONSOLE_URL ?? 'http://localhost:8080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
