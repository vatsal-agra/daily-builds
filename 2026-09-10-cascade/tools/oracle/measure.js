// Loads an HTML file in real headless Chromium and dumps every element's
// true getBoundingClientRect() as JSON -- the independent ground-truth
// oracle tests/test_diff_oracle.py diffs Cascade's own layout engine
// against. Usage: node measure.js <file.html> <viewportWidth>
const { chromium } = require("playwright");
const path = require("path");

async function main() {
  const [, , htmlPath, widthArg] = process.argv;
  const width = parseInt(widthArg || "900", 10);
  const browser = await chromium.launch({
    executablePath: "/opt/pw-browsers/chromium",
    args: ["--headless=new"],
  });
  try {
    const page = await browser.newPage({ viewport: { width, height: 2000 } });
    const fileUrl = "file://" + path.resolve(htmlPath);
    await page.goto(fileUrl);
    const boxes = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll("[data-probe]").forEach((el) => {
        const r = el.getBoundingClientRect();
        out.push({
          id: el.id,
          tag: el.tagName.toLowerCase(),
          x: r.x,
          y: r.y,
          width: r.width,
          height: r.height,
        });
      });
      return out;
    });
    process.stdout.write(JSON.stringify(boxes));
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
