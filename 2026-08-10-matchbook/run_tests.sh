#!/usr/bin/env bash
# Verification (Phase 5): the full unit-test suite, the differential
# fuzz harness, the end-to-end demo, and the pluggable-agent example —
# every feature this project claims to have, actually run.
set -euo pipefail
cd "$(dirname "$0")"

echo "== unit test suite =="
python3 -m unittest discover -s tests -p "test_*.py" -v

echo
echo "== differential fuzz harness (stretch feature) =="
python3 fuzz.py --trials 300 --ops-per-trial 200 --seed 0

echo
echo "== end-to-end demo session =="
python3 demo.py --ticks 3000 --seed 42

echo
echo "== pluggable Agent SDK example (stretch feature) =="
python3 examples/custom_agent_demo.py

echo
echo "ALL GREEN."
