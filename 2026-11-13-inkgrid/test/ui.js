'use strict';
// Browser end-to-end test (needs Playwright + Chromium). Run: node test/ui.js
const { chromium } = require('playwright'); const assert = require('assert'); const path = require('path');
const URL = 'file://' + path.resolve(__dirname, '..', 'index.html');
let n = 0; const ok = m => { n++; console.log('  ok  ' + m); };
(async () => {
  const b = await chromium.launch(); const errs = [];
  const mk = async (vp, hash) => { const p = await b.newPage({ viewport: vp }); p.on('pageerror', e => errs.push(e.message)); await p.goto(URL + (hash || '')); await p.waitForFunction(() => window.__inkgrid && window.__inkgrid.S.p); return p; };
  const cellXY = (p, x, y) => p.evaluate(([x, y]) => { const r = document.getElementById('board').getBoundingClientRect(), S = window.__inkgrid.S, k = r.width / S.geom.W, ky = r.height / S.geom.H; return [r.left + (S.geom.left + (x + .5) * S.geom.cell) * k, r.top + (S.geom.top + (y + .5) * S.geom.cell) * ky]; }, [x, y]);
  const click = async (p, x, y, opt) => { let [px, py] = await cellXY(p, x, y); if (py > (p.viewportSize().height - 10) || py < 0) { await p.evaluate(dy => window.scrollBy(0, dy), py - 200); [px, py] = await cellXY(p, x, y); } await p.mouse.move(px, py); if (opt && opt.right) { await p.mouse.down({ button: 'right' }); await p.mouse.up({ button: 'right' }); } else { await p.mouse.down(); await p.mouse.up(); } };
  const state = (p) => p.evaluate(() => ({ marks: Array.from(window.__inkgrid.S.marks), solved: window.__inkgrid.S.solved, sol: window.__inkgrid.S.solution, w: window.__inkgrid.S.w, h: window.__inkgrid.S.h }));

  console.log('UI: play through a full puzzle');
  let p = await mk({ width: 1100, height: 900 }, '');
  assert.ok((await p.textContent('#ratingPill')).includes('·')); ok('page boots with a generated, rated puzzle');
  let s = await state(p);
  let lastIdx = -1; for (let y = 0; y < s.h; y++) for (let x = 0; x < s.w; x++) if (s.sol[y][x]) { await click(p, x, y); lastIdx = y * s.w + x; }
  s = await state(p); assert.ok(s.solved); assert.ok(!(await p.locator('#banner').isHidden())); ok('filling the solution triggers win banner');
  assert.ok(s.marks.every(v => v !== -1)); ok('win tidies unknown cells to crosses');
  await p.click('#btnUndo'); s = await state(p);
  assert.ok(!s.solved); assert.strictEqual(s.marks[lastIdx], -1); assert.ok(s.marks.filter(v => v === 1).length === s.sol.flat().filter(Boolean).length - 1); ok('undo after win restores prior board (no stray crosses beyond auto-crosses)');
  await p.click('#btnRedo'); assert.ok((await state(p)).solved); ok('redo re-wins');
  await p.click('#btnClear'); s = await state(p); assert.ok(s.marks.every(v => v === -1) && !s.solved); ok('clear resets');

  console.log('UI: drag, cross, wrong-cell handling, hint');
  await p.click('#optAuto'); // auto-cross off for precision
  s = await state(p); const zeroCell = (() => { for (let y = 0; y < s.h; y++) for (let x = 0; x < s.w; x++) if (!s.sol[y][x]) return [x, y]; })();
  await click(p, zeroCell[0], zeroCell[1]); await p.click('#btnCheck'); assert.match(await p.textContent('#hintBox'), /1 cell is wrong/); ok('check flags a wrong cell');
  await p.click('#btnHint'); assert.match(await p.textContent('#hintBox'), /wrong/); ok('hint refuses to build on wrong marks');
  await click(p, zeroCell[0], zeroCell[1]); assert.strictEqual((await state(p)).marks[zeroCell[1] * s.w + zeroCell[0]], -1); ok('clicking a filled cell erases it');
  await click(p, zeroCell[0], zeroCell[1], { right: true }); assert.strictEqual((await state(p)).marks[zeroCell[1] * s.w + zeroCell[0]], 0); ok('right-click crosses');
  await p.click('#btnClear');
  await p.click('#btnHint'); const hb = await p.textContent('#hintBox'); assert.match(hb, /(Row|Column) \d+/); ok('hint explains a real line: ' + hb.slice(0, 50) + '…');
  const [x0, y0] = await cellXY(p, 0, 2), [x1] = await cellXY(p, 3, 2);
  await p.mouse.move(x0, y0); await p.mouse.down(); await p.mouse.move(x1, y0 + 3, { steps: 6 }); await p.mouse.up();
  s = await state(p); const row = s.marks.slice(2 * s.w, 2 * s.w + 5); assert.deepStrictEqual(row.slice(0, 4), [1, 1, 1, 1]); assert.strictEqual(row[4], -1); ok('dragging paints a straight run');
  await p.click('#btnUndo'); assert.ok((await state(p)).marks.slice(2 * s.w, 3 * s.w).every(v => v === -1)); ok('a drag is one undo step');

  console.log('UI: solver visualiser, reveal, generation controls');
  await p.click('#btnViz'); await p.fill('#vizSpeed', '10'); await p.click('#vizStep'); assert.match(await p.textContent('#vizInfo'), /Step 1 \//); ok('visualiser steps'); await p.click('#vizPlay');
  await p.waitForFunction(() => /Done/.test(document.getElementById('vizInfo').textContent), null, { timeout: 30000 }); ok('visualiser runs to completion');
  const same = await p.evaluate(() => { const v = window.__inkgrid.S.viz, S = window.__inkgrid.S; return v.board.cells.every((c, i) => c === S.solution[(i / S.w) | 0][i % S.w]); }); assert.ok(same); ok('visualiser final board equals the solution');
  await p.click('#vizExit'); await p.click('#btnReveal'); assert.ok((await state(p)).solved); ok('reveal solution');
  await p.fill('#optW', '8'); await p.fill('#optH', '6'); await p.fill('#optSeed', 'abc'); await p.selectOption('#optDiff', 'easy'); await p.click('#btnNew');
  await p.waitForFunction(() => window.__inkgrid.S.w === 8 && window.__inkgrid.S.h === 6); ok('generate respects size');
  const rows1 = await p.evaluate(() => JSON.stringify(window.__inkgrid.S.p)); await p.click('#btnNew'); await p.waitForTimeout(300);
  assert.strictEqual(rows1, await p.evaluate(() => JSON.stringify(window.__inkgrid.S.p))); ok('same seed -> same puzzle');
  await p.fill('#optW', '1'); await p.click('#btnNew'); await p.waitForFunction(() => /size/.test(document.getElementById('genNote').textContent)); ok('invalid size shows an error, board unchanged');

  console.log('UI: import / share');
  await p.click('#btnPaste'); await p.fill('#pasteText', 'garbage'); await p.click('#pasteGo'); assert.match(await p.textContent('#ioNote'), /rows/); ok('bad paste -> clear error');
  await p.fill('#pasteText', '{"rows":[[1],[1]],"cols":[[1],[1]]}'); await p.click('#pasteGo');
  await p.waitForFunction(() => window.__inkgrid.S.w === 2); assert.match(await p.textContent('#ratingPill'), /multiple|uniqueness/); ok('ambiguous puzzle loads and is labelled');
  await p.click('#btnPaste'); await p.fill('#pasteText', '{"rows":[[2],[2]],"cols":[[2],[1],[1]]}'); await p.click('#pasteGo'); assert.match(await p.textContent('#ioNote'), /no solution/); ok('unsolvable puzzle is refused with a reason');
  const hash = await p.evaluate(() => { const E = window.Inkgrid; return E.encodeShare(E.cluesFromGrid([[1, 0, 1], [1, 1, 0], [0, 1, 0]])); });
  const q = await mk({ width: 1000, height: 800 }, '#p=' + hash); assert.strictEqual(await q.evaluate(() => window.__inkgrid.S.w), 3); ok('share link opens the encoded puzzle');
  const bad = await mk({ width: 1000, height: 800 }, '#p=@@@'); assert.match(await bad.textContent('#ioNote'), /corrupt/); ok('corrupt share link falls back with a message');

  console.log('UI: narrow screen pointer mapping');
  const m = await mk({ width: 360, height: 740 }, ''); await m.fill('#optW', '30'); await m.fill('#optH', '30'); await m.click('#btnNew'); await m.waitForFunction(() => window.__inkgrid.S.w === 30);
  await m.click('#optAuto'); await click(m, 29, 29); await click(m, 0, 0); await click(m, 15, 7);
  const mm = await state(m); assert.deepStrictEqual([mm.marks[29 * 30 + 29], mm.marks[0], mm.marks[7 * 30 + 15]], [1, 1, 1]); assert.strictEqual(mm.marks.filter(v => v === 1).length, 3); ok('clicks land on the intended cells at 360px width');
  const overflow = await m.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1); assert.ok(!overflow); ok('no horizontal page overflow at 360px');

  console.log('UI: image import + .non export');
  const png = await p.evaluate(() => { const c = document.createElement('canvas'); c.width = c.height = 100; const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, 100, 100); x.fillStyle = '#000'; x.beginPath(); x.arc(50, 50, 38, 0, 7); x.fill(); x.fillRect(10, 10, 20, 20); return c.toDataURL('image/png').split(',')[1]; });
  const fs = require('fs'), os = require('os'), f = path.join(os.tmpdir(), 'inkgrid-test-' + process.pid + '.png'); fs.writeFileSync(f, Buffer.from(png, 'base64'));
  await p.fill('#optW', '12'); await p.fill('#optH', '12'); await p.setInputFiles('#fileImg', f);
  await p.waitForFunction(() => /Built a 12/.test(document.getElementById('ioNote').textContent)); 
  const u = await p.evaluate(() => { const S = window.__inkgrid.S, E = window.Inkgrid; return { w: S.w, uniq: S.unique, n: E.solve(S.p).count, mid: S.solution[6][6] }; });
  assert.deepStrictEqual(u, { w: 12, uniq: true, n: 1, mid: 1 }); ok('image becomes a unique 12x12 puzzle with the disc in the middle');
  const blank = path.join(os.tmpdir(), 'inkgrid-blank-' + process.pid + '.png');
  fs.writeFileSync(blank, Buffer.from(await p.evaluate(() => { const c = document.createElement('canvas'); c.width = c.height = 20; const x = c.getContext('2d'); x.fillStyle = '#fff'; x.fillRect(0, 0, 20, 20); return c.toDataURL().split(',')[1]; }), 'base64'));
  await p.setInputFiles('#fileImg', blank); await p.waitForFunction(() => /single tone/.test(document.getElementById('ioNote').textContent)); ok('blank image is rejected politely');
  fs.writeFileSync(blank, 'not an image'); await p.setInputFiles('#fileImg', { name: 'x.txt', mimeType: 'text/plain', buffer: Buffer.from('hi') }); await p.waitForFunction(() => /not an image/.test(document.getElementById('ioNote').textContent)); ok('non-image file is rejected');
  const [dl] = await Promise.all([p.waitForEvent('download'), p.click('#btnExport')]); const txt = fs.readFileSync(await dl.path(), 'utf8');
  assert.match(txt, /width 12/); assert.deepStrictEqual(await p.evaluate(t => { const q = window.Inkgrid.parsePuzzle(t), S = window.__inkgrid.S; return JSON.stringify(q.rows) === JSON.stringify(S.p.rows); }, txt), true); ok('exported .non re-imports identically'); fs.unlinkSync(f); fs.unlinkSync(blank);
  assert.deepStrictEqual(errs, []); ok('no page errors in console');
  await b.close(); console.log('\n' + n + ' UI checks passed — ALL GREEN');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
