#!/usr/bin/env node
/**
 * Boot the **built** bundle in a real browser and fail if the app does not
 * render.
 *
 * WHY THIS EXISTS: every other frontend check runs against the Vite *dev*
 * server — the unit suite, and all three Playwright lanes (the e2e webServer is
 * `npx vite --mode e2e`). On 2026-09-29 that gap shipped a broken production
 * bundle: `codeSplitting.includeDependenciesRecursively: false` produced a chunk
 * graph with invalid execution order, so `dist/` threw
 * `TypeError: D is not a function` at boot and the app sat on its "Đang tải…"
 * shell. Dev was fine, every gate was green, and the failure only appeared after
 * `make deploy-frontend` had replaced the production container.
 *
 * WHAT IT DOES: serves `dist/` with `vite preview`, opens it in Chromium, and
 * requires the login screen to render with no uncaught page errors. Run it after
 * `npm run build`; `--build` builds first.
 *
 * Usage:
 *   node scripts/smoke-built-bundle.mjs            # serve ./dist and check it
 *   node scripts/smoke-built-bundle.mjs --build    # npm run build, then check
 */

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const PORT = Number(process.env.SMOKE_PORT ?? 4179);
const BASE_URL = `http://127.0.0.1:${PORT}/`;
const BOOT_TIMEOUT_MS = 30_000;

const run = (command, args) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: frontendRoot,
      stdio: "inherit",
      env: process.env,
    });
    child.on("error", reject);
    child.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`${command} exited ${code}`)),
    );
  });

const waitForServer = async () => {
  const deadline = Date.now() + BOOT_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(BASE_URL);
      if (response.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`vite preview never answered on ${BASE_URL}`);
};

const main = async () => {
  if (process.argv.includes("--build")) await run("npm", ["run", "build"]);

  if (!fs.existsSync(path.join(frontendRoot, "dist", "index.html"))) {
    throw new Error("dist/index.html is missing — run `npm run build` first");
  }

  const preview = spawn(
    "npx",
    [
      "vite",
      "preview",
      "--host",
      "127.0.0.1",
      "--port",
      String(PORT),
      "--strictPort",
    ],
    { cwd: frontendRoot, stdio: ["ignore", "pipe", "pipe"] },
  );
  const previewLog = [];
  preview.stdout.on("data", (chunk) => previewLog.push(String(chunk)));
  preview.stderr.on("data", (chunk) => previewLog.push(String(chunk)));

  let browser;
  try {
    await waitForServer();
    const { chromium } = await import("@playwright/test");
    browser = await chromium.launch();
    const page = await browser.newPage();
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") pageErrors.push(message.text());
    });

    await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('input[type="email"]', {
      timeout: BOOT_TIMEOUT_MS,
    });

    const body = await page.innerText("body");
    if (/Đang tải…/.test(body) && !/Đăng nhập/.test(body)) {
      throw new Error("the app is stuck on its loading shell");
    }
    if (pageErrors.length > 0) {
      throw new Error(
        `the built bundle logged errors: ${pageErrors.join(" | ")}`,
      );
    }

    console.log(
      "Built bundle boots: the login screen rendered with no page errors.",
    );
  } catch (error) {
    console.error(`smoke-built-bundle FAILED: ${error.message}`);
    if (previewLog.length > 0)
      console.error(previewLog.join("").slice(0, 2000));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    preview.kill("SIGTERM");
  }
};

await main();
