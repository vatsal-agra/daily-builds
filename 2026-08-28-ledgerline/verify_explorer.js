// Headless-Chromium smoke check of the LedgerLine block explorer.
// Usage: node verify_explorer.js <url> <screenshot-out-path>
// Exits 0 if the page loads cleanly (no console errors), the node list
// actually renders real data from the running nodes, and a send-coins
// round trip through the UI's own form works — 1 otherwise, printing why.
const path = require("path");
const { chromium } = require(path.join("/opt/node22/lib/node_modules", "playwright"));

async function main() {
  const url = process.argv[2];
  const screenshotPath = process.argv[3];
  if (!url || !screenshotPath) {
    console.error("usage: node verify_explorer.js <url> <screenshot-out-path>");
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 } });

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  const failures = [];

  // NOT "networkidle": the explorer polls /api/status etc. every 1.5s
  // forever by design (live-updating UI), so the page never has a truly
  // quiet network window — "networkidle" intermittently times out
  // waiting for a condition that will never actually hold, nothing to do
  // with whether the page loaded correctly. "load" plus explicitly
  // waiting for real rendered data (below) is what actually proves this.
  await page.goto(url, { waitUntil: "load", timeout: 20000 });

  const title = await page.title();
  if (title !== "LedgerLine Explorer") failures.push(`unexpected title: ${JSON.stringify(title)}`);

  try {
    await page.waitForSelector(".node-card", { timeout: 15000 });
  } catch {
    failures.push("no .node-card ever appeared — the explorer never rendered live node data");
  }

  const nodeCardCount = await page.locator(".node-card").count();
  if (nodeCardCount < 1) failures.push(`expected at least 1 node card, found ${nodeCardCount}`);

  const headerText = await page.locator("#headerSub").textContent();
  if (!headerText || headerText.includes("connecting") || headerText.includes("lost")) {
    failures.push(`header never showed live status: ${JSON.stringify(headerText)}`);
  }

  // exercise the send form end-to-end: pick a real recipient address off
  // the second node card (if there is one), submit, confirm success text
  const nodeCount = await page.locator(".node-card").count();
  if (nodeCount >= 2) {
    // the .addr element on a card shows "host:port", not a coin address —
    // read the real recipient address straight from the API instead
    const status = await page.evaluate(async () => {
      const res = await fetch("/api/status");
      return res.json();
    });
    const recipient = status.nodes[1].address;
    await page.fill("#toAddress", recipient);
    await page.fill("#amount", "5");
    await page.click("#sendForm button[type=submit]");
    // a fixed sleep here raced the server: with real mining threads
    // competing for the GIL under load, /api/send can legitimately take
    // longer than a short fixed wait — poll for the actual result
    // instead of gambling on one fixed delay being long enough.
    try {
      await page.waitForFunction(
        () => {
          const el = document.querySelector("#sendMsg");
          return el && el.textContent && el.textContent.trim().length > 0;
        },
        { timeout: 10000 },
      );
    } catch {
      // fall through — the empty/timeout case is reported below
    }
    const sendMsg = await page.locator("#sendMsg").textContent();
    if (!sendMsg || !sendMsg.toLowerCase().includes("sent")) {
      failures.push(`send form did not report success: ${JSON.stringify(sendMsg)}`);
    }
  }

  await page.screenshot({ path: screenshotPath, fullPage: true });

  if (consoleErrors.length > 0) {
    failures.push(`console errors: ${JSON.stringify(consoleErrors)}`);
  }

  await browser.close();

  if (failures.length > 0) {
    console.error("EXPLORER CHECK FAILED:");
    for (const f of failures) console.error("  - " + f);
    process.exit(1);
  }
  console.log(`explorer check passed (${nodeCardCount} node cards, 0 console errors, screenshot saved to ${screenshotPath})`);
  process.exit(0);
}

main().catch((err) => {
  console.error("EXPLORER CHECK CRASHED:", err);
  process.exit(1);
});
