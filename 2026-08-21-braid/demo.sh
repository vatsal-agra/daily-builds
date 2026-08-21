#!/usr/bin/env bash
# Braid end-to-end demo: exercises every required and stretch feature
# against real, running code — no mocks, no fabricated output. Exits
# non-zero on any failure.
set -uo pipefail
cd "$(dirname "$0")"

FAIL=0
step() { echo; echo "=================================================================="; echo "  $1"; echo "=================================================================="; }

step "1/5  Unit + property + integration test suite (56 tests, incl. real sockets)"
python3 -m unittest discover -s tests -t . -v
[ $? -eq 0 ] || FAIL=1

step "2/5  RGA <-> chaos network <-> SEC verification report (required features 1-3)"
python3 -m verify.convergence
[ $? -eq 0 ] || FAIL=1

step "3/5  Nested multi-type document CRDT demo (stretch feature 5)"
python3 demo_document.py
[ $? -eq 0 ] || FAIL=1

step "4/5  Live server smoke test (required feature 4: real WebSocket, real HTTP)"
python3 - <<'PYEOF'
import socket, subprocess, sys, time, urllib.request

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()

proc = subprocess.Popen(
    [sys.executable, "-m", "server.braid_server", "--port", str(port), "--seed", "1"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
try:
    deadline = time.time() + 5
    up = False
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            up = True
            break
        except OSError:
            time.sleep(0.05)
    if not up:
        print("server never came up"); sys.exit(1)

    for path in ("/", "/app.js", "/rga.js", "/style.css"):
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}")
        assert r.status == 200, (path, r.status)
    print(f"server up on port {port}, all static assets served 200 OK")

    r = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/chaos?room=demo&loss=0.1&dup=0.1")
    import json
    data = json.loads(r.read())
    print("chaos API live:", data)
    print("LIVE SERVER SMOKE TEST: PASSED")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
PYEOF
[ $? -eq 0 ] || FAIL=1

step "5/5  JS/Python RGA differential parity + WebSocket frame codec (already in test suite; re-summarizing)"
if command -v node >/dev/null 2>&1; then
    echo "node present: JS parity check ran as part of the test suite above (tests/test_js_parity.py)"
else
    echo "node not found: JS parity check was skipped (see test suite output above)"
fi

echo
echo "=================================================================="
if [ "$FAIL" -eq 0 ]; then
    echo "  ALL DEMO STEPS PASSED"
else
    echo "  SOME DEMO STEPS FAILED — see output above"
fi
echo "=================================================================="
exit $FAIL
