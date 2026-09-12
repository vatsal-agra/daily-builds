// Headless-browser smoke test for visualizer/index.html: loads the
// self-contained page, exercises every dropdown, and asserts zero
// console/page errors plus real (non-empty, non-placeholder) rendered
// content in every panel.
//
// Usage: node visualizer_smoke.js <path-to-index.html>
// Exits 0 on success, 1 on any failure.
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const htmlPath = process.argv[2];
  if (!htmlPath) {
    console.error('usage: node visualizer_smoke.js <path>');
    process.exit(2);
  }
  const errors = [];
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (exc) => errors.push(String(exc)));

  await page.goto('file://' + path.resolve(htmlPath));
  await page.waitForTimeout(300);

  const algoOptions = await page.$$eval('#schedAlgo option', (els) => els.map((e) => e.value));
  if (algoOptions.length !== 6) throw new Error(`expected 6 scheduler algorithms, got ${algoOptions.length}: ${algoOptions}`);

  for (const algo of algoOptions) {
    await page.selectOption('#schedAlgo', algo);
    await page.waitForTimeout(50);
    const rows = await page.$$eval('#schedTable tbody tr', (els) => els.length);
    if (rows < 1) throw new Error(`algorithm ${algo}: schedule table has no rows`);
    const stat = await page.$eval('#schedStats .value', (el) => el.textContent.trim());
    if (!stat || stat === 'NaN') throw new Error(`algorithm ${algo}: bad stat value ${stat}`);
  }

  const frameOptions = await page.$$eval('#memFrames option', (els) => els.map((e) => e.value));
  const memAlgoOptions = await page.$$eval('#memAlgo option', (els) => els.map((e) => e.value));
  if (frameOptions.length < 2) throw new Error('expected multiple frame-count options');
  if (memAlgoOptions.length !== 4) throw new Error(`expected 4 memory algorithms, got ${memAlgoOptions.length}`);

  for (const f of frameOptions) {
    for (const a of memAlgoOptions) {
      await page.selectOption('#memFrames', f);
      await page.selectOption('#memAlgo', a);
      await page.waitForTimeout(30);
      const faults = await page.$eval('#memStats .value', (el) => el.textContent.trim());
      if (faults === '' || faults === 'undefined') throw new Error(`mem ${f}/${a}: bad fault count`);
    }
  }

  const beladyRows = await page.$$eval('#beladyTable tbody tr', (els) => els.length);
  if (beladyRows !== 2) throw new Error(`expected 2 Belady rows (3 and 4 frames), got ${beladyRows}`);
  const beladyBadge = await page.$eval('#beladyBadge', (el) => el.textContent);
  if (!/Belady/.test(beladyBadge) && !/DOES/.test(beladyBadge) && !/does not/.test(beladyBadge)) {
    throw new Error(`Belady badge text looks wrong: ${beladyBadge}`);
  }

  const optimalBadge = await page.$eval('#optimalBadge', (el) => el.textContent);
  if (!/Optimal-minimality/.test(optimalBadge)) throw new Error(`optimal badge missing: ${optimalBadge}`);
  if (/VIOLATED/.test(optimalBadge)) throw new Error('optimal-minimality invariant VIOLATED in rendered page');

  // Canvases must have actually drawn something (non-trivial pixel data)
  const ganttNonBlank = await page.$eval('#ganttCanvas', (c) => {
    const ctx = c.getContext('2d');
    const data = ctx.getImageData(0, 0, c.width, c.height).data;
    for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) return true;
    return false;
  });
  if (!ganttNonBlank) throw new Error('Gantt canvas appears blank');

  await browser.close();

  if (errors.length) {
    console.error('Console/page errors detected:');
    for (const e of errors) console.error(' -', e);
    process.exit(1);
  }
  console.log(`OK: ${algoOptions.length} scheduler algos x table rows, ${frameOptions.length} frame counts x ${memAlgoOptions.length} mem algos, Belady + Optimal badges verified, zero console errors.`);
}

main().catch((e) => { console.error('FAIL:', e.message); process.exit(1); });
