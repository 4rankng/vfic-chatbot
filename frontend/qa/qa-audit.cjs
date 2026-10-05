const { chromium } = require("playwright");
const fs = require("fs");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  const consoleErrors = [];
  const networkErrors = [];

  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[console] ${msg.text()}`);
  });
  page.on("pageerror", (err) =>
    consoleErrors.push(`[pageerror] ${err.message}`),
  );
  page.on("response", (resp) => {
    if (resp.status() >= 400) {
      networkErrors.push(
        `${resp.status()} ${resp.request().method()} ${resp.url()}`,
      );
    }
  });

  // Login
  console.log("=== LOGIN ===");
  await page.goto("http://localhost:5173/", { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  await page.fill(
    'input[name="email"], input[type="email"]',
    "admin@tingting.vip",
  );
  await page.fill(
    'input[name="password"], input[type="password"]',
    "t8fXyXcJzsMLaApT0Bk1YfyzAa1!",
  );
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle" }),
    page.click('button[type="submit"]'),
  ]).catch(() => {});
  await page.waitForTimeout(2500);
  console.log("After login URL:", page.url());
  await page.screenshot({
    path: "/tmp/qa-audit/02-dashboard.png",
    fullPage: true,
  });
  const dashText = await page.evaluate(() =>
    document.body.innerText.slice(0, 2000),
  );
  console.log("Dashboard text:", dashText);
  console.log("Console errors so far:", consoleErrors.length);
  console.log("Network errors so far:", networkErrors.length);

  // Navigation: find all nav links
  const navLinks = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a[href^="#/"]'));
    return links.map((a) => ({
      href: a.getAttribute("href"),
      text: a.innerText.trim().slice(0, 40),
    }));
  });
  console.log("\n=== NAV LINKS ===");
  navLinks.forEach((l) => console.log(`  ${l.text.padEnd(30)} ${l.href}`));

  // Visit each route
  const routes = [
    "/",
    "/conversations",
    "/leads",
    "/pipeline",
    "/dashboard",
    "/knowledge_sources",
    "/users",
    "/settings",
    "/profile",
    "/tags",
    "/sales",
  ];
  for (const route of routes) {
    consoleErrors.length = 0;
    networkErrors.length = 0;
    await page
      .goto(`http://localhost:5173/#${route}`, { waitUntil: "networkidle" })
      .catch((e) => console.log("nav err", e.message));
    await page.waitForTimeout(1500);
    const fname = `/tmp/qa-audit/route-${route.replace(/\//g, "_") || "root"}.png`;
    await page.screenshot({ path: fname, fullPage: true });
    const txt = await page.evaluate(() =>
      document.body.innerText.slice(0, 500),
    );
    console.log(`\n--- Route ${route} ---`);
    console.log("URL:", page.url());
    console.log("Text:", txt.replace(/\n/g, " | ").slice(0, 300));
    console.log("Console:", consoleErrors.length, consoleErrors.slice(0, 3));
    console.log("Network:", networkErrors.length, networkErrors.slice(0, 3));
  }

  // Mobile viewport
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of [
    "/",
    "/conversations",
    "/leads",
    "/dashboard",
    "/profile",
  ]) {
    await page
      .goto(`http://localhost:5173/#${route}`, { waitUntil: "networkidle" })
      .catch(() => {});
    await page.waitForTimeout(1200);
    const fname = `/tmp/qa-audit/mobile-${route.replace(/\//g, "_") || "root"}.png`;
    await page.screenshot({ path: fname, fullPage: true });
    console.log(`Mobile ${route}: ${page.url()}`);
  }

  await browser.close();
  console.log("\nDONE");
})();
