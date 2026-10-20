// Loads a qsim HTML report in headless Chromium (light and dark), fails on any page error and
// checks that the scorecard, chart and heap map actually rendered.  usage: node check_report.js report.html [shots-dir]
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const path = require("path");
(async () => {
  const file = path.resolve(process.argv[2]);
  const shots = process.argv[3];
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-sandbox"] });
  let failed = 0;
  const fail = (m) => { console.error("FAIL: " + m); failed++; };
  for (const scheme of ["light", "dark"]) {
    const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, colorScheme: scheme });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await page.goto("file://" + file);
    await page.waitForSelector("#score tr");
    const rows = await page.$$eval("#score tr", (r) => r.length);
    if (rows < 3) fail(scheme + ": scorecard has " + rows + " rows");
    const paths = await page.$$eval("#chart path", (p) => p.length);
    if (paths < 3) fail(scheme + ": chart drew " + paths + " paths");
    const hasMap = await page.$eval("#mapsec", (s) => getComputedStyle(s).display !== "none");
    if (hasMap) {
      const painted = await page.$eval("#map", (c) => { const x = c.getContext("2d"); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++; return n; });
      if (!painted) fail(scheme + ": heap map canvas is blank");
      await page.click("#play"); await page.waitForTimeout(500); await page.click("#play");
      const stat = await page.$eval("#mapstat", (e) => e.textContent);
      if (!/event/.test(stat)) fail(scheme + ": map status line empty");
    }
    // nothing may overflow horizontally at phone width
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(150);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (overflow > 1) fail(scheme + ": page scrolls horizontally by " + overflow + "px at 390px");
    if (errors.length) fail(scheme + ": page errors: " + errors.join("; "));
    if (shots) { await page.setViewportSize({ width: 1200, height: 900 }); await page.waitForTimeout(150); await page.screenshot({ path: path.join(shots, "report-" + scheme + ".png"), fullPage: true }); }
    await page.close();
  }
  await browser.close();
  if (failed) process.exit(1);
  console.log("report renders in light and dark, no page errors, no horizontal overflow at 390px");
})();
