// Headless check of a generated report: no page errors, canvases actually painted,
// controls work. Usage: node browser_check.js report.html
const { chromium } = require('playwright');
(async () => {
  const file = process.argv[2];
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
  const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.goto('file://' + file);
  await p.waitForTimeout(500);
  const painted = async id => p.evaluate(id => {
    const c = document.getElementById(id), x = c.getContext('2d');
    const d = x.getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
    return n;
  }, id);
  const fail = m => { console.log('FAIL: ' + m); process.exitCode = 1; };
  if ((await painted('orbit')) < 200) fail('orbit canvas is blank');
  if ((await painted('chart')) < 500) fail('chart canvas is blank');
  const rows = await p.$$eval('#tbl tr', r => r.length);
  if (rows < 4) fail('comparison table too short: ' + rows);
  const t0 = await p.textContent('#tlabel');
  await p.waitForTimeout(400);
  const t1 = await p.textContent('#tlabel');
  if (t0 === t1) fail('animation is not advancing');
  await p.click('#play');
  const a = await p.textContent('#tlabel'); await p.waitForTimeout(300);
  if (a !== await p.textContent('#tlabel')) fail('pause did not stop the animation');
  await p.fill('#scrub', '5');
  if (!(await p.textContent('#tlabel')).includes('t =')) fail('scrub label missing');
  await p.click('#scale'); await p.click('#trails');
  await p.hover('#chart', { position: { x: 200, y: 80 } });
  if (!(await p.textContent('#hover')).includes('t =')) fail('chart hover readout missing');
  await p.setViewportSize({ width: 390, height: 800 });
  await p.waitForTimeout(300);
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  if (overflow) fail('horizontal overflow at phone width');
  if (errs.length) fail('page errors: ' + errs.join(' | '));
  await b.close();
  if (!process.exitCode) console.log('browser check ok');
})();
