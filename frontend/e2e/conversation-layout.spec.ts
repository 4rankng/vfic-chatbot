import { expect, test } from "./fixtures";

test("follows transcript layout changes without native observer errors", async ({
  page,
  loginAsAdmin,
}) => {
  // Listen to the real browser event without intercepting it: the installed
  // virtualizer's measurements and the app observers must settle together.
  await page.addInitScript(() => {
    const layoutErrors: string[] = [];
    window.addEventListener("error", (event) => {
      layoutErrors.push(event.message);
    });
    Object.assign(window, { conversationLayoutErrors: layoutErrors });
  });
  const settleLayout = () =>
    page.evaluate(async () => {
      await document.fonts.ready;
      for (let frame = 0; frame < 4; frame++) {
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => resolve()),
        );
      }
    });

  await loginAsAdmin();
  await page.goto("/#/conversations");
  await expect(page.getByRole("heading", { name: "Hộp thư" })).toBeVisible();
  await page
    .getByRole("button", { name: /Mở hội thoại với/ })
    .first()
    .click();
  const latestMessage = page
    .getByRole("log", { name: "Luồng tin nhắn" })
    .getByText("E2E bot reply", { exact: true });
  await expect(latestMessage).toBeVisible();
  await settleLayout();

  await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
  const takeover = page.waitForResponse(
    (response) =>
      response.url().endsWith("/take-over") && response.status() === 200,
  );
  await page.getByRole("menuitem").filter({ hasText: "Tư vấn viên" }).click();
  await takeover;
  const composer = page.getByPlaceholder("Nhập tin nhắn...");
  await composer.fill(
    Array.from({ length: 8 }, () => "Một dòng tư vấn").join("\n"),
  );
  await settleLayout();
  await expect(latestMessage).toBeVisible();
  await composer.fill("");

  await page.getByRole("button", { name: "Đổi chế độ trả lời" }).click();
  const release = page.waitForResponse(
    (response) =>
      response.url().endsWith("/release") && response.status() === 200,
  );
  await page.getByRole("menuitem", { name: /^Chatbot\s/ }).click();
  await release;
  for (const width of [360, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await settleLayout();
    await expect(latestMessage).toBeVisible();
  }
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { conversationLayoutErrors: string[] })
          .conversationLayoutErrors,
    ),
  ).toEqual([]);
});
