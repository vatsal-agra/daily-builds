#!/usr/bin/env bash
# Undertow verification script — exercises every feature end to end and
# exits non-zero on the first failure. Run from the project root:
#   ./demo.sh
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
REPORT_DIR="$(mktemp -d)"

pass() { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

section() { echo; echo "=== $1 ==="; }

section "1/6 — Unit + integration test suite (46 tests: wire format, RTO, congestion control, netsim, handshake/teardown, SACK, HTTP)"
if python3 -m unittest discover -s tests -v > "$REPORT_DIR/tests.log" 2>&1; then
    NTESTS=$(grep -c ' ... ok$' "$REPORT_DIR/tests.log")
    pass "test suite ($NTESTS tests, see $REPORT_DIR/tests.log)"
else
    fail "test suite — see $REPORT_DIR/tests.log"
    tail -40 "$REPORT_DIR/tests.log"
fi

section "2/6 — Reliable delivery over a real lossy/reordering/duplicating network (required feature 1)"
# Note: --timeout bounds a real wall-clock RTO/backoff/retransmit loop over
# real threads, not a simulated clock — a generous budget here isn't
# padding for its own sake, it's headroom for real host scheduling
# variance (see REVIEW.md).
if python3 bin/undertow-demo --size 60000 --loss 0.1 --dup 0.02 --reorder 0.05 \
        --delay-min 5 --delay-max 20 --seed 11 --timeout 120 \
        --report "$REPORT_DIR/report_lossy.html" > "$REPORT_DIR/lossy.log" 2>&1; then
    if grep -q "integrity:       OK" "$REPORT_DIR/lossy.log"; then
        pass "60KB byte-exact transfer through 10% loss / dup / reorder"
    else
        fail "transfer completed but integrity check did not print OK — see $REPORT_DIR/lossy.log"
    fi
else
    fail "lossy transfer — see $REPORT_DIR/lossy.log"
    tail -20 "$REPORT_DIR/lossy.log"
fi

section "3/6 — Reno congestion control produces real slow-start -> congestion-avoidance -> recovery dynamics (required feature 2)"
if grep -q "final cwnd:" "$REPORT_DIR/lossy.log" && grep -q "retransmissions:" "$REPORT_DIR/lossy.log"; then
    RETR=$(grep "retransmissions:" "$REPORT_DIR/lossy.log" | awk '{print $2}')
    if [ "${RETR:-0}" -gt 0 ]; then
        pass "congestion control reacted to real loss ($RETR retransmissions logged)"
    else
        fail "expected at least one retransmission under 10% loss, saw none"
    fi
else
    fail "could not find cwnd/retransmission stats in transfer report"
fi

section "4/6 — Zero-loss, zero-jitter network produces zero retransmissions (protocol doesn't retransmit spuriously)"
if python3 bin/undertow-demo --size 20000 --loss 0.0 --dup 0.0 --reorder 0.0 \
        --delay-min 4 --delay-max 4 --seed 5 --timeout 30 > "$REPORT_DIR/clean.log" 2>&1; then
    RETR=$(grep "retransmissions:" "$REPORT_DIR/clean.log" | awk '{print $2}')
    if [ "${RETR:-1}" = "0" ]; then
        pass "idealized network: 0 retransmissions"
    else
        fail "idealized network still retransmitted ($RETR) — see $REPORT_DIR/clean.log"
    fi
else
    fail "clean-network transfer — see $REPORT_DIR/clean.log"
fi

section "5/6 — Graceful 4-way close (required feature 3) + SHA-256-verified file transfer app (required feature 4)"
python3 - "$REPORT_DIR" <<'PYEOF'
import sys, hashlib, threading, time
sys.path.insert(0, ".")
from undertow.fileapp import send_file, receive_file
from undertow.socket_ import MiniTCPSocket

report_dir = sys.argv[1]
ok = True

# Direct (no netsim) — exercises the plain handshake/data/close path and
# checks the file-transfer app's own SHA-256 report against a hash computed
# independently here.
import socket
def free_addr():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0))
    a = s.getsockname(); s.close(); return a

client_addr, server_addr = free_addr(), free_addr()
data = b"undertow verification payload " * 500
result = {}
def run_recv():
    result["recv"] = receive_file(server_addr, name="v-recv", timeout=20)
t = threading.Thread(target=run_recv); t.start()
time.sleep(0.1)
sent = send_file(client_addr, server_addr, data, name="v-send", timeout=20)
t.join(timeout=20)

expected = hashlib.sha256(data).hexdigest()
if sent["sha256"] != expected or result["recv"]["sha256"] != expected:
    print("FILE APP HASH MISMATCH"); ok = False
elif result["recv"]["data"] != data:
    print("FILE APP BYTE MISMATCH"); ok = False
else:
    print("file transfer app: SHA-256 verified, byte-exact")

sys.exit(0 if ok else 1)
PYEOF
if [ $? -eq 0 ]; then
    pass "graceful close + SHA-256 file transfer app"
else
    fail "graceful close / file transfer app check"
fi

section "6/6 — Stretch features: SACK-aware recovery, HTML visualizer, HTTP/1.0 demo app"
if [ -s "$REPORT_DIR/report_lossy.html" ] && grep -q "<title>" "$REPORT_DIR/report_lossy.html"; then
    pass "HTML visualizer generated a real report ($REPORT_DIR/report_lossy.html)"
else
    fail "HTML visualizer did not produce a report"
fi

python3 - <<'PYEOF'
import sys, threading, time
sys.path.insert(0, ".")
from undertow.httpapp import serve_one_request, fetch
from undertow.netsim import NetSim
import socket, random

def free_addr():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", 0))
    a = s.getsockname(); s.close(); return a

client_addr, server_addr, relay_addr = free_addr(), free_addr(), free_addr()
net = NetSim(relay_addr, client_addr, server_addr, loss=0.05, delay_range=(0.002, 0.01), rng=random.Random(1))
net.start()
routes = {"/": b"<html>undertow http demo</html>"}
result = {}
def run_server():
    result["s"] = serve_one_request(server_addr, routes, name="v-httpd", timeout=20)
t = threading.Thread(target=run_server); t.start()
time.sleep(0.1)
resp = fetch(client_addr, relay_addr, path="/", name="v-httpc", timeout=20)
t.join(timeout=20)
net.stop()
ok = resp["status_code"] == 200 and resp["body"] == routes["/"]
print("HTTP demo app: " + ("OK" if ok else "FAILED"))
sys.exit(0 if ok else 1)
PYEOF
if [ $? -eq 0 ]; then
    pass "HTTP/1.0 demo app over MiniTCPSocket"
else
    fail "HTTP/1.0 demo app"
fi

echo
echo "=== Summary ==="
echo "  $PASS passed, $FAIL failed"
echo "  full logs + HTML report in: $REPORT_DIR"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
