import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";

const OUT_DIR =
  "/Users/dev/.gemini/antigravity-cli/brain/e0010c74-1928-4d3d-9237-5601763c6894";
const SCREENSHOT_PATH = path.join(OUT_DIR, "lead-106-show.png");

async function capture() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  console.log("Launching browser...");
  const browser = await puppeteer.launch({
    executablePath:
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  try {
    console.log("Navigating to login page...");
    await page.goto("http://localhost:5173/#/login", {
      waitUntil: "networkidle2",
      timeout: 15000,
    });
    await page.waitForSelector("input[name='username'], input[type='email']", {
      timeout: 10000,
    });

    console.log("Filling in credentials...");
    // React Admin LoginPage usually has username/password inputs
    const usernameInput = await page.$(
      "input[name='username'], input[type='email']",
    );
    const passwordInput = await page.$(
      "input[name='password'], input[type='password']",
    );

    await usernameInput.type("admin@tingting.vip");
    await passwordInput.type("t8fXyXcJzsMLaApT0Bk1YfyzAa1!");

    console.log("Submitting login form...");
    const submitBtn = await page.$("button[type='submit']");
    await submitBtn.click();

    console.log("Waiting for redirection to dashboard...");
    await page.waitForFunction(() => !window.location.hash.includes("login"), {
      timeout: 15000,
    });
    await page.waitForNetworkIdle();

    console.log("Navigating to lead 106 show page...");
    await page.goto("http://localhost:5173/#/leads/106/show", {
      waitUntil: "networkidle2",
      timeout: 15000,
    });
    await new Promise((r) => setTimeout(r, 3000)); // wait for components/nivo charts to animate and render fully

    console.log("Capturing screenshot...");
    await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });
    console.log("Screenshot successfully captured:", SCREENSHOT_PATH);
  } catch (err) {
    console.error("Capture failed:", err);
  } finally {
    await browser.close();
  }
}

capture();
