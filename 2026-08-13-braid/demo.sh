#!/usr/bin/env bash
# demo.sh — full verification run: the Node test suite (RGA correctness,
# 100-scenario randomized convergence proof, regression tests) plus a
# real-browser smoke test that drives the actual app end to end.
set -euo pipefail
cd "$(dirname "$0")"

echo "======================================================"
echo " Braid — verification"
echo "======================================================"
echo
echo "--- 1/2: CRDT unit tests + convergence proof + regressions ---"
npm test
echo

echo "--- 2/2: browser smoke test (live UI, partitions, attribution, undo/redo) ---"
PORT="${BRAID_DEMO_PORT:-8321}"
python3 -m http.server "$PORT" >/tmp/braid-demo-http.log 2>&1 &
HTTP_PID=$!
trap 'kill "$HTTP_PID" 2>/dev/null || true' EXIT
sleep 1

node test/browser-demo.mjs "http://localhost:${PORT}/index.html"
STATUS=$?

echo
if [ "$STATUS" -eq 0 ]; then
  echo "======================================================"
  echo " ALL CHECKS PASSED"
  echo "======================================================"
else
  echo "======================================================"
  echo " DEMO FAILED — see output above"
  echo "======================================================"
fi
exit "$STATUS"
