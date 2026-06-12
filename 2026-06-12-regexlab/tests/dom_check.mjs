// Browser-side check: load a generated visualizer page in headless Chromium,
// type test strings, and print the page's verdicts as JSON for the Python
// test harness to compare against the Python engine.
//
// usage: node dom_check.mjs <file.html> <cases.json>
//   cases.json: [{"text": "...", "mode": "search|match|fullmatch"}, ...]
// output: JSON list of {text, mode, matched, span, steps, liveAtEnd, dfa}

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const pw = require("/opt/node22/lib/node_modules/playwright");

const [, , htmlPath, casesJson] = process.argv;
const cases = JSON.parse(readFileSync(casesJson, "utf-8"));

const browser = await pw.chromium.launch();
const page = await browser.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e)));
await page.goto("file://" + htmlPath);

const results = [];
for (const c of cases) {
  await page.selectOption("#mode", c.mode);
  await page.fill("#text", c.text);
  const r = await page.evaluate(() => {
    const tr = state.trace;
    return {
      matched: tr.matched !== null,
      span: tr.matched ? [tr.matched[0], tr.matched[1]] : null,
      groups: tr.matched
        ? Array.from({ length: DATA.ngroups }, (_, i) => {
            const a = tr.matched[2 * (i + 1)], b = tr.matched[2 * (i + 1) + 1];
            return a === null || b === null ? null : [a, b];
          })
        : null,
      steps: tr.steps.length,
      dfa: state.dtrace ? state.dtrace.verdict : null,
    };
  });
  results.push({ text: c.text, mode: c.mode, ...r });
}

// drive the stepper to make sure controls work (fresh input starts at step 1)
await page.fill("#text", cases[0].text);
const s0 = await page.textContent("#status");
await page.click("#bn");
const s1 = await page.textContent("#status");
const stepperWorks = s0.includes("step 1/") && s1.includes("step 2/");

await browser.close();
console.log(JSON.stringify({ results, stepperWorks, pageErrors }));
