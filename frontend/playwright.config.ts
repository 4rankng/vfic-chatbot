import { defineConfig, devices } from "@playwright/test";

import { randomUUID } from "node:crypto";
import path from "path";
import { fileURLToPath } from "url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Playwright owns a disposable FastAPI/PostgreSQL backend and a Vite server.
 * The test-only backend harness refuses non-`_e2e` databases and exposes no
 * production reset endpoint.
 */
const APP_URL = "http://127.0.0.1:4173";
const API_URL = "http://127.0.0.1:8000";
const BACKEND_PYTHON =
  process.env.VFIC_BACKEND_PYTHON ??
  path.resolve(__dirname, "../backend/.venv/bin/python");
const E2E_HARNESS = path.resolve(__dirname, "../backend/tests/e2e_harness.py");
const E2E_RUN_ID =
  process.env.VFIC_E2E_RUN_ID ?? randomUUID().replaceAll("-", "").slice(0, 12);
process.env.VFIC_E2E_RUN_ID = E2E_RUN_ID;
process.env.VFIC_BACKEND_PYTHON = BACKEND_PYTHON;
process.env.VFIC_E2E_DATABASE_URL ??=
  `postgresql+asyncpg://vfic:vfic@127.0.0.1:5432/vfic_${E2E_RUN_ID}_e2e`;
process.env.VFIC_E2E_DATABASE_URL_SYNC ??=
  `postgresql+psycopg://vfic:vfic@127.0.0.1:5432/vfic_${E2E_RUN_ID}_e2e`;

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: "./e2e",
  globalTeardown: "./e2e/global-teardown.ts",
  /* Run tests in files in parallel */
  fullyParallel: false,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* No parallel tests on CI as we depends on the same db. */
  workers: 1,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: "list",
  /* Shared settings for all projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: APP_URL,

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: "on-first-retry",
    actionTimeout: 5000,
  },

  webServer: [
    {
      command: `${JSON.stringify(BACKEND_PYTHON)} ${JSON.stringify(E2E_HARNESS)} serve --port 8000`,
      url: `${API_URL}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npx vite --mode e2e --host 127.0.0.1 --port 4173 --strictPort",
      url: APP_URL,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        VITE_API_BASE: API_URL,
        VITE_SOCKET_URL: API_URL,
      },
    },
  ],

  /* Configure projects for major browsers */
  projects: [
    {
      name: "chromium",
      testIgnore: /visual\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        ...(process.env.CI && { channel: "chromium-headless-shell" }),
      },
    },

    /* Test against mobile viewports. */
    {
      name: "Mobile Chrome",
      testIgnore: /visual\.spec\.ts/,
      use: {
        ...devices["Pixel 5"],
        ...(process.env.CI && { channel: "chromium-headless-shell" }),
      },
    },

    /* ── Visual regression (toHaveScreenshot) ───────────────────────────
       Baselines live in e2e/visual.spec.ts-snapshots/. Update intentionally
       with: npx playwright test visual --update-snapshots
       Determinism is handled inside the spec (fonts ready, animations off,
       fixed clock, masked dynamic regions, service worker unregistered). */
    {
      name: "visual-desktop",
      testMatch: /visual\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        reducedMotion: "reduce",
      },
    },
    {
      name: "visual-mobile",
      testMatch: /visual\.spec\.ts/,
      use: {
        ...devices["Pixel 5"],
        reducedMotion: "reduce",
      },
    },

    // Uncomment to test against additional devices

    /* Test against desktop browsers. */
    // {
    //   name: "chromium",
    //   use: { ...devices["Desktop Chrome"] },
    // },

    /* Test against additional mobile browsers. */
    // {
    //   name: "firefox",
    //   use: { ...devices["Desktop Firefox"] },
    // },
    // {
    //   name: "Mobile Safari",
    //   use: { ...devices["iPhone 12"] },
    // },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],
});
