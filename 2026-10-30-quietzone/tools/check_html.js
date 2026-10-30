// Replays flip sets against the generated explorer page in headless Chromium
// and prints the page's verdicts as JSON. Usage: node check_html.js page.html cases.json [shotPrefix]
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [page_, casesFile, shot] = process.argv.slice(2);
  const cases = JSON.parse(fs.readFileSync(casesFile, 'utf8'));
  const browser = await chromium.launch();
  const out = { verdicts: [], errors: [], blocks: null };
  for (const scheme of ['light', 'dark']) {
    const ctx = await browser.newContext({ colorScheme: scheme, viewport: { width: scheme === 'light' ? 1100 : 390, height: 900 } });
    const page = await ctx.newPage();
    page.on('pageerror', e => out.errors.push(String(e)));
    page.on('console', m => { if (m.type() === 'error') out.errors.push(m.text()); });
    await page.goto('file://' + page_);
    if (scheme === 'light') {
      for (const flips of cases) {
        await page.evaluate(f => { window.__qz.reset(); window.__qz.flipAll(f); }, flips);
        out.verdicts.push(await page.evaluate(() => window.__qz.verdict()));
      }
      await page.evaluate(() => window.__qz.reset());
    }
    // exercise every view tab and the buttons; make sure nothing throws
    const nTabs = (await page.$$('#tabs button')).length;
    for (let i = 0; i < nTabs; i++) { await page.locator('#tabs button').nth(i).click(); }
    await page.click('#rnd'); await page.click('#burst');
    if (shot) {
      await page.locator('#tabs button').nth(2).click();
      await page.screenshot({ path: `${shot}-${scheme}.png`, fullPage: true });
    }
    // no horizontal overflow at phone width
    out.overflow = out.overflow || await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
