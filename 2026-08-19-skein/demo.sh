#!/usr/bin/env bash
# End-to-end verification: unit suite, every CLI feature, and a live
# smoke test of the web playground's HTTP API. Exits non-zero on any
# failure.
set -euo pipefail
cd "$(dirname "$0")"

PY=python3
PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== 1/6 Unit test suite ==="
$PY -m unittest discover -s tests -q
echo "  ✓ full unit suite green"
PASS=$((PASS + 1))

echo
echo "=== 2/6 CLI: demo (narrated walkthrough of every core feature) ==="
$PY -m skein.cli demo
echo "  ✓ demo passed"
PASS=$((PASS + 1))

echo
echo "=== 3/6 CLI: sim (one chaos simulation) ==="
$PY -m skein.cli sim --sites 4 --edits 60 --seed 123 | tail -6
echo "  ✓ sim converged"
PASS=$((PASS + 1))

echo
echo "=== 4/6 CLI: chaos (200-trial randomized convergence proof) ==="
$PY -m skein.cli chaos --trials 200 --seed 7
echo "  ✓ chaos proof green"
PASS=$((PASS + 1))

echo
echo "=== 5/6 CLI: shuffle-proof (order-independence proof) ==="
$PY -m skein.cli shuffle-proof --trials 150 --edits 60 --seed 7
echo "  ✓ shuffle proof green"
PASS=$((PASS + 1))

echo
echo "=== 6/6 CLI: error handling on bad input (must NOT crash) ==="
if $PY -m skein.cli sim --sites 0 2>/tmp/skein_demo_err.txt; then
    echo "  ✗ --sites 0 should have exited non-zero"
    FAIL=$((FAIL + 1))
else
    if grep -q "^error:" /tmp/skein_demo_err.txt; then
        echo "  ✓ --sites 0 produced a clean error, not a traceback"
        PASS=$((PASS + 1))
    else
        echo "  ✗ --sites 0 did not produce a clean 'error:' message"
        cat /tmp/skein_demo_err.txt
        FAIL=$((FAIL + 1))
    fi
fi
rm -f /tmp/skein_demo_err.txt

echo
echo "=== 7/6 (bonus) Web playground: live HTTP smoke test ==="
PORT=8799
$PY -m skein.cli serve --port $PORT >/tmp/skein_demo_server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 1

check "GET / returns the page" bash -c "curl -sf http://127.0.0.1:$PORT/ | grep -q 'Skein'"
check "POST /api/type applies an edit" bash -c \
    "curl -sf -X POST http://127.0.0.1:$PORT/api/type -H 'Content-Type: application/json' -d '{\"site\":\"Alice\",\"pos\":0,\"text\":\"hello\"}' | grep -q hello"
sleep 1
check "the edit propagated to Bob" bash -c \
    "curl -sf http://127.0.0.1:$PORT/api/state | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['sites']['Bob']['text']=='hello'\""
check "oversized delete_range is rejected with HTTP 400, no data loss" bash -c \
    "code=\$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:$PORT/api/delete -H 'Content-Type: application/json' -d '{\"site\":\"Alice\",\"pos\":0,\"count\":9999}'); test \"\$code\" = 400"
check "document survived the rejected oversized delete" bash -c \
    "curl -sf http://127.0.0.1:$PORT/api/state | python3 -c \"import json,sys; d=json.load(sys.stdin); assert d['sites']['Alice']['text']=='hello'\""
check "bad site name returns HTTP 400, not a crash" bash -c \
    "code=\$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:$PORT/api/type -H 'Content-Type: application/json' -d '{\"site\":\"Nope\",\"pos\":0,\"text\":\"x\"}'); test \"\$code\" = 400"

kill $SERVER_PID 2>/dev/null || true
trap - EXIT

echo
echo "=========================================="
echo "  $PASS passed, $FAIL failed"
echo "=========================================="
if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
