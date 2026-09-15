// Headless-Chromium smoke test for the generated visualizer: loads the
// real HTML file `causeway viz` produces from a real captured event log,
// fails on any console/page error, and exercises the hover tooltip layer.
// Run via demo.sh (needs the globally-installed `playwright` npm package
// and the pre-installed Chromium binary -- not part of the Python test
// suite since this repo has no Node project of its own).
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const htmlPath = process.argv[2];
  if (!htmlPath) {
    console.error('usage: node browser_smoke_test.js <path-to-viz.html>');
    process.exit(2);
  }

  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', err => pageErrors.push(String(err)));

  await page.goto('file://' + path.resolve(htmlPath));
  await page.waitForTimeout(500);

  const box = await page.locator('#chart-cwnd').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(200);
  const tooltipVisible = await page.locator('#tip-cwnd').isVisible();
  const statCount = await page.locator('.stat').count();
  const subtitleText = await page.locator('#subtitle').innerText();

  await browser.close();

  let ok = true;
  if (consoleErrors.length) { console.log('CONSOLE ERRORS:', consoleErrors); ok = false; }
  if (pageErrors.length) { console.log('PAGE ERRORS:', pageErrors); ok = false; }
  if (!tooltipVisible) { console.log('FAIL: hover tooltip never appeared'); ok = false; }
  if (statCount < 5) { console.log(`FAIL: expected >=5 stat tiles, found ${statCount}`); ok = false; }
  if (!subtitleText || subtitleText.includes('loading')) { console.log('FAIL: subtitle never rendered'); ok = false; }

  if (ok) {
    console.log(`OK: visualizer loaded with zero console errors, ${statCount} stat tiles, hover tooltip works`);
    process.exit(0);
  }
  process.exit(1);
})();
