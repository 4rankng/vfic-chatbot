const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("console", (m) => {
    const text = m.text();
    if (text.includes("auth.canAccess") || text.includes("error")) {
      console.log(`[${m.type()}]`, text.slice(0, 500));
    }
  });

  await page.goto("http://localhost:5173/", { waitUntil: "networkidle" });
  await page.evaluate(() => {
    localStorage.clear();
  });
  await page.goto("http://localhost:5173/", { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  await page.fill("input[name=email]", "admin@tingting.vip");
  await page.fill("input[name=password]", "t8fXyXcJzsMLaApT0Bk1YfyzAa1!");
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle" }).catch(() => {}),
    page.click("button[type=submit]"),
  ]);
  await page.waitForTimeout(3000);

  // Try clicking the Users link directly via the menu
  const userMenu = await page.locator('[aria-haspopup="menu"]').last();
  await userMenu.click();
  await page.waitForTimeout(500);
  const usersLink = await page
    .locator('a:has-text("Users"), [role="menuitem"]:has-text("Users")')
    .first();
  await usersLink.click();
  await page.waitForTimeout(3000);

  await browser.close();
})();
