// Renders an HTML file in real headless Chromium (pre-installed at
// /opt/pw-browsers/chromium, driven via the globally-installed Node
// `playwright` package) and prints the getBoundingClientRect() of every
// element as JSON — the ground truth oracle/run_diff.py diffs Cascade's
// own layout numbers against.
//
// Usage: node diff.cjs <html-file-path> <viewport-width>

const path = require("path");
const { chromium } = require("/opt/node22/lib/node_modules/playwright");

async function main() {
  const [, , htmlPath, widthStr] = process.argv;
  const width = parseInt(widthStr || "800", 10);
  if (!htmlPath) {
    console.error("usage: node diff.cjs <html-file> <viewport-width>");
    process.exit(2);
  }
  const browser = await chromium.launch({
    executablePath: "/opt/pw-browsers/chromium",
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({ viewport: { width, height: 3000 } });
    await page.goto("file://" + path.resolve(htmlPath));
    const boxes = await page.evaluate(() => {
      const out = [];
      document.querySelectorAll("body, body *").forEach((el) => {
        const cs = getComputedStyle(el);
        if (cs.display === "none") return;
        const r = el.getBoundingClientRect();
        out.push({
          tag: el.tagName.toLowerCase(),
          id: el.id || null,
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

main().catch((e) => {
  console.error(e && e.stack ? e.stack : e);
  process.exit(1);
});
