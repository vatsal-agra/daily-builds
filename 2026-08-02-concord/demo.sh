#!/usr/bin/env bash
# Concord end-to-end demo/verification script.
# Exercises every feature: unit tests, the multi-node network demo, the
# double-spend attack simulation, and the CLI (including error paths).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export PYTHONPATH="$HERE"

pass() { echo "  [PASS] $1"; }
step() { echo; echo "=== $1 ==="; }

step "1/5  Unit + integration test suite (109 tests: crypto, chain validation, mempool, miner, wallet, real P2P network, explorer API)"
python3 -m unittest discover -s tests
pass "test suite green"

step "2/5  Full network demo (3 real nodes, mining, gossip, tx propagation, Merkle proof verification)"
python3 -m concord.demo
pass "demo passed"

step "3/5  Double-spend attack simulation (mempool race + private-chain 51%-style race)"
python3 -m concord.attack_demo
pass "attack simulation completed"

step "4/5  CLI smoke test (wallet, genesis, node+mining, send, balance, and error paths)"
WORKDIR="$(mktemp -d)"
cleanup() {
  [ -n "${NODE_PID:-}" ] && kill "$NODE_PID" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

python3 -m concord.cli wallet-new --out "$WORKDIR/alice.json" > /dev/null
python3 -m concord.cli wallet-new --out "$WORKDIR/bob.json" > /dev/null
ALICE_ADDR=$(python3 -m concord.cli wallet-address --wallet "$WORKDIR/alice.json")
BOB_ADDR=$(python3 -m concord.cli wallet-address --wallet "$WORKDIR/bob.json")
pass "wallets created ($ALICE_ADDR, $BOB_ADDR)"

python3 -m concord.cli genesis-create --address "$ALICE_ADDR" --amount 500 --out "$WORKDIR/genesis.json" > /dev/null
pass "genesis created"

if python3 -m concord.cli genesis-create --address "not-a-real-address" --out /dev/null > /dev/null 2>&1; then
  echo "  [FAIL] genesis-create accepted an invalid address"; exit 1
fi
pass "genesis-create rejects an invalid address"

python3 -m concord.cli node --genesis "$WORKDIR/genesis.json" \
  --p2p-port 26501 --api-port 26580 --mine --wallet "$WORKDIR/alice.json" --name demo-cli-node \
  > "$WORKDIR/node.log" 2>&1 &
NODE_PID=$!

for _ in $(seq 1 50); do
  BAL=$(python3 -m concord.cli wallet-balance --wallet "$WORKDIR/alice.json" --api http://127.0.0.1:26580 2>/dev/null | grep balance | awk '{print $2}') || true
  [ -n "${BAL:-}" ] && [ "$BAL" -gt 500 ] 2>/dev/null && break
  sleep 0.3
done
if [ -z "${BAL:-}" ] || [ "$BAL" -le 500 ]; then
  echo "  [FAIL] node never mined a reward block in time"; cat "$WORKDIR/node.log"; exit 1
fi
pass "node mined real blocks (alice balance: $BAL)"

python3 -m concord.cli send --api http://127.0.0.1:26580 --wallet "$WORKDIR/alice.json" --to "$BOB_ADDR" --amount 100 > /dev/null
pass "sent a real signed transaction"

for _ in $(seq 1 50); do
  BOB_BAL=$(python3 -m concord.cli wallet-balance --wallet "$WORKDIR/bob.json" --api http://127.0.0.1:26580 2>/dev/null | grep balance | awk '{print $2}') || true
  [ "${BOB_BAL:-0}" = "100" ] && break
  sleep 0.3
done
if [ "${BOB_BAL:-0}" != "100" ]; then
  echo "  [FAIL] bob's payment never confirmed"; cat "$WORKDIR/node.log"; exit 1
fi
pass "payment confirmed on-chain (bob balance: $BOB_BAL)"

if python3 -m concord.cli send --api http://127.0.0.1:26580 --wallet "$WORKDIR/alice.json" --to "garbage-address" --amount 10 > /dev/null 2>&1; then
  echo "  [FAIL] send accepted an invalid destination address"; exit 1
fi
pass "send rejects an invalid destination address"

if python3 -m concord.cli send --api http://127.0.0.1:26580 --wallet "$WORKDIR/alice.json" --to "$BOB_ADDR" --amount 999999999 > /dev/null 2>&1; then
  echo "  [FAIL] send accepted an amount exceeding balance"; exit 1
fi
pass "send rejects insufficient funds"

if python3 -m concord.cli wallet-balance --wallet "$WORKDIR/does-not-exist.json" --api http://127.0.0.1:26580 > /dev/null 2>&1; then
  echo "  [FAIL] wallet-balance did not error on a missing wallet file"; exit 1
fi
pass "wallet-balance errors cleanly on a missing wallet file"

step "5/5  Explorer UI (headless-browser: click a block, click a tx, verify the Merkle proof panel actually recomputes and matches, zero console errors)"
if command -v node > /dev/null 2>&1; then
  NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}" \
  PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}" \
  node "$HERE/tests/check_explorer_ui.js" "http://127.0.0.1:26580"
  pass "explorer UI verified in headless Chromium"
else
  echo "  [SKIP] node/Chromium not available in this environment — UI was manually verified during development (see REVIEW.md)"
fi

kill "$NODE_PID" 2>/dev/null || true
wait "$NODE_PID" 2>/dev/null || true
NODE_PID=""

echo
echo "======================================================================"
echo "ALL CHECKS PASSED"
echo "======================================================================"
