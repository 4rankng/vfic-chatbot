/**
 * Captures the viewer's empty-day explanations (the day the system checked
 * but could not transcribe, and the day without a call).
 *
 *   node plans/qa-261021/cloudfone-transcripts-empty-states.mjs
 */
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("../../frontend/node_modules/@playwright/test");

const APP = "http://127.0.0.1:4173";
const ARTIFACTS = path.resolve(path.dirname(new URL(import.meta.url).pathname));
const LOG = path.join(ARTIFACTS, "cloudfone-transcripts-empty-states.log");
const lines = [];
const log = (message) => {
  lines.push(message);
  console.log(message);
  fs.writeFileSync(LOG, lines.join("\n") + "\n");
};

const setDay = async (page, value) => {
  await page.evaluate((day) => {
    const input = document.querySelector("#cloudfone-transcripts-day");
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set;
    setter.call(input, day);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }, value);
};

const main = async () => {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.goto(APP);
  await page.locator('input[type="email"]').fill("admin@example.org");
  await page.locator('input[type="password"]').fill("Universal-E2E-Only-42!");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page.getByRole("heading", { name: "Tổng quan" }).waitFor({ timeout: 20_000 });
  log("login: ok");

  await page.goto(`${APP}/#/settings`);
  await page.getByRole("button", { name: "Cloudfone Phân tích cuộc gọi" }).click();
  await page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await page
    .getByRole("heading", { name: "Cloudfone · Bản ghi cuộc gọi" })
    .waitFor({ timeout: 15_000 });
  log("viewer: opened");

  // A checked day whose recordings could not be transcribed.
  await setDay(page, "2026-10-18");
  const untranscribable = page.getByText("Không chuyển được bản ghi sang văn bản");
  await untranscribable.waitFor({ timeout: 30_000 });
  const explanation = page.getByText(/cuộc gọi có bản ghi nhưng không chuyển sang văn bản/);
  await explanation.waitFor({ timeout: 10_000 });
  log(`untranscribable day: "${await untranscribable.innerText()}" — ${await explanation.innerText()}`);
  await page.screenshot({
    path: path.join(ARTIFACTS, "cloudfone-transcripts-untranscribable-day.png"),
    fullPage: true,
  });

  // A checked day without a single call.
  await setDay(page, "2026-10-19");
  const noCalls = page.getByText(/không có cuộc gọi nào/);
  await noCalls.waitFor({ timeout: 30_000 });
  log(`call-free day: "${await noCalls.innerText()}"`);
  await page.screenshot({
    path: path.join(ARTIFACTS, "cloudfone-transcripts-call-free-day.png"),
    fullPage: true,
  });

  await browser.close();
  log("driver: ok");
};

main().catch((error) => {
  log(`driver: FAILED → ${error.message}`);
  process.exit(1);
});
