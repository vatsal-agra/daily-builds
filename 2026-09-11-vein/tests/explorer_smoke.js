// Headless-browser smoke test for the block-explorer HTML: loads the
// exported page, waits for it to pull real data from a live node over
// its actual RPC/SSE endpoints, clicks into a real block, looks up a
// real balance, and asserts zero console/page errors throughout.
//
// Usage: node explorer_smoke.js <path-to-exported-explorer.html> <address-to-look-up>
// Exits 0 on success, 1 on any failure (missing data, console error, etc).

const { chromium } = require('playwright');
const path = require('path');

async function main() {
  const htmlPath = process.argv[2];
  const address = process.argv[3];
  if (!htmlPath) {
    console.error('usage: node explorer_smoke.js <html-path> [address]');
    process.exit(2);
  }

  const errors = [];
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (exc) => errors.push(String(exc)));

  await page.goto('file://' + path.resolve(htmlPath));
  await page.waitForTimeout(3000);

  const height = await page.$eval('#statGrid .stat .value', (el) => el.textContent).catch(() => null);
  const connected = await page.$eval('#connPill', (el) => el.textContent.trim()).catch(() => null);

  let ok = true;
  if (connected !== 'live') {
    console.error(`FAIL: expected connection status "live", got "${connected}"`);
    ok = false;
  }
  if (!height || height === '' || Number.isNaN(Number(height))) {
    console.error(`FAIL: expected a numeric height stat, got "${height}"`);
    ok = false;
  } else {
    console.log(`OK: connected, chain height = ${height}`);
  }

  const blockRowCount = await page.$$eval('.block-row', (rows) => rows.length);
  if (blockRowCount === 0) {
    console.error('FAIL: no block rows rendered');
    ok = false;
  } else {
    console.log(`OK: ${blockRowCount} block rows rendered`);
    await page.click('.block-row');
    await page.waitForTimeout(800);
    const modalTitle = await page.$eval('#modalTitle', (el) => el.textContent).catch(() => '');
    if (!modalTitle.startsWith('block ')) {
      console.error(`FAIL: block detail modal did not populate, title="${modalTitle}"`);
      ok = false;
    } else {
      console.log('OK: block detail modal populated');
    }
    await page.click('.close').catch(() => {});
    await page.waitForTimeout(300);
  }

  if (address) {
    await page.fill('#addrInput', address);
    await page.click('text=check');
    await page.waitForTimeout(800);
    const result = await page.$eval('#balanceResult', (el) => el.textContent).catch(() => '');
    if (!result.toLowerCase().includes('balance')) {
      console.error(`FAIL: balance lookup did not render a result, got "${result}"`);
      ok = false;
    } else {
      console.log(`OK: balance lookup rendered: ${result.trim()}`);
    }
  }

  await browser.close();

  if (errors.length > 0) {
    console.error(`FAIL: ${errors.length} browser console/page error(s):`);
    for (const e of errors) console.error('  ' + e);
    ok = false;
  } else {
    console.log('OK: zero console/page errors');
  }

  process.exit(ok ? 0 : 1);
}

main().catch((e) => { console.error('FAIL: smoke test threw:', e); process.exit(1); });
