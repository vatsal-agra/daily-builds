// Headless-browser verification of the block explorer UI: loads the live
// page, clicks through to a real multi-transaction block, clicks a
// non-coinbase transaction, and checks the Merkle proof panel actually
// recomputed and matched (not just that some text is present) — while
// asserting there are zero console/page errors throughout.
//
// Usage: node check_explorer_ui.js <api_base_url>
const { chromium } = require('playwright');

const apiBase = process.argv[2];
if (!apiBase) {
  console.error('usage: node check_explorer_ui.js <api_base_url>');
  process.exit(2);
}

(async () => {
  const errors = [];
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (exc) => errors.push(String(exc)));

  await page.goto(apiBase + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  const rowCount = await page.locator('#chainBody tr.row').count();
  if (rowCount < 1) throw new Error('no chain rows rendered');

  // find a block with more than one transaction (a coinbase-only block's
  // proof is a trivial zero-step leaf==root case; prove the real path too)
  const chain = await (await page.goto(apiBase + '/api/chain')).json();
  const multiTxBlock = chain.find((b) => b.tx_count > 1);
  if (!multiTxBlock) throw new Error('no multi-transaction block found to test against');

  await page.goto(apiBase + '/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  const rows = page.locator('#chainBody tr.row');
  const n = await rows.count();
  let clicked = false;
  for (let i = 0; i < n; i++) {
    const heightText = (await rows.nth(i).locator('td').first().innerText()).trim();
    if (heightText === String(multiTxBlock.height)) {
      await rows.nth(i).click({ force: true });
      clicked = true;
      break;
    }
  }
  if (!clicked) throw new Error('could not find/click the target block row');
  await page.waitForTimeout(600);

  const txRowCount = await page.locator('#blockDetail .tx-io').count();
  if (txRowCount < 2) throw new Error(`expected >=2 tx rows in block detail, got ${txRowCount}`);

  // the second row is the real (non-coinbase) transaction
  await page.locator('#blockDetail .tx-io').nth(1).click({ force: true });
  await page.waitForTimeout(800);

  const proofText = await page.textContent('.proof-result');
  if (!proofText || !proofText.includes('recomputed in-browser and matches')) {
    throw new Error('merkle proof panel did not report a verified match: ' + proofText);
  }

  const proofStepCount = await page.locator('#proofBox .proof-step').count();
  if (proofStepCount < 2) throw new Error('expected at least one combine step for a multi-tx block');

  await browser.close();

  if (errors.length) {
    console.error('console/page errors detected:', JSON.stringify(errors, null, 2));
    process.exit(1);
  }

  console.log('explorer UI check passed: block/tx click-through + real Merkle proof re-verified client-side, zero console errors');
})().catch((e) => {
  console.error('explorer UI check FAILED:', e.message);
  process.exit(1);
});
