// Headless check of the HTML inspector: loads it, clicks every tab, searches, opens the object browser.
// usage: NODE_PATH=$(npm root -g) node tools/check_report.js report.html
const { chromium } = require('playwright');
(async () => {
  const file = process.argv[2];
  const b = await chromium.launch();
  let bad = 0;
  const check = (c, m) => { if (!c) { console.log('FAIL', m); bad++; } else console.log('ok  ', m); };
  for (const [w, h, scheme] of [[1280, 900, 'light'], [390, 800, 'dark']]) {
    const p = await b.newPage({ viewport: { width: w, height: h }, colorScheme: scheme });
    const errs = [];
    p.on('pageerror', e => errs.push(String(e)));
    p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    await p.goto('file://' + file);
    check(await p.locator('.stat').count() >= 4, `${w}px ${scheme}: stats rendered`);
    check(await p.locator('.thumb img').count() >= 1, `${w}px: thumbnails rendered`);
    for (const t of ['Text', 'Fonts', 'File layout', 'Objects', 'Pages']) {
      await p.click(`nav button:has-text("${t}")`);
    }
    await p.click('nav button:has-text("Text")');
    await p.fill('#q', 'fox');
    check(await p.locator('mark').count() >= 1, `${w}px: text search highlights`);
    await p.click('nav button:has-text("Objects")');
    const n = await p.locator('#objlist div[data-n]').count();
    check(n > 3, `${w}px: object list has ${n} entries`);
    await p.locator('#objlist div[data-n]').nth(2).click();
    check((await p.locator('#objdesc').textContent()).length > 2, `${w}px: object detail shows`);
    await p.click('nav button:has-text("File layout")');
    check(await p.locator('#map rect').count() > 3, `${w}px: layout map has rects`);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    check(!overflow, `${w}px: no horizontal overflow`);
    check(errs.length === 0, `${w}px: no console/page errors ${errs.join('|')}`);
    await p.close();
  }
  await b.close();
  process.exit(bad ? 1 : 0);
})();
