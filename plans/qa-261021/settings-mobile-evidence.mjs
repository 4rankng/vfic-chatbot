/**
 * Captures the 390×844 settings-mobile evidence the UI verification contract
 * asks for: before/after screenshots of every flow step —
 *   (1) settings entry: 3 grouped cards → (2) drill-down Cloudfone →
 *   (3) transcripts call list → (4) tap call → sheet at 50% →
 *   (5) drag the sheet to full → (6) transcript bubbles —
 * plus DOM geometry assertions and a driver log.
 *
 *   node plans/qa-261021/settings-mobile-evidence.mjs before|after
 *
 * `before` runs against the pre-overhaul UI (mobile drawer nav, transcript
 * panel below the list); `after` runs against the drill-down + bottom-sheet UI.
 * Both need the local stack: uvicorn on :8000 (dev DB, seeded via
 * settings-mobile-seed.sql) and the Vite dev server on :5173.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("../../frontend/node_modules/@playwright/test");

const APP = "http://localhost:5173";
const ARTIFACTS = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "../../qa/2026-10-21-settings-mobile",
);
const STAGE = process.argv[2] ?? "after";
const LOG = path.join(ARTIFACTS, `${STAGE}-driver.log`);
const EMAIL = "admin@vfic.dev";
const PASSWORD = "admin123";

if (!["before", "after"].includes(STAGE)) {
  throw new Error(
    `usage: settings-mobile-evidence.mjs before|after (got ${STAGE})`,
  );
}

const lines = [];
const log = (message) => {
  lines.push(message);
  console.log(message);
  fs.writeFileSync(LOG, lines.join("\n") + "\n");
};

const shot = async (page, name) => {
  const file = path.join(ARTIFACTS, `${STAGE}-${name}.png`);
  await page.screenshot({ path: file });
  log(`shot ${path.basename(file)}`);
};

const boxOf = async (locator, label) => {
  const box = await locator.boundingBox();
  log(
    `${label}: x=${Math.round(box?.x ?? -1)} y=${Math.round(box?.y ?? -1)} ` +
      `w=${Math.round(box?.width ?? -1)} h=${Math.round(box?.height ?? -1)}`,
  );
  return box;
};

let page;

const main = async () => {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  log(`stage=${STAGE} run at ${new Date().toISOString()}`);

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  page = await context.newPage();

  // ---- Login -------------------------------------------------------------
  await page.goto(`${APP}/`);
  await page.getByRole("heading", { name: "Đăng nhập" }).waitFor();
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page
    .getByRole("heading", { name: "Tổng quan" })
    .waitFor({ timeout: 20_000 });
  log("login: signed in as admin");

  // ---- 1. Settings entry -------------------------------------------------
  await page.goto(`${APP}/#/settings`);
  if (STAGE === "before") {
    await page
      .getByRole("button", { name: "Mở danh mục cài đặt" })
      .waitFor({ timeout: 15_000 });
    await shot(page, "settings-3groups");
  } else {
    await page.getByText("Kênh & Tích hợp").waitFor({ timeout: 15_000 });
    for (const group of [
      "Kênh & Tích hợp",
      "Tài khoản & Bảo mật",
      "Hiển thị & Thông báo",
    ]) {
      if ((await page.getByText(group, { exact: true }).count()) !== 1) {
        throw new Error(`group card missing or duplicated: ${group}`);
      }
    }
    log("root: 3 grouped cards present");
    const firstRow = page
      .locator(".settings-mobile-row")
      .filter({ hasText: "Cloudfone" })
      .first();
    const rowBox = await boxOf(firstRow, "settings row (Cloudfone)");
    if (rowBox && (rowBox.height < 44 || rowBox.height > 56)) {
      throw new Error(`row height ${rowBox.height} outside 44–56px`);
    }
    await shot(page, "settings-3groups");
  }

  // ---- 2. Drill-down Cloudfone -------------------------------------------
  if (STAGE === "before") {
    await page.getByRole("button", { name: "Mở danh mục cài đặt" }).click();
    const dialog = page.getByRole("dialog", { name: "Cài đặt" });
    await dialog.waitFor();
    await dialog.getByRole("button", { name: /^Cloudfone/ }).click();
    await page
      .getByRole("heading", { name: "Cloudfone · Phân tích cuộc gọi" })
      .waitFor({ timeout: 15_000 });
    await shot(page, "drilldown-cloudfone");
  } else {
    await page
      .locator(".settings-mobile-row")
      .filter({ hasText: "Cloudfone" })
      .first()
      .click();
    await page
      .getByRole("heading", { name: "Cloudfone · Phân tích cuộc gọi" })
      .waitFor({ timeout: 15_000 });
    const back = page.getByRole("button", { name: "Quay lại" });
    await back.waitFor();
    await boxOf(back, "app bar back button");
    await shot(page, "drilldown-cloudfone");
  }

  // ---- 3. Transcripts call list ------------------------------------------
  await page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  if (STAGE === "before") {
    await page.getByRole("listitem").first().waitFor({ timeout: 15_000 });
    await shot(page, "tap-call");
  } else {
    await page
      .getByRole("searchbox", { name: "Tìm số điện thoại" })
      .waitFor({ timeout: 15_000 });
    const search = page.getByRole("searchbox", { name: "Tìm số điện thoại" });
    const searchBox = await boxOf(search, "search input");
    if (searchBox && (searchBox.height < 44 || searchBox.width > 390)) {
      throw new Error(
        `search box ${searchBox.width}x${searchBox.height} outside 44px-tall phone width`,
      );
    }
    const chip = page.getByRole("radio", { name: "Tất cả" });
    await chip.waitFor();
    // The visible chip is the label; the radio input is its full-size hidden
    // overlay minus the chip's borders.
    const chipBox = await boxOf(
      page.locator(".transcripts-chip").first(),
      "filter chip (Tất cả)",
    );
    if (chipBox && Math.abs(chipBox.height - 32) > 1) {
      throw new Error(`chip height ${chipBox.height} not 32px`);
    }
    if (!(await chip.isChecked())) {
      throw new Error("Tất cả chip should start active");
    }
    await page.getByRole("listitem").first().waitFor();
    await shot(page, "tap-call");
  }

  // ---- 4. Tap call → transcript at half height ---------------------------
  const firstCard = page.getByRole("listitem").first().getByRole("button");
  await firstCard.click();
  if (STAGE === "before") {
    // The hated panel: transcript below the list, out of the first viewport.
    await page.getByRole("button", { name: "Đóng bản ghi" }).waitFor();
    await shot(page, "sheet-50");
  } else {
    const sheet = page.getByRole("dialog");
    await sheet.waitFor();
    const half = await boxOf(sheet, "sheet at initial detent");
    if (half && Math.abs(half.height - 844 * 0.5) > 16) {
      throw new Error(`sheet height ${half.height} not ~50% of 844`);
    }
    await shot(page, "sheet-50");
  }

  // ---- 5. Expand to full -------------------------------------------------
  if (STAGE === "before") {
    // No sheet to drag: scroll the below-the-fold panel up, the old "full"
    // reading posture.
    await page.mouse.wheel(0, 320);
    await shot(page, "sheet-full");
  } else {
    const handle = page.locator(".bottom-sheet-handle");
    const handleBox = await handle.boundingBox();
    const cx = handleBox.x + handleBox.width / 2;
    const cy = handleBox.y + handleBox.height / 2;
    await page.mouse.move(cx, cy);
    await page.mouse.down();
    for (let step = 1; step <= 8; step += 1) {
      await page.mouse.move(cx, cy - step * 30);
    }
    await page.mouse.up();
    // The snap animates the height over 200ms; measure the settled detent.
    await page.waitForTimeout(400);
    const sheet = page.getByRole("dialog");
    const full = await boxOf(sheet, "sheet after drag");
    if (full && full.height < 844 * 0.85) {
      throw new Error(`sheet height ${full.height} did not expand past 85%`);
    }
    await shot(page, "sheet-full");
  }

  // ---- 6. Transcript content --------------------------------------------
  if (STAGE === "before") {
    await page
      .locator(".whitespace-pre-wrap")
      .first()
      .scrollIntoViewIfNeeded();
    await shot(page, "bubbles");
  } else {
    const firstBubble = page.locator(".transcript-bubble").first();
    await firstBubble.waitFor();
    const bubbleBox = await boxOf(firstBubble, "first bubble");
    const sheetBox = await page.getByRole("dialog").boundingBox();
    if (bubbleBox && sheetBox && bubbleBox.width > sheetBox.width * 0.8 + 2) {
      throw new Error(
        `bubble width ${bubbleBox.width} exceeds 80% of ${sheetBox.width}`,
      );
    }
    if ((await page.locator(".transcript-bubble").count()) < 4) {
      throw new Error("expected the seeded S1/S2 transcript as bubbles");
    }
    log(
      `bubbles: count=${await page.locator(".transcript-bubble").count()} ` +
        `copy-all=${await page.getByRole("button", { name: "Sao chép toàn bộ bản ghi" }).count()}`,
    );
    await shot(page, "bubbles");

    // Scrim tap-to-close (consult §3): press the backdrop above the sheet.
    await page.touchscreen.tap(195, 40);
    await page.waitForTimeout(300);
    if ((await page.getByRole("dialog").count()) !== 0) {
      throw new Error("scrim tap did not close the bottom sheet");
    }
    log("scrim tap closed the sheet");
  }

  log("done");
  await browser.close();
};

main().catch(async (error) => {
  log(`FAILED: ${error?.stack ?? error}`);
  if (page) {
    try {
      log(`failed url=${page.url()}`);
      await page.screenshot({
        path: path.join(ARTIFACTS, `${STAGE}-failed.png`),
      });
    } catch {
      // The page may already be closed; the log carries the failure.
    }
  }
  process.exit(1);
});
