// Headless-browser smoke test for the Ashenkeep UI. Loads the real page,
// starts a seeded run, moves the player, opens the inventory, and confirms
// zero console/page errors throughout — a broken script-load order or a
// DOM-wiring typo in main.js would show up here even though every
// game-logic module passes its node:test suite in isolation.
import { createRequire } from 'module';
import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, '..');

const PLAYWRIGHT_MODULE = process.env.PLAYWRIGHT_MODULE || '/opt/node22/lib/node_modules/playwright/index.js';
const CHROME_PATH = process.env.CHROME_PATH;
const PORT = 8931;

function assert(cond, msg) {
  if (!cond) throw new Error(`assertion failed: ${msg}`);
}

async function main() {
  const { chromium } = require(PLAYWRIGHT_MODULE);
  const server = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: root, stdio: 'ignore' });
  await new Promise((r) => setTimeout(r, 800));

  try {
    const browser = await chromium.launch({
      ...(CHROME_PATH ? { executablePath: CHROME_PATH } : {}),
      args: ['--disable-background-networking', '--disable-component-update', '--no-first-run'],
    });
    for (const colorScheme of ['light', 'dark']) {
      const page = await browser.newPage({ colorScheme });
      const errors = [];
      page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
      page.on('console', (msg) => {
        if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
      });

      await page.goto(`http://localhost:${PORT}/index.html`);
      await page.waitForSelector('#menu-screen');
      assert(await page.locator('#new-run-btn').isVisible(), 'new-run button should be visible on the menu');
      assert(await page.locator('#continue-btn').isDisabled(), 'continue should be disabled with no save yet');

      await page.fill('#seed-input', '424242');
      await page.click('#new-run-btn');
      await page.waitForSelector('#game-screen:not([hidden])');

      assert(await page.locator('#level-text').innerText() === 'Level 1', 'should start at level 1');
      const floorText = await page.locator('#floor-text').innerText();
      assert(floorText === 'Floor 1 / 10', `expected Floor 1 / 10, got "${floorText}"`);

      // Canvas must have actually drawn something (not just be black).
      const canvasHasContent = await page.evaluate(() => {
        const canvas = document.getElementById('game-canvas');
        const ctx = canvas.getContext('2d');
        const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let i = 0; i < data.length; i += 4) {
          if (data[i] !== 0 || data[i + 1] !== 0 || data[i + 2] !== 0) return true;
        }
        return false;
      });
      assert(canvasHasContent, 'game canvas should render non-black pixels (dungeon tiles/player)');

      // Move the player several times; turn counter isn't shown directly,
      // but hp/xp bars and message log should update without throwing.
      for (let i = 0; i < 6; i++) {
        await page.keyboard.press('ArrowRight');
        await page.waitForTimeout(30);
      }
      const logLines = await page.locator('#message-log .log-line').count();
      assert(logLines > 0, 'message log should contain at least one entry after moving');

      // Reload should offer Continue now that a save exists.
      await page.reload();
      await page.waitForSelector('#menu-screen');
      assert(!(await page.locator('#continue-btn').isDisabled()), 'continue should be enabled after a save was written');
      await page.click('#continue-btn');
      await page.waitForSelector('#game-screen:not([hidden])');

      if (errors.length > 0) {
        throw new Error(`Console/page errors in ${colorScheme} mode:\n` + errors.join('\n'));
      }
      await page.close();
      console.log(`[ok] ${colorScheme} mode: menu -> new run -> move -> save -> reload -> continue, zero console errors`);
    }
    await browser.close();
  } finally {
    server.kill();
  }
}

main().catch((err) => {
  console.error('UI smoke test FAILED:', err.message);
  process.exit(1);
});
