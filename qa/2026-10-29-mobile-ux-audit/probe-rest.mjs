import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = createRequire("/Volumes/LexarSSD/projects/chatbot/frontend/package.json")("@playwright/test");
const APP = "http://127.0.0.1:4173";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, locale: "vi-VN" });
const log = (s) => console.log(s);

// login
await page.goto(`${APP}/`, { timeout: 60000 });
await page.locator('input[type="email"]').fill("admin@vfic.dev");
await page.locator('input[type="password"]').fill("admin123");
await page.getByRole("button", { name: "Đăng nhập" }).click();
await page.waitForTimeout(2500);

// 1. skip link focused state
await page.keyboard.press("Tab");
await page.waitForTimeout(300);
const skip = await page.evaluate(() => {
  const el = document.activeElement;
  const s = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  return {
    text: (el.innerText || "").trim().slice(0, 30),
    cls: (el.getAttribute("class") || "").slice(0, 120),
    color: s.color,
    bg: s.backgroundColor,
    fs: s.fontSize,
    rect: { w: r.width, h: r.height, x: r.x, y: r.y },
  };
});
log("SKIP-FOCUSED " + JSON.stringify(skip));

// 2. inbox scrolled-to-bottom overlap check
await page.goto(`${APP}/#/conversations`, { timeout: 30000 });
await page.waitForTimeout(2200);
const inboxRest = await page.evaluate(async () => {
  const scroller = document.scrollingElement;
  const end = async () => {
    for (let i = 0; i < 20; i++) {
      window.scrollTo(0, scroller.scrollHeight);
      const panes = [...document.querySelectorAll("*")].filter((e) => e.scrollHeight > e.clientHeight + 50 && /auto|scroll/.test(getComputedStyle(e).overflowY));
      panes.forEach((p) => (p.scrollTop = p.scrollHeight));
      await new Promise((r) => setTimeout(r, 120));
    }
  };
  await end();
  const rows = [...document.querySelectorAll("button.conversation")];
  const bar = document.querySelector("nav.workspace-tabbar");
  const barR = bar ? bar.getBoundingClientRect() : null;
  const lastVisible = rows.filter((r) => {
    const b = r.getBoundingClientRect();
    return b.height > 0 && b.top < innerHeight;
  });
  const last = lastVisible[lastVisible.length - 1];
  const lr = last ? last.getBoundingClientRect() : null;
  return {
    rowCount: rows.length,
    barTop: barR ? barR.top : null,
    lastRow: lr ? { top: lr.top, bottom: lr.bottom, text: (last.innerText || "").replace(/\s+/g, " ").slice(0, 40) } : null,
    coveredByBar: lr && barR ? lr.bottom > barR.top + 4 : null,
    docScrollH: scroller.scrollHeight,
    innerH: innerHeight,
  };
});
log("INBOX-REST " + JSON.stringify(inboxRest));

// 3. settings scrolled-to-bottom overlap
await page.goto(`${APP}/#/settings`, { timeout: 30000 });
await page.waitForTimeout(2200);
const setRest = await page.evaluate(async () => {
  const scroller = document.scrollingElement;
  for (let i = 0; i < 20; i++) {
    window.scrollTo(0, scroller.scrollHeight);
    const panes = [...document.querySelectorAll("*")].filter((e) => e.scrollHeight > e.clientHeight + 50 && /auto|scroll/.test(getComputedStyle(e).overflowY));
    panes.forEach((p) => (p.scrollTop = p.scrollHeight));
    await new Promise((r) => setTimeout(r, 120));
  }
  const bar = document.querySelector("nav.workspace-tabbar");
  const barR = bar ? bar.getBoundingClientRect() : null;
  const interactive = [...document.querySelectorAll("button, a[href], input, select, textarea, summary")].filter((e) => {
    const r = e.getBoundingClientRect();
    return r.height > 0 && r.top < innerHeight && r.bottom > 0;
  });
  const last = interactive[interactive.length - 1];
  const lr = last ? last.getBoundingClientRect() : null;
  return {
    barTop: barR ? barR.top : null,
    lastControl: lr ? { top: lr.top, bottom: lr.bottom, tag: last.tagName, text: (last.innerText || last.getAttribute("aria-label") || "").replace(/\s+/g, " ").slice(0, 40) } : null,
    coveredByBar: lr && barR ? lr.bottom > barR.top + 4 : null,
  };
});
log("SETTINGS-REST " + JSON.stringify(setRest));

// 4. users "Sửa" white-text control geometry + bg chain
await page.goto(`${APP}/#/users`, { timeout: 30000 });
await page.waitForTimeout(2000);
const sua = await page.evaluate(() => {
  const spans = [...document.querySelectorAll("span")].filter((s) => /Sửa/.test(s.textContent || "") && getComputedStyle(s).color === "rgb(255, 255, 255)");
  return spans.slice(0, 3).map((s) => {
    const chain = [];
    let e = s;
    for (let i = 0; i < 5 && e; i++) {
      const cs = getComputedStyle(e);
      chain.push({ tag: e.tagName, cls: (e.getAttribute("class") || "").slice(0, 60), bg: cs.backgroundColor, bgImage: cs.backgroundImage.slice(0, 60), color: cs.color, radius: cs.borderRadius });
      e = e.parentElement;
    }
    const r = s.getBoundingClientRect();
    return { text: s.textContent.trim().slice(0, 30), rect: { w: r.width, h: r.height }, chain };
  });
});
log("SUA-CHAIN " + JSON.stringify(sua, null, 1));

// 5. performance table geometry + header cells
await page.goto(`${APP}/#/hieu-suat`, { timeout: 30000 });
await page.waitForTimeout(2500);
const perf = await page.evaluate(() => {
  const t = document.querySelector("table");
  if (!t) return null;
  const r = t.getBoundingClientRect();
  const headers = [...t.querySelectorAll("th")].map((th) => (th.innerText || "").trim().slice(0, 20));
  const scrollParents = [];
  let e = t.parentElement;
  while (e && e !== document.body) {
    const cs = getComputedStyle(e);
    if (/auto|scroll/.test(cs.overflowX)) scrollParents.push({ cls: (e.getAttribute("class") || "").slice(0, 50), scrollW: e.scrollWidth, clientW: e.clientWidth });
    e = e.parentElement;
  }
  return { rect: { w: r.width, h: r.height }, headers, tableScrollW: t.scrollWidth, tableClientW: t.clientWidth, scrollParents, bodyScrollW: document.body.scrollWidth };
});
log("PERF-TABLE " + JSON.stringify(perf, null, 1));

await browser.close();
