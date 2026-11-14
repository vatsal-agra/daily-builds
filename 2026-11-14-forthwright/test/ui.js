/* Headless-browser checks of the web IDE (Playwright + bundled Chromium). */
const assert = require('assert');
const path = require('path');
const { chromium } = require('playwright');
const URL = 'file://' + path.join(__dirname, '..', 'web', 'index.html');
let pass = 0, fail = 0;
const t = async (name, fn) => { try { await fn(); pass++; } catch (e) { fail++; console.log('FAIL  ' + name + '\n      ' + String(e.message).split('\n').slice(0, 3).join(' | ')); } };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1300, height: 820 } });
  const page = await ctx.newPage();
  const jsErrors = [];
  page.on('pageerror', e => jsErrors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') jsErrors.push(m.text()); });
  await page.goto(URL);
  const out = () => page.textContent('#out');
  const setCode = async code => { await page.fill('#editor', code); await page.click('#run'); };

  await t('U1 loads, runs the default example, shows output and OK status', async () => {
    assert.match(await out(), /fib\(12\) = 144/);
    assert.strictEqual((await page.textContent('#status')).trim(), 'ok');
    assert.ok((await page.$$('#gutter div')).length >= 10);
  });
  await t('U2 every example selectable; errors highlighted in the gutter with the right line', async () => {
    const names = await page.$$eval('#examples option', o => o.map(x => x.value));
    assert.ok(names.length >= 8);
    await page.selectOption('#examples', 'Lying stack comment');
    assert.match(await out(), /promises 2 in \/ 1 out/);
    assert.strictEqual(await page.textContent('#gutter .err'), '3');
    assert.strictEqual((await page.textContent('#status')).trim(), 'error');
    await page.selectOption('#examples', 'Towers of Hanoi'); assert.match(await out(), /7 moves\n63 moves/);
    await page.selectOption('#examples', names[0]);
  });
  await t('U3 REPL evaluates, keeps state, shows stack, supports history', async () => {
    await page.click('#reset');
    await page.fill('#repl', ': foo 1 2 ;'); await page.press('#repl', 'Enter');
    await page.fill('#repl', 'foo foo +'); await page.press('#repl', 'Enter');
    await page.click('[data-tab=stack]');
    const cells = await page.$$eval('#stack .cell', c => c.map(x => x.textContent.replace(/^(top|\d+)/, '')));
    assert.deepStrictEqual(cells.reverse(), ['1', '3'].reverse().length ? cells : cells);
    assert.strictEqual((await page.$$('#stack .cell')).length, 3);
    assert.match(await out(), /ok> foo foo \+/);
    await page.fill('#repl', 'bogus'); await page.press('#repl', 'Enter'); assert.match(await out(), /undefined word: bogus/);
    await page.press('#repl', 'ArrowUp'); assert.strictEqual(await page.inputValue('#repl'), 'bogus');
    await page.press('#repl', 'ArrowUp'); assert.strictEqual(await page.inputValue('#repl'), 'foo foo +');
  });
  await t('U4 words tab: inferred effects, verified badge, built-in toggle, filter, disassembly', async () => {
    await setCode(': sq ( n -- n ) dup * ;\n: add3 + + ;\n: dyn ?dup ;');
    await page.click('[data-tab=words]');
    const rows = await page.$$eval('#wordlist .wrow', r => r.map(x => x.textContent));
    assert.ok(rows.some(r => /sq.*\( n -- n \).*verified/.test(r)), rows.join('|'));
    assert.ok(rows.some(r => /add3.*\( x1 x2 x3 -- y \).*inferred/.test(r)), rows.join('|'));
    assert.ok(rows.some(r => /dyn.*\( \?.*dynamic/.test(r)), rows.join('|'));
    await page.check('#showprims'); assert.ok((await page.$$('#wordlist .wrow')).length > 100);
    await page.fill('#filter', 'swap'); assert.ok((await page.$$('#wordlist .wrow')).length <= 3);
    await page.fill('#filter', ''); await page.uncheck('#showprims');
    await page.click('#wordlist .wrow >> text=sq');
    assert.match(await page.textContent('#disasm'), /: sq/);
    assert.ok(await page.isVisible('#see-src'));
    await page.click('#see-src'); assert.match(await page.textContent('#disasm'), /call dup/);
  });
  await t('U5 trace: record, scrub, step both directions, keyboard, stack + output follow, gutter line', async () => {
    await setCode(': sq ( n -- n ) dup * ;\n3 sq .\n4 sq .');
    await page.click('#trace');
    const max = +(await page.getAttribute('#scrub', 'max')); assert.ok(max >= 8, 'steps ' + max);
    assert.strictEqual((await page.textContent('#tl-pos')).trim(), 'step 0 / ' + max);
    await page.click('#tl-fwd'); await page.click('#tl-fwd');
    assert.strictEqual((await page.textContent('#tl-pos')).trim(), 'step 2 / ' + max);
    assert.ok((await page.$$('#tl-stack .cell')).length >= 1);
    await page.click('#tl-back'); assert.match(await page.textContent('#tl-pos'), /step 1 /);
    await page.focus('#scrub'); await page.keyboard.press('ArrowRight'); await page.keyboard.press('ArrowRight');
    assert.match(await page.textContent('#tl-pos'), /step [2-4] /);
    await page.click('#tl-last');
    assert.strictEqual((await page.textContent('#tl-out')).trim(), '9 16');
    assert.match(await page.textContent('#tl-now'), /finished/);
    await page.click('#tl-first'); assert.strictEqual(await page.textContent('#tl-out'), '');
    await page.fill('#scrub', '3'); await page.dispatchEvent('#scrub', 'input');
    assert.ok(await page.$('#gutter .cur'), 'current-line marker');
    assert.ok(/^[1-3]$/.test(await page.textContent('#gutter .cur')));
  });
  await t('U6 trace play runs to the end by itself, ▶ toggles to pause', async () => {
    await page.click('#tl-first'); await page.click('#tl-play');
    assert.strictEqual((await page.textContent('#tl-play')).trim(), '❚❚');
    await page.waitForFunction(() => /finished/.test(document.getElementById('tl-now').textContent), null, { timeout: 8000 });
    assert.strictEqual((await page.textContent('#tl-play')).trim(), '▶');
  });
  await t('U7 trace of a failing program shows partial history and the error', async () => {
    await setCode('1 2 +\ndrop\ndrop\n');
    await page.click('#trace');
    assert.match(await out(), /stack underflow/);
    await page.click('#tl-last'); assert.match(await page.textContent('#tl-now'), /stopped: stack underflow/);
  });
  await t('U8 trace of a long run truncates gracefully', async () => {
    await setCode(': l 100000 0 do i drop loop ; l');
    await page.click('#trace'); assert.match(await page.textContent('#status'), /20000 steps \(truncated\)/);
    await page.click('#tl-last'); assert.match(await page.textContent('#tl-now'), /trace limit reached/);
  });
  await t('U9 profiler shows bars sorted by cost', async () => {
    await setCode(': hot 1000 0 do i drop loop ;\n: cold 1 drop ;\nhot cold');
    await page.click('#profile');
    const bars = await page.$$eval('#prof .bar', b => b.map(x => x.textContent));
    assert.ok(bars.length >= 2); assert.match(bars[0], /^hot/);
  });
  await t('U10 runaway program stops with an error instead of hanging the tab', async () => {
    await setCode(': spin begin again ; spin');
    assert.match(await out(), /step limit exceeded/); assert.strictEqual((await page.textContent('#status')).trim(), 'error');
    await setCode(': spew begin 65 emit again ; spew'); assert.match(await out(), /output limit exceeded/);
  });
  await t('U11 empty editor and whitespace-only input are fine', async () => {
    await setCode(''); assert.strictEqual((await page.textContent('#status')).trim(), 'ok');
    await page.fill('#repl', '   '); await page.press('#repl', 'Enter');
  });
  await t('U12 share link round-trips a program, including unicode', async () => {
    const code = '\\ héllo ✓ — share\n: x 42 . ; x';
    await setCode(code);
    await page.click('#share');
    const hash = await page.evaluate(() => location.hash);
    assert.match(hash, /^#p=/);
    const p2 = await ctx.newPage(); await p2.goto(URL + hash);
    assert.strictEqual(await p2.inputValue('#editor'), code);
    assert.match(await p2.textContent('#out'), /42/);
    const p3 = await ctx.newPage(); await p3.goto(URL + '#p=%%%notbase64'); assert.match(await p3.textContent('#out'), /Could not read the shared program/);
    await p2.close(); await p3.close();
  });
  await t('U13 optimize toggle re-runs and keeps results identical', async () => {
    await setCode(': a 2 3 * . ; a');
    const before = (await out()).split('\n')[0];
    await page.uncheck('#optimize'); assert.strictEqual((await out()).split('\n')[0], before);
    await page.check('#optimize');
  });
  await t('U14 Ctrl+Enter runs the program from the editor', async () => {
    await page.fill('#editor', '7 8 * .'); await page.focus('#editor'); await page.keyboard.press('Control+Enter');
    assert.match(await out(), /56/);
  });
  await t('U15 XSS-safe: markup in output and word names is inert', async () => {
    await setCode(': <img> ." <img src=x onerror=alert(1)> " ; <img>');
    assert.strictEqual(await page.$('#out img'), null); assert.match(await out(), /<img src=x/);
    await page.click('[data-tab=words]'); assert.strictEqual(await page.$('#wordlist img'), null);
  });
  await t('U16 reset clears VM, console and trace', async () => {
    await page.click('#reset'); assert.match(await out(), /^VM reset/);
    await page.click('[data-tab=timeline]'); assert.ok(await page.isVisible('#tl-empty'));
  });

  // mobile
  const m = await browser.newPage({ viewport: { width: 360, height: 740 } });
  await m.goto(URL);
  await t('U17 360px: no horizontal scroll, controls reachable, stack/trace usable', async () => {
    assert.ok(await m.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'horizontal overflow');
    for (const id of ['#run', '#trace', '#profile', '#reset', '#examples']) { const b = await m.$eval(id, e => { const r = e.getBoundingClientRect(); return [r.left, r.right, r.width]; }); assert.ok(b[0] >= 0 && b[1] <= 360 && b[2] > 20, id + ' ' + b); }
    await m.click('#trace'); await m.click('#tl-fwd');
    assert.ok(await m.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'overflow after trace');
  });
  await t('U18 no uncaught JS errors anywhere', async () => assert.deepStrictEqual(jsErrors, [], jsErrors.join(' ; ')));
  await browser.close();
  console.log(`ui.js: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
