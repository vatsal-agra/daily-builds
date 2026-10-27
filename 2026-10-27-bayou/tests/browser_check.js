// Headless-Chromium check of the HTML report: clicking works, numbers match the Go engine,
// impossible evidence is refused, the layout survives a phone viewport, no console errors.
// usage: node tests/browser_check.js report.html expected_marginals.json
const { chromium } = require('playwright');
const assert = require('assert');
const [,, file, expectFile] = process.argv;
const expected = require(require('path').resolve(expectFile)); // {"LungCancer": {"yes":0.64,...}} for evidence Smoking=yes,XRay=abnormal

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  for (const [label, vp, scheme] of [['desktop-light', { width: 1280, height: 800 }, 'light'], ['desktop-dark', { width: 1280, height: 800 }, 'dark'], ['phone', { width: 390, height: 844 }, 'light']]) {
    const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme });
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(label + ': ' + e));
    page.on('console', m => { if (m.type() === 'error') errors.push(label + ': ' + m.text()); });
    await page.goto('file://' + require('path').resolve(file));
    await page.waitForSelector('.node');

    // no horizontal page scroll at any width
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    assert(!overflow, label + ': horizontal overflow');

    if (label === 'desktop-light') {
      // click "yes" under Smoking and "abnormal" under XRay through the real DOM
      await page.click('g.row[aria-label="Observe Smoking = yes"]');
      await page.click('g.row[aria-label="Observe XRay = abnormal"]');
      const chips = await page.$$eval('#evidence .chip', es => es.map(e => e.textContent.replace('×', '').trim()));
      assert.deepStrictEqual(chips.sort(), ['Smoking = yes', 'XRay = abnormal']);
      const post = await page.evaluate(() => window.__bayou.posterior);
      const names = await page.evaluate(() => Array.from(document.querySelectorAll('.node .title')).map(t => t.firstChild.textContent));
      for (const [name, dist] of Object.entries(expected)) {
        const v = names.indexOf(name);
        const states = await page.evaluate(v => Array.from(document.querySelectorAll('.node')[v].querySelectorAll('.lab')).map(t => t.textContent), v);
        Object.entries(dist).forEach(([s, p]) => assert(Math.abs(post[v][states.indexOf(s)] - p) < 1e-6, `${name}=${s}: page ${post[v][states.indexOf(s)]} vs Go ${p}`));
      }
      // bar widths mirror the posterior; observed rows are highlighted
      const onRows = await page.$$eval('g.row.on', es => es.length);
      assert.strictEqual(onRows, 2);
      // toggling a state off removes the chip
      await page.click('g.row[aria-label="Observe XRay = abnormal"]');
      assert.strictEqual((await page.$$('#evidence .chip')).length, 1);
      // impossible observation (Either=no with Tuberculosis=yes) is refused with a toast and state unchanged
      await page.click('g.row[aria-label="Observe Tuberculosis = yes"]');
      await page.click('g.row[aria-label="Observe Either = no"]');
      await page.waitForSelector('#toast.show');
      const evNow = await page.evaluate(() => Object.keys(window.__bayou.evidence).length);
      assert.strictEqual(evNow, 2, 'impossible evidence must be rolled back');
      // inspector + d-separation dimming
      await page.click('text.title[aria-label="Inspect Bronchitis"]');
      assert((await page.textContent('#inspect')).includes('Markov blanket'));
      assert((await page.$$('.node.dim')).length > 0, 'selecting a node should dim d-separated variables');
      // keyboard operation
      await page.focus('g.row[aria-label="Observe VisitAsia = yes"]');
      await page.keyboard.press('Enter');
      assert((await page.evaluate(() => Object.keys(window.__bayou.evidence).length)) === 3);
      // URL hash carries the evidence so a view can be shared
      assert((await page.evaluate(() => location.hash)).includes('VisitAsia'));
      await page.click('#reset');
      assert.strictEqual((await page.$$('#evidence .chip')).length, 0);
      const pe = await page.textContent('#s-pe');
      assert.strictEqual(pe.trim(), '1');
    }
    if (label === 'desktop-dark') {
      const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      assert.notStrictEqual(bg, 'rgb(244, 246, 248)', 'dark scheme not applied');
    }
    await page.screenshot({ path: `/tmp/browser-${label}.png` });
    await ctx.close();
  }
  await browser.close();
  assert.deepStrictEqual(errors, [], 'console/page errors: ' + errors.join('\n'));
  console.log('browser check OK (desktop light/dark, phone)');
})().catch(e => { console.error('FAIL', e.message || e); process.exit(1); });
