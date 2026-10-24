// Renders the example graph in headless Chromium in both colour schemes and exercises the page.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const path = require('path'), os = require('os'), fs = require('fs');

(async () => {
  const root = path.join(__dirname, '..');
  const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pinion-')), 'g.html');
  execFileSync(path.join(root, 'bin/pinion'), ['graph', '-o', out], { cwd: path.join(root, 'examples/webapp') });
  const b = await chromium.launch();
  let failed = 0;
  const check = (ok, msg) => { console.log((ok ? '  ok   ' : '  FAIL ') + msg); if (!ok) failed++; };
  for (const scheme of ['light', 'dark']) {
    const p = await b.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: scheme });
    const errs = [];
    p.on('pageerror', e => errs.push(e.message));
    p.on('console', m => m.type() === 'error' && errs.push(m.text()));
    await p.goto('file://' + out);
    check((await p.$$('.node')).length === 13, `${scheme}: 12 packages + root drawn`);
    const bg = await p.evaluate(() => getComputedStyle(document.body).backgroundColor);
    check(scheme === 'dark' ? bg === 'rgb(20, 19, 15)' : bg === 'rgb(246, 244, 239)', `${scheme}: themed background (${bg})`);
    await p.click('.node[data-id="tlslib"]');
    const hot = (await p.$$('.hot')).length, dim = (await p.$$('.dim')).length;
    check(hot > 0 && dim > 0, `${scheme}: click traces paths (hot=${hot}, dim=${dim})`);
    check((await p.$$('tr.hl')).length === 1, `${scheme}: table row highlighted`);
    await p.keyboard.press('Escape');
    check((await p.$$('.dim')).length === 0, `${scheme}: Escape resets`);
    await p.fill('#q', 'json');
    check((await p.$$('#t tbody tr:not([hidden])')).length === 1, `${scheme}: filter narrows table`);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    check(!overflow, `${scheme}: no horizontal page overflow`);
    check(errs.length === 0, `${scheme}: no console errors ${errs.join('|')}`);
    await p.close();
  }
  const m = await b.newPage({ viewport: { width: 390, height: 800 } });
  await m.goto('file://' + out);
  check(!(await m.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)), 'phone width: page does not scroll sideways');
  await b.close();
  process.exit(failed ? 1 : 0);
})();
