import { expect, test } from "./fixtures";

test.describe("current recruitment workspace baseline", () => {
  test("authenticates through FastAPI and renders the recruitment dashboard", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();

    await expect(
      page.getByRole("heading", { name: "Tổng quan tuyển dụng" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Ứng viên cần xử lý ngay" }),
    ).toBeVisible();
  });

  test("keeps the authenticated conversation inbox route reachable", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/conversations");

    await expect(page.getByRole("heading", { name: "Tin nhắn" })).toBeVisible({
      timeout: 15_000,
    });
  });
});
