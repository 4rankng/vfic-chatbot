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
// where is the table exactly?
const info = await page.evaluate(() => {
  const t = document.querySelector("table.performance-trend-data");
  if (!t) return { found: false };
  const r = t.getBoundingClientRect();
  let e = t.parentElement;
  const parents = [];
  while (e && e !== document.body) {
    const cs = getComputedStyle(e);
    parents.push({ cls: (e.getAttribute("class") || "").slice(0, 40), op: cs.opacity, disp: cs.display, ov: cs.overflowY + "/" + cs.overflowX, h: e.getBoundingClientRect().height });
    e = e.parentElement;
  }
  return {
    found: true,
    rect: { x: r.x, y: r.y, w: r.width, h: r.height },
    vis: getComputedStyle(t).visibility,
    op: getComputedStyle(t).opacity,
    display: getComputedStyle(t).display,
    firstRow: (t.querySelector("tr")?.innerText || "").replace(/\s+/g, " ").slice(0, 80),
    rowSamples: [...t.querySelectorAll("tr")].slice(0, 6).map((tr) => (tr.innerText || "").replace(/\s+/g, " | ").slice(0, 70)),
    parents,
    bodyScrollH: document.body.scrollHeight,
    innerH: innerHeight,
  };
});
console.log(JSON.stringify(info, null, 1));
await page.screenshot({ path: `${OUT}/evidence-perf-full-390.png`, fullPage: true });
console.log("SHOT evidence-perf-full-390 (fullPage)");
await browser.close();
