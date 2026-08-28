#!/usr/bin/env bash
# End-to-end verification for LedgerLine: unit tests, the scripted CLI
# walkthrough of every feature (required + stretch), and a headless-
# Chromium check that the live web explorer actually renders real data
# and its send-coins form works. Exits non-zero the moment anything fails.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
step() {
    echo
    echo "=================================================================="
    echo "  $1"
    echo "=================================================================="
}

check() {
    if [ "$1" -eq 0 ]; then
        echo "  -> PASS: $2"
        PASS=$((PASS + 1))
    else
        echo "  -> FAIL: $2"
        FAIL=$((FAIL + 1))
    fi
}

step "1. keygen — CLI wallet generation + persistence"
KEYFILE=$(mktemp)
python3 -m ledgerline.cli keygen --out "$KEYFILE"
KEYGEN_OK=$?
ADDR1=$(python3 -c "import json; print(json.load(open('$KEYFILE'))['address'])" 2>/dev/null)
python3 -m ledgerline.cli network --nodes 1 --seconds 1 --bits 12 --wallet "$KEYFILE" > /tmp/ledgerline_wallet_reuse.log 2>&1
ADDR2=$(grep -o 'premine wallet: [A-Za-z0-9]*' /tmp/ledgerline_wallet_reuse.log | head -1 | awk '{print $3}')
if [ "$KEYGEN_OK" -eq 0 ] && [ -n "$ADDR1" ] && [ "$ADDR1" = "$ADDR2" ]; then
    check 0 "keygen saves a wallet and --wallet reuses the same address across runs ($ADDR1)"
else
    check 1 "keygen/--wallet reuse (addr1=$ADDR1 addr2=$ADDR2)"
fi
rm -f "$KEYFILE" /tmp/ledgerline_wallet_reuse.log

step "2. CLI input validation — clean errors, not tracebacks or hangs"
BAD=0
python3 -m ledgerline.cli network --nodes 0 > /tmp/ll_badargs.log 2>&1; [ $? -ne 0 ] || BAD=1
python3 -m ledgerline.cli network --bits -1 >> /tmp/ll_badargs.log 2>&1; [ $? -ne 0 ] || BAD=1
python3 -m ledgerline.cli network --bits 100 >> /tmp/ll_badargs.log 2>&1; [ $? -ne 0 ] || BAD=1
python3 -m ledgerline.cli explorer --http-port 0 >> /tmp/ll_badargs.log 2>&1; [ $? -ne 0 ] || BAD=1
grep -q "Traceback" /tmp/ll_badargs.log && BAD=1
check "$BAD" "invalid --nodes/--bits/--http-port rejected cleanly (no tracebacks)"
rm -f /tmp/ll_badargs.log

step "3. Unit test suite"
python3 -m ledgerline.cli test
check $? "full unit test suite (ecdsa/merkle/transaction/block/chain/mempool/node/network)"

step "4. Scripted end-to-end walkthrough — every required + stretch feature"
python3 -m ledgerline.cli demo
check $? "ledgerline demo (wallets, mining+gossip, tx+mempool, partition/reorg, double-spend, retargeting)"

step "5. Live web explorer — headless-Chromium check (real data + a working send)"
EXPLORER_PORT=22900
HTTP_PORT=8993
SCREENSHOT="/tmp/ledgerline_explorer_check.png"
python3 -m ledgerline.cli explorer --nodes 3 --bits 14 --port "$EXPLORER_PORT" --http-port "$HTTP_PORT" \
    > /tmp/ledgerline_explorer.log 2>&1 &
EXPLORER_PID=$!
trap 'kill -9 "$EXPLORER_PID" 2>/dev/null' EXIT

READY=1
for _ in $(seq 1 40); do
    if curl -s "http://127.0.0.1:$HTTP_PORT/api/status" 2>/dev/null | grep -q node0; then
        READY=0
        break
    fi
    sleep 0.5
done
if [ "$READY" -ne 0 ]; then
    check 1 "explorer server came up within 20s"
else
    node verify_explorer.js "http://127.0.0.1:$HTTP_PORT" "$SCREENSHOT"
    check $? "headless-Chromium explorer check (node cards render, no console errors, send form works)"
fi
kill -9 "$EXPLORER_PID" 2>/dev/null
trap - EXIT
rm -f /tmp/ledgerline_explorer.log

echo
echo "=================================================================="
echo "  RESULTS: $PASS passed, $FAIL failed"
echo "=================================================================="
if [ -f "$SCREENSHOT" ]; then
    echo "  explorer screenshot: $SCREENSHOT"
fi
[ "$FAIL" -eq 0 ]
