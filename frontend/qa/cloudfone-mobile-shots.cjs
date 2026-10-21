/**
 * QA evidence: Cloudfone transcripts section at 390×844 (iPhone-ish phone).
 *
 * Serves the frontend with Vite, opens
 * /qa/cloudfone-mobile-harness.html in headless Chromium at phone width,
 * answers the two admin transcript API calls from fixtures, and writes
 * full-page PNGs into ../../qa/<run>/.
 *
 *   node qa/cloudfone-mobile-shots.cjs <before|after> <outdir>
 */
const path = require("node:path");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");

const FRONTEND = path.resolve(__dirname, "..");
const PORT = 5199;
const OUTDIR = process.argv[3];

const ROWS = [
  {
    call_id: "1790848955",
    day: "2026-10-01",
    started_at: "2026-10-01T17:02:35",
    caller: "0362698948",
    talk_seconds: 221,
    transcript_preview: "S1: Alo ạ? Khách hỏi về giá dịch vụ.",
    created_at: "2026-10-02T01:00:00",
  },
  {
    call_id: "1790818523",
    day: "2026-10-01",
    started_at: "2026-10-01T09:15:11",
    caller: "0902065233",
    talk_seconds: 45,
    transcript_preview: "S1: Dạ em nghe ạ.",
    created_at: "2026-10-02T01:00:00",
  },
  {
    call_id: "1790790114",
    day: "2026-09-30",
    started_at: "2026-09-30T14:44:02",
    caller: "0987123456",
    talk_seconds: 98,
    transcript_preview: "S1: Chị hỏi về tiến độ dự án ạ.",
    created_at: "2026-10-01T01:00:00",
  },
];

const DETAIL = {
  ...ROWS[0],
  transcript:
    "S1: Alo chị nghe ạ.\nS2: Cho em hỏi giá dịch vụ gói cơ bản là bao nhiêu vậy?\nS1: Dạ gói cơ bản của bên em là 450 nghìn một tháng chị nhé, gồm lưu trữ và phân tích cuộc gọi.\nS2: Vậy thời hạn tối thiểu là bao nhiêu tháng?\nS1: Dạ tối thiểu sáu tháng chị, nếu đóng cả năm thì được giảm mười phần trăm ạ.",
};

async function waitForServer(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`vite did not start at ${url}`);
}

async function main() {
  if (!OUTDIR) throw new Error("usage: node cloudfone-mobile-shots.cjs <tag> <outdir>");

  const vite = spawn(
    "npx",
    ["vite", "--port", String(PORT), "--strictPort", "--host", "127.0.0.1"],
    { cwd: FRONTEND, stdio: ["ignore", "pipe", "pipe"] },
  );
  vite.stderr.on("data", (chunk) => process.stderr.write(chunk));

  const browser = await chromium.launch({ headless: true });
  try {
    await waitForServer(`http://127.0.0.1:${PORT}/`, 60_000);
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 2,
    });
    page.on("pageerror", (error) =>
      console.log("[pageerror]", String(error).slice(0, 300)),
    );

    await page.route("**/api/v1/admin/integrations/cloudfone/transcripts**", (route) => {
      const url = new URL(route.request().url());
      // Detail fetch has a call id path segment; the list has query params.
      const detailMatch = url.pathname.match(/\/transcripts\/([^/]+)$/);
      if (detailMatch) {
        return route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(DETAIL),
        });
      }
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: ROWS, total: 3, page: 1, page_size: 20 }),
      });
    });

    await page.goto(
      `http://127.0.0.1:${PORT}/qa/cloudfone-mobile-harness.html`,
      { waitUntil: "networkidle" },
    );
    await page
      .getByText("0362698948")
      .first()
      .waitFor({ state: "visible", timeout: 15_000 });
    await page.waitForTimeout(400);

    await page.screenshot({
      path: path.join(OUTDIR, `${process.argv[2]}-list.png`),
      fullPage: true,
    });

    // Open the first call's transcript: the pre-fix table needs its "Xem"
    // row button; the post-fix card list makes the whole card clickable.
    const xem = page.getByRole("button", { name: "Xem", exact: true }).first();
    if (await xem.isVisible().catch(() => false)) {
      await xem.click();
    } else {
      await page.getByText("0362698948").first().click();
    }
    await page
      .getByText(/Chị hỏi về tiến độ|Cho em hỏi giá dịch vụ/)
      .first()
      .waitFor({ state: "visible", timeout: 15_000 });
    await page.waitForTimeout(300);
    await page.screenshot({
      path: path.join(OUTDIR, `${process.argv[2]}-transcript.png`),
      fullPage: true,
    });

    console.log(`screenshots written to ${OUTDIR}`);
  } finally {
    await browser.close();
    vite.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
