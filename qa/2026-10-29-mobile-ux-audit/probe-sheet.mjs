import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = createRequire("/Volumes/LexarSSD/projects/chatbot/frontend/package.json")("@playwright/test");
const APP = "http://127.0.0.1:4173";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, locale: "vi-VN" });
await page.goto(`${APP}/`, { timeout: 60000 });
await page.locator('input[type="email"]').fill("admin@vfic.dev");
await page.locator('input[type="password"]').fill("admin123");
await page.getByRole("button", { name: "Đăng nhập" }).click();
await page.waitForTimeout(2500);
await page.goto(`${APP}/#/projects`, { timeout: 30000 });
await page.waitForTimeout(2200);
await page.locator("button.project-card-main").first().click();
await page.waitForTimeout(1500);

const modal = await page.evaluate(() => {
  const sheet = document.querySelector(".project-knowledge-sheet");
  const overlay = sheet ? sheet.closest("[role='dialog'], .fixed") : null;
  const dialog = document.querySelector("[role='dialog']");
  const closeButtons = [...document.querySelectorAll("button, a")].filter((b) => /đóng|close|x$/i.test((b.getAttribute("aria-label") || b.innerText || "").trim()));
  return {
    sheetCls: sheet ? (sheet.getAttribute("class") || "").slice(0, 80) : null,
    dialogRole: dialog ? { role: dialog.getAttribute("role"), ariaModal: dialog.getAttribute("aria-modal"), label: dialog.getAttribute("aria-label") || dialog.getAttribute("aria-labelledby") } : null,
    closeCandidates: closeButtons.map((b) => ({ tag: b.tagName, label: (b.getAttribute("aria-label") || b.innerText || "").trim().slice(0, 30) })),
  };
});
console.log("MODAL " + JSON.stringify(modal, null, 1));

// 1) tap the scrim (top 20% of screen)
await page.mouse.click(195, 120);
await page.waitForTimeout(900);
console.log("after scrim tap, sheet count =", await page.locator(".project-knowledge-sheet").count());

// reopen if closed, then try Escape
if ((await page.locator(".project-knowledge-sheet").count()) === 0) {
  await page.locator("button.project-card-main").first().click();
  await page.waitForTimeout(1200);
}
await page.keyboard.press("Escape");
await page.waitForTimeout(700);
console.log("after Escape, sheet count =", await page.locator(".project-knowledge-sheet").count());
await browser.close();
