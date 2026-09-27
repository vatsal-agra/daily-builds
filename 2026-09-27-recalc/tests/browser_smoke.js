// Headless-Chromium smoke test of the grid UI, run manually (not under
// `unittest`) against a live `python3 server.py` instance. Exits non-zero
// and prints details on any failure or console error.
const { chromium } = require("/opt/node22/lib/node_modules/playwright");

const BASE = process.argv[2] || "http://127.0.0.1:8765";

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text()); });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForSelector("#grid td");

  // 1. type a literal into A1
  await page.click('td[data-col="1"][data-row="1"]');
  await page.keyboard.type("5");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);

  // 2. type a formula into B1 referencing A1
  await page.click('td[data-col="2"][data-row="1"]');
  await page.keyboard.type("=A1*3");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);

  const b1Text = await page.textContent('td[data-col="2"][data-row="1"]');
  if (b1Text !== "15") throw new Error(`expected B1 == '15', got ${JSON.stringify(b1Text)}`);

  // 3. edit A1 and confirm B1 recalculates live
  await page.click('td[data-col="1"][data-row="1"]');
  await page.keyboard.type("10");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const b1Text2 = await page.textContent('td[data-col="2"][data-row="1"]');
  if (b1Text2 !== "30") throw new Error(`expected B1 == '30' after edit, got ${JSON.stringify(b1Text2)}`);

  // 4. copy/paste with reference translation
  await page.click('td[data-col="2"][data-row="1"]');
  await page.keyboard.press("Control+c");
  await page.click('td[data-col="2"][data-row="2"]');
  await page.keyboard.press("Control+v");
  await page.waitForTimeout(150);
  const b2Text = await page.textContent('td[data-col="2"][data-row="2"]');
  if (b2Text !== "0") throw new Error(`expected B2 == '0' (A2 is blank), got ${JSON.stringify(b2Text)}`);

  // 5. a real error value renders and is styled as an error
  await page.click('td[data-col="3"][data-row="1"]');
  await page.keyboard.type("=1/0");
  await page.keyboard.press("Enter");
  await page.waitForTimeout(150);
  const c1 = await page.$('td[data-col="3"][data-row="1"]');
  const c1Text = await c1.textContent();
  const c1Class = await c1.getAttribute("class");
  if (c1Text !== "#DIV/0!") throw new Error(`expected #DIV/0!, got ${JSON.stringify(c1Text)}`);
  if (!c1Class.includes("error-cell")) throw new Error("error cell missing error-cell class");

  // 6. undo restores the previous state
  await page.keyboard.press("Control+z");
  await page.waitForTimeout(150);
  const c1After = await page.textContent('td[data-col="3"][data-row="1"]');
  if (c1After !== "") throw new Error(`expected C1 blank after undo, got ${JSON.stringify(c1After)}`);

  // 7. chart panel opens with no console errors
  await page.click("#btn-chart");
  await page.waitForTimeout(150);
  const chartVisible = await page.isVisible("#chart-panel");
  if (!chartVisible) throw new Error("chart panel did not open");

  if (consoleErrors.length > 0) {
    throw new Error("console errors: " + JSON.stringify(consoleErrors));
  }

  await browser.close();
  console.log("browser_smoke: ALL CHECKS PASSED");
  process.exit(0);
})().catch((err) => {
  console.error("browser_smoke FAILED:", err.message);
  process.exit(1);
});
