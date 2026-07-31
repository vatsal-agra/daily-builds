#!/usr/bin/env bash
# Trellis end-to-end verification: the Python unit/integration test suite
# (engine + a real HTTP server on a live socket), the scripted `trellis
# demo` walkthrough, a curl-driven HTTP API walkthrough against a real
# running server, a real headless-Chromium UI test exercising every REVIEW.md
# regression, CLI smoke checks, and clean-error-handling checks.
set -euo pipefail
cd "$(dirname "$0")"

PORT=8799
BASE_URL="http://127.0.0.1:${PORT}"
SERVER_PID=""

cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo "=================================================================="
echo "1/6  Python test suite (unittest discover) -- 140+ tests, incl. a"
echo "     real HTTP server on a live socket"
echo "=================================================================="
python3 -m unittest discover -s tests -v

echo
echo "=================================================================="
echo "2/6  'trellis demo' -- scripted walkthrough of every feature"
echo "=================================================================="
python3 -m trellis demo

echo
echo "=================================================================="
echo "3/6  Live HTTP API walkthrough (curl against a real running server)"
echo "=================================================================="
python3 -m trellis serve --port "$PORT" > /tmp/trellis_demo_server.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 50); do
    if curl -s -o /dev/null "$BASE_URL/api/state"; then break; fi
    sleep 0.1
done

check_json() {
    local desc="$1" expect="$2"; shift 2
    echo "--- $desc ---"
    local out
    out="$("$@")"
    echo "$out" | head -c 300
    echo
    if ! echo "$out" | grep -q "$expect"; then
        echo "FAIL: expected to find '$expect' in response"
        exit 1
    fi
}

check_json "set A1=5" '"display": "5"' \
    curl -s -X POST "$BASE_URL/api/cell" -H 'Content-Type: application/json' \
    -d '{"sheet":"Sheet1","row":1,"col":1,"raw":"5"}'

check_json "set B1==A1*10 (live formula recalculation)" '"display": "50"' \
    curl -s -X POST "$BASE_URL/api/cell" -H 'Content-Type: application/json' \
    -d '{"sheet":"Sheet1","row":1,"col":2,"raw":"=A1*10"}'

check_json "div-by-zero reports a clean error, not a crash" '"error": "#DIV/0!"' \
    curl -s -X POST "$BASE_URL/api/cell" -H 'Content-Type: application/json' \
    -d '{"sheet":"Sheet1","row":2,"col":1,"raw":"=1/0"}'

check_json "circular reference reports #CIRCULAR!, server stays alive" '#CIRCULAR' \
    bash -c "curl -s -X POST '$BASE_URL/api/cell' -H 'Content-Type: application/json' -d '{\"sheet\":\"Sheet1\",\"row\":3,\"col\":1,\"raw\":\"=A4+1\"}' >/dev/null; curl -s -X POST '$BASE_URL/api/cell' -H 'Content-Type: application/json' -d '{\"sheet\":\"Sheet1\",\"row\":4,\"col\":1,\"raw\":\"=A3+1\"}'"

check_json "undo restores previous state" '"display": "5"' \
    bash -c "curl -s -X POST '$BASE_URL/api/cell' -H 'Content-Type: application/json' -d '{\"sheet\":\"Sheet1\",\"row\":1,\"col\":1,\"raw\":\"999\"}' >/dev/null; curl -s -X POST '$BASE_URL/api/undo' -H 'Content-Type: application/json' -d '{\"sheet\":\"Sheet1\"}'"

check_json "add a sheet" '"Data"' \
    curl -s -X POST "$BASE_URL/api/sheet" -H 'Content-Type: application/json' -d '{"name":"Data"}'

check_json "cross-sheet formula" '"84"' \
    bash -c "curl -s -X POST '$BASE_URL/api/cell' -H 'Content-Type: application/json' -d '{\"sheet\":\"Data\",\"row\":1,\"col\":1,\"raw\":\"42\"}' >/dev/null; curl -s -X POST '$BASE_URL/api/cell' -H 'Content-Type: application/json' -d '{\"sheet\":\"Sheet1\",\"row\":5,\"col\":1,\"raw\":\"=Data!A1*2\"}'"

check_json "rename sheet keeps cross-sheet formula alive (REVIEW.md #4)" '"84"' \
    bash -c "curl -s -X POST '$BASE_URL/api/sheet/rename' -H 'Content-Type: application/json' -d '{\"old\":\"Data\",\"new\":\"Source\"}' >/dev/null; curl -s '$BASE_URL/api/state?sheet=Sheet1'"

check_json "chart endpoint returns real SVG" '<svg' \
    curl -s "$BASE_URL/api/chart?sheet=Sheet1&range=A1:A2&kind=bar"

check_json "path traversal on static files is blocked" 'not found' \
    curl -s "$BASE_URL/static/../../etc/passwd"

echo
echo "--- deeply nested formula: clean #VALUE!, server survives (REVIEW.md #5) ---"
DEEP='='"$(printf '(%.0s' {1..500})"'1'"$(printf ')%.0s' {1..500})"
RESP="$(curl -s -X POST "$BASE_URL/api/cell" -H 'Content-Type: application/json' \
    -d "{\"sheet\":\"Sheet1\",\"row\":6,\"col\":1,\"raw\":\"${DEEP}\"}")"
echo "$RESP" | head -c 200; echo
echo "$RESP" | grep -q '#VALUE!'
curl -s -o /dev/null -w "server still alive, /api/state -> %{http_code}\n" "$BASE_URL/api/state"

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
SERVER_PID=""

echo
echo "=================================================================="
echo "4/6  Headless-Chromium UI test (every REVIEW.md finding, re-verified"
echo "     live against a fresh server -- step 3 above deliberately used"
echo "     a separate instance so its curl-driven edits/sheet-renames"
echo "     can't collide with this test's own assumptions about state)"
echo "=================================================================="
python3 -m trellis serve --port "$PORT" > /tmp/trellis_demo_server_ui.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 50); do
    if curl -s -o /dev/null "$BASE_URL/api/state"; then break; fi
    sleep 0.1
done
if command -v node >/dev/null 2>&1; then
    NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}" node tests/ui_browser_test.js "$BASE_URL"
else
    echo "SKIPPED: node not available in this environment"
fi

kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
SERVER_PID=""

echo
echo "=================================================================="
echo "5/6  CLI smoke checks"
echo "=================================================================="

echo "--- csv-import ---"
printf 'Item,Qty,Price,Total\nWidget,3,9.5,=B2*C2\nGadget,2,19,=B3*C3\n' > /tmp/trellis_demo.csv
python3 -m trellis csv-import /tmp/trellis_demo.csv --out /tmp/trellis_demo_out.csv
grep -q '28.5' /tmp/trellis_demo_out.csv
echo "OK: CSV import computed formula values correctly"
rm -f /tmp/trellis_demo.csv /tmp/trellis_demo_out.csv

echo "--- repl ---"
REPL_OUT="$(printf 'A1=5\nB1==A1*3\nshow\nquit\n' | python3 -m trellis repl)"
echo "$REPL_OUT" | grep -q "B1 = 15"
echo "OK: REPL evaluates formulas referencing prior REPL input"

echo
echo "=================================================================="
echo "6/6  Clean error handling (no raw tracebacks) on bad CLI input"
echo "=================================================================="
set +e
python3 -m trellis csv-import /no/such/file.csv 2>/tmp/trellis_err.txt
code=$?
set -e
if [ "$code" -ne 1 ] || ! grep -q "^error:" /tmp/trellis_err.txt || grep -q "Traceback" /tmp/trellis_err.txt; then
    echo "FAIL: missing-file error handling did not behave as expected"
    cat /tmp/trellis_err.txt
    exit 1
fi
echo "OK: missing CSV file produced a clean 'error: ...' message and exit code 1"
rm -f /tmp/trellis_err.txt

echo
echo "=================================================================="
echo "ALL CHECKS PASSED"
echo "=================================================================="
