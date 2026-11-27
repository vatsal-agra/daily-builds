// Browser end-to-end check of the web UI. Requires Playwright (resolved via NODE_PATH or local install).
// Usage: node test/ui.e2e.cjs   (starts its own server on a free port)
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const { createServer } = await import('../serve.js');
  const srv = createServer(); await new Promise(r => srv.listen(0, r));
  const base = `http://localhost:${srv.address().port}/web/index.html`;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  const state = () => page.textContent('#state');
  let n = 0; const ok = m => console.log(`  ok ${++n} - ${m}`);

  await page.goto(`${base}#d=beginner&seed=e2e1`);
  await page.waitForSelector('.c');
  assert.equal(await page.locator('.c').count(), 81); ok('9x9 board renders');
  assert.equal(await state(), 'Ready'); assert.equal(await page.textContent('#minesLeft'), '10');

  await page.click('.c >> nth=40');
  assert.equal(await state(), 'Playing'); assert.ok(await page.locator('.c.o').count() > 1); ok('first click is safe and opens an area');

  await page.click('.c.h >> nth=0', { button: 'right' });
  assert.equal(await page.textContent('#minesLeft'), '9'); ok('right-click flags');
  await page.click('.c.flag'); assert.ok(await page.locator('.c.flag').count() === 1); ok('flagged cell cannot be revealed by click');
  await page.click('.c.flag', { button: 'right' }); assert.equal(await page.textContent('#minesLeft'), '10'); ok('right-click unflags');

  await page.check('#heat');
  assert.ok(await page.locator('.c.h .pct').count() > 0); ok('heat-map overlay shows odds on hidden cells');
  await page.hover('.c.h >> nth=0');
  assert.match(await page.textContent('#inspect'), /mine/); assert.match(await page.textContent('#stats'), /Consistent layouts/); ok('inspector shows exact odds + solver stats');
  await page.click('#hint');
  assert.ok(await page.locator('.c.hint').count() >= 1); ok('hint highlights the suggested cell');
  await page.click('#flagmines');
  ok('flag-sure-mines runs');

  await page.check('#autoguess'); await page.click('#auto');
  await page.waitForFunction(() => /Cleared|Detonated/.test(document.getElementById('state').textContent), null, { timeout: 60000 });
  await page.waitForSelector('#reportCard:not([hidden])');
  assert.match(await page.textContent('#report'), /Risks taken/); ok(`auto-play finished (${await state()}) and luck report appears`);

  // seed determinism: same seed + same first click => same board
  const board = async () => page.evaluate(() => [...document.querySelectorAll('.c')].map(c => c.className.includes(' o') ? 1 : 0).join(''));
  await page.goto(`${base}#d=beginner&seed=det`); await page.waitForSelector('.c'); await page.click('.c >> nth=10'); const b1 = await board();
  await page.reload(); await page.waitForSelector('.c'); await page.click('.c >> nth=10'); const b2 = await board();
  assert.equal(b1, b2); ok('seed in URL reproduces the same board');
  await page.evaluate(() => { location.hash = '#d=beginner&seed=other'; });
  await page.waitForFunction(() => document.getElementById('seed').value === 'other');
  assert.equal(await state(), 'Ready'); ok('pasting a new link into an open tab starts that game');
  await page.click('.c >> nth=10'); assert.notEqual(await board(), b1); ok('different seed gives a different board');

  // no-guess mode: step-solving with guessing disallowed always wins
  await page.goto(`${base}#d=intermediate&seed=ngx&ng=1`); await page.waitForSelector('.c');
  assert.equal(await page.isChecked('#noguess'), true);
  await page.click('.c >> nth=120'); await page.click('#auto');
  await page.waitForFunction(() => /Cleared|Detonated/.test(document.getElementById('state').textContent), null, { timeout: 60000 });
  assert.equal(await state(), 'Cleared!'); ok('no-guess board is cleared by certain deductions only (auto never needed a guess)');

  // invalid custom config is handled
  await page.selectOption('#level', 'custom'); await page.fill('#cm', '999'); await page.dispatchEvent('#cm', 'change');
  assert.match(await page.textContent('#advice'), /Invalid setup/); ok('invalid custom config reports an error instead of crashing');

  // loss path
  await page.goto(`${base}#d=beginner&seed=lose`); await page.waitForSelector('.c'); await page.click('.c >> nth=40');
  for (let i = 0; i < 81 && (await state()) === 'Playing'; i++) { const h = page.locator('.c.h:not(.flag)'); if (!(await h.count())) break; await h.nth(0).click(); }
  assert.ok(['Detonated', 'Cleared!'].includes(await state())); ok('playing until the end reaches a terminal state');
  if ((await state()) === 'Detonated') assert.ok(await page.locator('.c.boom').count() === 1);

  // phone viewport: no horizontal page overflow
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`${base}#d=expert&seed=m`); await page.waitForSelector('.c');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true); ok('expert board on a phone does not overflow the page');

  assert.deepEqual(errors, []); ok('no page errors');
  await browser.close(); srv.close();
  console.log(`ui e2e: ${n} checks passed`);
})().catch(e => { console.error(e); process.exit(1); });
