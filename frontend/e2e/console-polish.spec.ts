import { expect, test } from "./fixtures";

test("keeps a long tablet form reachable and focuses its validation error", async ({
  page,
  loginAsAdmin,
}) => {
  await loginAsAdmin();
  await page.setViewportSize({ width: 900, height: 540 });
  await page.goto("/#/users/create");
  await expect(
    page.getByRole("heading", { name: "Tạo tài khoản", exact: true }),
  ).toBeVisible();
  const email = page.getByRole("textbox", { name: /^Email\s*\*?$/ });
  await page
    .getByRole("button", { name: "Tạo tài khoản", exact: true })
    .click();
  await expect(email).toBeFocused();
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await email.fill("new-admin@example.org");
  await page
    .getByRole("textbox", { name: /^Họ và tên\s*\*?$/ })
    .fill("Quản trị viên mới");
  await page.getByLabel(/^Mật khẩu\s*\*?$/).fill("Local-Only-Admin-42!");
  await page
    .getByLabel(/^Xác nhận mật khẩu\s*\*?$/)
    .fill("Local-Only-Admin-42!");
  const saved = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/v1/users"),
  );
  await page
    .getByRole("button", { name: "Tạo tài khoản", exact: true })
    .click();
  expect((await saved).status()).toBe(201);
  await expect(
    page.getByRole("heading", { name: "Tài khoản", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("new-admin@example.org", { exact: true }),
  ).toBeVisible();
});

test("skip navigation focuses the workspace without changing its route", async ({
  page,
  loginAsAdmin,
}) => {
  await loginAsAdmin();
  await page.goto("/#/projects");
  await expect(
    page.getByRole("heading", { name: "Dự án tuyển dụng", exact: true }),
  ).toBeVisible();
  const skip = page.getByRole("link", {
    name: "Bỏ qua điều hướng",
    exact: true,
  });
  await skip.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page).toHaveURL(/#\/projects$/);
});

test("keyboard command navigation stays inside the hash-routed workspace", async ({
  page,
  loginAsAdmin,
}) => {
  await loginAsAdmin();
  await page.keyboard.press("Control+k");
  await expect(
    page.getByPlaceholder("Tìm kiếm hoặc chuyển nhanh"),
  ).toBeFocused();
  const project = page.getByRole("option", { name: "Dự án", exact: true });
  await expect(project).toHaveAttribute("href", "#/projects");
  await project.click();
  await expect(page).toHaveURL(/#\/projects$/);
  await expect(
    page.getByRole("heading", { name: "Dự án tuyển dụng", exact: true }),
  ).toBeVisible();
});

test("renders real project detail at short phone and tablet sizes", async ({
  page,
  loginAsAdmin,
}, testInfo) => {
  test.setTimeout(120_000);
  await loginAsAdmin();
  for (const width of [390, 900, 1440]) {
    await page.setViewportSize({ width, height: 650 });
    await page.goto("/#/projects");
    await expect(
      page.getByRole("heading", { name: "E2E Project", exact: true }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Mở hoặc đóng kiến thức dự án E2E Project" })
      .click();
    await page.getByRole("button", { name: "Sửa dự án", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "E2E Project", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("textbox", { name: /^Tên dự án\s*\*?$/ }),
    ).toBeVisible();
    await expect(
      page.locator('#project-category-detail[aria-busy="true"]'),
    ).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath(`project-edit-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
    await expect
      .poll(() =>
        page.evaluate(
          () =>
            document.documentElement.scrollWidth -
            document.documentElement.clientWidth,
        ),
      )
      .toBeLessThanOrEqual(1);
  }
});

test("keeps every settings section accessible through desktop navigation and the phone drawer", async ({
  page,
  loginAsAdmin,
}, testInfo) => {
  test.setTimeout(120_000);
  await loginAsAdmin();
  for (const width of [390, 1440]) {
    await page.setViewportSize({ width, height: 650 });
    await page.goto("/#/settings");
    for (const [label, heading] of [
      ["Zalo", "Zalo"],
      ["Messenger", "Messenger"],
      ["AI Providers", "AI Providers"],
      ["Jev", "Jev"],
      ["TingTing", "TingTing · Đặt lại mật khẩu"],
      ["Người dùng", "Người dùng"],
    ]) {
      const mobile = width < 768;
      if (mobile) {
        await page
          .getByRole("button", { name: "Mở danh mục cài đặt", exact: true })
          .click();
      }
      const navigation = mobile
        ? page.getByRole("navigation", { name: "Mục cài đặt", exact: true })
        : page.getByRole("complementary", {
            name: "Nhóm cài đặt",
            exact: true,
          });
      await navigation
        .getByRole("button", { name: new RegExp(`^${label} `) })
        .click();
      if (mobile) {
        await expect(navigation).not.toBeVisible();
      }
      await expect(
        page.getByRole("heading", { name: heading, exact: true }).first(),
      ).toBeVisible();
      await page.evaluate(() => document.fonts.ready);
      await expect(page.locator('main [aria-busy="true"]')).toHaveCount(0);
      await expect(page.locator('main [data-slot="skeleton"]')).toHaveCount(0);
      await expect
        .poll(() =>
          page.evaluate(
            () =>
              document.documentElement.scrollWidth -
              document.documentElement.clientWidth,
          ),
        )
        .toBeLessThanOrEqual(1);
      await page.screenshot({
        path: testInfo.outputPath(`settings-${label}-${width}.png`),
        fullPage: true,
        animations: "disabled",
      });
    }
  }
});
