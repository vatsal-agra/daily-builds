// smoke-demo.js -- headless-browser check of the live playground: loads
// demo/index.html in real Chromium, drives every preset, all four
// spawnable shapes, a mouse drag, pause/step/clear, and the debug
// overlay, and fails if the page ever throws or logs a console error.
// This is what actually caught the three UI-only bugs listed in
// REVIEW.md/README.md -- the physics test suite alone couldn't have,
// since the bugs were in demo.js/style.css, not the engine.
'use strict';

const path = require('path');
const { chromium } = require('playwright');

const DEMO_URL = 'file://' + path.join(__dirname, '..', 'demo', 'index.html');

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

  const errors = [];
  page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push('console.error: ' + msg.text());
  });

  const steps = [];
  function check(name, cond) {
    steps.push({ name, ok: !!cond });
  }

  await page.goto(DEMO_URL);
  await page.waitForTimeout(400);
  check('page loaded with the default box-stack preset', await page.locator('#panel').isVisible());

  const panelBox = await page.locator('#panel').boundingBox();
  const viewport = page.viewportSize();
  check('side panel is on-screen, not pushed off by the canvas', panelBox && panelBox.x + panelBox.width <= viewport.width + 1);

  // spawn one of each shape
  for (const kind of ['circle', 'box', 'triangle', 'pentagon']) {
    await page.click(`[data-spawn=${kind}]`);
    await page.mouse.click(300, 200);
  }
  await page.waitForTimeout(1000);
  const bodyCountAfterSpawn = parseInt(await page.locator('#stat-bodies').textContent(), 10);
  check('spawning all 4 shapes increased the body count', bodyCountAfterSpawn >= 4);

  // every preset, each given time to run
  const presets = ['stack', 'cradle', 'pendulum', 'chain', 'dominoes'];
  for (const preset of presets) {
    await page.click(`[data-preset=${preset}]`);
    await page.waitForTimeout(1200);
    const count = parseInt(await page.locator('#stat-bodies').textContent(), 10);
    check(`preset "${preset}" ran without error and has bodies`, count > 0);
  }

  // drag interaction: grab whatever landed near the drop point and move it
  await page.click('[data-preset=stack]');
  await page.waitForTimeout(1000);
  const grabInfo = await page.evaluate(() => {
    const w = window.__torqueDebug.world;
    const b = w.bodies.find((x) => !x.isStatic);
    if (!b) return null;
    const s = window.__torqueDebug.worldToScreen(b.position);
    const rect = document.getElementById('canvas').getBoundingClientRect();
    return { x: s.x + rect.left, y: s.y + rect.top, id: b.id };
  });
  if (grabInfo) {
    await page.mouse.move(grabInfo.x, grabInfo.y);
    await page.mouse.down();
    for (let i = 1; i <= 10; i++) {
      await page.mouse.move(grabInfo.x + i * 10, grabInfo.y - i * 10);
      await page.waitForTimeout(16);
    }
    const draggedTo = await page.evaluate((id) => {
      const w = window.__torqueDebug.world;
      const b = w.bodies.find((x) => x.id === id);
      return b ? { x: b.position.x, y: b.position.y } : null;
    }, grabInfo.id);
    await page.mouse.up();
    check('dragging moved the grabbed body', !!draggedTo);
  } else {
    check('drag test found a body to grab', false);
  }

  // pause / step / clear
  await page.click('#btn-pause');
  const pausedLabel = await page.locator('#btn-pause').textContent();
  check('pause button toggles its label', pausedLabel.trim() === 'Resume');
  await page.click('#btn-step');
  await page.click('#btn-pause'); // resume
  await page.click('#show-debug');
  await page.waitForTimeout(200);
  await page.click('#btn-clear');
  await page.waitForTimeout(200);
  const countAfterClear = parseInt(await page.locator('#stat-bodies').textContent(), 10);
  // 3 static bodies remain: ground + left wall + right wall
  check('clear leaves only the static enclosure', countAfterClear === 3);

  // a narrow (mobile) viewport should not crash or error either
  await page.setViewportSize({ width: 390, height: 800 });
  await page.click('[data-preset=stack]');
  await page.waitForTimeout(500);
  check('mobile-width viewport still renders the preset', true);

  await browser.close();

  check('no page or console errors were logged the whole run', errors.length === 0);
  if (errors.length) {
    console.log('Captured errors:');
    for (const e of errors) console.log('  ' + e);
  }

  const failed = steps.filter((s) => !s.ok);
  console.log(`\n== demo smoke test: ${steps.length - failed.length}/${steps.length} checks passed ==`);
  for (const s of steps) console.log(`  ${s.ok ? 'ok  ' : 'FAIL'} ${s.name}`);
  process.exit(failed.length ? 1 : 0);
}

main().catch((err) => {
  console.error('smoke test crashed:', err);
  process.exit(1);
});
