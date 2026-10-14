// Headless-Chromium check of the HTML block map: no console errors, canvas actually painted,
// interactivity works. Usage: node check_map.js <map.html> [screenshot.png]
const { chromium } = require('playwright');
(async () => {
  const [file, shot] = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto('file://' + require('path').resolve(file));
  const fail = msg => { console.error('FAIL: ' + msg); process.exitCode = 1; };
  const painted = await page.evaluate(() => {
    const c = document.getElementById('map'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n;
  });
  if (painted < 1000) fail('canvas looks empty (' + painted + ' painted pixels)');
  const rows = await page.$$('tr.f');
  if (rows.length < 3) fail('expected inode rows, got ' + rows.length);
  if (shot) { await page.emulateMedia({ colorScheme: 'dark' }); await page.screenshot({ path: shot, fullPage: true }); }
  const before = await page.$eval('#detail', e => e.textContent);
  const big = await page.$('tr.f:has-text("big")') || rows[1];
  await big.click();
  const after = await page.$eval('#detail', e => e.textContent);
  if (before === after || !/extents/.test(after)) fail('clicking a file did not show its extents: ' + after);
  await page.fill('#q', 'zzzz-no-match');
  if ((await page.$$('tr.f')).length !== 0) fail('filter did not hide rows');
  await page.fill('#q', '');
  const box = await page.$eval('#map', e => { const r = e.getBoundingClientRect(); return [r.left, r.top]; });
  await page.mouse.move(box[0] + 20, box[1] + 10);
  const tip = await page.$eval('#tip', e => e.style.display + '|' + e.textContent);
  if (!/^block/.test(tip.split('|')[1] || '') ) fail('hover tooltip missing: ' + tip);
  const verdict = await page.$eval('#verdict', e => e.textContent);
  console.log('verdict badge:', verdict, '| rows:', rows.length, '| painted px:', painted);
  if (errors.length) fail('console errors: ' + errors.join('; '));
  await browser.close();
})();
