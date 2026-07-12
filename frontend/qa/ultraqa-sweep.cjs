// ultraqa-sweep.cjs — comprehensive visual QA sweep for /ultraqa 2026-07-13
// Logs in as admin@vfic.dev, captures every route at desktop 1440x900 + mobile 390x844,
// records console + network errors, asserts no horizontal overflow on mobile.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const OUT = '/Users/dev/Documents/projects/vfic-ats/ChatBot/plans/qa-2026-07-13';
const SCREENSHOTS = path.join(OUT, 'screenshots');
const CONSOLE = path.join(OUT, 'console-captures');
fs.mkdirSync(SCREENSHOTS, { recursive: true });
fs.mkdirSync(CONSOLE, { recursive: true });

const ROUTES = [
  // Resource routes
  { id: 'dashboard',         hash: '/' },
  { id: 'conversations',     hash: '/conversations' },
  { id: 'bot_runs',          hash: '/bot_runs' },
  { id: 'knowledge_sources', hash: '/knowledge_sources' },
  { id: 'projects',          hash: '/projects' },
  { id: 'personas',          hash: '/personas' },
  { id: 'users',             hash: '/users' },
  { id: 'settings',          hash: '/settings' },
  { id: 'profile',           hash: '/profile' },
  { id: 'hieu_suat',         hash: '/hieu-suat' },
  { id: 'forgot_password',   hash: '/forgot-password' },
  { id: 'login',             hash: '/login' },
];

const VIEWPORTS = [
  { id: 'desktop', width: 1440, height: 900 },
  { id: 'mobile',  width: 390,  height: 844, isMobile: true, deviceScaleFactor: 2, hasTouch: true },
];

const BASE = 'http://localhost:5173';

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const findings = [];
  const allErrors = {};

  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      isMobile: !!vp.isMobile,
      deviceScaleFactor: vp.deviceScaleFactor || 1,
      hasTouch: !!vp.hasTouch,
    });
    const page = await context.newPage();

    const errors = [];
    const networkErrors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(`[console] ${msg.text()}`);
    });
    page.on('pageerror', err => errors.push(`[pageerror] ${err.message}`));
    page.on('response', r => {
      if (r.status() >= 400) networkErrors.push(`${r.status()} ${r.request().method()} ${r.url()}`);
    });

    // Login
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(600);
    if (page.url().includes('/login')) {
      await page.fill('input[name="email"], input[type="email"]', 'admin@vfic.dev');
      await page.fill('input[name="password"], input[type="password"]', 'admin123');
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}),
        page.click('button[type="submit"]'),
      ]);
      await page.waitForTimeout(2000);
    }

    console.log(`\n=== viewport=${vp.id} ===`);
    for (const route of ROUTES) {
      // For login + forgot-password we may need to log out — skip auth requirement
      const url = `${BASE}/#${route.hash}`;
      errors.length = 0;
      networkErrors.length = 0;
      const t0 = Date.now();
      try {
        await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });
      } catch (e) {
        console.log(`  ✗ ${route.id}: nav error ${e.message}`);
      }
      await page.waitForTimeout(1800);
      const dt = Date.now() - t0;
      const fname = path.join(SCREENSHOTS, `${vp.id}-${route.id}.png`);
      await page.screenshot({ path: fname, fullPage: true });
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        bodyScroll: document.body.scrollWidth,
      })).catch(() => ({}));
      const horizOverflow = vp.id === 'mobile' && overflow.scrollWidth && overflow.scrollWidth > overflow.clientWidth + 2;
      const text = await page.evaluate(() => document.body.innerText.slice(0, 200)).catch(() => '');
      console.log(`  • ${route.id} (${dt}ms) → ${page.url().replace(BASE, '')} overflow=${horizOverflow ? 'YES' : 'no'}`);
      if (errors.length) console.log(`    console:`, errors.slice(0, 2));
      if (networkErrors.length) console.log(`    net:`, networkErrors.slice(0, 3));

      const key = `${vp.id}::${route.id}`;
      allErrors[key] = { errors: [...errors], networkErrors: [...networkErrors], overflow, text, dt };
      if (horizOverflow || errors.length || networkErrors.length) {
        findings.push({ vp: vp.id, route: route.id, errors: [...errors], networkErrors: [...networkErrors], overflow });
      }
    }

    await context.close();
  }

  fs.writeFileSync(path.join(CONSOLE, 'sweep-results.json'), JSON.stringify(allErrors, null, 2));
  fs.writeFileSync(path.join(OUT, 'sweep-summary.json'), JSON.stringify(findings, null, 2));
  console.log(`\n=== ${findings.length} routes with issues ===`);
  for (const f of findings) {
    console.log(`- ${f.vp} ${f.route}: console=${f.errors.length} net=${f.networkErrors.length} overflow=${f.overflow?.scrollWidth > f.overflow?.clientWidth + 2}`);
  }
  await browser.close();
})();
