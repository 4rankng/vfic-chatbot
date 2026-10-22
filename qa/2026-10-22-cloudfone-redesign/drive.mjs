/**
 * Cloudfone transcripts mobile redesign — rung-3 UI driver (22/10/2026).
 *
 * Boots the disposable e2e stack (FastAPI harness + Postgres vfic_*_e2e on
 * 5443, Redis db 15 on 6382, Vite on 4173), seeds cloudfone_call_transcripts,
 * then drives the real console in Chromium at 390x844 and captures the
 * consult's surfaces: list, sheet@50%, sheet@92vh, bubbles S1/S2, empty
 * state, error+retry, plus a desktop sanity shot.
 *
 * Artifacts land next to this script: *.png + driver.log.
 */
import { createRequire } from "node:module";
import { spawn, execFile } from "node:child_process";
import { mkdirSync, appendFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(__dirname, "../..");
const FRONTEND = path.join(REPO, "frontend");
const { chromium } = createRequire(path.join(FRONTEND, "package.json"))("@playwright/test");
const BACKEND = path.join(REPO, "backend");
const HARNESS = path.join(BACKEND, "tests", "e2e_harness.py");
const PY = path.join(BACKEND, ".venv", "bin", "python");
const API = "http://127.0.0.1:8000";
const APP = "http://127.0.0.1:4173";
const ADMIN_EMAIL = "admin@example.org";
const ADMIN_PASSWORD = "Universal-E2E-Only-42!";
const DB = "vfic_cloudfoneqa_e2e";

const log = (line) => {
  const stamped = `[${new Date().toISOString()}] ${line}`;
  console.log(stamped);
  appendFileSync(path.join(__dirname, "driver.log"), stamped + "\n");
};
const ok = (cond, label) => {
  if (!cond) throw new Error(`ASSERT FAILED: ${label}`);
  log(`PASS ${label}`);
};

const exec = promisify(execFile);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** SIGTERM to `npx`/wrappers orphans their children — free the ports hard. */
const freePorts = async (label) => {
  for (const port of [8000, 4173]) {
    try {
      await exec("sh", ["-c", `lsof -ti :${port} | xargs kill -9 2>/dev/null || true`]);
    } catch {}
  }
  await sleep(500);
  log(`ports freed (${label})`);
};

async function waitFor(url, label, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return log(`UP ${label}`);
    } catch {}
    await sleep(500);
  }
  throw new Error(`never came up: ${label}`);
}

const children = [];
const run = (cmd, args, opts = {}, pipe = false) => {
  const child = spawn(cmd, args, opts);
  children.push(child);
  if (pipe) {
    child.stdout.on("data", (d) =>
      appendFileSync(path.join(__dirname, "server.log"), `[${cmd}] ${d}`),
    );
    child.stderr.on("data", (d) =>
      appendFileSync(path.join(__dirname, "server.log"), `[${cmd}!] ${d}`),
    );
  }
  return child;
};

const SEED = `
import psycopg
rows = [
  ("cf-qa-1", "2026-10-21", "2026-10-21T17:02:35", "0362698948", 98,
   "S1: Alo, em nghe ạ.\\nS2: Chào chị, em gọi từ bộ phận hỗ trợ tuyển dụng VFIC. Chị có vài phút em hỏi về đơn ứng tuyển không ạ?\\nS1: Dạ em cứ hỏi ạ.\\nS2: Chị đã nộp hồ sơ cho vị trí chăm sóc khách hàng hôm thứ Ba phải không ạ?\\nS1: Dạ đúng rồi ạ.\\nS2: Em xác nhận lại: chị có kinh nghiệm 2 năm ở trung tâm cuộc gọi, và muốn làm giờ hành chính ở Hà Nội. Chính xác không ạ?\\nS1: Dạ đúng ạ. Lương mong muốn của em khoảng 12 triệu ạ.\\nS2: Dạ em ghi nhận lại ạ. Em sẽ chuyển hồ sơ của chị cho phòng nhân sự và phản hồi trong 2 ngày làm việc ạ."),
  ("cf-qa-2", "2026-10-21", "2026-10-21T09:15:11", "0902065233", 45,
   "S1: Dạ em nghe ạ.\\nS2: Em gọi xác nhận lịch phỏng vấn lúc 9 giờ sáng mai nhé ạ."),
  ("cf-qa-3", "2026-10-22", "2026-10-22T10:45:00", "0987654321", 210, ""),
  ("cf-qa-4", "2026-10-22", "2026-10-22T08:05:00", "0912345678", 12,
   "S1: Alo?\\nS2: Dạ em gọi nhầm số, xin lỗi chị ạ."),
]
with psycopg.connect("postgresql://vfic:vfic@127.0.0.1:5443/${DB}") as conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM cloudfone_call_transcripts WHERE call_id LIKE 'cf-qa-%'")
        cur.executemany(
            "INSERT INTO cloudfone_call_transcripts (call_id, day, started_at, caller, talk_seconds, transcript, created_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,'2026-10-22T02:00:00')", rows)
        cur.execute("SELECT count(*) FROM cloudfone_call_transcripts WHERE call_id LIKE 'cf-qa-%'")
        print("SEEDED", cur.fetchone()[0])
`;

async function main() {
  mkdirSync(__dirname, { recursive: true });
  writeFileSync(path.join(__dirname, "driver.log"), "");
  writeFileSync(path.join(__dirname, "server.log"), "");
  log("=== cloudfone redesign QA drive start ===");
  await freePorts("start");

  // 1. Boot backend + frontend. NOTE: the harness `serve` RESETS the
  // disposable DB on startup (truncate + admin), so seeding must happen
  // AFTER the backend is up, never before.
  const env = {
    ...process.env,
    VFIC_E2E_RUN_ID: "cloudfoneqa",
    VFIC_E2E_DATABASE_URL: `postgresql+asyncpg://vfic:vfic@127.0.0.1:5443/${DB}`,
    VFIC_E2E_DATABASE_URL_SYNC: `postgresql+psycopg://vfic:vfic@127.0.0.1:5443/${DB}`,
  };
  run(PY, [HARNESS, "serve", "--port", "8000"], { env, cwd: BACKEND }, true);
  run("npx", ["vite", "--mode", "e2e", "--host", "127.0.0.1", "--port", "4173", "--strictPort"], {
    env: { ...env, VITE_API_BASE: API, VITE_SOCKET_URL: API },
    cwd: FRONTEND,
  }, true);
  await waitFor(`${API}/health`, "backend :8000");
  await waitFor(APP, "vite :4173");

  // 2. Seed transcript rows (SQL side-effect proof lives in the log).
  const seed = await exec(PY, ["-c", SEED], { timeout: 30_000 });
  log(seed.stdout.trim());
  const probe = await fetch(
    `${API}/api/v1/admin/integrations/cloudfone/transcripts?page=1&page_size=20`,
  );
  log(`post-seed API probe (unauthenticated): HTTP ${probe.status}`);
  ok((await exec(PY, ["-c", `import psycopg
with psycopg.connect("postgresql://vfic:vfic@127.0.0.1:5443/${DB}") as c:
    with c.cursor() as cur:
        cur.execute("SELECT call_id, caller, talk_seconds, length(transcript) FROM cloudfone_call_transcripts WHERE call_id LIKE 'cf-qa-%' ORDER BY call_id")
        [print("DBROW", r) for r in cur.fetchall()]`])).stdout.includes("DBROW ('cf-qa-1'"),
    "seeded rows verifiable in Postgres (see DBROW lines above)");

  // 4. Drive.
  const browser = await chromium.launch();
  // Enter through the desktop console (the settings root is a drill-down at
  // phone width with different row labels), then live-resize: `useIsMobile`
  // reacts to the viewport change and swaps in the phone surface we test.
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
  });
  const apiLog = [];
  page.on("response", (r) => {
    if (r.url().includes("/api/v1/")) apiLog.push(`${r.status()} ${r.request().method()} ${r.url().replace(API, "")}`);
  });

  await page.goto(`${APP}/`, { timeout: 60_000 });
  await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page.getByRole("heading", { name: "Tổng quan" }).waitFor({ timeout: 30_000 });
  log("logged in as admin");

  await page.goto(`${APP}/#/settings`);
  await page.getByRole("button", { name: "Cloudfone Phân tích cuộc gọi" }).click();
  await page.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await page.getByRole("heading", { name: "Cloudfone · Bản ghi cuộc gọi" }).waitFor({ timeout: 30_000 });
  log("transcripts section open (desktop)");

  // ── phone surface: 390x844.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(800);
  log("after-resize body text: " + JSON.stringify(
    await page.evaluate(() => document.body.innerText.slice(0, 1200).replace(/\n+/g, " | ")),
  ));

  // ── 01 list: cards, search, chips, duration pills, 12-hour times.
  const firstCard = page.getByRole("button", { name: /0362698948/ });
  await firstCard.waitFor({ timeout: 30_000 });
  await page.waitForTimeout(400); // fonts settle
  ok((await page.locator(".call-card").count()) === 4, "4 call cards render");
  const card1 = await firstCard.textContent();
  ok(card1.includes("0362698948") && card1.includes("5:02 CH") && card1.includes("1p38s"),
    `card1 text = ${JSON.stringify(card1)}`);
  ok((await page.locator(".call-card-icon").count()) === 4, "call icon on every card");
  ok(await page.getByRole("searchbox", { name: "Tìm số điện thoại" }).isVisible(), "search field visible");
  ok(await page.getByRole("radio", { name: "Tất cả" }).isChecked(), "Tất cả chip starts active");
  await page.screenshot({ path: path.join(__dirname, "01-mobile-list.png") });
  log("SHOT 01-mobile-list.png");

  // ── 02 sheet @50% with S1/S2 bubbles.
  await firstCard.click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ timeout: 15_000 });
  await page.locator(".transcript-bubble--right").first().waitFor({ timeout: 15_000 });
  const sheetEl = page.locator(".bottom-sheet");
  const h50 = await sheetEl.evaluate((el) => el.style.height);
  ok(h50.includes("0.5"), `sheet starts at 50% (style.height=${h50})`);
  await page.getByText("1p38s • 21/10/2026 17:02").waitFor();
  ok(true, "header meta shows 'duration • date'");
  const bubblesL = await page.locator(".transcript-bubble--left").count();
  const bubblesR = await page.locator(".transcript-bubble--right").count();
  ok(bubblesL === 4 && bubblesR === 4, `bubbles S1=${bubblesL} left / S2=${bubblesR} right`);
  const s1Label = await page.locator(".transcript-speaker").first().textContent();
  const s2Label = await page.locator(".transcript-speaker").nth(1).textContent();
  ok(s1Label === "S1" && s2Label === "S2", `speaker labels S1/S2 (${s1Label}/${s2Label})`);
  await page.screenshot({ path: path.join(__dirname, "02-mobile-sheet-50-bubbles.png") });
  log("SHOT 02-mobile-sheet-50-bubbles.png");

  // ── 03 drag grip → 92vh.
  const grip = page.locator(".bottom-sheet-handle");
  const box = await grip.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, 120, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(400); // snap transition
  const hFull = await sheetEl.evaluate((el) => el.style.height);
  ok(hFull.includes("0.92"), `sheet snaps to 92vh after drag (style.height=${hFull})`);
  // Bubbles visible at full height (S2 utterance deep in the transcript).
  ok(await page.getByText("2 năm ở trung tâm cuộc gọi").isVisible(), "S2 bubble text readable at full snap");
  await page.screenshot({ path: path.join(__dirname, "03-mobile-sheet-full.png") });
  log("SHOT 03-mobile-sheet-full.png");

  // ── 04 close; error state via intercepted 500, then retry recovers.
  await page.getByRole("button", { name: "Đóng bản ghi" }).click();
  await dialog.waitFor({ state: "detached" });
  await page.route("**/api/v1/admin/integrations/cloudfone/transcripts/cf-qa-2", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"boom"}' }),
  );
  await page.getByRole("button", { name: /0902065233/ }).click();
  await page.getByText("Không thể tải hội thoại").waitFor({ timeout: 15_000 });
  ok(await page.getByText("Đã xảy ra lỗi khi bóc băng hoặc tải dữ liệu").isVisible(), "error sub-copy visible");
  ok(await page.getByRole("button", { name: "Thử lại" }).isVisible(), "retry button visible");
  await page.screenshot({ path: path.join(__dirname, "04-mobile-error-state.png") });
  log("SHOT 04-mobile-error-state.png");
  await page.unroute("**/api/v1/admin/integrations/cloudfone/transcripts/cf-qa-2");
  await page.getByRole("button", { name: "Thử lại" }).click();
  await page.locator(".transcript-bubble--right").first().waitFor({ timeout: 15_000 });
  ok(true, "retry reloads the conversation (bubbles render)");
  await page.getByRole("button", { name: "Đóng bản ghi" }).click();
  await dialog.waitFor({ state: "detached" });

  // ── 05 empty transcript state.
  await page.getByRole("button", { name: /0987654321/ }).click();
  await page.getByText("Chưa có nội dung cuộc gọi").waitFor({ timeout: 15_000 });
  ok(await page.getByText("Nội dung bóc băng sẽ hiển thị tại đây").isVisible(), "empty sub-copy visible");
  await page.screenshot({ path: path.join(__dirname, "05-mobile-empty-state.png") });
  log("SHOT 05-mobile-empty-state.png");
  await page.getByRole("button", { name: "Đóng bản ghi" }).click();
  await dialog.waitFor({ state: "detached" });

  // ── 06 desktop: table + panel below, unchanged surface (same browser
  // context so the admin session carries over).
  const desktopPage = await page.context().newPage({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
  });
  const dlog = [];
  desktopPage.on("response", (r) => {
    if (r.url().includes("/api/v1/")) dlog.push(`${r.status()} ${r.url().replace(API, "")}`);
  });
  await desktopPage.goto(`${APP}/#/settings`, { timeout: 60_000 });
  await desktopPage.getByRole("button", { name: "Cloudfone Phân tích cuộc gọi" }).click();
  await desktopPage.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await desktopPage.getByRole("cell", { name: "0362698948" }).waitFor({ timeout: 30_000 });
  await desktopPage.getByRole("button", { name: "Xem", exact: true }).first().click();
  await desktopPage.locator(".transcript-bubble--right").first().waitFor({ timeout: 15_000 });
  ok((await desktopPage.locator('[role="table"], [role="grid"]').count()) > 0, "desktop table renders");
  ok(await desktopPage.getByRole("button", { name: "Sao chép toàn bộ bản ghi" }).isVisible(),
    "desktop panel keeps a copy-all affordance");
  await desktopPage.screenshot({ path: path.join(__dirname, "06-desktop-table-panel.png"), fullPage: true });
  log("SHOT 06-desktop-table-panel.png");

  log("API calls (mobile page): " + JSON.stringify(apiLog, null, 1));
  log("API calls (desktop page): " + JSON.stringify(dlog, null, 1));
  await browser.close();
  log("=== ALL PASS — 6 screenshots + assertions ===");

  await freePorts("done");
  process.exit(0);
}

main().catch(async (err) => {
  log(`FATAL ${err?.stack ?? err}`);
  await freePorts("fatal");
  process.exit(1);
});
