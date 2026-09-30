const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("console", (m) => {
    const t = m.type();
    if (t === "error" || t === "warning")
      console.log(`[${t}]`, m.text().slice(0, 300));
  });
  page.on("pageerror", (e) =>
    console.log("[pageerror]", e.message.slice(0, 400)),
  );

  await page.goto("http://localhost:5173/", { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  await page.fill("input[name=email]", "admin@tingting.vip");
  await page.fill("input[name=password]", "t8fXyXcJzsMLaApT0Bk1YfyzAa1!");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle" }).catch(() => {}),
    page.click("button[type=submit]"),
  ]);
  await page.waitForTimeout(3000);

  // Visit /users; observe logs
  await page.goto("http://localhost:5173/#/users", {
    waitUntil: "networkidle",
  });
  await page.waitForTimeout(5000);
  const t = await page.evaluate(() => document.body.innerText.slice(0, 500));
  console.log("TEXT:", t);

  // Probe: what resources does ra-core know about?
  const resources = await page.evaluate(() => {
    // ra-core stores resources in ResourceContext
    // Try to introspect via a known side effect
    const links = Array.from(document.querySelectorAll('a[href^="#/"]')).map(
      (a) => a.getAttribute("href"),
    );
    return [...new Set(links)];
  });
  console.log("Internal nav links:", resources);

  await browser.close();
})();
