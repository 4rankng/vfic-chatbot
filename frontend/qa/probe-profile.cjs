const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on('console', m => {
    const text = m.text();
    if (m.type() === 'error' || text.includes('notif') || text.includes('error')) {
      console.log(`[${m.type()}]`, text.slice(0, 400));
    }
  });
  page.on('pageerror', e => console.log('[pageerror]', e.message.slice(0, 400)));

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.evaluate(() => { localStorage.clear(); });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.fill('input[name=email]', 'admin@tingting.vip');
  await page.fill('input[name=password]', 't8fXyXcJzsMLaApT0Bk1YfyzAa1!');
  await Promise.all([page.waitForNavigation({waitUntil: 'networkidle'}).catch(()=>{}), page.click('button[type=submit]')]);
  await page.waitForTimeout(3000);

  await page.goto('http://localhost:5173/#/profile', { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);
  const t = await page.evaluate(() => document.body.innerText.slice(0, 500));
  console.log('PROFILE TEXT:', t);
  await page.screenshot({ path: '/tmp/qa-audit/profile-with-toast.png', fullPage: true });
  await browser.close();
})();