// Headless check: report renders, no horizontal scroll at phone width, charts + images present in both themes.
const { chromium } = require('playwright');
(async () => {
  const file = process.argv[2];
  const b = await chromium.launch();
  let bad = 0;
  for (const scheme of ['light', 'dark']) {
    for (const w of [390, 1000]) {
      const p = await b.newPage({ viewport: { width: w, height: 800 }, colorScheme: scheme });
      await p.goto('file://' + file);
      const r = await p.evaluate(() => ({
        sw: document.documentElement.scrollWidth,
        svgs: document.querySelectorAll('svg').length,
        visImgs: [...document.querySelectorAll('figure img')].filter(i => i.offsetWidth > 0 && i.naturalWidth > 0).length,
        cards: document.querySelectorAll('.card').length,
      }));
      const ok = r.sw <= w && r.svgs >= 1 && r.visImgs >= 2 && r.cards >= 2;
      if (!ok) bad++;
      console.log(`${scheme} ${w}px: scrollWidth=${r.sw} svgs=${r.svgs} visibleImgs=${r.visImgs} cards=${r.cards} ${ok ? 'ok' : 'FAIL'}`);
    }
  }
  await b.close();
  process.exit(bad ? 1 : 0);
})();
