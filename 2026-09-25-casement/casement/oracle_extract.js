// Loads a local HTML file in headless Chromium and reports every
// [data-cid]-tagged element's real getBoundingClientRect() as JSON on
// stdout. Used by `casement compare` as an external ground truth for
// Casement's own computed box geometry -- see PLAN.md for what this
// comparison is (and isn't) meant to cover.
const { chromium } = require('playwright');

async function main() {
  const filePath = process.argv[2];
  const viewportWidth = parseInt(process.argv[3] || '800', 10);
  const browser = await chromium.launch({ executablePath: process.env.CASEMENT_CHROMIUM_PATH || '/opt/pw-browsers/chromium' });
  try {
    const page = await browser.newPage({ viewport: { width: viewportWidth, height: 800 } });
    await page.goto('file://' + filePath);
    const rects = await page.evaluate(() => {
      const out = {};
      document.querySelectorAll('[data-cid]').forEach((el) => {
        const r = el.getBoundingClientRect();
        out[el.getAttribute('data-cid')] = {
          x: r.x, y: r.y, width: r.width, height: r.height, tag: el.tagName.toLowerCase(),
        };
      });
      return out;
    });
    process.stdout.write(JSON.stringify(rects));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack || err) + '\n');
  process.exit(1);
});
