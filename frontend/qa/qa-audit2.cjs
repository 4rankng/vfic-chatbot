const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  const consoleErrors = [];
  const networkErrors = [];

  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(`[console] ${msg.text()}`);
  });
  page.on('pageerror', err => consoleErrors.push(`[pageerror] ${err.message}`));
  page.on('response', resp => {
    if (resp.status() >= 400) {
      networkErrors.push(`${resp.status()} ${resp.request().method()} ${resp.url()}`);
    }
  });

  // Login
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.fill('input[name="email"], input[type="email"]', 'admin@tingting.vip');
  await page.fill('input[name="password"], input[type="password"]', 't8fXyXcJzsMLaApT0Bk1YfyzAa1!');
  await Promise.all([
    page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}),
    page.click('button[type="submit"]')
  ]);
  await page.waitForTimeout(2500);

  // Visit each route
  const routes = ['/', '/conversations', '/leads', '/knowledge_sources', '/bot_runs', '/users', '/profile'];
  for (const route of routes) {
    consoleErrors.length = 0;
    networkErrors.length = 0;
    await page.goto(`http://localhost:5173/#${route}`, { waitUntil: 'networkidle' }).catch(e => console.log('nav err', e.message));
    await page.waitForTimeout(2500);
    const fname = `/tmp/qa-audit/v2-${route.replace(/\//g, '_') || 'root'}.png`;
    await page.screenshot({ path: fname, fullPage: true });
    const txt = await page.evaluate(() => document.body.innerText.slice(0, 300));
    const url = page.url();
    console.log(`\n--- Route ${route} → ${url} ---`);
    console.log('Text:', txt.replace(/\n/g, ' | ').slice(0, 250));
    if (consoleErrors.length) {
      console.log('CONSOLE ERRORS:', consoleErrors.slice(0,3));
    }
    if (networkErrors.length) {
      console.log('NETWORK ERRORS:', networkErrors.slice(0,5));
    }
  }

  await browser.close();
  console.log('\nDONE');
})();