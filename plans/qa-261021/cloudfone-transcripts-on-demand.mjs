/**
 * Drives the Cloudfone transcripts viewer against the local stack
 * (disposable DB + mock vendor) and captures the artifacts the UI
 * verification contract asks for: screenshots, DOM assertions and a log.
 *
 *   node qa/cloudfone-transcripts-on-demand.mjs
 */
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

// Playwright lives in the frontend workspace; resolve it from there.
const require = createRequire(import.meta.url);
const { chromium } = require("../frontend/node_modules/@playwright/test");

const APP = "http://127.0.0.1:4173";
const API = "http://127.0.0.1:8000";
const ARTIFACTS = path.resolve(path.dirname(new URL(import.meta.url).pathname));
const LOG = path.join(ARTIFACTS, "cloudfone-transcripts-on-demand.log");
const EMAIL = "admin@example.org";
const PASSWORD = "Universal-E2E-Only-42!";
const CALL_DAY = "2026-10-20";
const EMPTY_DAY = "2026-10-19";

const lines = [];
const log = (message) => {
  lines.push(message);
  console.log(message);
  fs.writeFileSync(LOG, lines.join("\n") + "\n");
};

const psql = (sql) =>
  execFileSync(
    "docker",
    ["exec", "backend-postgres-1", "psql", "-U", "vfic", "-d", "vfic_verify01_e2e", "-tAc", sql],
    { encoding: "utf8" },
  ).trim();

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
  log(`run at ${new Date().toISOString()}`);

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const network = [];
  page.on("request", (request) => {
    if (request.url().includes("/cloudfone/transcripts")) {
      network.push(`${request.method()} ${request.url().replace(API, "")}`);
    }
  });

  // 1. Log in as the admin.
  await page.goto(APP);
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page.getByRole("heading", { name: "Tổng quan" }).waitFor({ timeout: 20_000 });
  log("login: ok (dashboard heading visible)");

  // 2. Settings → Cloudfone → the transcripts viewer.
  await page.goto(`${APP}/#/settings`);
  await page.getByRole("button", { name: "Cloudfone Phân tích cuộc gọi" }).click();
  await page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await page
    .getByRole("heading", { name: "Cloudfone · Bản ghi cuộc gọi" })
    .waitFor({ timeout: 15_000 });
  log("viewer: opened");

  // 3. A day the system never checked → the viewer fetches it on demand.
  await setDay(page, CALL_DAY);
  await page
    .getByRole("row", { name: /0902113344/ })
    .waitFor({ timeout: 60_000 });
  const rowText = await page.getByRole("row", { name: /0902113344/ }).innerText();
  log(`day ${CALL_DAY}: row rendered → ${rowText.replace(/\s+/g, " ").trim()}`);
  await page.screenshot({
    path: path.join(ARTIFACTS, "cloudfone-transcripts-fetched-day.png"),
    fullPage: true,
  });

  // 4. The stored transcript opens in the detail panel.
  await page
    .getByRole("row", { name: /0902113344/ })
    .getByRole("button", { name: "Xem", exact: true })
    .click();
  const detail = page.getByText(/chị gửi em thông tin hàng để em báo giá chính xác/);
  await detail.waitFor({ timeout: 20_000 });
  log(`detail panel: ${(await detail.innerText()).replace(/\s+/g, " ").trim()}`);
  await page.screenshot({
    path: path.join(ARTIFACTS, "cloudfone-transcripts-detail.png"),
    fullPage: true,
  });

  // 5. A day with no calls → checked once, then known (and not fetched again).
  await setDay(page, EMPTY_DAY);
  const emptyTitle = page.getByText("Ngày này không có bản ghi");
  await emptyTitle.waitFor({ timeout: 60_000 });
  log(`day ${EMPTY_DAY}: empty state → "${await emptyTitle.innerText()}"`);
  await page.screenshot({
    path: path.join(ARTIFACTS, "cloudfone-transcripts-known-empty-day.png"),
    fullPage: true,
  });

  // Re-open the same known day: no second vendor fetch.
  const callsBefore = network.filter((entry) => entry.startsWith("POST")).length;
  await page.getByRole("button", { name: "Quay lại cài đặt Cloudfone" }).click();
  await page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await setDay(page, EMPTY_DAY);
  await emptyTitle.waitFor({ timeout: 30_000 });
  await page.waitForTimeout(2000);
  const callsAfter = network.filter((entry) => entry.startsWith("POST")).length;
  log(
    `known day reopened: backfill POSTs before=${callsBefore} after=${callsAfter} (no new fetch expected)`,
  );
  if (callsAfter !== callsBefore) {
    throw new Error(`known day was fetched again (${callsBefore} → ${callsAfter})`);
  }

  // 6. The database side effects.
  const transcripts = psql(
    "select call_id || ' | ' || day || ' | ' || caller || ' | ' || talk_seconds from cloudfone_call_transcripts order by created_at",
  );
  const days = psql(
    "select day || ' | ' || status || ' | calls=' || call_count || ' | transcripts=' || transcript_count from cloudfone_transcript_days order by day",
  );
  log(`db cloudfone_call_transcripts:\n${transcripts}`);
  log(`db cloudfone_transcript_days:\n${days}`);
  log(`network calls:\n${network.join("\n")}`);

  await browser.close();
  log("driver: ok");
};

main().catch((error) => {
  log(`driver: FAILED → ${error.message}`);
  process.exit(1);
});
