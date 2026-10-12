#!/usr/bin/env node
// Validator/decoder differential test. Takes valid modules produced by `wick fuzz`, corrupts them
// in many ways, and checks that Wick (decode + validate) and V8 (WebAssembly.validate) agree on
// accept/reject. Wick must also never panic on any input, accepted or not.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const [srcDir, countArg, seedArg] = process.argv.slice(2);
if (!srcDir) {
  console.error("usage: node diff/validate_diff.js SRCDIR [MUTANTS_PER_MODULE=20] [SEED=1] [--show-all]");
  process.exit(2);
}
const asIs = process.argv.includes("--as-is"); // files are already mutants (see `wick mutants`)
const perModule = asIs ? 0 : parseInt(countArg || "20", 10);
let seed = parseInt(seedArg || "1", 10) >>> 0;
const showAll = process.argv.includes("--show-all");
function rnd() { // xorshift32
  seed ^= seed << 13; seed >>>= 0; seed ^= seed >>> 17; seed ^= seed << 5; seed >>>= 0;
  return seed / 4294967296;
}
const ri = (n) => Math.floor(rnd() * n);

function mutate(buf) {
  let b = Buffer.from(buf);
  const n = 1 + (rnd() < 0.3 ? ri(3) : 0);
  for (let k = 0; k < n; k++) {
    const kind = ri(7);
    const pos = 8 + ri(Math.max(1, b.length - 8)); // keep the header intact most of the time
    switch (kind) {
      case 0: b[pos] ^= 1 << ri(8); break;                       // bit flip
      case 1: b[pos] = ri(256); break;                           // random byte
      case 2: b = Buffer.concat([b.subarray(0, pos), b.subarray(pos + 1)]); break; // delete
      case 3: b = Buffer.concat([b.subarray(0, pos), Buffer.from([ri(256)]), b.subarray(pos)]); break; // insert
      case 4: { const q = 8 + ri(Math.max(1, b.length - 8)); const t = b[pos]; b[pos] = b[q]; b[q] = t; break; } // swap
      case 5: b[pos] = [0x00, 0x01, 0x0b, 0x0c, 0x0d, 0x1a, 0x1b, 0x20, 0x21, 0x41, 0x6a, 0x7f, 0x7e, 0x40][ri(14)]; break; // interesting bytes
      case 6: if (b.length > 20) b = b.subarray(0, 8 + ri(b.length - 8)); break; // truncate
    }
  }
  return b;
}

const sources = fs.readdirSync(srcDir).filter((f) => f.endsWith(".wasm")).sort();
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wick-mut-"));
const mutants = [];
let idx = 0;
for (const f of sources) {
  const orig = fs.readFileSync(path.join(srcDir, f));
  // the unmutated module must be accepted by both
  const names = asIs ? [[`m${idx++}.wasm`, orig]] : [[`m${idx++}_orig.wasm`, orig]];
  for (let k = 0; k < perModule; k++) names.push([`m${idx++}.wasm`, mutate(orig)]);
  for (const [name, bytes] of names) {
    fs.writeFileSync(path.join(tmp, name), bytes);
    mutants.push({ name, bytes });
  }
}
const r = spawnSync(path.join(__dirname, "..", "target", "release", "wick"), ["check-batch", tmp], { encoding: "utf8", maxBuffer: 1 << 30 });
if (r.status !== 0) { console.error("wick check-batch failed:", r.stderr); process.exit(2); }
const verdicts = new Map(r.stdout.trim().split("\n").map((l) => { const [n, ...v] = l.split("\t"); return [n, v.join("\t")]; }));

let agreeAccept = 0, agreeReject = 0, panics = 0, unsupported = 0;
const wickLax = [], wickStrict = [];
for (const m of mutants) {
  const v = verdicts.get(m.name) || "MISSING";
  const v8 = WebAssembly.validate(m.bytes);
  if (v.startsWith("REJECT decode") && /unknown opcode|multi-memory|unsupported 0xFC|unsupported (element|data) segment|invalid value type|invalid block type|unknown section id|invalid import kind|invalid export kind|table element type/.test(v) && v8) { unsupported++; continue; }
  if (v === "PANIC") { panics++; wickLax.push({ m, v, v8, why: "PANIC" }); continue; }
  const wick = v === "ACCEPT";
  if (wick && v8) agreeAccept++;
  else if (!wick && !v8) agreeReject++;
  else if (wick && !v8) wickLax.push({ m, v, v8 });
  else wickStrict.push({ m, v, v8 });
}
function v8Reason(bytes) { try { new WebAssembly.Module(bytes); return "?"; } catch (e) { return e.message.replace(/^WebAssembly\.Module\(\): /, "").slice(0, 160); } }
console.log(`mutants: ${mutants.length}  both-accept: ${agreeAccept}  both-reject: ${agreeReject}  panics: ${panics}  V8-only-features (post-MVP opcodes etc., expected): ${unsupported}`);
console.log(`Wick accepts but V8 rejects (validator too lax): ${wickLax.length}`);
console.log(`Wick rejects but V8 accepts (too strict / unsupported): ${wickStrict.length}`);
const show = (title, list) => {
  const seen = new Set();
  for (const x of list.slice(0, showAll ? 1000 : 400)) {
    const key = (x.v.replace(/\d+/g, "N") + "|" + v8Reason(x.m.bytes).replace(/@\+?\d+/g, "").replace(/\d+/g, "N"));
    if (seen.has(key)) continue;
    seen.add(key);
    if (seen.size > (showAll ? 100 : 12)) break;
    console.log(`  [${title}] ${x.m.name}: wick=${x.v}\n        v8=${v8Reason(x.m.bytes)}`);
  }
};
show("LAX", wickLax);
show("STRICT", wickStrict);
if (process.argv.includes("--keep")) console.log("mutants kept in", tmp);
else fs.rmSync(tmp, { recursive: true, force: true });
process.exit(panics || wickLax.length || wickStrict.length ? 1 : 0);
