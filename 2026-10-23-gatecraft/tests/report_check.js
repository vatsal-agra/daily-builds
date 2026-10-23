// Opens a generated report in headless Chromium and checks that the waveform viewer really works.
const { chromium } = require('playwright');
(async () => {
  const file = process.argv[2];
  const exe = ['/opt/pw-browsers/chromium-1194/chrome-linux/chrome'].find(p => require('fs').existsSync(p));
  const browser = await chromium.launch(exe ? { executablePath: exe } : {});
  let failed = false;
  for (const scheme of ['light', 'dark']) {
    const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: scheme })).newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto('file://' + file);
    const check = (ok, msg) => { if (!ok) { console.error(`${scheme}: ${msg}`); failed = true; } };
    check(await page.locator('section.card').count() >= 4, 'expected at least four report sections');
    const painted = await page.evaluate(() => { const c = document.getElementById('wave'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; });
    check(painted > 10000, `waveform canvas looks empty (${painted} painted pixels)`);
    await page.locator('#wave').scrollIntoViewIfNeeded();
    const box = await page.locator('#wave').boundingBox();
    await page.mouse.move(box.x + box.width * 0.5, box.y + 50);
    const label = await page.locator('#tlabel').textContent();
    check(/\d+ ns/.test(label) && !label.startsWith('end'), `cursor did not update the time label: ${label}`);
    const [r0] = await page.evaluate(() => [window.__wave.range.slice()]);
    await page.click('#zin');
    const r1 = await page.evaluate(() => window.__wave.range.slice());
    check(r1[1] - r1[0] < r0[1] - r0[0], 'zoom in did not narrow the visible range');
    await page.click('#fit');
    await page.fill('#flt', 'result');
    const n = await page.evaluate(() => window.__wave.visibleCount);
    check(n >= 1 && n <= 3, `filter "result" should leave a few signals, got ${n}`);
    await page.click('[data-radix="10"]');
    const val = await page.locator('.wv-row .vl').first().textContent();
    check(/^\d+$/.test(val), `decimal radix should show digits, got ${val}`);
    check(errors.length === 0, 'page errors: ' + errors.join('; '));
    await page.context().close();
  }
  await browser.close();
  if (failed) process.exit(1);
  console.log('report OK (light + dark)');
})();
