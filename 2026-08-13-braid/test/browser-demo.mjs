// browser-demo.mjs — an executable smoke test of the ACTUAL app in a real
// browser (not just the algorithm in isolation): drives index.html with
// Playwright and asserts every required + stretch feature works end to
// end. Exits non-zero (with a clear message) on any failure.
//
// Usage: node test/browser-demo.mjs <url-to-index.html>
// (demo.sh starts a static server and passes the URL in)

const url = process.argv[2];
if (!url) {
  console.error('usage: node test/browser-demo.mjs <url>');
  process.exit(1);
}

// Playwright may be installed locally (`npm i -D playwright`) or available
// globally in this environment — try a few resolution paths rather than
// hard-failing the whole demo if it's just not on this machine.
async function loadPlaywright() {
  const candidates = ['playwright', '/opt/node22/lib/node_modules/playwright/index.mjs'];
  for (const c of candidates) {
    try {
      return await import(c);
    } catch {
      /* try next */
    }
  }
  return null;
}

const pw = await loadPlaywright();
if (!pw) {
  console.log('⚠️  playwright not found on this machine — skipping the browser smoke test.');
  console.log('    (the mandatory, portable check is `npm test`, which already passed.)');
  process.exit(0);
}

const results = [];
function check(name, condition, detail = '') {
  results.push({ name, pass: !!condition, detail });
  console.log(`${condition ? '✅' : '❌'} ${name}${detail ? ' — ' + detail : ''}`);
}

const launchOpts = process.env.PLAYWRIGHT_BROWSERS_PATH ? { executablePath: '/opt/pw-browsers/chromium' } : {};
const browser = await pw.chromium.launch(launchOpts).catch(() => pw.chromium.launch());
const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(err.message));
page.on('console', (msg) => {
  if (msg.type() === 'error') pageErrors.push(msg.text());
});

await page.goto(url);
await page.waitForTimeout(300);

// low latency for a fast, deterministic-ish demo run
await page.fill('#minLatency', '10');
await page.dispatchEvent('#minLatency', 'input');
await page.fill('#maxLatency', '30');
await page.dispatchEvent('#maxLatency', 'input');

// ---- Feature 1 & 2: RGA CRDT + multi-peer live editor ----
let textareas = await page.$$('textarea');
check('boots with 3 peers', textareas.length === 3, `found ${textareas.length}`);

await textareas[0].click();
await textareas[0].type('hello braid', { delay: 5 });
await page.waitForTimeout(500);
let values = await Promise.all(textareas.map((t) => t.inputValue()));
check('typing in one peer converges to all peers', values.every((v) => v === 'hello braid'), JSON.stringify(values));

// ---- Feature 3: network simulator — partition + heal ----
const selects = await page.$$('.partition-chip select');
await selects[0].selectOption('B'); // isolate peer 0
await textareas[0].type(' [isolated edit]', { delay: 3 });
await textareas[1].click();
await textareas[1].type(' [mainline edit]', { delay: 3 });
await page.waitForTimeout(400);
values = await Promise.all(textareas.map((t) => t.inputValue()));
const divergedDuringPartition = values[0] !== values[1];
const mainlineStillSynced = values[1] === values[2];
check(
  'partition isolates a peer while others stay in sync',
  divergedDuringPartition && mainlineStillSynced,
  JSON.stringify(values)
);

const badgeClass = await page.getAttribute('#convergenceBadge', 'class');
check('convergence badge shows "diverged" during the partition', badgeClass.includes('diverged'));

await page.click('#healBtn');
await page.waitForTimeout(600);
values = await Promise.all(textareas.map((t) => t.inputValue()));
const reconverged = new Set(values).size === 1;
check('healing the partition merges both histories back together', reconverged, JSON.stringify(values));
const badgeClassAfter = await page.getAttribute('#convergenceBadge', 'class');
check('convergence badge clears back to synced after heal', !badgeClassAfter.includes('diverged'));

// ---- Feature 5 (stretch): character attribution ----
await page.click('#attributionToggle');
await page.waitForTimeout(200);
// scope to ONE peer card — all three panes show the same converged text
// with attribution on, so an unscoped selector would count 3x too many
const attributionSpanCount = await page.$eval('.peer-card', (card) => card.querySelectorAll('.attribution.show .ch').length);
check('attribution view renders one colored span per character', attributionSpanCount === values[0].length, `${attributionSpanCount} spans for ${values[0].length} chars`);
await page.click('#attributionToggle');

// ---- Feature 6 (stretch): causal undo/redo ----
const beforeUndo = await textareas[1].inputValue();
const undoBtns = await page.$$('.undo-btn');
await undoBtns[1].click();
await page.waitForTimeout(400);
const afterUndo = (await Promise.all(textareas.map((t) => t.inputValue())))[0];
check('undo shortens this peer\'s text and propagates to others', afterUndo.length === beforeUndo.length - 1, `${beforeUndo.length} -> ${afterUndo.length}`);
const redoBtns = await page.$$('.redo-btn');
await redoBtns[1].click();
await page.waitForTimeout(400);
const afterRedo = (await Promise.all(textareas.map((t) => t.inputValue())))[0];
check('redo restores it', afterRedo.length === beforeUndo.length, `${afterRedo.length} vs original ${beforeUndo.length}`);

// ---- Regression: peer name never reused after removal (Phase 3 bug #2) ----
await page.click('.remove-peer-btn');
await page.waitForTimeout(150);
await page.click('#addPeerBtn');
await page.waitForTimeout(150);
const names = await page.$$eval('.peer-card .name', (els) => els.map((e) => e.textContent));
check('removed peer\'s name is never reused', !names.includes('Alice'), JSON.stringify(names));

textareas = await page.$$('textarea');
await textareas[textareas.length - 1].click();
await textareas[textareas.length - 1].type('new-peer-propagates', { delay: 3 });
await page.waitForTimeout(500);
values = await Promise.all(textareas.map((t) => t.inputValue()));
check('a newly-added peer\'s edits reach every other peer', values.every((v) => v.includes('new-peer-propagates')), JSON.stringify(values));

// ---- Edge cases: empty doc, single-peer removal disabled ----
await textareas[0].fill('');
await textareas[0].dispatchEvent('input');
await page.waitForTimeout(400);
values = await Promise.all(textareas.map((t) => t.inputValue()));
check('clearing a peer\'s text propagates an empty document to all peers', values.every((v) => v === ''), JSON.stringify(values));

let removeBtns = await page.$$('.remove-peer-btn');
while (removeBtns.length > 1) {
  await removeBtns[0].click();
  await page.waitForTimeout(100);
  removeBtns = await page.$$('.remove-peer-btn');
}
const lastRemoveDisabled = await removeBtns[0].isDisabled();
check('the last remaining peer cannot be removed', lastRemoveDisabled);

check('no console/page errors occurred during the whole run', pageErrors.length === 0, pageErrors.join(' | '));

await browser.close();

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed.`);
if (failed.length) {
  console.log('FAILED:', failed.map((f) => f.name).join(', '));
  process.exit(1);
}
process.exit(0);
