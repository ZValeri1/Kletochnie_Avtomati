import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  outputDir: "./.artifacts/playwright",
  timeout: 30_000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:8000",
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "dark",
  },
  projects: [
    { name: "unit", testMatch: "unit/frontend/*.spec.ts" },
    {
      name: "e2e",
      testMatch: "e2e/*.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
