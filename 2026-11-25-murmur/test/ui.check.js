'use strict';
// Browser end-to-end check (needs Playwright; skipped by demo.sh when unavailable).
const path = require('path'); const assert = require('assert/strict');
let chromium; try { ({ chromium } = require('playwright')); } catch { console.log('SKIP ui.check: playwright not installed'); process.exit(0); }
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = []; p.on('pageerror', (e) => errs.push(e.message)); p.on('console', (m) => m.type() === 'error' && errs.push(m.text()));
  await p.goto('file://' + path.join(__dirname, '..', 'index.html')); await p.waitForTimeout(800);
  const st = () => p.evaluate(() => { const f = murmur.flock; return { n: f.n, pred: f.predators.length, obs: f.obstacles.length, mode: f.p.mode, bd: f.p.boundary, step: f.step_n, k: f.p.k, noise: f.p.noise }; });
  let s = await st(); assert.ok(s.step > 5, 'simulation advances on its own');
  const box = await p.locator('#c').boundingBox(); const at = (x, y) => [box.x + x / 900 * box.width, box.y + y / 560 * box.height];
  await p.click('[data-tool=predator]'); await p.mouse.click(...at(450, 280)); assert.equal((await st()).pred, 1);
  await p.click('[data-tool=obstacle]'); await p.mouse.click(...at(200, 200)); assert.equal((await st()).obs, 1);
  await p.click('[data-tool=erase]'); await p.mouse.click(...at(200, 200)); assert.equal((await st()).obs, 0, 'erase removes obstacle');
  await p.mouse.click(...at(700, 500)); assert.equal((await st()).pred, 0, 'erase on empty space clears predators');
  await p.click('[data-mode=topological]'); await p.click('[data-bd=wall]'); s = await st(); assert.equal(s.mode, 'topological'); assert.equal(s.bd, 'wall');
  await p.locator('#sl_n').fill('300'); assert.equal((await st()).n, 300, 'agents slider resizes live');
  await p.locator('#sl_k').fill('3'); assert.equal((await st()).k, 3);
  await p.click('#presetHot'); assert.ok((await st()).noise >= 0.6);
  await p.click('#play'); const a = (await st()).step; await p.waitForTimeout(300); assert.equal((await st()).step, a, 'pause freezes'); await p.click('#stepb'); assert.equal((await st()).step, a + 1, 'single step');
  const dl = p.waitForEvent('download'); await p.click('#save'); const file = path.join(require('os').tmpdir(), 'murmur-ui-snap.json'); await (await dl).saveAs(file);
  await p.click('#reset'); await p.setInputFiles('#file', file); await p.waitForTimeout(200);
  s = await st(); assert.equal(s.step, a + 1, 'snapshot loads back to saved step'); assert.match(await p.locator('#msg').textContent(), /loaded step/);
  const bad = path.join(require('os').tmpdir(), 'murmur-bad.json'); require('fs').writeFileSync(bad, '{"v":1}'); await p.setInputFiles('#file', bad); await p.waitForTimeout(200);
  assert.match(await p.locator('#msg').textContent(), /could not load/);
  assert.deepEqual(errs, [], 'no console errors');
  await b.close(); console.log('ui.check: all browser checks passed');
})().catch((e) => { console.error('UI CHECK FAILED:', e.message); process.exit(1); });
