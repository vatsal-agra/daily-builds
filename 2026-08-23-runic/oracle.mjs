// oracle.mjs — runs a compiled .wasm module through Node's *native*,
// independently-implemented WebAssembly engine (V8's), and reports results
// as JSON. This is the "third party" half of the dual-oracle verifier in
// verify.py: it never touches any code from this project's compiler or
// interpreter, so agreement between it and our own interpreter is a real
// correctness signal, not a tautology.
//
// Usage: node oracle.mjs <path-to-wasm>   (reads a JSON call plan on stdin)
// Call plan: {"calls": [{"func": "fib", "args": [10]}, ...], "readMemoryBytes": 40}
// Output: {"results": [{"func","args","value"|"trap"}], "memory": [...]|null}

import { readFileSync } from "node:fs";

async function main() {
  const wasmPath = process.argv[2];
  if (!wasmPath) {
    console.error(JSON.stringify({ error: "usage: node oracle.mjs <wasm-file> < plan.json" }));
    process.exit(2);
  }

  let plan;
  try {
    const stdinText = readFileSync(0, "utf-8");
    plan = JSON.parse(stdinText);
  } catch (e) {
    console.error(JSON.stringify({ error: `failed to read/parse call plan: ${e.message}` }));
    process.exit(2);
  }

  const bytes = readFileSync(wasmPath);

  let instance;
  try {
    ({ instance } = await WebAssembly.instantiate(bytes));
  } catch (e) {
    // A load/validate failure is itself a meaningful oracle result: it means
    // the encoder produced bytes a real engine rejects.
    console.log(JSON.stringify({ loadError: `${e.name}: ${e.message}` }));
    return;
  }

  const results = [];
  for (const call of plan.calls || []) {
    const fn = instance.exports[call.func];
    if (typeof fn !== "function") {
      results.push({ func: call.func, args: call.args, error: `no such export: ${call.func}` });
      continue;
    }
    try {
      const value = fn(...call.args);
      results.push({ func: call.func, args: call.args, value });
    } catch (e) {
      results.push({ func: call.func, args: call.args, trap: `${e.name}: ${e.message}` });
    }
  }

  let memory = null;
  if (plan.readMemoryBytes && instance.exports.memory) {
    const view = new Uint8Array(instance.exports.memory.buffer, 0, plan.readMemoryBytes);
    memory = Array.from(view);
  }

  console.log(JSON.stringify({ results, memory }));
}

main();
