// browser_test.js — end-to-end multi-tab test against a REAL running
// `braid serve` instance, using Playwright/Chromium. This is what proves
// the live collaborative editor actually works in a browser, not just
// that the underlying engine's unit tests pass — SSE wiring, the DOM
// diffing in app.js, and the two bugs (REVIEW.md #2 and #3) that every
// headless test happened to route around are all only reachable through
// this path.
//
// Usage: node tests/browser_test.js [port]   (default port: 8420)
// Requires: a `braid serve --port <port>` instance already running.
// Playwright/Chromium are pre-installed in this environment at
// /opt/pw-browsers/chromium; falls back to Playwright's own resolution
// if that path doesn't exist, so this still works outside that sandbox.

const { chromium } = require("playwright");
const fs = require("fs");

const port = process.argv[2] || "8420";
const BASE_URL = `http://localhost:${port}/`;
const PW_CHROMIUM = "/opt/pw-browsers/chromium";
const launchOpts = fs.existsSync(PW_CHROMIUM) ? { executablePath: PW_CHROMIUM } : {};

(async () => {
  const browser = await chromium.launch(launchOpts);
  const ctx1 = await browser.newContext(); // separate context = separate sessionStorage = separate identity
  const ctx2 = await browser.newContext();
  const page1 = await ctx1.newPage();
  const page2 = await ctx2.newPage();

  const errors = [];
  page1.on("pageerror", (e) => errors.push("page1: " + e.message));
  page2.on("pageerror", (e) => errors.push("page2: " + e.message));
  page1.on("console", (m) => { if (m.type() === "error") errors.push("page1 console: " + m.text()); });
  page2.on("console", (m) => { if (m.type() === "error") errors.push("page2 console: " + m.text()); });

  await page1.goto(BASE_URL);
  await page2.goto(BASE_URL);
  await page1.waitForSelector("#editor");
  await page2.waitForSelector("#editor");
  await page1.waitForTimeout(300);

  // 1) basic typing in tab1 shows up in tab2 (R3: real-time collaborative editor)
  await page1.click("#editor");
  await page1.type("#editor", "hello from tab one", { delay: 25 });
  await page1.waitForTimeout(1500);
  const t2 = await page2.inputValue("#editor");
  console.log("[1] tab2 sees:", JSON.stringify(t2));
  if (t2 !== "hello from tab one") throw new Error("basic sync failed: " + t2);

  // 2) concurrent typing in both tabs converges (R1: the CRDT itself)
  await page2.click("#editor");
  await page2.press("#editor", "End");
  await page2.type("#editor", " !!!", { delay: 25 });
  await page1.press("#editor", "Home");
  await page1.type("#editor", ">>> ", { delay: 25 });
  await page1.waitForTimeout(700);
  const final1 = await page1.inputValue("#editor");
  const final2 = await page2.inputValue("#editor");
  console.log("[2] tab1 final:", JSON.stringify(final1));
  console.log("[2] tab2 final:", JSON.stringify(final2));
  if (final1 !== final2) throw new Error("CONCURRENT EDIT DID NOT CONVERGE: " + final1 + " vs " + final2);

  // 3) presence panel shows the other tab (S2: live presence)
  const presenceText = await page1.textContent("#presence-list");
  console.log("[3] presence on tab1:", presenceText.trim().replace(/\s+/g, " "));
  if (/Just you/.test(presenceText)) throw new Error("presence did not show the other tab");

  // 4) offline + reconnect (S2: network-chaos panel; R2's guarantee, live)
  await page2.click("#offline-btn");
  await page2.waitForTimeout(200);
  await page2.type("#editor", " (offline edit)", { delay: 20 });
  await page1.type("#editor", " (online edit)", { delay: 20 });
  await page1.waitForTimeout(1500);
  await page2.click("#offline-btn"); // back online
  await page2.waitForTimeout(1200);
  await page1.waitForTimeout(1500);
  const r1 = await page1.inputValue("#editor");
  const r2 = await page2.inputValue("#editor");
  console.log("[4] after reconnect tab1:", JSON.stringify(r1));
  console.log("[4] after reconnect tab2:", JSON.stringify(r2));
  if (r1 !== r2) throw new Error("OFFLINE/RECONNECT DID NOT CONVERGE: " + r1 + " vs " + r2);
  if (!r1.includes("(offline edit)") || !r1.includes("(online edit)")) {
    throw new Error("merged doc missing one side's edits: " + r1);
  }

  // 5) undo (S1: CRDT-aware undo/redo)
  await page1.click("#editor");
  await page1.press("#editor", "Control+z");
  await page1.waitForTimeout(400);
  const afterUndo1 = await page1.inputValue("#editor");
  console.log("[5] after undo tab1:", JSON.stringify(afterUndo1));
  if (afterUndo1 === r1) throw new Error("undo had no visible effect");

  // 5b) emoji + mid-document sequential insert — regression coverage for
  // REVIEW.md #3 (Lamport clocks) and #4 (code-point-aware Unicode)
  await page1.click("#editor");
  await page1.keyboard.press("Control+a");
  await page1.type("#editor", "cat", { delay: 20 });
  await page1.waitForTimeout(600);
  await page2.waitForTimeout(200);
  const beforeEmoji2 = await page2.inputValue("#editor");
  console.log("[5b] tab2 before emoji test:", JSON.stringify(beforeEmoji2));
  if (beforeEmoji2 !== "cat") throw new Error("setup for emoji test failed: " + beforeEmoji2);
  await page2.click("#editor");
  await page2.evaluate(() => document.getElementById("editor").setSelectionRange(1, 1));
  await page2.keyboard.insertText("😀Z");
  await page1.waitForTimeout(700);
  const emojiResult1 = await page1.inputValue("#editor");
  const emojiResult2 = await page2.inputValue("#editor");
  console.log("[5b] emoji result tab1:", JSON.stringify(emojiResult1));
  console.log("[5b] emoji result tab2:", JSON.stringify(emojiResult2));
  if (emojiResult1 !== emojiResult2) throw new Error("emoji edit did not converge: " + emojiResult1 + " vs " + emojiResult2);
  if (emojiResult2 !== "c😀Zat") throw new Error("sequential insert landed in the wrong place: " + emojiResult2 + " (expected c😀Zat)");

  // 6) light/dark theming renders without console errors (Phase 4 polish)
  await page1.emulateMedia({ colorScheme: "dark" });
  await page1.waitForTimeout(150);
  const darkBg = await page1.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page1.emulateMedia({ colorScheme: "light" });
  await page1.waitForTimeout(150);
  const lightBg = await page1.evaluate(() => getComputedStyle(document.body).backgroundColor);
  console.log("[6] dark bg:", darkBg, "| light bg:", lightBg);
  if (darkBg === lightBg) throw new Error("dark/light theme did not change background");

  if (errors.length) {
    console.log("CONSOLE/PAGE ERRORS:", errors);
    throw new Error("console errors detected");
  }

  console.log("\nALL BROWSER CHECKS PASSED");
  await browser.close();
})().catch((e) => {
  console.error("\nBROWSER TEST FAILED:", e);
  process.exit(1);
});
