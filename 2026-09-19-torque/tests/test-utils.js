// test-utils.js -- a hand-rolled assert + runner, deliberately with zero
// npm dependencies (matches the engine itself: this whole project runs on
// nothing but the Node/browser standard library).
'use strict';

let current = null;
const results = [];

function test(name, fn) {
  current = { name: name, failures: [] };
  try {
    fn();
  } catch (err) {
    current.failures.push(err.message || String(err));
  }
  results.push(current);
  current = null;
}

function fail(message) {
  throw new Error(message);
}

function assert(cond, message) {
  if (!cond) fail(message || 'assertion failed');
}

function assertClose(actual, expected, tol, message) {
  tol = tol === undefined ? 1e-6 : tol;
  if (Math.abs(actual - expected) > tol) {
    fail(
      (message ? message + ': ' : '') +
        `expected ${expected} +/- ${tol}, got ${actual} (diff ${Math.abs(actual - expected)})`
    );
  }
}

function summarize(label) {
  const failed = results.filter((r) => r.failures.length > 0);
  console.log(`\n== ${label}: ${results.length - failed.length}/${results.length} passed ==`);
  for (const r of failed) {
    console.log(`  FAIL: ${r.name}`);
    for (const f of r.failures) console.log(`    - ${f}`);
  }
  return failed.length === 0;
}

function reset() {
  results.length = 0;
}

module.exports = { test, assert, assertClose, fail, summarize, reset };
