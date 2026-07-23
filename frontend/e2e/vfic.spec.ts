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
  });

  test("loads a real conversation and preserves takeover/release behavior", async ({
    loginAsAdmin,
    page,
  }) => {
    await loginAsAdmin();
    await page.goto("/#/conversations");

    await expect(page.getByRole("heading", { name: "Hộp thư" })).toBeVisible({
      timeout: 15_000,
    });

    await page
      .getByRole("button", { name: /Mở hội thoại với/ })
      .first()
      .click();
    await expect(
      page
        .getByRole("log", { name: "Luồng tin nhắn" })
        .getByText("E2E bot reply", { exact: true }),
    ).toBeVisible();

    await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    const takeOverResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/take-over") && response.status() === 200,
    );
    await page.getByRole("menuitem").filter({ hasText: "Tư vấn viên" }).click();
    await takeOverResponse;
    await expect(
      page.getByRole("button", { name: "Đổi chế độ trả lời" }),
    ).toContainText("Tư vấn viên");

    await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
    const releaseResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/release") && response.status() === 200,
    );
    await page
      .getByRole("menuitem", { name: "Chatbot Chatbot tự động xử lý" })
      .click();
    await releaseResponse;
    await expect(
      page.getByRole("button", { name: "Đổi chế độ trả lời" }),
    ).toContainText("Chatbot");
  });
});
