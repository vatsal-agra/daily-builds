// Headless-Chromium smoke test for the Sente server UI: loads the page,
// plays a few real moves against the real server-backed agent, checks
// the visualization panel actually populates, and asserts ZERO console
// errors -- the repo's established bar for any UI claim.
const { chromium } = require('playwright');

const BASE = process.argv[2] || 'http://127.0.0.1:8765';

(async () => {
  const errors = [];
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));

  console.log('Loading', BASE);
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForSelector('.cell');

  const cellCount = await page.locator('.cell').count();
  if (cellCount !== 9) throw new Error(`expected 9 cells for tictactoe default, got ${cellCount}`);
  console.log('OK: board rendered with', cellCount, 'cells');

  const statusText0 = await page.locator('#status').innerText();
  console.log('Initial status:', statusText0);

  // Play a few legal moves by clicking legal cells until game over or 5 moves played.
  for (let i = 0; i < 5; i++) {
    const legalCell = page.locator('.cell.legal').first();
    const count = await legalCell.count();
    if (count === 0) { console.log('No legal cells left (game likely over) after', i, 'human moves'); break; }
    await legalCell.click();
    await page.waitForTimeout(300);
    const bars = await page.locator('.bar-row').count();
    if (bars === 0) throw new Error('visualization panel did not populate any bars after a move');
  }

  const barsFinal = await page.locator('.bar-row').count();
  console.log('OK: visualization panel has', barsFinal, 'move bars after play');

  const gaugeStyle = await page.locator('#gaugeMarker').getAttribute('style');
  console.log('OK: value gauge marker style =', gaugeStyle);

  // Test the hint button too.
  const hintBtn = page.locator('#hintBtn');
  if (!(await hintBtn.isDisabled())) {
    await hintBtn.click();
    await page.waitForTimeout(300);
  }

  // Switch game to Connect Four Jr and start a new game.
  await page.selectOption('#gameSelect', 'connect4jr');
  await page.selectOption('#sideSelect', 'X');
  await page.locator('#newGameBtn').click();
  await page.waitForTimeout(500);
  const c4cells = await page.locator('.cell').count();
  if (c4cells !== 20) throw new Error(`expected 20 cells for connect4jr (5x4), got ${c4cells}`);
  console.log('OK: switched to Connect Four Jr, board rendered with', c4cells, 'cells');

  const legalC4 = page.locator('.cell.legal').first();
  if (await legalC4.count() > 0) {
    await legalC4.click();
    await page.waitForTimeout(400);
  }
  const barsC4 = await page.locator('.bar-row').count();
  console.log('OK: Connect Four Jr visualization has', barsC4, 'move bars');

  // Responsive check: no horizontal scroll at phone width.
  await page.setViewportSize({ width: 375, height: 720 });
  await page.waitForTimeout(200);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log('Phone-width (375px) horizontal overflow:', overflow, 'px');
  if (overflow > 1) throw new Error(`horizontal scroll at phone width: ${overflow}px overflow`);
  console.log('OK: no horizontal scroll at phone width');

  await browser.close();

  if (errors.length > 0) {
    console.error('CONSOLE ERRORS DETECTED:');
    for (const e of errors) console.error(' -', e);
    process.exit(1);
  }
  console.log('\nALL CHECKS PASSED, ZERO CONSOLE ERRORS.');
})().catch((e) => {
  console.error('SMOKE TEST FAILED:', e);
  process.exit(1);
});
