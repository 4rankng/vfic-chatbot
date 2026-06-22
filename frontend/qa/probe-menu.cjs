const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.evaluate(() => { localStorage.clear(); });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.fill('input[name=email]', 'admin@tingting.vip');
  await page.fill('input[name=password]', 't8fXyXcJzsMLaApT0Bk1YfyzAa1!');
  await Promise.all([page.waitForNavigation({waitUntil: 'networkidle'}).catch(()=>{}), page.click('button[type=submit]')]);
  await page.waitForTimeout(3000);

  // Stay on dashboard
  // Find the user menu (top right)
  const userMenu = await page.locator('[aria-haspopup="menu"]').last();
  await userMenu.click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: '/tmp/qa-audit/usermenu-open.png' });
  console.log('User menu opened');

  // Find the "Users" menu item
  const usersLink = await page.locator('a:has-text("Users"), [role="menuitem"]:has-text("Users")').first();
  if (await usersLink.count() > 0) {
    console.log('Found Users menu item');
    await usersLink.click();
    await page.waitForTimeout(3000);
    const t = await page.evaluate(() => document.body.innerText.slice(0, 500));
    console.log('AFTER CLICK:', t);
  } else {
    console.log('Users menu NOT FOUND — admin should see it');
  }

  await browser.close();
})();