import { defineConfig, devices } from "@playwright/test";

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */
import dotenv from "dotenv";
import path from "path";
import { fileURLToPath } from "url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(__dirname, ".env.e2e") });

/**
 * The app is served from the e2e production build (`npm run build:e2e` → dist/).
 * `vite preview` provides SPA fallback so client routes (e.g. /leads) resolve.
 * The build bakes the .env.e2e values via Vite's `define`, so no runtime env is
 * needed to boot. Run `npm run build:e2e` once before `npx playwright test`.
 */
const APP_URL = "http://localhost:4173";

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: "./e2e",
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

  /* Serve the e2e build before running any project. */
  webServer: {
    command: "npx vite preview --port 4173 --strictPort",
    url: APP_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },

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
