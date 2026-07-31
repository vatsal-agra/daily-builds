// Drives the real Trellis server in a real headless Chromium browser and
// asserts every UI-level bug found in REVIEW.md stays fixed, plus the core
// interactive-grid feature itself. Exits non-zero on any failure so
// demo.sh can gate on it like any other test.
//
// Usage: node ui_browser_test.js <base-url>

const { chromium } = require('playwright');

const BASE_URL = process.argv[2] || 'http://127.0.0.1:8765';
let failures = 0;

function check(label, condition) {
  if (condition) {
    console.log(`  [OK] ${label}`);
  } else {
    console.log(`  [FAIL] ${label}`);
    failures++;
  }
}

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  await page.goto(BASE_URL);
  await page.waitForSelector('#grid td.cell');

  // -- REVIEW.md #1/#2: first keystroke + duplicate commit ----------------
  await page.click('td.cell[data-r="1"][data-c="1"]');
  await page.keyboard.type('5');
  await page.keyboard.press('Enter');
  await page.click('td.cell[data-r="1"][data-c="2"]');
  await page.keyboard.type('=A1*10');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(150);
  check('formula entry (no duplicated first char): B1 = 50',
    (await page.textContent('td.cell[data-r="1"][data-c="2"]')) === '50');

  // -- REVIEW.md #3: same-cell click mid-edit must not discard text -------
  await page.dblclick('td.cell[data-r="2"][data-c="1"]');
  await page.keyboard.type('hello');
  await page.click('td.cell[data-r="2"][data-c="1"]'); // click inside same cell
  const input = await page.$('td.cell[data-r="2"][data-c="1"] input');
  const stillHasValue = input && (await input.inputValue()) === 'hello';
  check('clicking inside the cell being edited preserves in-progress text', stillHasValue);
  await page.keyboard.press('Enter');
  await page.waitForTimeout(150);
  check('A2 committed correctly after same-cell click: "hello"',
    (await page.textContent('td.cell[data-r="2"][data-c="1"]')) === 'hello');

  // click-away mid-edit must commit the typed value, not a stale one
  await page.dblclick('td.cell[data-r="3"][data-c="1"]');
  await page.keyboard.type('world');
  await page.click('td.cell[data-r="9"][data-c="9"]');
  await page.waitForTimeout(150);
  check('clicking away mid-edit commits the typed value: A3 = "world"',
    (await page.textContent('td.cell[data-r="3"][data-c="1"]')) === 'world');

  // -- error handling in the UI --------------------------------------------
  await page.click('td.cell[data-r="4"][data-c="1"]');
  await page.keyboard.type('=1/0');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(150);
  const errCell = await page.textContent('td.cell[data-r="4"][data-c="1"]');
  const errClass = await page.getAttribute('td.cell[data-r="4"][data-c="1"]', 'class');
  check('#DIV/0! displayed and visually flagged as an error',
    errCell === '#DIV/0!' && errClass.includes('error'));

  // -- keyboard navigation --------------------------------------------------
  await page.click('td.cell[data-r="1"][data-c="1"]');
  await page.keyboard.press('ArrowRight');
  check('ArrowRight moves selection to B1', (await page.textContent('#cellref')) === 'B1');
  await page.keyboard.press('ArrowDown');
  check('ArrowDown moves selection to B2', (await page.textContent('#cellref')) === 'B2');

  // -- undo/redo --------------------------------------------------------------
  // Undo everything (rather than a hardcoded click count, which would
  // silently drift out of sync with however many edits happened above) by
  // clicking Undo until the button itself reports nothing left to undo.
  let undoClicks = 0;
  while (!(await page.isDisabled('#undoBtn')) && undoClicks < 50) {
    await page.click('#undoBtn');
    await page.waitForTimeout(100);
    undoClicks++;
  }
  check('undo-to-start actually ran (did something)', undoClicks > 0);
  check('undo-to-start clears A1 back to blank', (await page.textContent('td.cell[data-r="1"][data-c="1"]')) === '');
  check('undo-to-start clears B1 back to blank', (await page.textContent('td.cell[data-r="1"][data-c="2"]')) === '');

  for (let i = 0; i < undoClicks; i++) {
    await page.click('#redoBtn');
    await page.waitForTimeout(100);
  }
  check('redo-to-end restores A1 = 5', (await page.textContent('td.cell[data-r="1"][data-c="1"]')) === '5');
  check('redo-to-end restores B1 = 50', (await page.textContent('td.cell[data-r="1"][data-c="2"]')) === '50');

  // -- charts (light + dark) -------------------------------------------------
  await page.click('td.cell[data-r="10"][data-c="1"]'); await page.keyboard.type('x'); await page.keyboard.press('Enter');
  await page.click('td.cell[data-r="10"][data-c="2"]'); await page.keyboard.type('7'); await page.keyboard.press('Enter');
  await page.click('td.cell[data-r="11"][data-c="1"]'); await page.keyboard.type('y'); await page.keyboard.press('Enter');
  await page.click('td.cell[data-r="11"][data-c="2"]'); await page.keyboard.type('3'); await page.keyboard.press('Enter');
  await page.click('#chartBtn');
  await page.fill('#chartrange', 'A10:B11');
  await page.click('#chartRefresh');
  await page.waitForTimeout(300);
  const chartSrc = await page.getAttribute('#chartimg', 'src');
  check('chart image src set after Draw', !!chartSrc && chartSrc.includes('/api/chart'));

  // -- multi-sheet: add / rename / delete via the real tab UI ---------------
  page.once('dialog', async (d) => { await d.accept('Data'); });
  await page.click('#addsheet');
  await page.waitForTimeout(150);
  let tabs = await page.$$eval('.tab span:first-child', (els) => els.map((e) => e.textContent));
  check('add sheet via UI creates "Data" tab', tabs.includes('Data'));

  page.once('dialog', async (d) => { await d.accept('Source'); });
  await page.dblclick('.tab:has-text("Data")');
  await page.waitForTimeout(150);
  tabs = await page.$$eval('.tab span:first-child', (els) => els.map((e) => e.textContent));
  check('double-click rename: "Data" -> "Source"', tabs.includes('Source') && !tabs.includes('Data'));

  page.once('dialog', async (d) => { await d.accept(); });
  await page.click('.tab:has-text("Source") .close');
  await page.waitForTimeout(150);
  tabs = await page.$$eval('.tab span:first-child', (els) => els.map((e) => e.textContent));
  check('delete sheet via UI removes "Source" tab', !tabs.includes('Source'));

  // -- CSV export link (existence check only, not download content) ---------
  check('Export CSV button present', !!(await page.$('#csvExportBtn')));

  // -- theming: dark mode doesn't produce console errors and re-renders -----
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.waitForTimeout(150);
  await page.screenshot({ path: '/tmp/trellis_demo_dark.png' });
  await page.emulateMedia({ colorScheme: 'light' });
  await page.waitForTimeout(150);
  await page.screenshot({ path: '/tmp/trellis_demo_light.png' });

  check('zero browser console errors across the whole run', consoleErrors.length === 0);
  if (consoleErrors.length) console.log('  console errors:', JSON.stringify(consoleErrors));

  await browser.close();

  if (failures > 0) {
    console.log(`\n${failures} UI check(s) FAILED`);
    process.exit(1);
  }
  console.log('\nAll UI checks passed.');
}

main().catch((err) => {
  console.error('UI test crashed:', err);
  process.exit(1);
});
