const { chromium } = require("playwright");

(async () => {
  const errors = [];
  const consoleErrors = [];
  const networkErrors = [];

  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(err.message));
  page.on("requestfailed", (req) => {
    networkErrors.push(
      `${req.method()} ${req.url()} -> ${req.failure() && req.failure().errorText}`,
    );
  });
  page.on("response", (resp) => {
    if (resp.status() >= 400) {
      networkErrors.push(
        `${resp.status()} ${resp.request().method()} ${resp.url()}`,
      );
    }
  });

  console.log("=== Navigating to http://localhost:5173/ ===");
  try {
    await page.goto("http://localhost:5173/", {
      waitUntil: "networkidle",
      timeout: 30000,
    });
  } catch (e) {
    console.log("Goto error:", e.message);
  }

  await page.waitForTimeout(2000);
  console.log("Final URL:", page.url());
  console.log("Title:", await page.title());

  await page.screenshot({
    path: "/tmp/qa-audit/01-initial.png",
    fullPage: true,
  });

  const bodyText = await page.evaluate(() =>
    document.body.innerText.slice(0, 3000),
  );
  console.log("--- Body text (first 3000 chars) ---");
  console.log(bodyText);

  console.log("\n--- Page errors ---");
  console.log(JSON.stringify(errors, null, 2));
  console.log("\n--- Console errors ---");
  console.log(JSON.stringify(consoleErrors, null, 2));
  console.log("\n--- Network errors ---");
  console.log(JSON.stringify(networkErrors.slice(0, 30), null, 2));

  await browser.close();
})();
