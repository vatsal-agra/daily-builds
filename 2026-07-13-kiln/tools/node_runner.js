// Tiny harness used as the differential-testing oracle: load a .wasm file
// with Node's real, spec-compliant WebAssembly engine, call one exported
// function with the given arguments, and print the result(s) as JSON.
// Usage: node node_runner.js <module.wasm> <exportName> <arg1> <arg2> ...
"use strict";

const fs = require("fs");

async function main() {
  const [, , wasmPath, exportName, ...rawArgs] = process.argv;
  const bytes = fs.readFileSync(wasmPath);
  const imports = {
    env: {
      print: (x) => { console.log(typeof x === "bigint" ? x.toString() : x); },
    },
    wasi_snapshot_preview1: {
      fd_write: (fd, iovsPtr, iovsLen, nwrittenPtr) => {
        const mem = new Uint8Array(instanceMemory());
        const view = new DataView(mem.buffer);
        if (fd !== 1 && fd !== 2) return 8;
        let total = 0;
        let out = "";
        for (let i = 0; i < iovsLen; i++) {
          const base = iovsPtr + i * 8;
          const bufPtr = view.getUint32(base, true);
          const bufLen = view.getUint32(base + 4, true);
          out += Buffer.from(mem.buffer, bufPtr, bufLen).toString("utf8");
          total += bufLen;
        }
        (fd === 1 ? process.stdout : process.stderr).write(out);
        view.setUint32(nwrittenPtr, total, true);
        return 0;
      },
    },
  };
  let instanceMemory = () => { throw new Error("memory accessed before instantiation"); };
  const { instance } = await WebAssembly.instantiate(bytes, imports);
  if (instance.exports.memory) {
    instanceMemory = () => instance.exports.memory.buffer;
  }
  const fn = instance.exports[exportName];
  if (typeof fn !== "function") {
    console.error(JSON.stringify({ error: `export ${exportName} is not callable (or missing)` }));
    process.exit(1);
  }
  const args = rawArgs.map((a) => {
    if (a.includes(".")) return Number(a);
    const n = BigInt(a);
    return n > BigInt(Number.MAX_SAFE_INTEGER) || n < BigInt(Number.MIN_SAFE_INTEGER) ? n : Number(a);
  });
  let result;
  try {
    result = fn(...args);
  } catch (e) {
    console.log(JSON.stringify({ trap: String(e && e.message || e) }));
    return;
  }
  const normalize = (v) => (typeof v === "bigint" ? v.toString() : v);
  const values = Array.isArray(result) ? result.map(normalize) : result === undefined ? [] : [normalize(result)];
  console.log(JSON.stringify({ results: values }));
}

main().catch((e) => {
  console.log(JSON.stringify({ trap: String(e && e.message || e) }));
});
