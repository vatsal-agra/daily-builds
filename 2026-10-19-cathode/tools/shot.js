// Screenshot an HTML file with the pre-installed Chromium: node tools/shot.js in.html out.png [light|dark] [--info]
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const [, , input, output, scheme = 'dark'] = process.argv;
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' , args: ['--no-sandbox'] });
  const p = await b.newPage({ viewport: { width: 1000, height: 700 }, colorScheme: scheme });
  await p.goto('file://' + require('path').resolve(input));
  await p.screenshot({ path: output, fullPage: true });
  if (process.argv.includes('--info')) {
    const rows = await p.$$eval('.r', els => els.map(e => Math.round(e.getBoundingClientRect().height * 10) / 10));
    console.log(JSON.stringify({ rows: rows.length, h: [...new Set(rows)] }));
  }
  await b.close();
})();
