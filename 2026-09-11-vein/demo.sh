#!/usr/bin/env bash
# Vein — end-to-end demo/verification script.
# Exercises every required and stretch feature from PLAN.md and exits
# non-zero if any check fails.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0

check() {
  local name="$1"
  local status="$2"
  if [ "$status" -eq 0 ]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
}

echo "============================================================"
echo " VEIN — demo.sh (full verification suite)"
echo "============================================================"

echo
echo "[1/5] Unit test suite (crypto, script/UTXO, chain/mempool, reorg)"
python3 -m unittest discover -s tests > /tmp/vein_unittest.log 2>&1
check "unit test suite (see /tmp/vein_unittest.log)" $?
tail -3 /tmp/vein_unittest.log | sed 's/^/    /'

echo
echo "[2/5] Core walkthrough: crypto -> mining -> UTXO spend -> retargeting"
python3 -m vein.cli demo > /tmp/vein_demo.log 2>&1
check "vein demo" $?
tail -3 /tmp/vein_demo.log | sed 's/^/    /'

echo
echo "[3/5] Live node: wallet CLI payment + block explorer (headless browser)"
if command -v node >/dev/null 2>&1 && [ -x /opt/pw-browsers/chromium ]; then
  python3 scripts/live_node_demo.py > /tmp/vein_live_node.log 2>&1
  check "wallet send/receive + explorer smoke test" $?
else
  echo "  [SKIP] no headless Chromium available in this environment"
fi
tail -25 /tmp/vein_live_node.log | sed 's/^/    /'

echo
echo "[4/5] Multi-process P2P network: partition, double-spend, reorg, convergence"
python3 -m vein.cli partition-demo > /tmp/vein_partition.log 2>&1
check "vein partition-demo (4 real subprocesses)" $?
tail -8 /tmp/vein_partition.log | sed 's/^/    /'

echo
echo "[5/5] CLI error handling on invalid/empty input (no raw tracebacks)"
ERR_OK=0
python3 -m vein.cli wallet address --wallet /tmp/__vein_does_not_exist__.json > /tmp/vein_err1.log 2>&1
[ $? -eq 1 ] && grep -q "^error:" /tmp/vein_err1.log || ERR_OK=1
python3 -m vein.cli wallet new --out /tmp/__vein_err_wallet__.json > /dev/null 2>&1
python3 -m vein.cli wallet send --wallet /tmp/__vein_err_wallet__.json --to notanaddress --amount 1 \
  > /tmp/vein_err2.log 2>&1
[ $? -eq 1 ] && grep -q "^error:" /tmp/vein_err2.log || ERR_OK=1
python3 -m vein.cli status --rpc http://127.0.0.1:1 > /tmp/vein_err3.log 2>&1
[ $? -eq 1 ] && grep -q "^error:" /tmp/vein_err3.log || ERR_OK=1
check "clean (non-traceback) errors on bad input" $ERR_OK

echo
echo "============================================================"
echo " RESULTS: $PASS passed, $FAIL failed"
echo "============================================================"
[ "$FAIL" -eq 0 ]
