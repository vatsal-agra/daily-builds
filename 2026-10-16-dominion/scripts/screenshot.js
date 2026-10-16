// Renders a Dominion HTML report in headless Chromium, fails on any page error, and saves PNGs.
// usage: NODE_PATH=$(npm root -g) node scripts/screenshot.js report.html out-prefix [stageIndex ...]
const { chromium } = require("playwright");
(async () => {
  const [file, prefix, ...stages] = process.argv.slice(2);
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" }).catch(() => chromium.launch());
  const errors = [];
  for (const scheme of ["light", "dark"]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: scheme });
    page.on("pageerror", e => errors.push(String(e)));
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await page.goto("file://" + require("path").resolve(file));
    const n = await page.evaluate(() => D.stages.length);
    const picks = stages.length ? stages.map(Number) : [0, n - 1];
    for (const s of picks) {
      await page.evaluate(i => { stage = i; render(); }, Math.min(s, n - 1));
      await page.screenshot({ path: `${prefix}-${scheme}-${s}.png`, fullPage: true });
    }
    const info = await page.evaluate(() => ({ nodes: document.querySelectorAll("#cfg .node").length, paths: document.querySelectorAll("#cfg path.edge").length, rows: document.querySelectorAll("#bench tr").length }));
    console.log(scheme, "stages", n, JSON.stringify(info));
    if (!info.nodes || info.rows !== 5) errors.push("report did not render: " + JSON.stringify(info));
    await page.close();
  }
  await browser.close();
  if (errors.length) { console.error("ERRORS:\n" + errors.join("\n")); process.exit(1); }
})();
