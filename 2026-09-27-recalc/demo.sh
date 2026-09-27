#!/usr/bin/env bash
# Runs every verification this project has: the Python unit/fuzz suite,
# the narrated CLI walkthrough, a CSV batch round trip, and a real
# headless-Chromium pass over the actual browser UI. Exits non-zero (and
# prints where) on the first failure.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
PORT=8799
SERVER_PID=""

check() {
  local name="$1"
  shift
  echo
  echo "--- $name ---"
  if "$@"; then
    echo "[ok] $name"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
}

cleanup() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
  fi
  rm -f /tmp/recalc_demo_server.log
}
trap cleanup EXIT

echo "=== Recalc verification ==="

check "1/5 Python unit + fuzz test suite (80 tests)" \
  python3 -m unittest discover -s tests -q

check "2/5 Narrated CLI walkthrough (recalc.py demo)" \
  python3 recalc.py demo

echo
echo "--- 3/5 CSV batch round trip (recalc.py run) ---"
TMP_CSV=$(mktemp /tmp/recalc_demo_XXXX.csv)
TMP_OUT=$(mktemp /tmp/recalc_demo_out_XXXX.csv)
printf '10,20,=A1+B1\n5,,=A2*3\n' > "$TMP_CSV"
python3 recalc.py run "$TMP_CSV" --export "$TMP_OUT"
EXPECTED=$'10,20,30\n5,,15\n'
ACTUAL=$(cat "$TMP_OUT")
if [ "$ACTUAL" == "$(printf '%s' "$EXPECTED")" ]; then
  echo "[ok] 3/5 CSV batch round trip"
  PASS=$((PASS + 1))
else
  echo "[FAIL] 3/5 CSV batch round trip: expected $(printf '%q' "$EXPECTED"), got $(printf '%q' "$ACTUAL")"
  FAIL=$((FAIL + 1))
fi
rm -f "$TMP_CSV" "$TMP_OUT"

echo
echo "--- 4/5 starting server for browser check ---"
python3 recalc.py serve --port "$PORT" > /tmp/recalc_demo_server.log 2>&1 &
SERVER_PID=$!
UP=0
for i in $(seq 1 30); do
  if curl -s "http://127.0.0.1:$PORT/api/sheet" > /dev/null 2>&1; then
    UP=1
    break
  fi
  sleep 0.3
done
if [ "$UP" != "1" ]; then
  echo "[FAIL] 4/5 server did not start"
  FAIL=$((FAIL + 1))
else
  check "4/5 Real headless-Chromium UI check (browser_smoke.js)" \
    node tests/browser_smoke.js "http://127.0.0.1:$PORT"
fi

echo
echo "--- 5/5 server survives a malformed request (no crash) ---"
BAD=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:$PORT/api/cell" -H "Content-Type: application/json" -d '{}')
STILL_UP=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/api/sheet")
if [ "$BAD" == "400" ] && [ "$STILL_UP" == "200" ]; then
  echo "[ok] 5/5 malformed request returned 400 and the server is still up"
  PASS=$((PASS + 1))
else
  echo "[FAIL] 5/5 expected 400 then 200, got $BAD then $STILL_UP"
  FAIL=$((FAIL + 1))
fi

echo
echo "=== $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
