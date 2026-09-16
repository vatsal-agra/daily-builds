#!/usr/bin/env bash
# Undertow verification script -- exercises every required and stretch
# feature through the real CLI and the real test suite, and fails loudly
# (non-zero exit) the moment anything doesn't check out.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

check() {
    local desc="$1"
    shift
    if "$@" >"$TMPDIR/out.log" 2>&1; then
        echo "  PASS  $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $desc"
        sed 's/^/        /' "$TMPDIR/out.log" | tail -20
        FAIL=$((FAIL + 1))
    fi
}

echo "== Undertow verification =="
echo

echo "[1/9] Unit + integration test suite"
check "63-test suite (packet/seqmath/rto/congestion/vegas/connection/regressions)" \
    python3 -m unittest discover -s tests

echo
echo "[2/9] Wire format sanity (checksum + corruption detection)"
check "packet encode/decode round-trip and corruption detection" \
    python3 -c "
from undertow.packet import Packet, PacketError
p = Packet(seq=1, ack=2, flags=2, payload=b'demo.sh check')
raw = bytearray(p.encode())
assert Packet.decode(bytes(raw)).payload == b'demo.sh check'
raw[20] ^= 0xFF
try:
    Packet.decode(bytes(raw)); raise SystemExit('corruption not detected')
except PacketError:
    pass
"

echo
echo "[3/9] Handshake + reliable transfer on a clean link"
check "clean-link demo transfer, byte-exact" \
    python3 transfer.py demo --size 300000 --loss 0 --dup 0 --reorder 0 --seed 11

echo
echo "[4/9] Reliable transfer over a real lossy/reordering/duplicating link"
check "lossy-link demo transfer, byte-exact, with real retransmission" \
    python3 transfer.py demo --size 500000 --loss 0.05 --dup 0.02 --reorder 0.05 --seed 1

echo
echo "[5/9] Sequence-number wraparound across the 2**32 boundary"
check "wraparound transfer via the connection test suite" \
    python3 -m unittest tests.test_connection.TestSequenceWraparound -v

echo
echo "[6/9] Reno vs. Vegas head-to-head over a real bottleneck link"
check "compare command: both controllers complete correctly" \
    python3 transfer.py compare --size 40000 --bottleneck-bps 60000 --bottleneck-buffer 20000 --timeout 30

echo
echo "[7/9] Real two-process send/serve over actual OS sockets"
(
    python3 transfer.py serve 39217 "$TMPDIR/received.bin" --peer-port 39218 --timeout 15 \
        >"$TMPDIR/serve.log" 2>&1
) &
SERVE_PID=$!
sleep 0.4
head -c 400000 /dev/urandom >"$TMPDIR/sent.bin" 2>/dev/null || python3 -c "
import os
open('$TMPDIR/sent.bin','wb').write(os.urandom(400000))
"
check "send CLI reaches serve CLI across two real processes" \
    python3 transfer.py send 127.0.0.1 39217 "$TMPDIR/sent.bin" --bind-port 39218 --timeout 15
wait "$SERVE_PID" 2>/dev/null
if cmp -s "$TMPDIR/sent.bin" "$TMPDIR/received.bin"; then
    echo "  PASS  sent and received files are byte-identical"
    PASS=$((PASS + 1))
else
    echo "  FAIL  sent and received files differ"
    cat "$TMPDIR/serve.log" | sed 's/^/        /'
    FAIL=$((FAIL + 1))
fi

echo
echo "[8/9] CLI error handling on realistic mistakes"
check "clean error (not a traceback) on a missing input file" \
    bash -c "python3 transfer.py send 127.0.0.1 1 /no/such/file.bin 2>&1 | grep -q 'undertow: error:'"
check "clean error (not a traceback) on a connection that can't be reached" \
    bash -c "python3 transfer.py send 127.0.0.1 1 '$TMPDIR/sent.bin' --bind-port 39218 --timeout 2 2>&1 | grep -q 'undertow: error:'"
check "empty (zero-byte) transfer completes cleanly" \
    python3 transfer.py demo --size 0

echo
echo "[9/9] HTML trace visualizer renders a real trace with no console errors"
if command -v node >/dev/null 2>&1 && [ -d /opt/node22/lib/node_modules/playwright ]; then
    python3 transfer.py compare --size 20000 --bottleneck-bps 60000 --bottleneck-buffer 20000 \
        --trace-out "$TMPDIR/trace" --timeout 30 >/dev/null 2>&1
    check "viz/index.html loads both traces with zero console/page errors" \
        node -e "
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const path = require('path');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('file://' + path.resolve('viz/index.html'));
  const input = await page.\$('#fileInput');
  await input.setInputFiles(['$TMPDIR/trace.reno.json', '$TMPDIR/trace.vegas.json']);
  await page.waitForTimeout(500);
  const panels = await page.locator('.panel').count();
  await browser.close();
  if (errors.length) { console.error('console errors:', errors); process.exit(1); }
  if (panels < 8) { console.error('expected >=8 panels, got', panels); process.exit(1); }
  console.log('ok:', panels, 'panels, 0 errors');
})();
"
else
    echo "  SKIP  node/playwright not available in this environment -- viz checked manually during Phase 4"
fi

echo
echo "== $PASS passed, $FAIL failed =="
[ "$FAIL" -eq 0 ]
