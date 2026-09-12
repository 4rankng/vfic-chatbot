import { execFile } from "node:child_process";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { expect, test as base, type Page } from "@playwright/test";

const execFileAsync = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_PYTHON =
  process.env.VFIC_BACKEND_PYTHON ??
  path.resolve(__dirname, "../../backend/.venv/bin/python");
const E2E_HARNESS = path.resolve(
  __dirname,
  "../../backend/tests/e2e_harness.py",
);

export const ADMIN_EMAIL = "admin@example.org";
export const ADMIN_PASSWORD = "Universal-E2E-Only-42!";

async function resetDatabase(): Promise<void> {
  await execFileAsync(
    BACKEND_PYTHON,
    [
      E2E_HARNESS,
      "reset",
      "--email",
      ADMIN_EMAIL,
      "--password",
      ADMIN_PASSWORD,
    ],
    { env: process.env, timeout: 120_000 },
  );
}

async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto("/");
  await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/auth/login") &&
      response.status() === 200,
  );
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await loginResponse;
  await expect(page.getByRole("heading", { name: "Tổng quan" })).toBeVisible({
    timeout: 15_000,
  });
}

export const test = base.extend<{
  resetDb: void;
  networkGuard: void;
  loginAsAdmin: () => Promise<void>;
}>({
  resetDb: [
    // Playwright requires object destructuring for fixture dependency analysis.
    // eslint-disable-next-line no-empty-pattern
    async ({}, provide) => {
      await resetDatabase();
      await provide();
    },
    { auto: true },
  ],
  networkGuard: [
    async ({ page }, provide) => {
      const blockedExternalRequests: string[] = [];
      await page.route("**/*", async (route) => {
        const url = new URL(route.request().url());
        const external =
          ["http:", "https:", "ws:", "wss:"].includes(url.protocol) &&
          !["127.0.0.1", "localhost"].includes(url.hostname);
        if (external) {
          blockedExternalRequests.push(route.request().url());
          await route.abort("blockedbyclient");
          return;
        }
        await route.continue();
      });
      await provide();
      const unexpected = blockedExternalRequests.filter(
        (requestUrl) =>
          !["fonts.googleapis.com", "fonts.gstatic.com"].includes(
            new URL(requestUrl).hostname,
          ),
      );
      expect(unexpected).toEqual([]);
    },
    { auto: true },
  ],
  loginAsAdmin: async ({ page }, provide) => {
    await provide(() => loginAsAdmin(page));
  },
});

export { expect };
