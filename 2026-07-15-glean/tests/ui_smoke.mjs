// Headless-browser smoke test for the Glean search UI. Requires a `glean
// serve` instance already running (see demo.sh). Exits non-zero on any
// check failure.
let chromium;
try {
  ({ chromium } = await import('playwright'));
} catch {
  // Fall back to a known global install location when playwright isn't a
  // local dependency (this project has no node_modules of its own).
  ({ chromium } = await import('/opt/node22/lib/node_modules/playwright/index.mjs'));
}

const BASE = process.env.GLEAN_UI_URL || 'http://127.0.0.1:8752';
const CHROME_PATH = process.env.GLEAN_CHROME_PATH || null;

let failures = 0;
function check(name, condition) {
  if (condition) {
    console.log(`  ok  - ${name}`);
  } else {
    console.log(`FAIL  - ${name}`);
    failures++;
  }
}

const launchOpts = { args: ['--no-sandbox'] };
if (CHROME_PATH) launchOpts.executablePath = CHROME_PATH;
const browser = await chromium.launch(launchOpts);
const page = await browser.newPage();
const jsErrors = [];
page.on('pageerror', (e) => jsErrors.push(String(e)));

await page.goto(BASE + '/');
await page.waitForSelector('#stats:not(:empty)', { timeout: 5000 });
check('stats line loads', (await page.textContent('#stats')).includes('documents'));

await page.fill('#q', 'roman empire');
await page.waitForTimeout(500);
check('bare-word query returns a result card', (await page.locator('.card').count()) >= 1);
check('matched terms are highlighted', (await page.locator('.card mark').count()) >= 1);

await page.fill('#q', '"printing press"');
await page.waitForTimeout(500);
const phraseTitle = await page.locator('.card .card-title').first().textContent().catch(() => '');
check('phrase query finds the right article', phraseTitle.includes('Printing Press'));

await page.fill('#q', 'football NOT basketball');
await page.waitForTimeout(500);
const notCards = await page.locator('.card .card-title').allTextContents();
check('NOT query excludes the right document', !notCards.some((t) => t.toLowerCase().includes('three-pointer')));

await page.fill('#q', '');
await page.type('#q', 'phot');
await page.waitForTimeout(400);
check('autocomplete dropdown opens while typing', (await page.locator('#autocomplete.open').count()) === 1);
const acFirst = await page.locator('#autocomplete div').first().textContent().catch(() => '');
check('autocomplete suggests a real word', acFirst === 'photosynthesis');

await page.keyboard.press('ArrowDown');
await page.keyboard.press('Tab');
check('tab-completes the highlighted suggestion', (await page.inputValue('#q')) === 'photosynthesis');

await page.fill('#q', 'photosinthesis');
await page.waitForTimeout(500);
check('misspelled query shows a "did you mean" suggestion', await page.locator('#suggest').isVisible());
if (await page.locator('#suggest button').count() > 0) {
  await page.locator('#suggest button').first().click();
  await page.waitForTimeout(500);
  check('clicking the suggestion re-runs the search with results', (await page.locator('.card').count()) >= 1);
}

await page.fill('#q', '(unterminated');
await page.waitForTimeout(500);
check('invalid query syntax shows a clean error, not a blank page', await page.locator('.error').isVisible());

await page.fill('#q', '');
await page.waitForTimeout(300);
check('clearing the query restores the hint text', await page.locator('#hint').isVisible());

check('no uncaught JS exceptions during the whole run', jsErrors.length === 0);
if (jsErrors.length) console.log('  JS errors:', jsErrors);

await browser.close();
process.exit(failures ? 1 : 0);
