// Headless-Chromium end-to-end test of the exported game. usage: node browser.test.js game.html
const { chromium } = require('playwright');
const path = require('path');
let fails = 0;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) fails++; };
(async () => {
  const file = path.resolve(process.argv[2]);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 800 } });
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto('file://' + file);
  const n = await p.evaluate(() => __shove.levels.length);
  ok(n >= 10, `loaded ${n} levels`);

  // 1. every embedded solution, replayed by the page's own rules engine, solves its level
  const replay = await p.evaluate(() => {
    const s = __shove, bad = [];
    for (let i = 0; i < s.levels.length; i++) {
      s.load(i);
      for (const c of s.levels[i].solution.toLowerCase()) if (!s.move(c)) { bad.push(i + ':illegal'); break; }
      if (!s.solved()) bad.push(i + ':unsolved');
      if (s.deadlocked() && !s.solved()) bad.push(i + ':deadlock-flag');
    }
    return bad;
  });
  ok(replay.length === 0, 'all embedded solutions replay legally and solve (JS rules engine) ' + replay);

  // 2. in-browser A* agrees with the Go solver's optimum on every level it can finish
  const par = await p.evaluate(() => {
    const s = __shove, out = [];
    for (let i = 0; i < s.levels.length; i++) {
      s.load(i);
      const t = s.state(), r = s.aStar(Object.keys(t.boxes).map(Number), t.p, 1e9, performance.now() + 6000);
      out.push([i, s.levels[i].pushes, r ? r.path.length : null]);
    }
    return out;
  });
  const finished = par.filter(r => r[2] !== null), wrong = finished.filter(r => r[1] !== r[2]);
  ok(finished.length === par.length && wrong.length === 0, `JS A* == Go optimum on ${finished.length}/${par.length} levels`);

  // 3. real key events drive the game; counters, undo, restart
  await p.evaluate(() => __shove.load(1));      // Corner Office: 2 pushes
  await p.keyboard.press('ArrowUp');
  let t = await p.evaluate(() => __shove.state());
  ok(t.moves === 1, 'ArrowUp moves the player');
  await p.keyboard.press('z');
  t = await p.evaluate(() => __shove.state());
  ok(t.moves === 0 && t.pushes === 0, 'Z undoes');
  await p.keyboard.press('ArrowUp'); await p.keyboard.press('ArrowUp');   // pushes a box into the top wall row
  const warn = await p.textContent('#warn');
  ok(/Deadlock/.test(warn), 'deadlock warning appears for a box pushed onto a dead square');
  await p.keyboard.press('r');
  t = await p.evaluate(() => __shove.state());
  ok(t.moves === 0 && (await p.textContent('#warn')) === '', 'R restarts and clears the warning');

  // 4. modifier keys are not hijacked
  await p.keyboard.press('ArrowRight');
  await p.keyboard.press('Control+r');
  t = await p.evaluate(() => __shove.state());
  ok(t.moves === 1, 'Ctrl+R does not restart the level');
  await p.keyboard.press('r');

  // 5. solving by hand records a best and says "Perfect"
  await p.evaluate(() => { const s = __shove; for (const c of s.levels[1].solution.toLowerCase()) s.move(c); });
  ok(/Perfect/.test(await p.textContent('#msg')), 'optimal solve shows "Perfect"');
  ok((await p.textContent('#sBest')) !== '–', 'best score recorded');

  // 6. watching the solution is not solving (fresh page + storage: earlier steps legitimately recorded bests)
  await p.evaluate(() => localStorage.clear()); await p.reload();
  await p.evaluate(() => __shove.load(2));
  await p.evaluate(() => { document.getElementById('spd').value = 30; });
  await p.click('#bSolve');
  await p.waitForFunction(() => /Solution shown/.test(document.getElementById('msg').textContent), null, { timeout: 8000 });
  const sb = await p.textContent('#sBest'); ok(sb === '–', 'solution playback does not record a best (sBest=' + sb + ', best=' + (await p.evaluate(() => localStorage.getItem('shove-best-Shove'))) + ')');

  // 7. Hint plays the next push of a real plan from a mid-level position
  await p.evaluate(() => { __shove.load(5); __shove.move('l'); });
  await p.evaluate(() => { document.getElementById('spd').value = 30; });
  const before = await p.evaluate(() => __shove.state().pushes + ':' + __shove.state().moves);
  await p.click('#bHint');
  await p.waitForFunction(() => /push\(es\) left/.test(document.getElementById('msg').textContent), null, { timeout: 12000 });
  const after = await p.evaluate(() => __shove.state().pushes);
  ok(after >= 1 && !/Deadlock/.test(await p.textContent('#warn')), `Hint performed a push (before ${before}, pushes now ${after}) without deadlocking`);

  // 8. mobile layout: no horizontal overflow
  await p.setViewportSize({ width: 390, height: 844 });
  await p.evaluate(() => __shove.load(9));
  ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= 390, 'no horizontal scroll at 390px');

  ok(errs.length === 0, 'no console/page errors ' + errs.join('|'));
  await b.close();
  console.log(fails ? `\n${fails} FAILED` : '\nbrowser: ALL PASS');
  process.exit(fails ? 1 : 0);
})();
