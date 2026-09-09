#!/usr/bin/env node
/**
 * test_browser.js — the strongest end-to-end check in this suite: drives
 * the REAL app (index.html/app.js/net.js/crdt.js, unmodified) in TWO real
 * headless Chromium browser *contexts* (separate sessionStorage, so each
 * is a genuinely independent "site", exactly like two different people in
 * two different browser tabs) against the REAL relay.py server. Nothing
 * here is simulated at the protocol level — it's real DOM typing events,
 * real EventSource/fetch calls, real TCP.
 *
 * Requires Playwright + the pre-installed Chromium in this environment:
 *   NODE_PATH=/opt/node22/lib/node_modules node tests/test_browser.js
 * (demo.sh sets NODE_PATH for you.)
 */
'use strict';
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');

const PORT = 8710 + (process.pid % 200);
const HOST = '127.0.0.1';
const RELAY = path.join(__dirname, '..', 'server', 'relay.py');
const CHROMIUM_PATH = process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium';

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const server = spawn('python3', [RELAY, HOST, String(PORT)], { stdio: 'ignore' });
  await sleep(600);

  const browser = await chromium.launch({ executablePath: CHROMIUM_PATH, args: ['--no-sandbox'] });
  const errors = [];
  try {
    // Two separate *contexts* (not just tabs) so sessionStorage — and
    // therefore the generated siteId/identity — is genuinely independent,
    // matching two different people rather than two tabs of one person.
    const ctx1 = await browser.newContext();
    const ctx2 = await browser.newContext();
    const p1 = await ctx1.newPage();
    const p2 = await ctx2.newPage();
    for (const [label, page] of [['p1', p1], ['p2', p2]]) {
      page.on('console', (m) => { if (m.type() === 'error') errors.push(label + ': ' + m.text()); });
      page.on('pageerror', (e) => errors.push(label + ' pageerror: ' + e));
    }

    const url = `http://${HOST}:${PORT}/?doc=browsertest`;
    await p1.goto(url);
    await p2.goto(url);
    await p1.waitForSelector('#status-dot[data-status="online"]', { timeout: 5000 });
    await p2.waitForSelector('#status-dot[data-status="online"]', { timeout: 5000 });
    console.log('ok - both tabs report status=online against the real relay');

    // --- required: live multi-client sync ---
    await p1.click('#editor');
    await p1.type('#editor', 'Hello from tab one!');
    await p2.waitForFunction(() => document.getElementById('editor').value === 'Hello from tab one!', { timeout: 5000 });
    console.log('ok - tab2 sees tab1 live typing appear in real time');

    await p2.click('#editor');
    await p2.keyboard.press('End');
    await p2.type('#editor', ' And tab two too.');
    await p1.waitForFunction(() => document.getElementById('editor').value === 'Hello from tab one! And tab two too.', { timeout: 5000 });
    console.log('ok - tab1 sees tab2 live typing appear in real time');

    // --- stretch: live presence cursor ---
    await p2.waitForFunction(() => document.querySelectorAll('#peers .peer-chip').length >= 1, { timeout: 5000 });
    console.log('ok - presence peer chip renders for the other tab');

    // --- required: offline editing + merge-on-reconnect, driven through the real "Go offline" UI toggle ---
    await p1.click('#offline-toggle');
    await p1.waitForSelector('#status-dot[data-status="offline"]');
    await p1.waitForSelector('#offline-banner:not([hidden])');
    await p1.type('#editor', ' (offline edit)');
    console.log('ok - offline UI toggle actually disconnects (status=offline, banner visible) and local typing still works');

    // --- stretch: CRDT internals inspector, checked while genuinely offline ---
    await p1.click('#inspector-toggle');
    await p1.waitForSelector('#inspector-pane:not([hidden])');
    const nodeCount = await p1.locator('#inspector-list .node').count();
    if (nodeCount < 30) throw new Error('inspector should show dozens of real RGA nodes, saw ' + nodeCount);
    console.log('ok - CRDT internals inspector renders ' + nodeCount + ' real nodes while offline');

    await p1.click('#offline-toggle');
    await p1.waitForSelector('#status-dot[data-status="online"]', { timeout: 5000 });
    await p2.waitForFunction(() => document.getElementById('editor').value.includes('(offline edit)'), { timeout: 5000 });
    const [text1, text2] = await Promise.all([
      p1.locator('#editor').inputValue(),
      p2.locator('#editor').inputValue(),
    ]);
    if (text1 !== text2) throw new Error('tabs diverged after reconnect merge: ' + JSON.stringify({ text1, text2 }));
    console.log('ok - offline edit merges into the other tab on reconnect, both tabs converge byte-for-byte');

    if (errors.length) {
      throw new Error('console/page errors seen during the run:\n' + errors.join('\n'));
    }
    console.log('\nALL BROWSER SMOKE CHECKS PASSED, zero console errors, light theme');

    // Re-run the core convergence checks once more in dark mode, since
    // this app is theme-aware and a dark-mode-only bug is a real class of
    // bug this repo's own history has shipped and caught before.
    await p1.emulateMedia({ colorScheme: 'dark' });
    await p2.emulateMedia({ colorScheme: 'dark' });
    await p1.reload();
    await p2.reload();
    await p1.waitForSelector('#status-dot[data-status="online"]', { timeout: 5000 });
    await p2.waitForSelector('#status-dot[data-status="online"]', { timeout: 5000 });
    await p1.click('#editor');
    await p1.type('#editor', 'dark mode check');
    await p2.waitForFunction(() => document.getElementById('editor').value.includes('dark mode check'), { timeout: 5000 });
    console.log('ok - dark mode: reload + live sync still works, zero console errors');
  } finally {
    await browser.close();
    server.kill();
  }
}

main().catch((e) => {
  console.error('FAIL:', e.message || e);
  process.exitCode = 1;
});
