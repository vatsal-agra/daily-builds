// Headless check of the replay viewer: loads a page, clicks every tab, scrubs to
// the end, and fails on any console/page error or blank canvas.
// usage: NODE_PATH=$(npm root -g) node tools/verify_viewer.js path/to/replay.html [screenshot.png]
const { chromium } = require('playwright');
(async () => {
  const file = process.argv[2];
  if (!file) { console.error('usage: verify_viewer.js replay.html [shot.png]'); process.exit(2); }
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 800 } });
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto('file://' + require('path').resolve(file));
  const n = (await p.$$('.tab')).length;
  for (let i = 0; i < n; i++) {
    await (await p.$$('.tab'))[i].click();
    await p.evaluate(() => { const s = document.getElementById('scrub'); s.value = s.max; s.dispatchEvent(new Event('input')); });
    const painted = await p.evaluate(() => {
      const c = document.getElementById('cv'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      const seen = new Set(); for (let i = 0; i < d.length; i += 4 * 97) seen.add(d[i] + ',' + d[i + 1] + ',' + d[i + 2]);
      return seen.size;
    });
    if (painted < 4) errs.push(`tab ${i}: canvas looks blank (${painted} colours)`);
    await p.click('#play'); await p.waitForTimeout(100); await p.click('#rst');
  }
  if (process.argv[3]) await p.screenshot({ path: process.argv[3] });
  await b.close();
  if (errs.length) { console.error('FAIL', errs); process.exit(1); }
  console.log(`viewer OK: ${n} tabs, no errors`);
})();
