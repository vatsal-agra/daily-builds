#!/usr/bin/env node
// Replays the hand-written conformance corpus (tests/corpus/*.wat) on V8, so that the expected
// values in the corpus are themselves checked against an independent engine.
// Wick assembles each module (`wick asm --no-validate`); V8 compiles and runs the same directives.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.join(__dirname, "..");
const wick = path.join(root, "target", "release", "wick");
const corpusDir = path.join(root, "tests", "corpus");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wick-corpus-"));

const f32 = new Float32Array(1), u32 = new Uint32Array(f32.buffer);
const f64 = new Float64Array(1), u64 = new BigUint64Array(f64.buffer);

function parseTyped(s) {
  const i = s.indexOf(":");
  const ty = s.slice(0, i), v = s.slice(i + 1);
  const num = (txt, wide) => {
    if (txt === "nan") return NaN;
    if (txt === "inf") return Infinity;
    if (txt === "-inf") return -Infinity;
    if (txt === "-0") return -0;
    if (txt.startsWith("bits:")) {
      if (ty === "f32") { u32[0] = Number(BigInt(txt.slice(5))); return f32[0]; }
      u64[0] = BigInt(txt.slice(5)); return f64[0];
    }
    return Number(txt);
  };
  switch (ty) {
    case "i32": return { ty, v: Number(BigInt.asIntN(32, BigInt(v))) };
    case "i64": return { ty, v: BigInt.asIntN(64, BigInt(v)) };
    case "f32": return { ty, v: num(v) };
    case "f64": return { ty, v: num(v) };
  }
  throw new Error("bad typed value " + s);
}
function same(want, got) {
  if (want.ty === "i32") return (got | 0) === want.v;
  if (want.ty === "i64") return BigInt.asIntN(64, got) === want.v;
  if (Number.isNaN(want.v)) return Number.isNaN(got);
  if (want.ty === "f32") { f32[0] = got; const a = u32[0]; f32[0] = want.v; return a === u32[0]; }
  f64[0] = got; const a = u64[0]; f64[0] = want.v; return a === u64[0];
}
function category(e) {
  const m = String(e && e.message);
  if (/unreachable/i.test(m)) return "unreachable";
  if (/divide by zero|remainder by zero/i.test(m)) return "div_zero";
  if (/unrepresentable|integer overflow/i.test(m)) return "int_overflow_or_conv";
  if (/table index is out of bounds/i.test(m)) return "table_oob";
  if (/out of bounds/i.test(m)) return "memory_oob";
  if (/null function|signature mismatch|indirect/i.test(m)) return "indirect";
  if (/call stack|stack overflow/i.test(m)) return "stack";
  return "other:" + m;
}
const norm = (c) => (c === "conv" ? "int_overflow_or_conv" : c);

const imports = {
  env: { print_i32() {}, print_i64() {}, print_f32() {}, print_f64() {}, print_char() {} },
};

let checked = 0, failed = 0, skipped = 0;
const fail = (where, msg) => { failed++; console.log(`✗ ${where}: ${msg}`); };

for (const file of fs.readdirSync(corpusDir).filter((f) => f.endsWith(".wat")).sort()) {
  const src = fs.readFileSync(path.join(corpusDir, file), "utf8");
  const chunks = [[]];
  for (const line of src.split("\n")) {
    if (line.trimStart().startsWith(";; ---")) chunks.push([]);
    else chunks[chunks.length - 1].push(line);
  }
  chunks.forEach((lines, ci) => {
    const text = lines.join("\n");
    if (!text.trim()) return;
    const where = `${file}[module ${ci}]`;
    const dirs = lines.map((l) => l.trim()).filter((l) => /^;; (assert|trap|global|invalid|malformed|link-error|init-trap) /.test(l)).map((l) => l.slice(3));
    if (dirs.some((d) => d.startsWith("malformed "))) { skipped++; return; }
    const wat = path.join(tmp, "m.wat"), wasm = path.join(tmp, "m.wasm");
    fs.writeFileSync(wat, text);
    const r = spawnSync(wick, ["asm", wat, "-o", wasm, "--no-validate"], { encoding: "utf8" });
    if (r.status !== 0) return fail(where, "Wick could not assemble: " + r.stderr.trim());
    const bytes = fs.readFileSync(wasm);
    if (dirs.some((d) => d.startsWith("invalid "))) {
      checked++;
      if (WebAssembly.validate(bytes)) fail(where, "V8 accepts a module the corpus marks invalid");
      return;
    }
    let inst;
    try {
      inst = new WebAssembly.Instance(new WebAssembly.Module(bytes), imports);
    } catch (e) {
      checked++;
      const d = dirs.find((d) => d.startsWith("init-trap ") || d.startsWith("link-error "));
      if (!d) return fail(where, "V8 failed to instantiate: " + e.message);
      if (d.startsWith("init-trap ") && !(e instanceof WebAssembly.RuntimeError)) fail(where, `expected a trap, V8 threw ${e.constructor.name}: ${e.message}`);
      if (d.startsWith("link-error ") && e instanceof WebAssembly.RuntimeError) fail(where, "expected link error, V8 trapped: " + e.message);
      return;
    }
    if (dirs.some((d) => d.startsWith("init-trap ") || d.startsWith("link-error "))) {
      // memory/table size limits are engine-specific; only flag when it is not a size-limit case
      if (dirs.some((d) => /exceeds|limit/.test(d))) { skipped++; return; }
      return fail(where, "instantiation succeeded on V8 but the corpus expects failure");
    }
    for (const d of dirs) {
      const [kind, rest] = [d.slice(0, d.indexOf(" ")), d.slice(d.indexOf(" ") + 1)];
      const [lhs, rhs = ""] = rest.split("=>").map((s) => s.trim());
      const toks = lhs.split(/\s+/);
      const name = toks[0];
      checked++;
      if (kind === "global") {
        const want = parseTyped(rhs);
        if (!same(want, inst.exports[name].value)) fail(where, `${d}: V8 gave ${inst.exports[name].value}`);
        continue;
      }
      if (kind !== "assert" && kind !== "trap") continue;
      const args = toks.slice(1).map(parseTyped).map((a) => a.v);
      let got, err = null;
      try { got = inst.exports[name](...args); } catch (e) { err = e; }
      if (kind === "trap") {
        if (!err) fail(where, `${d}: V8 returned ${got}`);
        else if (norm(category(err)) !== norm(rhs)) fail(where, `${d}: V8 trapped with ${category(err)} (${err.message})`);
      } else {
        const want = rhs.split(/\s+/).filter(Boolean).map(parseTyped);
        if (err) { fail(where, `${d}: V8 threw ${err.message}`); continue; }
        const arr = want.length === 1 ? [got] : want.length === 0 ? [] : got;
        if (want.length !== arr.length || want.some((w, i) => !same(w, arr[i]))) fail(where, `${d}: V8 gave ${arr}`);
      }
    }
  });
}
fs.rmSync(tmp, { recursive: true, force: true });
console.log(`corpus directives checked on V8: ${checked}, failed: ${failed}, skipped (V8-irrelevant): ${skipped}`);
process.exit(failed ? 1 : 0);
