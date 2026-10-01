import type { Locator } from "@playwright/test";

import { expect, test } from "./fixtures";

const frameStyle = (input: Locator) =>
  input.evaluate((element) => {
    const style = getComputedStyle(element.parentElement!);
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d")!;
    const luminance = (color: string) => {
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      const channels = [...context.getImageData(0, 0, 1, 1).data]
        .slice(0, 3)
        .map((value) => {
          const channel = value / 255;
          return channel <= 0.04045
            ? channel / 12.92
            : ((channel + 0.055) / 1.055) ** 2.4;
        });
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    };
    const outline = luminance(style.outlineColor);
    const background = luminance(style.backgroundColor);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      outlineColor: style.outlineColor,
      outlineOffset: style.outlineOffset,
      backgroundColor: style.backgroundColor,
      height: element.parentElement!.getBoundingClientRect().height,
      boxShadow: style.boxShadow,
      contrast:
        (Math.max(outline, background) + 0.05) /
        (Math.min(outline, background) + 0.05),
    };
  });

test(
  "keeps authentication fields visibly bounded with flat surfaces",
  {
    tag: "@visual-only",
  },
  async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const email = page.getByRole("textbox", { name: /^Email/ });
    const password = page.getByLabel(/^Mật khẩu\s*\*?$/);
    await expect(email).toBeVisible();
    await expect(password).toBeVisible();

    const idle = await frameStyle(email);
    for (const field of [email, password]) {
      const style = await frameStyle(field);
      expect(style.outlineStyle).toBe("solid");
      expect(style.outlineWidth).toBe("1px");
      expect(style.outlineColor).not.toBe(style.backgroundColor);
      expect(style.outlineColor).not.toBe("rgba(0, 0, 0, 0)");
      expect(style.boxShadow).toBe("none");
      expect(style.contrast).toBeGreaterThanOrEqual(3);
    }

    await email.focus();
    await expect
      .poll(async () => (await frameStyle(email)).outlineWidth)
      .toBe("2px");
    const focused = await frameStyle(email);
    expect(focused.outlineColor).not.toBe(idle.outlineColor);
    expect(focused.height).toBe(idle.height);

    await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
    await expect(email).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByText("Vui lòng nhập email.")).toBeVisible();
    await expect
      .poll(async () => (await frameStyle(email)).outlineColor)
      .not.toBe(focused.outlineColor);
    expect((await frameStyle(email)).height).toBe(idle.height);

    await page.getByRole("link", { name: "Quên mật khẩu?" }).click();
    await expect(page).toHaveURL(/#\/forgot-password$/);
    await expect(
      page.getByRole("heading", { name: "Khôi phục mật khẩu", exact: true }),
    ).toBeVisible();
    const recoveryEmail = page.getByRole("textbox", { name: /Email/ });
    await expect(recoveryEmail).toBeVisible();
    const recovery = await frameStyle(recoveryEmail);
    expect(recovery.outlineStyle).toBe("solid");
    expect(recovery.outlineWidth).toBe("1px");
    expect(recovery.outlineColor).not.toBe(recovery.backgroundColor);
    expect(recovery.contrast).toBeGreaterThanOrEqual(3);
  },
);

test("keeps workspace fields distinct from the card separators", async ({
  loginAsAdmin,
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await loginAsAdmin();
  await page.goto("/#/users/create");
  const email = page.getByRole("textbox", { name: /^Email/ });
  await expect(email).toBeVisible();
  const idle = await frameStyle(email);
  expect(idle.outlineStyle).toBe("solid");
  expect(idle.outlineWidth).toBe("1px");
  expect(idle.contrast).toBeGreaterThanOrEqual(3);
  expect(idle.boxShadow).toBe("none");

  await email.focus();
  await expect
    .poll(async () => (await frameStyle(email)).outlineWidth)
    .toBe("2px");
  const focused = await frameStyle(email);
  expect(focused.outlineColor).not.toBe(idle.outlineColor);
  expect(focused.height).toBe(idle.height);

  await page
    .getByRole("button", { name: "Tạo tài khoản", exact: true })
    .click();
  await expect(email).toHaveAttribute("aria-invalid", "true");
  await expect
    .poll(async () => (await frameStyle(email)).outlineColor)
    .not.toBe(focused.outlineColor);
  expect((await frameStyle(email)).height).toBe(idle.height);
});
