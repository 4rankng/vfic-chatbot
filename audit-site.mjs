// Direct Playwright audit script — bypasses the wedged MCP wrapper.
// Usage: node audit-site.mjs <output-dir>
// Logs in with the admin credentials, screenshots every page, dumps
// console + network errors, and writes a structured report.

import { chromium } from '/Users/dev/Documents/projects/vfic-ats/ChatBotN8N/frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
import path from 'node:path';

const BASE = 'https://bot.tingting.vip';
const USER = process.env.CRM_USERNAME || 'admin@tingting.vip';
const PASS = process.env.CRM_PASSWORD || 'Kmve1Ju0dof1bYCi1f2v';
const OUT = process.argv[2] || './audit-out';

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 }, // iPhone 14
];

fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.join(OUT, 'screens'), { recursive: true });

const report = {
  base: BASE,
  pages: [],
  consoleErrors: [],
  networkFailures: [],
  findings: [],
};

async function withTimeout(promise, ms, label) {
  return Promise.race([
    promise,
    new Promise((_, rej) => setTimeout(() => rej(new Error(`${label} timed out after ${ms}ms`)), ms)),
  ]);
}

async function shoot(page, file) {
  const p = path.join(OUT, 'screens', file);
  await page.screenshot({ path: p, fullPage: true });
  console.log('  📸', file);
  return p;
}

async function auditPage(page, name, url, viewport) {
  console.log(`\n▶ ${viewport.name} | ${name} -> ${url}`);
  const consoleMsgs = [];
  const netFails = [];
  page.on('console', (m) => {
    if (m.type() === 'error' || m.type() === 'warning') {
      consoleMsgs.push({ type: m.type(), text: m.text() });
    }
  });
  page.on('requestfailed', (r) => {
    netFails.push({ url: r.url(), failure: r.failure()?.errorText });
  });
  page.on('response', (r) => {
    if (r.status() >= 400) {
      netFails.push({ url: r.url(), status: r.status() });
    }
  });

  try {
    await withTimeout(page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 }), 22000, 'goto');
    // Wait a bit for SPA to render
    await page.waitForTimeout(2500);
    await shoot(page, `${viewport.name}-${name}.png`);
    const title = await page.title();
    const h1 = await page.locator('h1, h2').first().textContent().catch(() => null);
    report.pages.push({ viewport: viewport.name, name, url, title, heading: h1 });
  } catch (e) {
    report.findings.push({ page: name, viewport: viewport.name, severity: 'critical', issue: `Load failed: ${e.message}` });
  }
  report.consoleErrors.push(...consoleMsgs.map((m) => ({ ...m, page: name, viewport: viewport.name })));
  report.networkFailures.push(...netFails.map((m) => ({ ...m, page: name, viewport: viewport.name })));
}

async function login(page) {
  console.log('\n=== Logging in via UI ===');
  await page.goto(`${BASE}/#/login`, { waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(1500);
  // react-admin LoginPage: email + password fields
  const emailInput = page.locator('input[name="email"], input[type="email"], input[name="username"]').first();
  const passInput = page.locator('input[name="password"], input[type="password"]').first();
  await emailInput.fill(USER, { timeout: 5000 });
  await passInput.fill(PASS);
  await shoot(page, 'desktop-login-filled.png');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(3000);
  await shoot(page, 'desktop-after-login.png');
  const url = page.url();
  console.log('  Post-login URL:', url);
  if (url.includes('/login')) {
    report.findings.push({ severity: 'critical', issue: `Login UI did not redirect — still at ${url}` });
  }
}

async function run() {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });

  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);

    // 1) Public landing
    await auditPage(page, 'landing', `${BASE}/`, vp);

    // 2) Login page
    await auditPage(page, 'login', `${BASE}/#/login`, vp);

    // 3) Login + tour dashboard
    if (vp.name === 'desktop') {
      await login(page);

      // Tour every resource
      const routes = [
        ['dashboard', '/#/'],
        ['leads', '/#/leads'],
        ['leads-new', '/#/leads/create'],
        ['conversations', '/#/conversations'],
        ['bot-runs', '/#/bot_runs'],
        ['knowledge', '/#/knowledge_sources'],
        ['users', '/#/users'],
        ['settings', '/#/settings'],
      ];
      for (const [name, url] of routes) {
        await auditPage(page, name, BASE + url, vp);
      }
    }

    await context.close();
  }

  await browser.close();

  // Write report
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2));
  console.log('\n=== SUMMARY ===');
  console.log(`Pages:       ${report.pages.length}`);
  console.log(`Console:     ${report.consoleErrors.length} warnings/errors`);
  console.log(`Network:     ${report.networkFailures.length} failures`);
  console.log(`Findings:    ${report.findings.length} issues`);
  console.log(`\nReport: ${path.join(OUT, 'report.json')}`);
  console.log(`Screens: ${path.join(OUT, 'screens/')}`);
}

run().catch((e) => {
  console.error('FATAL:', e);
  process.exit(1);
});