/**
 * Mobile UI/UX audit driver (29/10/2026) — AUDIT ONLY, no app code changes.
 * Local disposable stack: vite :4173 + e2e harness :3002 (harness pins CORS
 * to :4173 origins; API base is an explicit IPv4 literal).
 *
 * Walks the real console at 390x844 (iPhone) + 768px checkpoints and measures
 * doctrine triggers per screen:
 *   - page horizontal overflow / overlap
 *   - tap targets < 44px (touch)
 *   - truncated content with no way back (ellipsis / line-clamp)
 *   - tables rendered at mobile width (doctrine: cards < 768px)
 *   - inputs with font < 16px (iOS zoom)
 *   - covered/dead controls (elementFromPoint hit test)
 *   - contrast failures (measured fg/bg ratios only)
 *   - viewport-fit=cover vs env(safe-area-inset-*) usage
 *
 * Artifacts: NN-*.png screenshots + findings.json + driver.log, next to this file.
 */
import { createRequire } from "node:module";
import { mkdirSync, appendFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = "/Volumes/LexarSSD/projects/chatbot/frontend";
const { chromium } = createRequire(path.join(FRONTEND, "package.json"))("@playwright/test");
const APP = "http://127.0.0.1:4173";
const ADMIN_EMAIL = "admin@vfic.dev";
const ADMIN_PASSWORD = "admin123";

const log = (line) => {
  const stamped = `[${new Date().toISOString()}] ${line}`;
  console.log(stamped);
  appendFileSync(path.join(__dirname, "driver.log"), stamped + "\n");
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── in-page audit: returns a JSON-serializable findings object ─────────── */
function auditWindow() {
  const out = {
    url: location.href,
    viewport: { w: window.innerWidth, h: window.innerHeight },
    pageOverflow: null,
    viewportMeta: null,
    tapSmall: [],
    truncated: [],
    smallInputs: [],
    tables: [],
    deadControls: [],
    contrastFails: [],
    fixedBottom: [],
    navLinks: [],
    buttonDumps: [],
  };
  const seen = (el) => {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden" || +s.opacity < 0.1) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const desc = (el) => {
    const cls = (el.getAttribute("class") || "").split(/\s+/).slice(0, 4).join(".");
    const txt = (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().replace(/\s+/g, " ").slice(0, 48);
    return { tag: el.tagName.toLowerCase(), cls, text: txt };
  };

  out.pageOverflow = {
    docScrollW: document.documentElement.scrollWidth,
    docClientW: document.documentElement.clientWidth,
    bodyScrollW: document.body.scrollWidth,
  };
  const meta = document.querySelector('meta[name="viewport"]');
  out.viewportMeta = meta ? meta.getAttribute("content") : null;

  const interactive =
    'button, a[href], input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="link"], [role="tab"], [role="menuitem"], [role="option"], [role="checkbox"], [role="radio"], [role="switch"]';
  for (const el of document.querySelectorAll(interactive)) {
    if (!seen(el)) continue;
    const r = el.getBoundingClientRect();
    const minDim = Math.min(r.width, r.height);
    if (minDim >= 44) continue;
    if (el.closest("[aria-hidden='true']")) continue;
    out.tapSmall.push({
      ...desc(el),
      w: +r.width.toFixed(1),
      h: +r.height.toFixed(1),
      disabled: el.matches(":disabled, [aria-disabled='true']"),
    });
  }

  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    const clamped = s.webkitLineClamp && s.webkitLineClamp !== "none";
    const ellipsed = s.textOverflow === "ellipsis" && s.overflow === "hidden";
    if (!clamped && !ellipsed) continue;
    const overW = el.scrollWidth > el.clientWidth + 1;
    const overH = el.scrollHeight > el.clientHeight + 1;
    if (!overW && !overH) continue;
    if (!el.childNodes.length) continue;
    const hasTitle = el.hasAttribute("title");
    const parentExpandable =
      el.closest("details") !== null ||
      (el.parentElement && el.parentElement.querySelector(":scope > [aria-expanded], :scope > button, :scope > a")) !== null;
    out.truncated.push({
      ...desc(el),
      clamp: clamped ? s.webkitLineClamp : null,
      overW,
      overH,
      hasTitle,
      parentExpandable,
    });
  }

  for (const el of document.querySelectorAll('input:not([type="hidden"]), textarea, select')) {
    if (!seen(el)) continue;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 16) {
      out.smallInputs.push({ ...desc(el), fontSize: fs, type: el.getAttribute("type") || el.tagName.toLowerCase() });
    }
  }

  for (const el of document.querySelectorAll('table, [role="table"], [role="grid"]')) {
    if (!seen(el)) continue;
    out.tables.push({
      ...desc(el),
      rows: el.querySelectorAll("tr, [role='row']").length,
      scrollW: el.scrollWidth,
      clientW: el.clientWidth,
    });
  }

  for (const el of document.querySelectorAll(interactive)) {
    if (!seen(el)) continue;
    if (el.closest("[aria-hidden='true']")) continue;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) continue;
    const hit = document.elementFromPoint(cx, cy);
    if (!hit) continue;
    if (hit === el || el.contains(hit) || hit.contains(el)) continue;
    out.deadControls.push({
      ...desc(el),
      hitTag: hit.tagName.toLowerCase(),
      hitCls: (hit.getAttribute("class") || "").split(/\s+/).slice(0, 4).join("."),
      hitText: (hit.innerText || "").trim().replace(/\s+/g, " ").slice(0, 32),
    });
  }

  const parseRGB = (c) => {
    const m = c.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)/);
    return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null;
  };
  const lum = ({ r, g, b }) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (l1 + 0.05) / (l2 + 0.05);
  };
  for (const el of document.querySelectorAll("body *")) {
    const directText = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join(" ")
      .trim();
    if (!directText) continue;
    if (!seen(el)) continue;
    if (el.matches(":disabled, [aria-disabled='true']") || el.closest(":disabled, [aria-disabled='true']")) continue;
    const s = getComputedStyle(el);
    if (+s.opacity < 0.95) continue;
    const fg = parseRGB(s.color);
    if (!fg || fg.a < 0.95) continue;
    let bgEl = el;
    let bg = null;
    while (bgEl) {
      const c = parseRGB(getComputedStyle(bgEl).backgroundColor);
      if (c && c.a >= 0.95) {
        bg = c;
        break;
      }
      bgEl = bgEl.parentElement;
    }
    if (!bg) bg = { r: 255, g: 255, b: 255, a: 1 };
    const fs = parseFloat(s.fontSize);
    const fw = parseInt(s.fontWeight, 10) || 400;
    const large = fs >= 24 || (fs >= 18.66 && fw >= 700);
    const need = large ? 3 : 4.5;
    const got = +ratio(fg, bg).toFixed(2);
    if (got < need) {
      out.contrastFails.push({
        ...desc(el),
        fg: s.color,
        bgEl: bgEl ? bgEl.tagName.toLowerCase() + "." + (bgEl.getAttribute("class") || "").split(/\s+/).slice(0, 3).join(".") : "canvas",
        bg: `rgb(${bg.r}, ${bg.g}, ${bg.b})`,
        ratio: got,
        need,
        fontSize: fs,
        fontWeight: fw,
      });
    }
  }

  for (const el of document.querySelectorAll("body *")) {
    const s = getComputedStyle(el);
    if (s.position !== "fixed" && s.position !== "sticky") continue;
    if (!seen(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.bottom < innerHeight - 40 || r.top < innerHeight / 2) continue;
    out.fixedBottom.push({
      ...desc(el),
      h: +r.height.toFixed(1),
      paddingBottom: s.paddingBottom,
      bottom: +(innerHeight - r.bottom).toFixed(1),
    });
  }

  for (const a of document.querySelectorAll('a[href^="#/"]')) {
    if (!seen(a)) continue;
    out.navLinks.push({ href: a.getAttribute("href"), text: (a.innerText || a.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 40) });
  }
  for (const b of document.querySelectorAll("button")) {
    if (!seen(b)) continue;
    out.buttonDumps.push((b.innerText || b.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 48));
  }

  return out;
}

function scanSafeArea() {
  let used = 0;
  let rules = 0;
  const visit = (list) => {
    for (const r of list) {
      rules++;
      if (r.cssRules && r.cssRules.length) {
        visit(r.cssRules);
        continue;
      }
      if (r.cssText && r.cssText.includes("safe-area-inset")) used++;
    }
  };
  for (const sheet of document.styleSheets) {
    try {
      visit(sheet.cssRules);
    } catch {}
  }
  return { safeAreaRules: used, totalRules: rules };
}

const findings = {};
function flush() {
  writeFileSync(path.join(__dirname, "findings.json"), JSON.stringify(findings, null, 2));
}

async function main() {
  mkdirSync(__dirname, { recursive: true });
  writeFileSync(path.join(__dirname, "driver.log"), "");
  log("=== mobile ux audit drive start ===");

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    hasTouch: true,
    locale: "vi-VN",
  });
  const page = await ctx.newPage();

  const shot = async (name) => {
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(__dirname, `${name}.png`) });
    log(`SHOT ${name}.png`);
  };
  const audit = async (name) => {
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const res = await page.evaluate(auditWindow);
        const sa = await page.evaluate(scanSafeArea);
        res.safeAreaScan = sa;
        findings[name] = res;
        log(`AUDIT ${name}: overflow=${res.pageOverflow.docScrollW}/${res.pageOverflow.docClientW} tapSmall=${res.tapSmall.length} truncated=${res.truncated.length} smallInputs=${res.smallInputs.length} tables=${res.tables.length} dead=${res.deadControls.length} contrast=${res.contrastFails.length} safeAreaRules=${sa.safeAreaRules}`);
        flush();
        return res;
      } catch (e) {
        log(`AUDIT ${name} attempt ${attempt + 1} failed: ${String(e).slice(0, 120)}`);
        await page.waitForTimeout(2000);
      }
    }
    findings[name] = { error: "audit failed after retries" };
    flush();
    return findings[name];
  };
  const visit = async (hash, name) => {
    try {
      await page.goto(`${APP}/${hash}`, { timeout: 30_000 });
      await page.waitForTimeout(2000);
      await shot(name);
      await audit(name);
    } catch (e) {
      log(`VISIT ${name} failed: ${String(e).slice(0, 160)}`);
      await shot(`${name}-error`).catch(() => {});
    }
  };

  // ── 00 login (unauthenticated) ──
  await page.goto(`${APP}/`, { timeout: 60_000 });
  await page.locator('input[type="email"]').waitFor({ timeout: 30_000 });
  await shot("00-login-390");
  const loginAudit = await audit("login");

  await page.locator('input[type="email"]').fill(ADMIN_EMAIL);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page.waitForTimeout(2500);
  log(`after-login url=${page.url()}`);

  // ── 01 dashboard ──
  await visit("#/", "01-dashboard-390");
  const dash = findings["01-dashboard-390"];
  if (dash?.navLinks) {
    writeFileSync(path.join(__dirname, "nav-links.json"), JSON.stringify(dash.navLinks, null, 2));
  }

  // ── 02 conversations (inbox) ──
  await visit("#/conversations", "02-inbox-390");

  // open the first conversation thread row (button.conversation per ConversationList.tsx)
  let threadOpened = false;
  for (const sel of ["button.conversation", "a[href*='conversations?id=']"]) {
    const first = page.locator(sel).first();
    if ((await first.count()) > 0 && (await first.isVisible().catch(() => false))) {
      await first.click().catch(() => {});
      await page.waitForTimeout(1800);
      threadOpened = true;
      log(`thread opened via ${sel} → ${page.url()}`);
      break;
    }
  }
  if (threadOpened) {
    await shot("03-inbox-thread-390");
    await audit("03-inbox-thread-390");
  } else {
    log("WARN no conversation thread could be opened");
  }

  // ── 04 projects ──
  await visit("#/projects", "04-projects-390");

  // project card main → knowledge sheet (the project knowledge surface on mobile)
  let sheetOpened = false;
  const card = page.locator("button.project-card-main").first();
  if ((await card.count()) > 0 && (await card.isVisible().catch(() => false))) {
    await card.click().catch(() => {});
    await page.waitForTimeout(1800);
    sheetOpened = (await page.locator(".project-knowledge-sheet").count()) > 0;
    log(`knowledge sheet opened=${sheetOpened} → ${page.url()}`);
  }
  if (sheetOpened) {
    await shot("05-project-knowledge-sheet-390");
    await audit("05-project-knowledge-sheet-390");
    // drill: scroll the sheet for hidden/truncated content below the fold
    await page.mouse.wheel(0, 600).catch(() => {});
    await page.waitForTimeout(600);
    await shot("05b-project-knowledge-sheet-scrolled-390");
    await audit("05b-project-knowledge-sheet-scrolled-390");
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(600);
  } else {
    log("WARN knowledge sheet did not open");
  }

  // ── 06 settings ──
  await visit("#/settings", "06-settings-390");

  // settings section: channels (query-nav) + cloudfone panel (button-nav)
  await visit("#/settings?section=channels", "07-settings-channels-390");

  try {
    await page.goto(`${APP}/#/settings`, { timeout: 30_000 });
    await page.waitForTimeout(1500);
    const cf = page.getByRole("button", { name: /Cloudfone/i }).first();
    if ((await cf.count()) > 0 && (await cf.isVisible().catch(() => false))) {
      await cf.click().catch(() => {});
      await page.waitForTimeout(1600);
      await shot("08-settings-cloudfone-390");
      await audit("08-settings-cloudfone-390");
    } else {
      log("cloudfone settings button not found");
    }
  } catch (e) {
    log(`cloudfone section failed: ${String(e).slice(0, 160)}`);
  }

  // ── 09 users (admin) ──
  await visit("#/users", "09-users-390");

  // ── 10 call records (cloudfone) ──
  await visit("#/ban-ghi-cuoc-goi", "10-call-records-390");

  // ── 11 performance ──
  await visit("#/hieu-suat", "11-performance-390");

  // ── 12 profile ──
  await visit("#/profile", "12-profile-390");

  // ── 768px checkpoints (tablet) ──
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.waitForTimeout(800);
  for (const [hash, name] of [
    ["#/", "t-dashboard-768"],
    ["#/conversations", "t-inbox-768"],
    ["#/projects", "t-projects-768"],
    ["#/settings", "t-settings-768"],
  ]) {
    await visit(hash, name);
  }

  flush();
  log("=== audit complete — findings.json written ===");
  await browser.close();
}

main().catch((e) => {
  log(`FATAL ${e.stack || e}`);
  flush();
  process.exit(1);
});
