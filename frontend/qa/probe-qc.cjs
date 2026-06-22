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

  // Inject a wrapper that logs canAccess calls
  await page.evaluate(async () => {
    // Try to find authProvider via React DevTools — not available.
    // Instead, inspect the React Query cache directly
    const qc = window.__REACT_QUERY_CLIENT__;
    console.log('Window RQC:', !!qc);
    const cache = qc?.getQueryCache?.();
    const queries = cache?.getAll?.() ?? [];
    console.log('Total queries:', queries.length);
    const canAccess = queries.filter(q => q.queryKey?.[0] === 'auth' && q.queryKey?.[1] === 'canAccess');
    console.log('canAccess queries:', canAccess.length);
    canAccess.forEach(q => {
      console.log('  key:', JSON.stringify(q.queryKey.slice(2)));
      console.log('  state:', JSON.stringify({ status: q.state.status, data: q.state.data, error: q.state.error?.message }));
    });
  });

  // Try /users
  await page.goto('http://localhost:5173/#/users', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);
  const result = await page.evaluate(() => {
    const qc = window.__REACT_QUERY_CLIENT__;
    const cache = qc?.getQueryCache?.();
    const queries = cache?.getAll?.() ?? [];
    return {
      total: queries.length,
      canAccess: queries.filter(q => q.queryKey?.[0] === 'auth' && q.queryKey?.[1] === 'canAccess').map(q => ({
        key: JSON.stringify(q.queryKey.slice(2)),
        status: q.state.status,
        data: q.state.data,
        error: q.state.error?.message
      }))
    };
  });
  console.log('after /users:', JSON.stringify(result, null, 2));

  await browser.close();
})();