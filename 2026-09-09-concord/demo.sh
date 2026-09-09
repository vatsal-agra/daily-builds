#!/usr/bin/env bash
# Concord end-to-end verification script.
#
# Exercises every required feature (R1-R4) and every stretch feature
# (S1-S2), plus the full test suite (engine fuzz, server integration,
# relay unit tests, and a real headless-browser run of the actual app),
# and prints a final PASS/FAIL tally. Exits non-zero if anything fails.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

check() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  [PASS] $desc"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "=================================================================="
echo "Concord verification"
echo "=================================================================="

echo
echo "--- Core engine: property-fuzz convergence suite ---"
if node tests/fuzz_convergence.js 3000 > "$WORKDIR/fuzz.log" 2>&1; then
    N=$(grep -oE "^OK: [0-9]+ trials" "$WORKDIR/fuzz.log" | grep -oE "[0-9]+")
    echo "  [PASS] $N randomized convergence trials, all replicas byte-identical"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] convergence fuzz suite -- see below"
    tail -40 "$WORKDIR/fuzz.log"
    FAIL=$((FAIL + 1))
fi

echo
echo "--- R1: RGA sequence CRDT engine (deterministic concurrent-insert ordering) ---"
check "two sites concurrently inserting at the same position converge to identical text" node -e "
const { RGA } = require('./client/crdt.js');
const a = new RGA('a'), b = new RGA('b');
a.localInsert(0, 'hello ').forEach(op => b.applyRemote(op));
const opsA = a.localInsert(a.length(), 'world');
const opsB = b.localInsert(b.length(), 'there');
opsA.forEach(op => b.applyRemote(op));
opsB.forEach(op => a.applyRemote(op));
process.exit(a.text() === b.text() && a.text().length === 'hello '.length + 'world'.length + 'there'.length ? 0 : 1);
"
check "delete tombstones rather than corrupts a concurrent insert at the same spot" node -e "
const { RGA } = require('./client/crdt.js');
const a = new RGA('a'), b = new RGA('b');
a.localInsert(0, 'abc').forEach(op => b.applyRemote(op));
const del = a.localDelete(1, 1); // delete 'b'
const ins = b.localInsert(1, 'X'); // insert 'X' at the same spot, concurrently
del.forEach(op => b.applyRemote(op));
ins.forEach(op => a.applyRemote(op));
process.exit(a.text() === b.text() && a.text().length === 3 ? 0 : 1);
"
check "out-of-range positions no longer crash the replica (regression, see REVIEW.md #2)" node -e "
const { RGA } = require('./client/crdt.js');
const a = new RGA('a');
a.localInsert(0, 'abc');
a.localInsert(-5, 'x');
a.localInsert(9999, 'y');
process.exit(0);
"
check "a 5,000-character paste completes in well under a second (regression, see REVIEW.md #7)" node -e "
const { RGA } = require('./client/crdt.js');
const a = new RGA('a');
const t0 = Date.now();
a.localInsert(0, 'x'.repeat(5000));
const ms = Date.now() - t0;
process.stderr.write('(' + ms + 'ms) ');
process.exit(ms < 1000 && a.length() === 5000 ? 0 : 1);
"

echo
echo "--- R2 + R3 + R4: live sync, causal buffering, offline + merge-on-reconnect (real relay.py, real HTTP/SSE) ---"
if node tests/test_integration.js > "$WORKDIR/integration.log" 2>&1; then
    echo "  [PASS] live sync + offline/merge-on-reconnect against the real relay"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] integration suite -- see below"
    tail -40 "$WORKDIR/integration.log"
    FAIL=$((FAIL + 1))
fi
check "causal buffering: an op delivered before its dependency doesn't corrupt or drop it" node -e "
const { RGA } = require('./client/crdt.js');
const a = new RGA('a');
const ops = a.localInsert(0, 'hello');
const b = new RGA('b');
// deliver in REVERSE order: dependency arrives last on purpose
ops.slice().reverse().forEach(op => b.applyRemote(op));
process.exit(b.text() === 'hello' && b.pendingCount() === 0 ? 0 : 1);
"

echo
echo "--- Relay HTTP API: validation, atomic batches, SSE backlog/live replay ---"
if python3 -m unittest tests.test_relay -v > "$WORKDIR/relay.log" 2>&1; then
    N=$(grep -oE "Ran [0-9]+ test" "$WORKDIR/relay.log" | grep -oE "[0-9]+")
    echo "  [PASS] relay unit suite ($N tests green)"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] relay unit suite -- see below"
    tail -40 "$WORKDIR/relay.log"
    FAIL=$((FAIL + 1))
fi

echo
echo "--- Narrated walkthrough (S1+S2 context, human-readable) ---"
check "examples/two_clients_demo.js runs end-to-end against a real relay" node examples/two_clients_demo.js

echo
echo "--- Full app: S1 (multi-cursor presence), S2 (CRDT internals inspector), and every required feature through the real UI ---"
if command -v node >/dev/null 2>&1 && [ -d /opt/node22/lib/node_modules/playwright ]; then
    if env NODE_PATH=/opt/node22/lib/node_modules node tests/test_browser.js > "$WORKDIR/browser.log" 2>&1; then
        N=$(grep -c "^ok - " "$WORKDIR/browser.log")
        echo "  [PASS] real two-tab headless-Chromium run ($N checks, zero console errors, light + dark)"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] headless-browser suite -- see below"
        tail -60 "$WORKDIR/browser.log"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  [SKIP] headless browser check (node/playwright not available in this environment)"
fi

echo
echo "=================================================================="
echo "RESULT: $PASS passed, $FAIL failed"
echo "=================================================================="
[ "$FAIL" -eq 0 ]
