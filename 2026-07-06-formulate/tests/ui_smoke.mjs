// Headless-browser smoke test of the real UI, driving the real Python server.
// Run via: NODE_PATH=<global node_modules> node tests/ui_smoke.mjs
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

const PORT = 8917;
const CHROME_PATH = process.env.CHROME_PATH || "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

function assert(cond, msg) {
  if (!cond) throw new Error("ASSERTION FAILED: " + msg);
}

// Edits are committed asynchronously (fetch to the real server); poll rather
// than assume the DOM has updated by the time the next line runs.
async function waitForText(page, selector, expected, tries = 30) {
  let last = null;
  for (let i = 0; i < tries; i++) {
    last = await page.textContent(selector);
    if (last === expected) return last;
    await sleep(50);
  }
  return last;
}

async function waitForServer(url, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try {
      const res = await fetch(url);
      if (res.ok) return;
    } catch {}
    await sleep(150);
  }
  throw new Error("server never came up");
}

async function main() {
  const proc = spawn("python3", ["cli.py", "serve", "--port", String(PORT)], {
    cwd: new URL("..", import.meta.url).pathname,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let serverLog = "";
  proc.stdout.on("data", (d) => (serverLog += d));
  proc.stderr.on("data", (d) => (serverLog += d));

  try {
    await waitForServer(`http://127.0.0.1:${PORT}/api/state`);

    const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true, args: ["--no-sandbox"] });
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("pageerror", (err) => consoleErrors.push(String(err)));
    page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });

    await page.goto(`http://127.0.0.1:${PORT}/`);
    await page.waitForSelector("#grid td.cell");

    const cell = (r, c) => `td.cell[data-row="${r}"][data-col="${c}"]`;

    // 1. Type a value, tab to next cell, type a formula referencing it.
    await page.click(cell(0, 0));
    await page.keyboard.type("12");
    await page.keyboard.press("Tab");
    await page.keyboard.type("=A1*2");
    await page.keyboard.press("Enter");
    let text = await waitForText(page, cell(0, 0), "12");
    assert(text === "12", `A1 should show 12, got ${text}`);
    text = await waitForText(page, cell(0, 1), "24");
    assert(text === "24", `B1 should show 24 (computed by the server), got ${text}`);

    // 2. Formula bar shows the raw formula when selecting the cell, not the value.
    await page.click(cell(0, 1));
    const fx = await page.inputValue("#formula-input");
    assert(fx === "=A1*2", `formula bar should show =A1*2, got ${fx}`);

    // 3. Editing a precedent live-updates the dependent cell (dependency graph).
    await page.click(cell(0, 0));
    await page.keyboard.type("100");
    await page.keyboard.press("Enter");
    text = await waitForText(page, cell(0, 1), "200");
    assert(text === "200", `B1 should recompute to 200 after A1 changes, got ${text}`);

    // 4. Undo restores both cells.
    await page.keyboard.down("Control");
    await page.keyboard.press("z");
    await page.keyboard.up("Control");
    text = await waitForText(page, cell(0, 1), "24");
    assert(text === "24", `B1 should be 24 again after undo, got ${text}`);

    // 5. A genuine circular reference shows #CIRC! and doesn't hang the page.
    await page.click(cell(2, 2)); // C3 (row index 2, col index 2)
    await page.keyboard.type("=C3+1");
    await page.keyboard.press("Enter");
    text = await waitForText(page, cell(2, 2), "#CIRC!");
    assert(text === "#CIRC!", `C3 self-cycle should show #CIRC!, got ${text}`);
    const isError = await page.evaluate((sel) => document.querySelector(sel).classList.contains("error"), cell(2, 2));
    assert(isError, "error cell should get the .error highlight class");

    // 6. Drag-fill: fill B1's formula down through B2/B3 with relative-ref shift.
    await page.click(cell(3, 0));
    await page.keyboard.type("5");
    await page.keyboard.press("Enter");
    await page.click(cell(0, 1));
    await page.hover(cell(0, 1));
    const handle = await page.$(".fill-handle");
    const box = await handle.boundingBox();
    await page.mouse.move(box.x + 2, box.y + 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 2, box.y + 2 + 24 * 3);
    await page.mouse.up();
    text = await waitForText(page, cell(3, 1), "10");
    assert(text === "10", `B4 fill-down of =A1*2 shifted to =A4*2 should be 10, got ${text}`);

    // 7. Multi-sheet: add a sheet via the "+" tab (backed by a window.prompt()).
    page.once("dialog", (d) => d.accept("Data"));
    await page.click("#add-sheet");
    await page.waitForFunction(() => document.querySelectorAll(".tab").length >= 2);
    const tabs = await page.$$eval(".tab", (els) => els.map((e) => e.textContent));
    assert(tabs.includes("Data"), `expected a Data sheet tab, got ${tabs}`);

    await page.screenshot({ path: "/tmp/formulate_ui_smoke.png" });
    await browser.close();

    assert(consoleErrors.length === 0, `unexpected browser console errors: ${consoleErrors.join(" | ")}`);

    console.log("UI SMOKE TEST: ALL PASSED");
  } finally {
    proc.kill();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
