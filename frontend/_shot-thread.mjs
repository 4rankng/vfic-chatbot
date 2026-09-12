import { chromium } from "playwright";

const BASE = process.argv[3] ?? "http://[::1]:5173";
const TARGET = `${BASE}/#/conversations?channel_provider=zalo_oa&id=5c3aa51e-d3be-4723-ae55-2ca50fe75773`;
const LOGIN = `${BASE}/#/login`;
const TAG = process.argv[2] ?? "before";

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});
const page = await ctx.newPage();
// Block the dev service worker (it caches CSS) + bust GET cache so a fresh run
// always renders the latest styles. Leave POST untouched (login).
await ctx.route("**/*", (route) => {
  const req = route.request();
  if (/\/(dev-)?sw\.js|workbox|registerSW/i.test(req.url()))
    return route.abort();
  if (req.method() === "GET") {
    const h = req.headers();
    return route.continue({
      headers: { ...h, "Cache-Control": "no-cache", Pragma: "no-cache" },
    });
  }
  return route.continue();
});
page.on("console", (m) => {
  if (m.type() === "error")
    console.log("console.error:", m.text().slice(0, 220));
});

try {
  await page.goto(LOGIN, { waitUntil: "domcontentloaded", timeout: 20000 });
  await page.waitForSelector('input[type="email"]', { timeout: 15000 });
  await page.fill('input[type="email"]', "admin@vfic.dev");
  await page.fill('input[type="password"]', "admin123");
  await page.getByRole("button", { name: "Đăng nhập" }).click();
  await page.waitForTimeout(2500); // land post-login
  await page.goto(TARGET, { waitUntil: "domcontentloaded", timeout: 20000 });
  try {
    await page.waitForSelector(".chat-header", { timeout: 15000 });
  } catch {
    console.log(`[${TAG}] .chat-header not seen in 15s`);
  }
  await page.waitForTimeout(3000); // messages + realtime settle
  await page.screenshot({ path: `/tmp/vfic-thread-${TAG}.png` });
  const msgs = await page.locator("[data-message-id]").count();
  const probe = await page.evaluate(() => {
    const pick = (sel, props) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const cs = getComputedStyle(el);
      return Object.fromEntries(props.map((p) => [p, cs[p]]));
    };
    let elevationLoaded = false;
    for (const ss of document.styleSheets) {
      try {
        const txt = [...ss.cssRules].map((r) => r.cssText).join("\n");
        if (txt.includes("UntitledUI chat elevation")) {
          elevationLoaded = true;
          break;
        }
      } catch (e) {}
    }
    return {
      elevationLoaded,
      bubble: pick(".inbox-bg-container .bubble", [
        "boxShadow",
        "borderRadius",
      ]),
      composer: pick(".inbox-bg-container .composer", [
        "boxShadow",
        "borderRadius",
      ]),
      send: pick(".inbox-bg-container .composer-action.send", [
        "backgroundImage",
        "backgroundColor",
      ]),
    };
  });
  console.log(`[${TAG}] url=${page.url()} messages=${msgs}`);
  console.log(`[${TAG}] PROBE ${JSON.stringify(probe)}`);
} catch (e) {
  console.log(`[${TAG}] error: ${e.message}`);
  await page
    .screenshot({ path: `/tmp/vfic-thread-${TAG}.png` })
    .catch(() => {});
}
await browser.close();
