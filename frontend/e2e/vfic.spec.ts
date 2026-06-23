import { test, expect } from "@playwright/test";

// These smoke tests are aspirational: the app uses `requireAuth` (Supabase
// session), so navigating to "/" without an authenticated session redirects to
// the login page — the dashboard assertions below never hold. They are kept as
// `.fixme` so the suite stays green and the intent is recorded. Re-enable per
// route once an authenticated e2e fixture (seeded local Supabase or an
// e2e-only auth bypass) is in place. See e2e/visual.spec.ts for the working
// unauthenticated baseline.
test.describe.fixme("VFIC CRM end-to-end", () => {
  test("should navigate to the dashboard successfully", async ({ page }) => {
    // We assume the app is running on the local dev server and standard auth is bypassed/mocked or not required on dashboard
    // If auth is required, we would use a fixture to log in.
    await page.goto("/");

    // Check if the dashboard title is visible
    await expect(page.locator("text=Analytics Overview")).toBeVisible({
      timeout: 10000,
    });

    // Check if KPI cards are visible
    await expect(page.locator("text=Total Leads")).toBeVisible();
    await expect(page.locator("text=Active Conversations")).toBeVisible();
  });

  test("should navigate to leads pipeline", async ({ page }) => {
    await page.goto("/leads");

    // Check if the title is visible
    await expect(page.locator("text=Leads Pipeline")).toBeVisible({
      timeout: 10000,
    });

    // Check if pipeline stages are visible
    await expect(page.locator("text=NEW")).toBeVisible();
    await expect(page.locator("text=QUALIFIED")).toBeVisible();
    await expect(page.locator("text=INTERVIEWING")).toBeVisible();
  });

  test("should navigate to conversations inbox", async ({ page }) => {
    await page.goto("/conversations");

    // Check if the title is visible
    await expect(page.locator("text=Conversations")).toBeVisible({
      timeout: 10000,
    });
  });

  test("should navigate to profiles management", async ({ page }) => {
    await page.goto("/profiles");

    // Check if the title is visible
    await expect(page.locator("text=Profiles")).toBeVisible({ timeout: 10000 });
  });
});
