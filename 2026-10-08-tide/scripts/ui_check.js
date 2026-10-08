// Drives the dashboard in headless Chromium and asserts on the real DOM.
// usage: NODE_PATH=<dir with playwright> node scripts/ui_check.js http://127.0.0.1:8428
const { chromium } = require('playwright');
const url = process.argv[2];
const exe = process.env.CHROMIUM || '/opt/pw-browsers/chromium';
let failed = 0;
const ok = (c, m) => { console.log((c ? '  ok   ' : '  FAIL ') + m); if (!c) failed++; };
(async () => {
  const b = await chromium.launch({ executablePath: exe });
  const errs = [];
  for (const [name, vp, scheme] of [['desktop-light', { width: 1300, height: 900 }, 'light'], ['phone-dark', { width: 390, height: 844 }, 'dark']]) {
    const p = await b.newPage({ viewport: vp, colorScheme: scheme });
    p.on('pageerror', e => errs.push(e.message));
    await p.goto(url); await p.waitForSelector('#grid .panel svg path', { timeout: 8000 });
    ok(await p.locator('#grid .panel svg path[stroke]').count() > 3, `${name}: charts render series paths`);
    ok((await p.textContent('#stats')).includes('compression'), `${name}: stat chips show compression`);
    ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${name}: no horizontal overflow`);
    const bg = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
    ok(scheme === 'dark' ? bg !== 'rgb(244, 247, 249)' : bg === 'rgb(244, 247, 249)', `${name}: theme follows prefers-color-scheme (${bg})`);
    // hover tooltip
    await p.locator('#grid .panel:first-child .chart').scrollIntoViewIfNeeded();
    const box = await p.locator('#grid .panel:first-child .chart').boundingBox();
    await p.mouse.move(box.x + box.width * 0.6, box.y + box.height / 2); await p.waitForTimeout(200);
    ok(await p.locator('#grid .panel:first-child .tip').evaluate(e => e.style.display === 'block' && e.textContent.length > 5), `${name}: hover tooltip shows values`);
    // bad query shows caret error
    await p.fill('#q', 'sum(avg(cpu_usage_percent'); await p.click('#run'); await p.waitForTimeout(300);
    const err = await p.textContent('#qerr');
    ok(/parse error/.test(err) && err.includes('^'), `${name}: parse error with caret`);
    // good ad-hoc query becomes first panel
    await p.fill('#q', 'p95(http_latency_ms{route="/api/orders"}) step 1m'); await p.click('#run'); await p.waitForTimeout(600);
    ok((await p.textContent('#grid .panel:first-child .pt')).includes('p95'), `${name}: ad-hoc query renders as panel`);
    const legend = p.locator('#grid .panel:first-child .legend span').first();
    await legend.click(); await p.waitForTimeout(150);
    ok(await p.locator('#grid .panel:first-child .legend span.off').count() === 1, `${name}: legend toggle hides a series`);
    // empty result is handled
    await p.fill('#q', 'does_not_exist'); await p.click('#run'); await p.waitForTimeout(400);
    ok((await p.textContent('#grid .panel:first-child .body')).includes('No data'), `${name}: empty result message`);
    // persistence stores only queries
    await p.click('#add'); await p.waitForTimeout(200);
    const saved = JSON.parse(await p.evaluate(() => localStorage.getItem('tide.panels')));
    ok(saved.every(x => Object.keys(x).join() === 'q'), `${name}: localStorage holds only {q}`);
    await p.close();
  }
  // alerts strip
  const p = await b.newPage({ viewport: { width: 1300, height: 900 } });
  await p.goto(url); await p.waitForTimeout(1200);
  if (process.env.EXPECT_ALERTS) ok(await p.locator('#alerts .alert').count() > 0, 'alerts strip lists rules/instances');
  ok(errs.length === 0, 'no uncaught JS errors ' + JSON.stringify(errs));
  await b.close();
  process.exit(failed ? 1 : 0);
})();
