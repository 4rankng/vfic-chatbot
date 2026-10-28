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
await page.goto(`${APP}/#/hieu-suat`, { timeout: 30000 });
await page.waitForTimeout(3000);
const probe = await page.evaluate(() => {
  const t = document.querySelector("table.performance-trend-data");
  const td = t.querySelector("tbody td") || t.querySelector("td");
  const th = t.querySelector("th");
  const csTd = td ? getComputedStyle(td) : null;
  const csT = getComputedStyle(t);
  // what element is actually painted at the table's first-cell center?
  const r = td ? td.getBoundingClientRect() : null;
  const hit = r ? document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) : null;
  return {
    tableStyle: { color: csT.color, bg: csT.backgroundColor, visibility: csT.visibility, borderCollapse: csT.borderCollapse, fontSize: csT.fontSize },
    tdStyle: csTd ? { color: csTd.color, bg: csTd.backgroundColor, fontSize: csTd.fontSize, visibility: csTd.visibility, text: (td.innerText || "").slice(0, 20) } : null,
    thStyle: th ? { color: getComputedStyle(th).color, text: (th.innerText || "").slice(0, 20) } : null,
    tdRect: r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null,
    hitAtTdCenter: hit ? { tag: hit.tagName, cls: (hit.getAttribute("class") || "").slice(0, 60) } : null,
  };
});
console.log(JSON.stringify(probe, null, 1));
const t = page.locator("table.performance-trend-data");
await t.screenshot({ path: `${OUT}/evidence-perf-table-element.png` }).catch((e) => console.log("elem shot fail", String(e).slice(0, 100)));
console.log("SHOT evidence-perf-table-element");
await browser.close();
