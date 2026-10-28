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
await page.goto(`${APP}/#/users`, { timeout: 30000 });
await page.waitForTimeout(2200);

// hover the first edit utility button to open its tooltip
const btn = page.locator("a.user-directory-action, .user-directory-action").first();
await btn.hover().catch((e) => console.log("hover failed", String(e).slice(0, 80)));
await page.waitForTimeout(700);
const tip = await page.evaluate(() => {
  const spans = [...document.querySelectorAll("span.text-white")].filter((s) => /Sửa|Kích hoạt|Vô hiệu|Đổi mật khẩu/.test(s.textContent || ""));
  return spans.map((s) => {
    const div = s.parentElement;
    const dcs = getComputedStyle(div);
    const scs = getComputedStyle(s);
    const r = div.getBoundingClientRect();
    return {
      text: s.textContent.trim().slice(0, 30),
      parentCls: (div.getAttribute("class") || "").slice(0, 100),
      parentBg: dcs.backgroundColor,
      spanColor: scs.color,
      rect: { w: r.width, h: r.height },
      opacity: dcs.opacity,
    };
  });
});
console.log("TOOLTIP " + JSON.stringify(tip, null, 1));
await page.screenshot({ path: "/Users/dev/.paseo/worktrees/2rn7uyc3/task-mobile-ux-audit/qa/2026-10-29-mobile-ux-audit/probe-tooltip-users.png" });
await browser.close();
