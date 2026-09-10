// Headless-Chromium smoke test for the interactive box inspector
// (viz.py / `cascade viz`): loads the generated page, clicks a box, and
// reports console errors + whether the detail panel populated -- as JSON
// on stdout so tests/test_viz_ui.py can assert on it without needing a
// Python Playwright binding.
const { chromium } = require("playwright");

async function main() {
  const [, , htmlPath] = process.argv;
  const browser = await chromium.launch({
    executablePath: "/opt/pw-browsers/chromium",
    args: ["--headless=new"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1300, height: 700 } });
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    await page.goto("file://" + require("path").resolve(htmlPath));
    const boxCount = await page.locator(".box").count();
    await page.locator(".box").last().click({ force: true });
    const detailText = await page.locator("#detail").innerText();
    const hasBoxModelDiagram = await page.locator(".bm-content").count();
    process.stdout.write(JSON.stringify({
      consoleErrors,
      boxCount,
      detailPopulated: detailText.trim().length > 0,
      hasBoxModelDiagram: hasBoxModelDiagram > 0,
    }));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
