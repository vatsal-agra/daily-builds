// Drives the generated HTML player in headless Chromium: node tools/check_player.js player.html out.png
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const [, , input, output] = process.argv;
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const p = await b.newPage({ viewport: { width: 900, height: 600 }, colorScheme: 'dark' });
  const errors = [];
  p.on('pageerror', e => errors.push(String(e)));
  await p.goto('file://' + require('path').resolve(input));
  const n = await p.evaluate(() => FRAMES.length);
  const last = await p.textContent('#scr');
  await p.fill('#seek', '0').catch(() => {});
  await p.evaluate(() => { const s = document.getElementById('seek'); s.value = Math.floor(FRAMES.length / 2); s.dispatchEvent(new Event('input')); });
  const mid = await p.textContent('#scr');
  await p.screenshot({ path: output, fullPage: true });
  await p.click('#pp');
  await p.waitForTimeout(400);
  const playing = await p.textContent('#pp');
  console.log(JSON.stringify({ frames: n, lastHasText: last.trim().length > 0, midDiffers: mid !== last, playButton: playing, errors }));
  await b.close();
})();
