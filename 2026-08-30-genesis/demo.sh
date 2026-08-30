#!/usr/bin/env bash
# Genesis -- full verification script. Exercises every feature end to end:
# the unit/integration test suite, the narrated cross-cutting demonstration
# (src/demo.py), the wallet CLI's own persistence, and a live spin-up of the
# block-explorer server. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS="\033[92mPASS\033[0m"
FAIL="\033[91mFAIL\033[0m"
SECTION=0

section() {
    SECTION=$((SECTION + 1))
    echo
    echo "=================================================================="
    echo "  [$SECTION] $1"
    echo "=================================================================="
}

ok() { echo -e "  ${PASS}  $1"; }
fail() { echo -e "  ${FAIL}  $1"; exit 1; }

section "Unit + integration test suite (87 tests)"
if python3 -m unittest discover -s tests -v 2>&1 | tail -6 | tee /tmp/genesis_test_output.txt | grep -q "^OK"; then
    ok "full test suite green"
else
    cat /tmp/genesis_test_output.txt
    fail "test suite did not report OK"
fi

section "Narrated end-to-end demonstration (mining, retargeting, ECDSA auth, merkle proofs, multi-node fork/reorg, wallet)"
if python3 src/demo.py; then
    ok "all demonstration sections passed"
else
    fail "demo.py reported a failure"
fi

section "Wallet CLI (on-disk persistence across separate process invocations)"
# Isolated temp data dir -- never touches a real ./data a user might already
# have, and self-cleans regardless of how this script exits.
export GENESIS_DATA_DIR
GENESIS_DATA_DIR="$(mktemp -d)"
trap 'rm -rf "$GENESIS_DATA_DIR"' EXIT

python3 cli.py init > /tmp/genesis_cli_init.txt
grep -q "wallet address" /tmp/genesis_cli_init.txt && ok "wallet initialized"
ADDRESS=$(python3 cli.py address)
[ -n "$ADDRESS" ] && ok "address derived: $ADDRESS"
python3 cli.py mine 3 > /tmp/genesis_cli_mine.txt
grep -q "mined block #3" /tmp/genesis_cli_mine.txt && ok "mined 3 blocks"
BALANCE=$(python3 cli.py balance)
echo "$BALANCE" | grep -q "150.00000000 coins" && ok "balance is exactly 3 x 50 coin subsidy: $BALANCE"

# a second, independent wallet to send to
BOB_ADDR=$(python3 -c "
import sys; sys.path.insert(0, 'src')
from wallet import Wallet
print(Wallet().address)
")
python3 cli.py send "$BOB_ADDR" 12.5 --fee 2000 > /tmp/genesis_cli_send.txt
grep -q "queued tx" /tmp/genesis_cli_send.txt && ok "signed transaction queued into the mempool"
python3 cli.py mine 1 > /tmp/genesis_cli_mine2.txt
grep -q "1 tx" /tmp/genesis_cli_mine2.txt && ok "queued transaction was picked up and mined"
NEW_BALANCE=$(python3 cli.py balance)
echo "$NEW_BALANCE" | grep -q "187.5" && ok "post-send balance correct (150 - 12.5 + 50 new reward): $NEW_BALANCE"

section "Live block-explorer server (real HTTP, real gossip, real mining)"
python3 -c "
import sys, os, threading, time, json, http.client
sys.path.insert(0, 'src')
import server as srv
from http.server import ThreadingHTTPServer

network = srv.Network(seed=99)
srv.Handler.network = network
httpd = ThreadingHTTPServer(('127.0.0.1', 0), srv.Handler)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
stop = threading.Event()
threading.Thread(target=srv.mining_loop, args=(network, stop), daemon=True).start()
time.sleep(4)

def get(path):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    conn.request('GET', path)
    r = conn.getresponse()
    body = r.read()
    conn.close()
    return r.status, body

status, body = get('/')
assert status == 200 and b'Genesis' in body, 'index page did not serve correctly'
print('  PASS  index page served')

status, body = get('/api/status')
assert status == 200
data = json.loads(body)
assert set(data['names']) == {'Ada', 'Grace', 'Katherine'}
print('  PASS  status API returned all 3 nodes')

total_mined = sum(n['blocks_mined'] for n in data['nodes'].values())
assert total_mined > 0, 'no blocks were mined in 4 seconds of live operation'
print(f'  PASS  {total_mined} blocks mined live across the network')

status, body = get('/../../etc/passwd')
assert status == 404, 'path traversal was not rejected'
print('  PASS  path traversal correctly rejected (404)')

stop.set()
httpd.shutdown()
"

echo
echo "=================================================================="
echo "  ALL VERIFICATION SECTIONS PASSED"
echo "=================================================================="
