// Headless-Chromium smoke test for the standalone HTML replay viewer:
// loads it, drives every control (step, play/pause, scrub, click a log
// entry), and fails if the page throws or logs a console error.
//
// Usage: node scripts/viz_smoke.js <path-to-replay.html>
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const htmlPath = process.argv[2];
  if (!htmlPath) {
    console.error('usage: node viz_smoke.js <path-to-replay.html>');
    process.exit(2);
  }

  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));

  await page.goto('file://' + path.resolve(htmlPath));
  await page.waitForTimeout(400);

  const meta = await page.textContent('#metaLine');
  if (!meta || meta.includes('loading')) {
    console.error('FAIL: meta line never populated:', meta);
    process.exit(1);
  }
  console.log('meta:', meta);

  for (let i = 0; i < 15; i++) await page.click('#stepFwd');
  await page.click('#playPause');
  await page.waitForTimeout(600);
  await page.click('#playPause');

  await page.$eval('#scrubber', (el) => { el.value = Math.floor(el.max / 2); el.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(150);
  await page.$eval('#scrubber', (el) => { el.value = el.max; el.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(150);
  await page.$eval('#scrubber', (el) => { el.value = 0; el.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(150);

  const firstEntry = await page.$('.entry');
  if (firstEntry) await firstEntry.click();

  const posLabel = await page.textContent('#posLabel');
  console.log('posLabel after interaction:', posLabel);

  await browser.close();

  if (errors.length) {
    console.error('FAIL: console errors:', errors);
    process.exit(1);
  }
  console.log('OK: viz_smoke passed, zero console errors');
}

main().catch((err) => { console.error(err); process.exit(1); });
