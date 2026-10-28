// Headless-browser check of the HTML report: renders in light / dark / phone widths, no overflow,
// charts present, no console errors, no network requests.
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const file = path.resolve(process.argv[2]);
  const b = await chromium.launch();
  let bad = 0;
  for (const [name, scheme, w] of [['light', 'light', 1100], ['dark', 'dark', 1100], ['phone', 'light', 375]]) {
    const p = await b.newPage({ viewport: { width: w, height: 900 }, colorScheme: scheme });
    const errors = [], requests = [];
    p.on('console', m => m.type() === 'error' && errors.push(m.text()));
    p.on('pageerror', e => errors.push(String(e)));
    p.on('request', r => !r.url().startsWith('file:') && requests.push(r.url()));
    await p.goto('file://' + file);
    const r = await p.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > window.innerWidth,
      svgs: document.querySelectorAll('svg').length,
      kpis: document.querySelectorAll('.kpi').length,
      bg: getComputedStyle(document.body).backgroundColor,
      ticks: document.querySelectorAll('svg .tp, svg .fp, svg .fn, svg .call').length,
    }));
    const ok = !r.overflow && r.svgs >= 3 && r.kpis >= 4 && r.ticks > 0 && !errors.length && !requests.length;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: svgs=${r.svgs} kpis=${r.kpis} ticks=${r.ticks} overflow=${r.overflow} bg=${r.bg} errors=${errors.length} requests=${requests.length}`);
    if (!ok) bad++;
    await p.close();
  }
  await b.close();
  process.exit(bad ? 1 : 0);
})();
