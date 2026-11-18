// Headless-browser check of the player. usage: node browser_check.js <player.html> <serve-url|->
const { chromium } = require('playwright');
const SOLVED = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB';
let failed = 0;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) failed++; };
(async () => {
  const [file, serve] = process.argv.slice(2);
  const b = await chromium.launch();
  for (const vp of [{ width: 390, height: 800 }, { width: 1100, height: 760 }]) {
    const p = await b.newPage({ viewport: vp });
    const errs = []; p.on('pageerror', e => errs.push(e.message));
    await p.goto('file://' + file);
    ok(!(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth)), `${vp.width}px: no horizontal overflow`);
    ok((await p.textContent('#verdict')).startsWith('✔'), `${vp.width}px: in-browser physical verification passes`);
    const n = +(await p.textContent('#sLen'));
    await p.click('#bNext'); await p.waitForTimeout(700); await p.click('#bNext'); await p.waitForTimeout(700);
    ok(await p.inputValue('#scrub') === '2', `${vp.width}px: two forward steps`);
    await p.click('#bPrev'); await p.waitForTimeout(700);
    ok(await p.inputValue('#scrub') === '1', `${vp.width}px: step back`);
    await p.fill('#scrub', String(n)); await p.dispatchEvent('#scrub', 'input');
    ok(await p.evaluate(() => readFacelets(stickers)) === SOLVED, `${vp.width}px: scrub to end = solved cube`);
    await p.keyboard.press('Home');
    ok(await p.evaluate(() => readFacelets(stickers)) !== SOLVED, `${vp.width}px: Home = scrambled again`);
    await p.click('#bPlay'); await p.waitForTimeout(4000 + n * 400);
    ok(await p.evaluate(() => readFacelets(stickers)) === SOLVED, `${vp.width}px: autoplay finishes solved`);
    // canvas actually painted
    const painted = await p.evaluate(() => { const c = document.getElementById('cv'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let k = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) k++; return k; });
    ok(painted > 50000, `${vp.width}px: canvas painted (${painted} px)`);
    ok(errs.length === 0, `${vp.width}px: no JS errors ${errs.join(';')}`);
    await p.close();
  }
  if (serve && serve !== '-') {
    const p = await b.newPage({ viewport: { width: 1100, height: 900 } });
    await p.goto(serve);
    await p.fill('#inScr', "R U R' U' F2 D L' B2 U2 R"); await p.click('#bSolveScr'); await p.waitForSelector('.chip');
    ok((await p.textContent('#verdict')).startsWith('✔'), 'serve: scramble solved + verified');
    await p.fill('#inScr', 'R U x'); await p.click('#bSolveScr'); await p.waitForTimeout(500);
    ok((await p.textContent('#err')).includes('unsupported move'), 'serve: bad notation shows error');
    await p.fill('#inFace', 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBR'); await p.click('#bSolveFace'); await p.waitForTimeout(500);
    ok((await p.textContent('#err')).includes('9 times'), 'serve: bad facelets shows error');
    await p.click('#bRand'); await p.waitForFunction(() => document.getElementById('scr').textContent.startsWith('(random'), null, { timeout: 15000 });
    ok((await p.textContent('#verdict')).startsWith('✔'), 'serve: random state solved + verified');
    await p.close();
  }
  await b.close();
  console.log(failed ? `${failed} browser check(s) FAILED` : 'browser checks: all passed');
  process.exit(failed ? 1 : 0);
})();
