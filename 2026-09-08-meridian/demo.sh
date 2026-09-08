#!/usr/bin/env bash
# Meridian verification script: runs the full test suite, a randomized
# multi-feature fuzz sweep, a walkthrough of every CLI subcommand, and a
# headless-Chromium check of the interactive visualizer. Exits non-zero if
# anything fails; prints a numbered PASS/FAIL for each check either way.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
N=0

check() {
  N=$((N + 1))
  local desc="$1"; shift
  echo ""
  echo "[$N] $desc"
  echo "    \$ $*"
  if "$@" > /tmp/meridian_demo_check_$N.log 2>&1; then
    echo "    PASS"
    PASS=$((PASS + 1))
  else
    echo "    FAIL (exit $?) -- see /tmp/meridian_demo_check_$N.log"
    tail -n 25 /tmp/meridian_demo_check_$N.log | sed 's/^/    | /'
    FAIL=$((FAIL + 1))
  fi
}

echo "=============================================="
echo " Meridian verification"
echo "=============================================="

check "unit test suite" python3 -m unittest discover -s tests
check "multi-feature fuzz sweep (60 seeds)" python3 scripts/fuzz_sweep.py

mkdir -p /tmp/meridian_demo_artifacts
SAMPLE_FILE=/tmp/meridian_demo_artifacts/sample.txt
python3 - "$SAMPLE_FILE" <<'PYEOF'
import sys
path = sys.argv[1]
text = "Meridian demo.sh sample file.\n" * 300
with open(path, "w") as f:
    f.write(text)
PYEOF

check "CLI: run (with churn)" python3 -m meridian.cli run --nodes 40 --seed 100 --ticks 5000 --churn --lookups 15
check "CLI: demo (scripted end-to-end walkthrough)" python3 -m meridian.cli demo --nodes 30 --seed 101
check "CLI: filedemo (real file, cross-node retrieval)" python3 -m meridian.cli filedemo "$SAMPLE_FILE" --nodes 20 --seed 102
check "CLI: filedemo on an empty file" bash -c 'F=/tmp/meridian_demo_artifacts/empty.bin; : > "$F"; python3 -m meridian.cli filedemo "$F" --nodes 10 --seed 103'
check "CLI: viz (writes trace.json + standalone HTML viewer)" python3 -m meridian.cli viz --nodes 30 --seed 104 --lookups 10 --churn-ticks 1500 --out /tmp/meridian_demo_artifacts/trace.json --html-out /tmp/meridian_demo_artifacts/replay.html

if command -v node > /dev/null 2>&1; then
  export NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}"
  check "headless-Chromium smoke test of the visualizer" node scripts/viz_smoke.js /tmp/meridian_demo_artifacts/replay.html
else
  echo ""
  echo "[skip] node not found -- skipping headless-Chromium visualizer check"
fi

check "CLI: bad input is a clean error, not a traceback" bash -c '! python3 -m meridian.cli run --nodes 0 2>&1 | grep -q Traceback'

echo ""
echo "=============================================="
echo " $PASS/$((PASS + FAIL)) checks passed"
echo "=============================================="

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
exit 0
