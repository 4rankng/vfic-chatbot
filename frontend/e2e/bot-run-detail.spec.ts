import { expect, test } from "./fixtures";

test.describe("bot-run audit journey", () => {
  test("renders the seeded run row and its fact sheet", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/bot_runs");

    await expect(
      page.getByRole("heading", { name: "Lần chạy bot" }),
    ).toBeVisible({ timeout: 15_000 });

    // Audit rows contain both a reply preview and outcome metadata. The global
    // compact-control ceiling must not clip one into the next row on phones.
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 844 });
      const row = page.locator(".bot-run-row").first();
      await expect(row).toBeVisible();
      const bounds = await row.evaluate((element) => {
        const frame = element.getBoundingClientRect();
        const content = element.firstElementChild!.getBoundingClientRect();
        return {
          height: frame.height,
          topInset: content.top - frame.top,
          bottomInset: frame.bottom - content.bottom,
        };
      });
      expect(bounds.height).toBeGreaterThanOrEqual(64);
      expect(bounds.topInset).toBeGreaterThanOrEqual(0);
      expect(bounds.bottomInset).toBeGreaterThanOrEqual(0);
    }

    await page.getByText("E2E bot reply").first().click();

    await expect(
      page.getByRole("heading", { name: /Lần chạy bot #/ }),
    ).toBeVisible({ timeout: 15_000 });
    // The detail page is a fact sheet only: the run carries no thinking log.
    await expect(page.getByText("Dấu vết quyết định")).toHaveCount(0);
    await expect(page.getByText("Lượt suy luận")).toHaveCount(0);
  });
});
