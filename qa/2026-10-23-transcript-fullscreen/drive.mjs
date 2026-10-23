/**
 * Cloudfone transcript FULL-SCREEN mobile overlay — rung-3 UI driver
 * (23/10/2026, owner decision 09:24: full-screen thay bottom sheet).
 *
 * Boots the disposable e2e stack (FastAPI harness + Postgres vfic_*_e2e on
 * 5443, Vite on 4173), seeds cloudfone_call_transcripts, then drives the real
 * console in Chromium at 390x844:
 *   - tap a call card → the transcript opens as a FULL-SCREEN overlay (no
 *     bottom sheet), script-asserted: overlay height ≥ 95% of the viewport,
 *     width = 100%, one ~56px header row (‹ Quay lại | number · duration ·
 *     date | copy-all), S1/S2 bubbles visible;
 *   - ‹ Quay lại returns to the call-card list (overlay detached, cards
 *     back);
 *   - desktop 1280px keeps the panel under the table, unchanged.
 *
 * Artifacts land next to this script: 01-03 *.png + driver.log.
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
const PY = "/Volumes/LexarSSD/projects/chatbot/backend/.venv/bin/python";
const API = "http://127.0.0.1:8000";
const APP = "http://127.0.0.1:4173";
const ADMIN_EMAIL = "admin@example.org";
const ADMIN_PASSWORD = "Universal-E2E-Only-42!";
const DB = "vfic_cloudfonefsqa_e2e";

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
  log("=== transcript full-screen QA drive start ===");
  await freePorts("start");

  // 1. Boot backend + frontend. The harness `serve` RESETS the disposable DB
  // on startup, so seeding must happen AFTER the backend is up.
  const env = {
    ...process.env,
    VFIC_E2E_RUN_ID: "cloudfonefsqa",
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

  // 2. Seed transcript rows (DB side-effect proof: DBROW lines in the log).
  const seed = await exec(PY, ["-c", SEED], { timeout: 30_000 });
  log(seed.stdout.trim());
  ok(seed.stdout.includes("SEEDED 4"), "seeded 4 transcript rows");
  ok((await exec(PY, ["-c", `import psycopg
with psycopg.connect("postgresql://vfic:vfic@127.0.0.1:5443/${DB}") as c:
    with c.cursor() as cur:
        cur.execute("SELECT call_id, caller, talk_seconds, length(transcript) FROM cloudfone_call_transcripts WHERE call_id LIKE 'cf-qa-%' ORDER BY call_id")
        [print("DBROW", r) for r in cur.fetchall()]`])).stdout.includes("DBROW ('cf-qa-1'"),
    "seeded rows verifiable in Postgres (see DBROW lines above)");

  // 3. Drive. Log in through the desktop console, then live-resize to the
  // phone width (`useIsMobile` swaps in the phone surface).
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
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
  const firstCard = page.getByRole("button", { name: /0362698948/ });
  await firstCard.waitFor({ timeout: 30_000 });
  await page.waitForTimeout(400); // fonts settle
  ok((await page.locator(".call-card").count()) === 4, "4 call cards render on the list");
  await page.screenshot({ path: path.join(__dirname, "00-mobile-list.png") });
  log("SHOT 00-mobile-list.png");

  // ── 01 tap a call → FULL-SCREEN overlay (not a sheet).
  await firstCard.click();
  const overlay = page.locator(".transcript-fullscreen");
  await overlay.waitFor({ timeout: 15_000 });
  await page.locator(".transcript-bubble--right").first().waitFor({ timeout: 15_000 });
  await page.waitForTimeout(350); // slide-in (200ms) settles

  // Script assertion (not eyeballs): the overlay claims ≥95% of the viewport
  // height and 100% of its width.
  const geom = await overlay.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const h = el.getBoundingClientRect().height;
    const header = el.querySelector(".transcript-fullscreen-header");
    return {
      height: h,
      width: r.width,
      innerH: window.innerHeight,
      innerW: window.innerWidth,
      headerH: header ? header.getBoundingClientRect().height : 0,
      styleHeight: el.style.height,
    };
  });
  log(`overlay geometry: ${JSON.stringify(geom)}`);
  ok(geom.height >= 0.95 * geom.innerH, `overlay height ${geom.height} ≥ 95% of ${geom.innerH}`);
  ok(geom.width === geom.innerW, `overlay width ${geom.width} = viewport width ${geom.innerW}`);
  ok(geom.styleHeight === "var(--visual-viewport-height, 100dvh)", `inline height = ${geom.styleHeight}`);
  ok(geom.headerH > 0 && geom.headerH <= 96, `one header row (~56px): ${geom.headerH}px`);
  ok((await page.locator(".bottom-sheet").count()) === 0, "no bottom sheet rendered");

  // Header row contents: ‹ Quay lại | number · duration · date | copy-all.
  ok(await page.getByRole("button", { name: "Quay lại", exact: true }).isVisible(), "back button visible");
  ok(await page.getByText("1p38s · 21/10/2026 17:02").isVisible(), "header meta 'duration · date' visible");
  ok(await page.getByRole("button", { name: "Sao chép toàn bộ bản ghi" }).isVisible(), "copy-all visible");
  const backBox = await page.getByRole("button", { name: "Quay lại", exact: true }).boundingBox();
  const copyBox = await page.getByRole("button", { name: "Sao chép toàn bộ bản ghi" }).boundingBox();
  ok(backBox && backBox.height >= 44 && backBox.width >= 44, `back target ≥44px (${JSON.stringify(backBox)})`);
  ok(copyBox && copyBox.height >= 44 && copyBox.width >= 44, `copy target ≥44px (${JSON.stringify(copyBox)})`);

  // Bubbles: S1 left gray / S2 right, and a deep S2 line is actually readable.
  const bubblesL = await page.locator(".transcript-bubble--left").count();
  const bubblesR = await page.locator(".transcript-bubble--right").count();
  ok(bubblesL === 4 && bubblesR === 4, `bubbles S1=${bubblesL} left / S2=${bubblesR} right`);
  ok(await page.getByText("2 năm ở trung tâm cuộc gọi").isVisible(), "deep S2 bubble text readable");
  // Body scrolls inside the overlay only (header stays pinned above it).
  const bodyScroll = await page.locator(".transcript-fullscreen-body").evaluate(
    (el) => el.scrollHeight > el.clientHeight,
  );
  ok(bodyScroll, "overlay body is the scroll surface (scrollHeight > clientHeight)");
  await page.screenshot({ path: path.join(__dirname, "01-mobile-fullscreen-open.png") });
  log("SHOT 01-mobile-fullscreen-open.png");

  // ── 02 ‹ Quay lại returns to the list.
  await page.getByRole("button", { name: "Quay lại", exact: true }).click();
  await overlay.waitFor({ state: "detached", timeout: 15_000 });
  ok((await page.locator(".call-card").count()) === 4, "back returns to the call-card list");
  ok(await firstCard.isVisible(), "the tapped card is visible again");
  await page.screenshot({ path: path.join(__dirname, "02-mobile-after-back.png") });
  log("SHOT 02-mobile-after-back.png");

  // ── 03 desktop ≥768px keeps the panel under the table (same browser
  // context so the admin session carries over).
  const desktopCtx = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 2,
    storageState: await page.context().storageState(),
  });
  const desktopPage = await desktopCtx.newPage();
  await desktopPage.goto(`${APP}/#/settings`, { timeout: 60_000 });
  await desktopPage.getByRole("button", { name: "Cloudfone Phân tích cuộc gọi" }).click();
  await desktopPage.getByRole("button", { name: "Xem bản ghi cuộc gọi" }).click();
  await desktopPage.evaluate(() => {
    const input = document.querySelector("#cloudfone-transcripts-day");
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, "value",
    ).set;
    setter.call(input, "2026-10-21");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await desktopPage.getByText("0362698948", { exact: true }).first().waitFor({ timeout: 30_000 });
  await desktopPage.getByRole("button", { name: "Xem", exact: true }).first().click();
  await desktopPage.locator(".transcript-bubble--right").first().waitFor({ timeout: 15_000 });
  ok((await desktopPage.locator('[role="table"], [role="grid"]').count()) > 0, "desktop table renders");
  ok((await desktopPage.locator(".transcript-fullscreen").count()) === 0, "no full-screen overlay at desktop width");
  ok(await desktopPage.getByRole("button", { name: "Sao chép toàn bộ bản ghi" }).isVisible(),
    "desktop panel keeps its copy-all affordance");
  await desktopPage.screenshot({ path: path.join(__dirname, "03-desktop-panel-unchanged.png"), fullPage: true });
  log("SHOT 03-desktop-panel-unchanged.png");

  await browser.close();
  log("=== ALL PASS — 4 screenshots + script assertions ===");

  await freePorts("done");
  process.exit(0);
}

main().catch(async (err) => {
  log(`FATAL ${err?.stack ?? err}`);
  await freePorts("fatal");
  process.exit(1);
});
