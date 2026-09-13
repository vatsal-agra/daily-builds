// Headless-browser smoke test for visualizer/index.html.
// Loads the generated page, exercises every tab and interactive control,
// and fails if the browser logs any console error or uncaught exception.
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });
  const page = await browser.newPage();
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));

  const filePath = "file://" + path.resolve(__dirname, "..", "visualizer", "index.html");
  await page.goto(filePath);
  await page.waitForTimeout(200);

  // Schnorr tab: step through all 4 steps.
  for (let i = 0; i < 3; i++) {
    await page.click("#s-next");
    await page.waitForTimeout(30);
  }
  const honestBadge = (await page.textContent("#s-honest-badge")).trim();
  if (honestBadge !== "accepted") throw new Error(`expected 'accepted', got '${honestBadge}'`);

  // OR-proof tab.
  await page.click('[data-tab="orproof"]');
  await page.waitForTimeout(80);
  const orBadge = (await page.textContent("#or-verified-badge")).trim();
  if (orBadge !== "proof verifies") throw new Error(`expected 'proof verifies', got '${orBadge}'`);
  const memberCards = await page.$$(".member-card");
  if (memberCards.length < 2) throw new Error("expected multiple member cards rendered");

  // Coloring tab: step through rounds, then autoplay briefly.
  await page.click('[data-tab="coloring"]');
  await page.waitForTimeout(80);
  for (let i = 0; i < 5; i++) {
    await page.click("#c-next");
    await page.waitForTimeout(30);
  }
  const roundBadge = (await page.textContent("#c-round-badge")).trim();
  if (roundBadge !== "accepted") throw new Error(`expected round to show 'accepted', got '${roundBadge}'`);
  await page.click("#c-play");
  await page.waitForTimeout(1300);
  await page.click("#c-play");

  await browser.close();

  if (errors.length) {
    console.error("CONSOLE ERRORS:", errors);
    process.exit(1);
  }
  console.log("  visualizer smoke test: zero console errors, all tabs interactive");
})().catch((err) => {
  console.error("SMOKE TEST FAILED:", err);
  process.exit(1);
});
