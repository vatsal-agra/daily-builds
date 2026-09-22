// Headless-Chromium smoke test for the live dashboard page: starts a real
// `swarm dashboard` server, posts synthetic events at it over real HTTP
// (exactly what a Node process does), loads the page in Chromium, and
// checks it actually renders the swarm state live via SSE with zero
// console errors. Run with:
//   NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers node tests/dashboard_browser_test.cjs
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");

async function waitForPort(proc) {
  return new Promise((resolve, reject) => {
    let buf = "";
    const onData = (chunk) => {
      buf += chunk.toString();
      const m = buf.match(/listening on http:\/\/[^:]+:(\d+)\//);
      if (m) {
        proc.stdout.off("data", onData);
        resolve(parseInt(m[1], 10));
      }
    };
    proc.stdout.on("data", onData);
    setTimeout(() => reject(new Error("timed out waiting for dashboard to report its port")), 10000);
  });
}

async function main() {
  const proc = spawn("python3", ["-m", "swarm.cli", "dashboard", "--host", "127.0.0.1", "--port", "0"], {
    stdio: ["ignore", "pipe", "inherit"],
  });
  let browser = null;
  try {
    const port = await waitForPort(proc);
    const base = `http://127.0.0.1:${port}`;

    async function post(evt) {
      const res = await fetch(`${base}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(evt),
      });
      if (res.status !== 204) throw new Error(`POST /events returned ${res.status}`);
    }

    const numPieces = 8;
    // bitfield with pieces 0 and 1 already set (MSB-first): 0b11000000 = 0xc0
    await post({ type: "hello", node: "a".repeat(40), port: 6001, info_hash: "f".repeat(40), torrent_name: "demo.bin", num_pieces: numPieces, have_bitfield: "c0" });
    await post({ type: "peer_connected", node: "a".repeat(40), peer: "b".repeat(40), addr: ["127.0.0.1", 6002], outbound: true });
    await post({ type: "piece_complete", node: "a".repeat(40), peer: "b".repeat(40), piece: 2 });
    await post({ type: "choke_update", node: "a".repeat(40), unchoked: ["b".repeat(40)] });

    browser = await chromium.launch();
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });
    page.on("pageerror", (err) => consoleErrors.push(String(err)));

    await page.goto(`${base}/`, { waitUntil: "load" });
    await page.waitForFunction(() => document.getElementById("status").textContent.trim() === "live", { timeout: 5000 });
    await page.waitForSelector(".swarm .peer-row", { timeout: 5000 });

    // piece_complete marks a cell "flash" first, settling to solid "have"
    // after ~900ms (see dashboard.html) -- wait for that so the freshly
    // completed piece is counted rather than caught mid-animation.
    await page.waitForFunction(() => document.querySelectorAll(".cell.have").length >= 3, { timeout: 3000 });

    const haveCount = await page.evaluate(() => document.querySelectorAll(".cell.have").length);
    if (haveCount < 3) throw new Error(`expected at least 3 "have" cells (2 from hello + 1 from piece_complete), got ${haveCount}`);

    const statusText = await page.evaluate(() => document.getElementById("status").textContent);
    if (statusText.trim() !== "live") throw new Error(`expected SSE status "live", got "${statusText}"`);

    const logLines = await page.evaluate(() => document.querySelectorAll("#log-lines .line").length);
    if (logLines < 3) throw new Error(`expected event log entries, got ${logLines}`);

    if (consoleErrors.length) throw new Error(`browser console errors: ${JSON.stringify(consoleErrors)}`);

    console.log(`PASS: dashboard rendered ${haveCount} have-cells, status=live, ${logLines} log lines, 0 console errors`);
  } finally {
    if (browser) await browser.close();
    proc.kill();
  }
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error("FAIL:", err.message || err);
    process.exit(1);
  }
);
