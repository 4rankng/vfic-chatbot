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

// performance table in view
await page.goto(`${APP}/#/hieu-suat`, { timeout: 30000 });
await page.waitForTimeout(2500);
await page.locator("table.performance-trend-data").scrollIntoViewIfNeeded().catch((e) => console.log("scroll fail", String(e).slice(0, 80)));
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/evidence-perf-table-390.png` });
console.log("SHOT evidence-perf-table-390");

// projects filter select + cards
await page.goto(`${APP}/#/projects`, { timeout: 30000 });
await page.waitForTimeout(2200);
await page.screenshot({ path: `${OUT}/evidence-projects-390.png` });
console.log("SHOT evidence-projects-390");

// settings groups (checklist/summaries small targets)
await page.goto(`${APP}/#/settings`, { timeout: 30000 });
await page.waitForTimeout(2200);
await page.mouse.wheel(0, 500).catch(() => {});
await page.waitForTimeout(600);
await page.screenshot({ path: `${OUT}/evidence-settings-scrolled-390.png` });
console.log("SHOT evidence-settings-scrolled-390");

// cloudfone panel
await page.goto(`${APP}/#/settings`, { timeout: 30000 });
await page.waitForTimeout(1500);
const cf = page.getByRole("button", { name: /Cloudfone/i }).first();
if ((await cf.count()) > 0) {
  await cf.click().catch(() => {});
  await page.waitForTimeout(1600);
  await page.screenshot({ path: `${OUT}/evidence-cloudfone-panel-390.png` });
  console.log("SHOT evidence-cloudfone-panel-390");
}

// knowledge sheet open
await page.goto(`${APP}/#/projects`, { timeout: 30000 });
await page.waitForTimeout(2200);
const card = page.locator("button.project-card-main").first();
await card.click().catch(() => {});
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/evidence-knowledge-sheet-390.png` });
console.log("SHOT evidence-knowledge-sheet-390");

// tablet settings
await page.setViewportSize({ width: 768, height: 1024 });
await page.goto(`${APP}/#/settings`, { timeout: 30000 });
await page.waitForTimeout(2200);
await page.screenshot({ path: `${OUT}/evidence-settings-768.png` });
console.log("SHOT evidence-settings-768");

await browser.close();
