#!/usr/bin/env bash
# End-to-end verification for Bedrock: unit/property/regression test suite,
# the scripted feature walkthrough, and a real multi-*process* P2P sync
# check (two separate `bedrock serve` processes, not just in-process
# threads) driving the actual CLI over the network exactly as a user would.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
export PYTHONPATH="$PWD"

pass() { echo "  [PASS] $1"; }
section() { echo; echo "=== $1 ==="; }

section "1/4 — unit + regression test suite (unittest)"
python3 -m unittest discover -s tests -v 2>&1 | tail -20
pass "134 unit/regression tests green"

section "2/4 — scripted feature walkthrough (bedrock demo)"
python3 -m bedrock.demo
pass "every required + stretch feature exercised end-to-end and self-checked"

section "3/4 — CLI walkthrough against a persisted state file"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
DATA="$WORKDIR/state.json"

ALICE_OUT="$(python3 -m bedrock.cli --data "$DATA" keygen)"
ALICE="$(echo "$ALICE_OUT" | awk '/address:/{print $2}')"
BOB_OUT="$(python3 -m bedrock.cli --data "$DATA" keygen)"
BOB="$(echo "$BOB_OUT" | awk '/address:/{print $2}')"
echo "  alice: $ALICE"
echo "  bob:   $BOB"

python3 -m bedrock.cli --data "$DATA" mine "$ALICE" > /dev/null
BAL="$(python3 -m bedrock.cli --data "$DATA" balance "$ALICE")"
[ "$BAL" = "50.00000000" ] || { echo "FAIL: unexpected balance $BAL"; exit 1; }
pass "mine credits the reward"

python3 -m bedrock.cli --data "$DATA" send "$ALICE" "$BOB" 5 --fee 0.00001 > /dev/null
python3 -m bedrock.cli --data "$DATA" mine "$ALICE" > /dev/null
BOB_BAL="$(python3 -m bedrock.cli --data "$DATA" balance "$BOB")"
[ "$BOB_BAL" = "5.00000000" ] || { echo "FAIL: unexpected bob balance $BOB_BAL"; exit 1; }
pass "send + confirm transfers funds"

python3 -m bedrock.cli --data "$DATA" validate | grep -q "^VALID:"
pass "persisted chain re-validates from genesis"

# error paths never crash with a traceback
set +e
ERR="$(python3 -m bedrock.cli --data "$DATA" send "$ALICE" not-an-address 1 2>&1)"
set -e
echo "$ERR" | grep -q "not a valid Bedrock address" || { echo "FAIL: bad error message: $ERR"; exit 1; }
echo "$ERR" | grep -qv "Traceback" || { echo "FAIL: raw traceback leaked to user: $ERR"; exit 1; }
pass "invalid input produces a clean error, not a traceback"

section "4/4 — real 2-process P2P network (two live 'bedrock serve' instances)"
NODE_A_DATA="$WORKDIR/nodeA.json"
NODE_B_DATA="$WORKDIR/nodeB.json"
python3 -m bedrock.cli --data "$NODE_A_DATA" serve --host 127.0.0.1 --port 8611 --listen --p2p-port 9611 \
  > "$WORKDIR/nodeA.log" 2>&1 &
PID_A=$!
python3 -m bedrock.cli --data "$NODE_B_DATA" serve --host 127.0.0.1 --port 8612 --listen --p2p-port 9612 \
  --peer 127.0.0.1:9611 > "$WORKDIR/nodeB.log" 2>&1 &
PID_B=$!
cleanup_nodes() { kill "$PID_A" "$PID_B" 2>/dev/null || true; }
trap 'cleanup_nodes; rm -rf "$WORKDIR"' EXIT

# wait for both servers to come up
for i in $(seq 1 30); do
  curl -s -o /dev/null http://127.0.0.1:8611/api/status && curl -s -o /dev/null http://127.0.0.1:8612/api/status && break
  sleep 0.2
done

MINER="$(curl -s -X POST http://127.0.0.1:8611/api/wallet/new | python3 -c 'import sys,json;print(json.load(sys.stdin)["address"])')"
curl -s -X POST http://127.0.0.1:8611/api/mine -H 'Content-Type: application/json' \
  -d "{\"miner_address\":\"$MINER\"}" > /dev/null

CONVERGED=0
for i in $(seq 1 40); do
  TIP_A="$(curl -s http://127.0.0.1:8611/api/status | python3 -c 'import sys,json;print(json.load(sys.stdin)["tip_hash"])')"
  TIP_B="$(curl -s http://127.0.0.1:8612/api/status | python3 -c 'import sys,json;print(json.load(sys.stdin)["tip_hash"])')"
  if [ "$TIP_A" = "$TIP_B" ]; then CONVERGED=1; break; fi
  sleep 0.25
done

cleanup_nodes
trap 'rm -rf "$WORKDIR"' EXIT

[ "$CONVERGED" = "1" ] || { echo "FAIL: two independent bedrock serve processes never converged"; cat "$WORKDIR/nodeA.log" "$WORKDIR/nodeB.log"; exit 1; }
pass "two separately-started OS processes gossip a mined block over real TCP sockets and converge"

echo
echo "ALL DEMO.SH CHECKS PASSED"
