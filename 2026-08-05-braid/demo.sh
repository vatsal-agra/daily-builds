#!/usr/bin/env bash
# demo.sh — exercises every feature Braid ships, end to end, and exits
# non-zero if anything failed. Run this after any change.
#
#   R1  from-scratch RGA CRDT engine               -> tests/test_rga.py
#   R2  adversarial network sim + convergence proof -> tests/test_network_convergence.py, `cli.py sweep`
#   R3  real-time multi-peer collaborative editor   -> tests/browser_test.js (live server + Chromium)
#   R4  headless CLI simulation & scripted scenario -> `cli.py scenario`
#   S1  CRDT-aware undo/redo                        -> tests/test_site.py, browser_test.js step 5
#   S2  live presence + network-chaos panel         -> browser_test.js steps 3-4
#
# plus tests/test_server.py (server relay/validation/path-traversal),
# tests/test_cli.py (argument validation), and tests/test_parity.py
# (Python<->JS engine parity, skipped cleanly if Node isn't available).

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
PORT=8420
SERVER_PID=""

pass() { PASS=$((PASS+1)); echo "  OK  $1"; }
fail() { FAIL=$((FAIL+1)); echo "FAIL  $1"; }

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
  fi
}
trap cleanup EXIT

echo "======================================================================"
echo "Braid demo.sh — full feature walkthrough"
echo "======================================================================"

echo
echo "--- 1/5: Python unit test suite (crdt engine, site, network, server, cli) ---"
if python3 -m unittest discover -s tests -q; then
  pass "unit test suite (72 tests: rga, site, network_convergence, server, cli, parity)"
else
  fail "unit test suite"
fi

echo
echo "--- 2/5: CLI convergence sweep (R2: Strong Eventual Consistency proof) ---"
if python3 cli.py sweep --count 100 --sites 5 --ops 50; then
  pass "convergence sweep — 100/100 seeds"
else
  fail "convergence sweep"
fi

echo
echo "--- 3/5: CLI narrated offline/reconnect scenario (R4) ---"
if python3 cli.py scenario; then
  pass "offline/reconnect scenario"
else
  fail "offline/reconnect scenario"
fi

echo
echo "--- 4/5: single simulate run, verbose (R2, sanity check on real output) ---"
if python3 cli.py simulate --seed 7 --sites 4 --ops 40; then
  pass "simulate --seed 7"
else
  fail "simulate --seed 7"
fi

echo
echo "--- 5/5: live server + real browser, multiple tabs (R3, S1, S2) ---"
# Playwright is often installed globally rather than in this project's own
# node_modules (there isn't one — no bundler/build step anywhere in Braid);
# NODE_PATH is what makes `require('playwright')` find it either way.
export NODE_PATH="${NODE_PATH:-$(npm root -g 2>/dev/null)}"
if ! command -v node >/dev/null 2>&1; then
  echo "  SKIP  node not on PATH — browser test skipped (engine/CLI coverage above still ran)"
elif ! node -e "require('playwright')" >/dev/null 2>&1; then
  echo "  SKIP  playwright not resolvable — browser test skipped"
else
  # find a free port so this doesn't collide with an already-running `braid serve`
  PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()")
  python3 server.py --port "$PORT" >/tmp/braid-demo-server.log 2>&1 &
  SERVER_PID=$!
  ready=0
  for _ in $(seq 1 50); do
    if curl -s -o /dev/null "http://localhost:$PORT/"; then ready=1; break; fi
    sleep 0.1
  done
  if [ "$ready" != "1" ]; then
    fail "server did not come up on port $PORT (see /tmp/braid-demo-server.log)"
  elif node tests/browser_test.js "$PORT"; then
    pass "live multi-tab browser test (sync, concurrency, offline/reconnect, undo, emoji, theming)"
  else
    fail "live multi-tab browser test"
  fi
fi

echo
echo "======================================================================"
echo "RESULT: $PASS passed, $FAIL failed"
echo "======================================================================"
[ "$FAIL" -eq 0 ]
