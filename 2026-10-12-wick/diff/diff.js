#!/usr/bin/env node
// Differential harness: replays every case written by `wick fuzz` on V8 (Node's built-in WebAssembly
// engine) and compares each call's results / trap category, final memory hash and exported globals
// against what Wick computed.
"use strict";
const fs = require("fs");
const path = require("path");

const dir = process.argv[2];
if (!dir) {
  console.error("usage: node diff/diff.js DIR [--verbose]");
  process.exit(2);
}
const verbose = process.argv.includes("--verbose");

const f32buf = new Float32Array(1);
const u32buf = new Uint32Array(f32buf.buffer);
const f64buf = new Float64Array(1);
const u64buf = new BigUint64Array(f64buf.buffer);

function decodeArg(s) {
  const [ty, v] = [s.slice(0, 3), s.slice(4)];
  switch (ty) {
    case "i32": return parseInt(v, 10) | 0;
    case "i64": return BigInt(v);
    case "f32": if (v === "nan") return NaN; u32buf[0] = parseInt(v, 16); return f32buf[0];
    case "f64": if (v === "nan") return NaN; u64buf[0] = BigInt("0x" + v); return f64buf[0];
  }
  throw new Error("bad arg " + s);
}

// Encode a JS value returned by V8 given the Wick-side expected string (which carries the type).
function encodeLike(expected, v) {
  const ty = expected.slice(0, 3);
  switch (ty) {
    case "i32": return "i32:" + (v | 0);
    case "i64": return "i64:" + BigInt.asIntN(64, v).toString();
    case "f32":
      if (Number.isNaN(v)) return "f32:nan";
      f32buf[0] = v; return "f32:" + u32buf[0].toString(16).padStart(8, "0");
    case "f64":
      if (Number.isNaN(v)) return "f64:nan";
      f64buf[0] = v; return "f64:" + u64buf[0].toString(16).padStart(16, "0");
  }
  throw new Error("bad type " + expected);
}

function trapCategory(e) {
  const m = String(e && e.message);
  if (/unreachable/i.test(m)) return "unreachable";
  if (/divide by zero|remainder by zero/i.test(m)) return "div_zero";
  if (/unrepresentable|integer overflow/i.test(m)) return "int_overflow_or_conv";
  if (/float unrepresentable|invalid conversion/i.test(m)) return "int_overflow_or_conv";
  if (/memory access out of bounds|out of bounds/i.test(m) && !/table/i.test(m)) return "memory_oob";
  if (/table index is out of bounds|table.*out of bounds/i.test(m)) return "table_oob";
  if (/null function|signature mismatch|indirect/i.test(m)) return "indirect";
  if (/call stack|stack overflow/i.test(m)) return "stack";
  return "other:" + m;
}

// Wick distinguishes NaN-vs-overflow on trunc; V8 reports both identically, so fold them.
function norm(cat) {
  return cat === "conv" ? "int_overflow_or_conv" : cat;
}

function fnv32(bytes) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < bytes.length; i++) {
    h ^= bytes[i];
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

const files = fs.readdirSync(dir).filter((f) => /^case\d+\.json$/.test(f)).sort((a, b) => parseInt(a.slice(4)) - parseInt(b.slice(4)));
let ok = 0, skipped = 0, bad = 0, calls = 0, traps = 0;
const failures = [];

for (const jf of files) {
  const expect = JSON.parse(fs.readFileSync(path.join(dir, jf), "utf8"));
  if (expect.skip) { skipped++; continue; }
  const wasmPath = path.join(dir, jf.replace(".json", ".wasm"));
  const problems = [];
  let inst;
  try {
    inst = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(wasmPath)), {});
  } catch (e) {
    failures.push({ file: jf, problems: ["V8 rejected the module: " + e.message] });
    bad++;
    continue;
  }
  for (const [i, c] of expect.calls.entries()) {
    calls++;
    let got, gotTrap = null;
    try {
      got = inst.exports[c.fn](...c.args.map(decodeArg));
    } catch (e) {
      gotTrap = norm(trapCategory(e));
    }
    if (c.trap) {
      traps++;
      const want = norm(c.trap);
      if (gotTrap === null) problems.push(`call #${i} ${c.fn}(${c.args}): Wick trapped (${want}) but V8 returned ${JSON.stringify(got, (k, v) => typeof v === "bigint" ? v.toString() : v)}`);
      else if (gotTrap !== want) problems.push(`call #${i} ${c.fn}(${c.args}): trap kind differs: Wick=${want} V8=${gotTrap}`);
    } else {
      if (gotTrap !== null) { problems.push(`call #${i} ${c.fn}(${c.args}): Wick returned ${c.ret} but V8 trapped (${gotTrap})`); continue; }
      const arr = c.ret.length === 0 ? [] : c.ret.length === 1 ? [got] : got;
      const enc = c.ret.map((e, k) => encodeLike(e, arr[k]));
      if (JSON.stringify(enc) !== JSON.stringify(c.ret)) problems.push(`call #${i} ${c.fn}(${c.args}): Wick=${c.ret} V8=${enc}`);
    }
  }
  const mem = inst.exports.mem;
  const bytes = new Uint8Array(mem.buffer);
  if (mem.buffer.byteLength / 65536 !== expect.pages) problems.push(`memory pages: Wick=${expect.pages} V8=${mem.buffer.byteLength / 65536}`);
  else if (fnv32(bytes) !== expect.hash) problems.push(`final memory differs (hash Wick=${expect.hash.toString(16)} V8=${fnv32(bytes).toString(16)})`);
  expect.globals.forEach((g, k) => {
    const v = inst.exports["g" + k].value;
    const e = encodeLike(g, v);
    if (e !== g) problems.push(`global g${k}: Wick=${g} V8=${e}`);
  });
  if (problems.length) { bad++; failures.push({ file: jf, problems }); } else ok++;
}

console.log(`cases: ${files.length}  agree: ${ok}  skipped: ${skipped}  DISAGREE: ${bad}  (calls compared: ${calls}, of which traps: ${traps})`);
for (const f of failures.slice(0, verbose ? 1000 : 10)) {
  console.log(`\n✗ ${f.file}`);
  for (const p of f.problems.slice(0, 6)) console.log("   " + p);
}
process.exit(bad ? 1 : 0);
