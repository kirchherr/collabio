import { defineConfig, devices } from "@playwright/test";

const artifactDir = process.env.WORK_E2E_ARTIFACT_DIR || "/tmp/work-e2e-artifacts";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  outputDir: `${artifactDir}/test-results`,
  reporter: [
    ["line"],
    ["json", { outputFile: `${artifactDir}/results.json` }],
  ],
  use: {
    locale: "de-DE",
    timezoneId: "Europe/Berlin",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "desktop-chromium",
      testIgnore: /mobile-only\.spec\.mjs/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 960 },
      },
    },
    {
      name: "mobile-chromium",
      testMatch: /responsive\.spec\.mjs/,
      use: {
        ...devices["Pixel 7"],
      },
    },
  ],
});
