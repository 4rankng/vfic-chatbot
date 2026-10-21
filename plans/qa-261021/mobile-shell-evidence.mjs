/**
 * Captures the 390×844 mobile-shell evidence the UI verification contract
 * asks for: before/after screenshots of (1) the primary navigation, (2) a
 * centered dialog rendered as a bottom sheet, and (3) the login form, plus
 * DOM geometry assertions and a driver log.
 *
 *   node plans/qa-261021/mobile-shell-evidence.mjs before|after
 *
 * Requires the local stack: uvicorn on :8000 (dev DB with admin@vfic.dev)
 * and the Vite dev server on :5173.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("../../frontend/node_modules/@playwright/test");

const APP = "http://localhost:5173";
const ARTIFACTS = path.resolve(
  path.dirname(new URL(import.meta.url).pathname),
  "../../qa/2026-10-21-mobile-shell",
);
const LOG = path.join(
  ARTIFACTS,
  `${process.argv[2] ?? "run"}-driver.log`,
);
const EMAIL = "admin@vfic.dev";
const PASSWORD = "admin123";
const STAGE = process.argv[2] ?? "after";

if (!["before", "after"].includes(STAGE)) {
  throw new Error(`usage: mobile-shell-evidence.mjs before|after (got ${STAGE})`);
}

const lines = [];
const log = (message) => {
  lines.push(message);
  console.log(message);
  fs.writeFileSync(LOG, lines.join("\n") + "\n");
};

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
  const page = await context.newPage();

  // ---- 1. Login (before/after) -------------------------------------------
  await page.goto(`${APP}/`);
  await page.getByRole("heading", { name: "Đăng nhập" }).waitFor();
  const submit = page.getByRole("button", { name: "Đăng nhập" });
  const submitBox = await submit.boundingBox();
  log(
    `login: submit button box height=${submitBox?.height}px width=${submitBox?.width}px`,
  );
  await page.screenshot({ path: path.join(ARTIFACTS, `${STAGE}-login.png`) });

  // ---- Sign in for the shell surfaces -------------------------------------
  await page.locator('input[type="email"]').fill(EMAIL);
  await page.locator('input[type="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page.getByRole("heading", { name: "Tổng quan" }).waitFor({
    timeout: 20_000,
  });
  log("login: signed in as admin (dashboard heading visible)");

  // ---- 2. Primary navigation at 390px ------------------------------------
  await page.goto(`${APP}/#/conversations`);
  await page.getByRole("button", { name: "Mở điều hướng" }).waitFor({
    timeout: 15_000,
  });

  const navProbe = await page.evaluate(() => {
    const tabbar = document.querySelector(".workspace-tabbar");
    if (!tabbar) return { tabbar: null };
    const rect = tabbar.getBoundingClientRect();
    const style = getComputedStyle(tabbar);
    return {
      tabbar: {
        rect: { top: rect.top, bottom: rect.bottom, height: rect.height },
        position: style.position,
        display: style.display,
        paddingBottom: style.paddingBottom,
      },
    };
  });
  log(`nav: probe ${JSON.stringify(navProbe)}`);

  await page.screenshot({
    path: path.join(ARTIFACTS, `${STAGE}-nav-inbox.png`),
  });

  // The dialog surface: Users → "Đổi mật khẩu" (a centered modal on desktop).
  await page.goto(`${APP}/#/users`);
  await page.getByRole("button", { name: /Đổi mật khẩu/ }).first().waitFor({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: /Đổi mật khẩu/ }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ timeout: 10_000 });
  // Let the enter animation settle so the probe measures resting geometry.
  await page.waitForTimeout(500);

  const dialogProbe = await page.evaluate(() => {
    const dialogEl = document.querySelector('[role="dialog"]');
    // The sheet box is the modal wrapper around the dialog; the overlay
    // carries the alignment. The drag handle is a sibling of the dialog.
    const sheet = dialogEl?.parentElement;
    const overlay = sheet?.parentElement;
    if (!dialogEl || !sheet || !overlay) return null;
    const box = sheet.getBoundingClientRect();
    const overlayStyle = getComputedStyle(overlay);
    const sheetStyle = getComputedStyle(sheet);
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    return {
      sheet: {
        left: box.left,
        right: box.right,
        top: box.top,
        bottom: box.bottom,
        width: box.width,
      },
      viewport: { width: viewportWidth, height: viewportHeight },
      overflowRight: Math.round(box.right - viewportWidth),
      flushBottom: Math.abs(box.bottom - viewportHeight) < 1,
      overlayAlign: overlayStyle.alignItems,
      overlayPaddingBottom: overlayStyle.paddingBottom,
      radiusTop: sheetStyle.borderTopLeftRadius,
      radiusBottom: sheetStyle.borderBottomLeftRadius,
      maxHeight: sheetStyle.maxHeight,
      handle: Boolean(sheet.querySelector(".app-sheet-handle")),
      handleVisible: (() => {
        const handle = sheet.querySelector(".app-sheet-handle");
        return handle
          ? getComputedStyle(handle).display !== "none"
          : false;
      })(),
    };
  });
  log(`dialog: probe ${JSON.stringify(dialogProbe)}`);

  const fieldLabel = await dialog.getByText("Mật khẩu mới").count();
  log(`dialog: password field present=${fieldLabel > 0}`);
  await page.screenshot({
    path: path.join(ARTIFACTS, `${STAGE}-modal-bottom-sheet.png`),
  });

  if (STAGE === "after") {
    // Drag the handle past the threshold and confirm the sheet dismisses.
    const handleBox = await page.evaluate(() => {
      const handle = document.querySelector(".app-sheet-handle");
      if (!handle) return null;
      const box = handle.getBoundingClientRect();
      return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    });
    if (handleBox) {
      await page.mouse.move(handleBox.x, handleBox.y);
      await page.mouse.down();
      await page.mouse.move(handleBox.x, handleBox.y + 220, { steps: 6 });
      await page.mouse.up();
      try {
        // The sheet dismisses through React Aria's Escape path and leaves
        // after its 200ms exit animation.
        await dialog.waitFor({ state: "detached", timeout: 3000 });
        log("dialog: drag-to-dismiss dismissed=true");
      } catch {
        log("dialog: drag-to-dismiss dismissed=false");
      }
    } else {
      log("dialog: handle missing — drag-to-dismiss not driven");
    }
  }

  await browser.close();
  log(`stage=${STAGE}: artifacts written to ${ARTIFACTS}`);
};

main().catch((error) => {
  log(`FATAL: ${error.stack ?? error}`);
  process.exitCode = 1;
});
