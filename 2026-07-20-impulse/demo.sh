#!/usr/bin/env bash
# Full verification run for Impulse: unit tests, the headless physics demo,
# and a live server smoke test (spawn a body over HTTP, read the SSE stream,
# confirm it actually falls under gravity end-to-end).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PORT="${IMPULSE_DEMO_PORT:-8799}"
SERVER_PID=""

cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "======================================================================"
echo "1/3  Unit tests (tests/test_engine.py)"
echo "======================================================================"
python3 -m unittest tests.test_engine -v

echo
echo "======================================================================"
echo "2/3  Headless physics demo (demo.py)"
echo "======================================================================"
python3 demo.py

echo
echo "======================================================================"
echo "3/3  Live server smoke test"
echo "======================================================================"
rm -f /tmp/impulse_demo_server.log
python3 server.py "$PORT" > /tmp/impulse_demo_server.log 2>&1 &
SERVER_PID=$!

# wait for the server to come up
for i in $(seq 1 30); do
    if curl -s -o /dev/null "http://localhost:$PORT/api/state"; then
        break
    fi
    sleep 0.2
    if [ "$i" -eq 30 ]; then
        echo "  [FAIL] server never came up"
        cat /tmp/impulse_demo_server.log || true
        exit 1
    fi
done
echo "  [PASS] server is up on port $PORT"

# static assets
for path in / /static/app.js /static/style.css; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT$path")
    if [ "$code" != "200" ]; then
        echo "  [FAIL] GET $path returned $code"
        exit 1
    fi
done
echo "  [PASS] index.html, app.js, style.css all served"

# spawn a body and confirm it falls under gravity via the real HTTP API
curl -s -X POST "http://localhost:$PORT/api/reset" > /dev/null
curl -s -X POST "http://localhost:$PORT/api/spawn" \
    -H "Content-Type: application/json" \
    -d '{"shape":"circle","x":450,"y":100,"radius":20}' > /dev/null
sleep 0.3
Y1=$(curl -s "http://localhost:$PORT/api/state" | python3 -c "
import json,sys
d = json.load(sys.stdin)
dyn = [b for b in d['bodies'] if not b['static']]
print(dyn[0]['y'] if dyn else -1)
")
sleep 1.0
Y2=$(curl -s "http://localhost:$PORT/api/state" | python3 -c "
import json,sys
d = json.load(sys.stdin)
dyn = [b for b in d['bodies'] if not b['static']]
print(dyn[0]['y'] if dyn else -1)
")
FELL=$(python3 -c "print('yes' if $Y2 > $Y1 + 20 else 'no')")
if [ "$FELL" != "yes" ]; then
    echo "  [FAIL] spawned body did not fall under gravity (y went $Y1 -> $Y2)"
    exit 1
fi
echo "  [PASS] spawned body fell under gravity over HTTP (y went $Y1 -> $Y2)"

# scene presets all load without error
for scene in pyramid bridge stack cradle; do
    resp=$(curl -s -X POST "http://localhost:$PORT/api/scene/load" \
        -H "Content-Type: application/json" -d "{\"name\":\"$scene\"}")
    if [[ "$resp" != *'"ok": true'* ]]; then
        echo "  [FAIL] scene '$scene' failed to load: $resp"
        exit 1
    fi
done
echo "  [PASS] all four preset scenes load cleanly"

# NaN-input regression guard (see REVIEW.md finding #1): must not crash the
# physics thread -- the server should keep answering afterward.
curl -s -X POST "http://localhost:$PORT/api/scene/import" \
    -H "Content-Type: application/json" -d '{"bodies":[{"shape":"circle","x":NaN,"y":100,"radius":20}]}' > /dev/null
sleep 0.5
code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/api/state")
if [ "$code" != "200" ]; then
    echo "  [FAIL] server did not survive a NaN scene import"
    exit 1
fi
echo "  [PASS] server survives a NaN scene import (regression guard for REVIEW.md #1)"

echo
echo "======================================================================"
echo "ALL CHECKS PASSED"
echo "======================================================================"
