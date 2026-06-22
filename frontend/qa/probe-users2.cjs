const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on('console', m => console.log(`[${m.type()}]`, m.text().slice(0, 300)));
  page.on('pageerror', e => console.log('[pageerror]', e.message.slice(0, 400)));

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  // Clear all localStorage
  await page.evaluate(() => { localStorage.clear(); });
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.fill('input[name=email]', 'admin@tingting.vip');
  await page.fill('input[name=password]', 't8fXyXcJzsMLaApT0Bk1YfyzAa1!');
  await Promise.all([page.waitForNavigation({waitUntil: 'networkidle'}).catch(()=>{}), page.click('button[type=submit]')]);
  await page.waitForTimeout(3000);

  // Verify canAccess works
  const result = await page.evaluate(async () => {
    // Read what React knows about canAccess
    const ls = {};
    for (let i=0; i<localStorage.length; i++) {
      const k = localStorage.key(i);
      ls[k] = localStorage.getItem(k);
    }
    return ls;
  });
  console.log('--- LS ---');
  for (const [k,v] of Object.entries(result)) {
    if (k.includes('profile') || k.includes('auth')) {
      console.log(k, '=', v.slice(0, 200));
    }
  }

  await page.goto('http://localhost:5173/#/users', { waitUntil: 'networkidle' });
  await page.waitForTimeout(5000);
  const t = await page.evaluate(() => document.body.innerText.slice(0, 500));
  console.log('USERS TEXT:', t);

  await browser.close();
})();