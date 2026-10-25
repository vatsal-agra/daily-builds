// Opens the generated viewers in headless Chromium: no console errors, canvas actually painted,
// hover shows triangle details, layer toggles repaint, light + dark + phone widths render.
// usage: node tests/browser_check.js <dir with *.html> [screenshot dir]
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path');
const dir = process.argv[2] || 'out', shots = process.argv[3];

async function painted(page) {
  return page.evaluate(() => {
    const c = document.getElementById('cv'), g = c.getContext('2d');
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n / (c.width * c.height);
  });
}

(async () => {
  const browser = await chromium.launch();
  let failures = 0;
  const fail = (m) => { failures++; console.log('  FAIL:', m); };
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.html')).sort()) {
    console.log(f);
    for (const [scheme, vp] of [['light', { width: 1280, height: 800 }], ['dark', { width: 1280, height: 800 }], ['light', { width: 390, height: 844 }]]) {
      const ctx = await browser.newContext({ colorScheme: scheme, viewport: vp });
      const page = await ctx.newPage();
      const errors = [];
      page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
      page.on('pageerror', e => errors.push(String(e)));
      page.on('request', r => { if (!r.url().startsWith('file:') && !r.url().startsWith('data:')) errors.push('external request ' + r.url()); });
      await page.goto('file://' + path.resolve(dir, f));
      await page.waitForTimeout(150);
      const cover = await painted(page);
      if (cover < 0.02) fail(`${scheme} ${vp.width}px: canvas looks empty (${cover.toFixed(4)} painted)`);
      // hover: scan the canvas for a triangle that reports details
      const box = await page.locator('#cv').boundingBox();
      let got = false;
      for (let k = 0; k < 40 && !got; k++) {
        await page.mouse.move(box.x + box.width * (0.3 + 0.4 * ((k * 0.37) % 1)), box.y + box.height * (0.3 + 0.4 * ((k * 0.61) % 1)));
        got = (await page.locator('#info dl').count()) > 0;
      }
      if (shots) { fs.mkdirSync(shots, { recursive: true }); await page.screenshot({ path: path.join(shots, `${f.replace('.html', '')}-${scheme}-${vp.width}.png`) }); }
      if (vp.width > 800) {
        if (!got) fail('hover never showed triangle details');
        const before = await painted(page);
        for (const id of ['L_tri', 'L_fill', 'L_pts']) await page.locator('#' + id).click();
        const after = await painted(page);
        if (Math.abs(after - before) < 1e-6) fail('toggling layers did not repaint');
        await page.mouse.wheel(0, -400);
        await page.dblclick('#cv');
      }
      if (errors.length) fail(`${scheme} ${vp.width}px: ${errors.slice(0, 3).join(' | ')}`);
      await ctx.close();
    }
  }
  await browser.close();
  console.log(failures ? `${failures} failure(s)` : 'browser check OK');
  process.exit(failures ? 1 : 0);
})();
