import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = createRequire("/Volumes/LexarSSD/projects/chatbot/frontend/package.json")("@playwright/test");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
page.on("response", async (r) => {
  if (r.url().includes("/api/")) {
    let body = "";
    try { body = (await r.text()).slice(0, 300); } catch {}
    console.log("RESP", r.status(), r.url(), body);
  }
});
page.on("console", (m) => { if (m.type() === "error") console.log("CONSOLE", m.text().slice(0, 200)); });
await page.goto("http://127.0.0.1:4173/", { timeout: 60000 });
await page.locator('input[type="email"]').waitFor({ timeout: 30000 });
console.log("inputs:", await page.locator("input").evaluateAll((els) => els.map((e) => ({ type: e.type, name: e.name, ph: e.placeholder }))));
await page.locator('input[type="email"]').fill("admin@vfic.dev");
await page.locator('input[type="password"]').fill("admin123");
await page.getByRole("button", { name: "Đăng nhập" }).click();
await page.waitForTimeout(4000);
console.log("url after:", page.url());
console.log("body text:", (await page.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 500));
await page.screenshot({ path: "/Users/dev/.paseo/worktrees/2rn7uyc3/task-mobile-ux-audit/qa/2026-10-29-mobile-ux-audit/probe-login.png" });
await browser.close();
