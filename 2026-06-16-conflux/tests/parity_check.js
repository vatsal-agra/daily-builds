// Python<->JS parity harness.
// Usage: node parity_check.js <solver.js> <cases.json> <py_verdicts.json>
// cases.json: [{n, clauses:[[..],..]}, ...]
// py_verdicts.json: ["SAT"|"UNSAT", ...] aligned with cases
// Prints: "mismatches=<k> badmodels=<m>"
const path = process.argv[2], casesPath = process.argv[3], pyPath = process.argv[4];
const C = require(path);
const fs = require("fs");
const cases = JSON.parse(fs.readFileSync(casesPath));
const py = JSON.parse(fs.readFileSync(pyPath));
let mism = 0, bad = 0;
for (let i = 0; i < cases.length; i++) {
  const { result, model } = C.solveCNF(cases[i].n, cases[i].clauses, {});
  if (result !== py[i]) { mism++; if (mism <= 5) console.error("mismatch idx", i, "js", result, "py", py[i]); }
  if (result === "SAT" && !C.isSatisfied(cases[i].n, cases[i].clauses, model)) bad++;
}
console.log("mismatches=" + mism + " badmodels=" + bad);
