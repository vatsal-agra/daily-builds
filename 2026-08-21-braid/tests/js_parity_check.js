// Companion to tests/test_js_parity.py: replays the exact same op
// histories the Python side generated (via crdt/rga.py) through the
// JavaScript port (server/static/rga.js) and checks the resulting text
// matches byte-for-byte. Run standalone: node tests/js_parity_check.js <cases.json>
"use strict";
const fs = require("fs");
const path = require("path");
const { RGA, CausalDeliveryBuffer } = require(path.join(__dirname, "..", "server", "static", "rga.js"));

function mulberry32(seed) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function shuffle(arr, rng) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
}

const casesPath = process.argv[2];
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));

let allOk = true;
for (const c of cases) {
  const rng = mulberry32(c.seed + 1000);
  const doc = new RGA("js-checker");
  const buf = new CausalDeliveryBuffer((id) => doc.hasId(id));
  const ops = c.ops.map((op) => ({ ...op }));
  shuffle(ops, rng);
  for (const op of ops) buf.submit(op, (o) => doc.applyRemote(o));
  if (buf.size !== 0) {
    console.log(`seed ${c.seed}: ${buf.size} ops never became deliverable`);
    allOk = false;
    continue;
  }
  const actual = doc.text();
  if (actual !== c.expected_text) {
    console.log(`seed ${c.seed}: MISMATCH python=${JSON.stringify(c.expected_text)} js=${JSON.stringify(actual)}`);
    allOk = false;
  }
}
console.log(allOk ? `PARITY_OK ${cases.length} cases` : "PARITY_FAILED");
process.exit(allOk ? 0 : 1);
