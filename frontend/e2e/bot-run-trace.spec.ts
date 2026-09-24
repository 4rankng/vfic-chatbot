import { expect, test } from "./fixtures";

test.describe("bot-run trace journey", () => {
  test("renders the seeded run row and its decision-trace detail", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/bot_runs");

    await expect(
      page.getByRole("heading", { name: "Lần chạy bot" }),
    ).toBeVisible({ timeout: 15_000 });

    await page.getByText("E2E bot reply").first().click();

    await expect(
      page.getByRole("heading", { name: /Lần chạy bot #/ }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("minimax-m2").first()).toBeVisible();
  });
});
