#!/usr/bin/env bash
# Quantum — end-to-end demo/verification script.
# Exercises every required and stretch feature from PLAN.md and exits
# non-zero if any check fails.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0

check() {
  local name="$1"
  local status="$2"
  if [ "$status" -eq 0 ]; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    FAIL=$((FAIL + 1))
  fi
}

PYTEST="${PYTEST_BIN:-pytest}"
command -v "$PYTEST" >/dev/null 2>&1 || PYTEST="/root/.local/bin/pytest"
NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}"
export NODE_PATH

echo "============================================================"
echo " QUANTUM — demo.sh (full verification suite)"
echo "============================================================"

echo
echo "[1/6] Unit test suite (scheduler, memory, workload, compare, cow, thrash)"
"$PYTEST" tests/ -q > /tmp/quantum_pytest.log 2>&1
check "pytest suite (see /tmp/quantum_pytest.log)" $?
tail -5 /tmp/quantum_pytest.log | sed 's/^/    /'

echo
echo "[2/6] Ground-truth oracle: Belady's MIN vs. brute-force exhaustive search"
python3 -m quantum.cli oracle --ref "7,0,1,2,0,3,0,4,2,3,0,3,2,1,2,0,1,7,0,1" --frames 3 \
  > /tmp/quantum_oracle.log 2>&1
grep -q "MATCH" /tmp/quantum_oracle.log
check "brute-force oracle agrees with Optimal (see /tmp/quantum_oracle.log)" $?
cat /tmp/quantum_oracle.log | sed 's/^/    /'

echo
echo "[3/6] Required feature 1+2: full scheduler/memory algorithm-matrix comparison"
python3 -m quantum.cli compare --n 8 --seed 3 --out /tmp/quantum_compare.json \
  > /tmp/quantum_compare.log 2>&1
check "compare (6 scheduler + 4 memory algorithms) (see /tmp/quantum_compare.log)" $?
grep -q "Optimal-minimality holds: True" /tmp/quantum_compare.log
check "Optimal-minimality invariant holds" $?
tail -12 /tmp/quantum_compare.log | sed 's/^/    /'

echo
echo "[4/6] Required feature 3: Belady's Anomaly reproduced on demand"
python3 -m quantum.cli memory --belady --algo fifo --frames 3 > /tmp/quantum_belady3.log 2>&1
python3 -m quantum.cli memory --belady --algo fifo --frames 4 > /tmp/quantum_belady4.log 2>&1
F3=$(grep "page faults:" /tmp/quantum_belady3.log | grep -o '[0-9]\+' | head -1)
F4=$(grep "page faults:" /tmp/quantum_belady4.log | grep -o '[0-9]\+' | head -1)
if [ "$F3" = "9" ] && [ "$F4" = "10" ]; then st=0; else st=1; fi
check "FIFO faults: 3 frames=$F3 (want 9), 4 frames=$F4 (want 10) -- anomaly reproduced" $st

echo
echo "[5/6] Required feature 4: visualizer builds + headless-browser smoke test"
python3 -m quantum.build_visualizer > /tmp/quantum_build_viz.log 2>&1
check "build_visualizer (see /tmp/quantum_build_viz.log)" $?
node tests/visualizer_smoke.js visualizer/index.html > /tmp/quantum_viz_smoke.log 2>&1
check "headless-browser smoke test, zero console errors (see /tmp/quantum_viz_smoke.log)" $?
cat /tmp/quantum_viz_smoke.log | sed 's/^/    /'

echo
echo "[6/6] Stretch features: copy-on-write fork + multiprogramming thrashing cliff"
python3 -m quantum.cli cow --pages 5 > /tmp/quantum_cow.log 2>&1
grep -q "must be False.*False\|False (must be False)" /tmp/quantum_cow.log
check "CoW fork: write diverges exactly one frame (see /tmp/quantum_cow.log)" $?
python3 -m quantum.cli thrash > /tmp/quantum_thrash.log 2>&1
grep -q "collapses" /tmp/quantum_thrash.log
check "thrashing cliff: throughput rises then collapses (see /tmp/quantum_thrash.log)" $?
tail -6 /tmp/quantum_thrash.log | sed 's/^/    /'

echo
echo "============================================================"
echo " RESULT: $PASS passed, $FAIL failed"
echo "============================================================"
[ "$FAIL" -eq 0 ]
