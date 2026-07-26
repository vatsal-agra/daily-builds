// Headless-browser smoke test for the Waveforge UI. Exercises the full
// interactive path: add/remove tracks, click a step through its velocity
// cycle, play/stop, load the demo song, and export a WAV — asserting zero
// console/page errors throughout.
import { createRequire } from 'module';
import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');

const PLAYWRIGHT_MODULE = process.env.PLAYWRIGHT_MODULE;
const CHROME_PATH = process.env.CHROME_PATH;
const PORT = 8917;

function assert(cond, msg) {
  if (!cond) throw new Error(`assertion failed: ${msg}`);
}

async function main() {
  const { chromium } = require(PLAYWRIGHT_MODULE);
  const server = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: root, stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 800));

  try {
    const browser = await chromium.launch({ executablePath: CHROME_PATH });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`console: ${msg.text()}`); });

    await page.goto(`http://localhost:${PORT}/index.html`);
    await page.waitForSelector('.track-row', { timeout: 10000 });
    assert((await page.locator('.track-row').count()) === 4, 'expected 4 default tracks');

    await page.click('#addTrackBtn');
    assert((await page.locator('.track-row').count()) === 5, 'add track should create a 5th row');

    await page.locator('.track-row').last().locator('.btn.danger').click();
    assert((await page.locator('.track-row').count()) === 4, 'remove track should return to 4 rows');

    const firstCell = page.locator('.track-row').first().locator('.step-cell').first();
    await firstCell.click();
    assert((await firstCell.getAttribute('class')).includes('soft'), 'first click should cycle to "soft" level');

    await page.click('#playBtn');
    await page.waitForTimeout(400);
    assert(await page.locator('#playBtn').isDisabled(), 'play button should disable while playing');
    await page.click('#stopBtn');
    await page.waitForTimeout(100);
    assert(!(await page.locator('#playBtn').isDisabled()), 'play button should re-enable after stop');

    await page.click('#loadDemoBtn');
    await page.waitForTimeout(300);
    assert((await page.locator('.track-row').count()) === 6, 'demo song should load 6 tracks');

    const downloadPromise = page.waitForEvent('download', { timeout: 5000 });
    await page.click('#exportBtn');
    const download = await downloadPromise;
    assert((await download.suggestedFilename()) === 'waveforge-song.wav', 'export should download a wav file');

    assert(errors.length === 0, `expected zero console/page errors, got: ${JSON.stringify(errors)}`);

    await browser.close();
    console.log('UI smoke test: all assertions passed, zero console errors.');
  } finally {
    server.kill();
  }
}

main().catch((err) => {
  console.error('UI SMOKE TEST FAILED:', err.message);
  process.exit(1);
});
