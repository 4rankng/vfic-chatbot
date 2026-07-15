import { type Page } from "@playwright/test";

import { expect, test } from "./fixtures";

/**
 * Visual regression baselines.
 *
 * The app is served by the Playwright-owned Vite server while a disposable
 * FastAPI/PostgreSQL backend is available for authenticated suites.
 *
 * Determinism strategy:
 *  - Telemetry is short-circuited; the login page uses the real auth boundary.
 *  - Theme is driven via `page.emulateMedia({ colorScheme })` on first paint
 *    (default theme is "system") plus a forced `.dark`/`.light` class.
 *  - Service-worker registration is neutered so the PWA SW can't cache-stamp.
 *  - Fonts are awaited (`document.fonts.ready`) before any snapshot.
 *  - `animations: "disabled"` + `reducedMotion: "reduce"` kill transitions.
 *
 * Baselines live next to this file in `visual.spec.ts-snapshots/`. Update them
 * intentionally:
 *     npx playwright test visual --update-snapshots
 */

type Mode = "light" | "dark";

/** Pages that render without authentication (deterministic, zero-backend). */
const UNAUTH_ROUTES = [{ name: "login", path: "/" }] as const;

async function setTheme(page: Page, mode: Mode) {
  // Drive the "system" default via prefers-color-scheme, then force the class in
  // case a stored theme would otherwise win.
  await page.emulateMedia({ colorScheme: mode });
  await page.evaluate((m) => {
    const root = window.document.documentElement;
    root.classList.remove("light", "dark");
    root.classList.add(m);
  }, mode);
}

async function stabilize(page: Page) {
  await page.evaluate(() => (document.fonts ? document.fonts.ready : null));
  await page.waitForLoadState("networkidle");
}

test.beforeEach(async ({ page }) => {
  // Production builds fire the Atomic CRM telemetry pixel — block it.
  await page.route("**/atomic-crm-telemetry*", (r) => r.abort());
  // Defense-in-depth: block the PWA service-worker file itself, in case the
  // navigator.serviceWorker re-define below ever falls through (a future build
  // marking the prop non-configurable). Keeps the harness flake-free.
  await page.route("**/sw.js", (r) => r.abort());
  // The e2e build registers a PWA service worker — neuter it.
  await page.addInitScript(() => {
    try {
      // @ts-expect-error - intentional test shim
      Object.defineProperty(navigator, "serviceWorker", {
        configurable: true,
        value: {
          register: async () => ({ unregister: async () => true }),
          getRegistrations: async () => [],
          ready: Promise.resolve({ unregister: async () => true }),
        },
      });
    } catch {
      /* ignore — SW already absent */
    }
  });
});

for (const mode of ["light", "dark"] as const) {
  for (const route of UNAUTH_ROUTES) {
    test(`${route.name} renders (${mode})`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: mode });
      await page.goto(route.path);
      await setTheme(page, mode);

      // The login form is the anchor that tells us StartPage resolved to LoginPage.
      const email = page.locator('input[type="email"]').first();
      await expect(email).toBeVisible({ timeout: 15_000 });

      await stabilize(page);

      // Playwright appends `-<projectName>-<platform>` to the name, so desktop
      // and mobile baselines never collide.
      await expect(page).toHaveScreenshot(`${route.name}-${mode}.png`, {
        fullPage: true,
        maxDiffPixelRatio: 0.1,
        animations: "disabled",
        caret: "hide",
      });
    });
  }
}
