import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = createRequire("/Volumes/LexarSSD/projects/chatbot/frontend/package.json")("@playwright/test");
const APP = "http://127.0.0.1:4173";
const OUT = "/Users/dev/.paseo/worktrees/2rn7uyc3/task-mobile-ux-audit/qa/2026-10-29-mobile-ux-audit";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, locale: "vi-VN" });
await page.goto(`${APP}/`, { timeout: 60000 });
await page.locator('input[type="email"]').fill("admin@vfic.dev");
await page.locator('input[type="password"]').fill("admin123");
await page.getByRole("button", { name: "Đăng nhập" }).click();
await page.waitForTimeout(2500);

// 1) projects card geometry
await page.goto(`${APP}/#/projects`, { timeout: 30000 });
await page.waitForTimeout(2200);
const geo = await page.evaluate(() => {
  const btn = document.querySelector("button.project-card-main");
  const card = btn ? btn.parentElement : null;
  const badges = btn ? btn.querySelector(".project-card-badges") : null;
  const pill = badges ? badges.firstElementChild : null;
  const cs = btn ? getComputedStyle(btn) : null;
  const rect = (e) => (e ? (({ x, y, width: w, height: h }) => ({ x: +x.toFixed(1), y: +y.toFixed(1), w: +w.toFixed(1), h: +h.toFixed(1) }))(e.getBoundingClientRect()) : null);
  return {
    btn: rect(btn),
    btnStyle: cs ? { height: cs.height, minHeight: cs.minHeight, overflow: cs.overflow, display: cs.display, padding: cs.padding } : null,
    card: rect(card),
    cardCls: card ? (card.getAttribute("class") || "").slice(0, 50) : null,
    badges: rect(badges),
    pill: rect(pill),
    btnScrollH: btn ? btn.scrollHeight : null,
    overflowPx: badges && btn ? +(badges.getBoundingClientRect().bottom - btn.getBoundingClientRect().bottom).toFixed(1) : null,
  };
});
console.log("CARD-GEO " + JSON.stringify(geo, null, 1));
await page.screenshot({ path: `${OUT}/evidence-project-card-closeup.png` });

// 2) users delete confirmation check (do NOT confirm anything)
await page.goto(`${APP}/#/users`, { timeout: 30000 });
await page.waitForTimeout(2200);
const delBtn = page.locator(".user-directory-action").nth(3);
const delInfo = await delBtn.evaluate((e) => ({
  tag: e.tagName,
  label: e.getAttribute("aria-label") || (e.innerText || "").trim().slice(0, 30),
  cls: (e.getAttribute("class") || "").slice(0, 60),
}));
console.log("DEL-BTN " + JSON.stringify(delInfo));
await delBtn.click().catch((e) => console.log("del click failed", String(e).slice(0, 80)));
await page.waitForTimeout(1200);
const dlg = await page.evaluate(() => {
  const dialogs = [...document.querySelectorAll("[role='dialog'], [role='alertdialog']")];
  return dialogs.map((d) => ({
    role: d.getAttribute("role"),
    text: (d.innerText || "").replace(/\s+/g, " ").slice(0, 160),
    buttons: [...d.querySelectorAll("button")].map((b) => (b.innerText || b.getAttribute("aria-label") || "").trim().slice(0, 24)),
  }));
});
console.log("AFTER-DEL-CLICK dialogs=" + JSON.stringify(dlg, null, 1));
console.log("url now:", page.url());
await page.screenshot({ path: `${OUT}/evidence-users-delete-check.png` });
await browser.close();
