#!/usr/bin/env bash
# Loom verification script (Phase 5): runs the automated test suite, then
# runs the full CLI pipeline end to end (gradcheck -> train -> generate ->
# viz export) via `loom demo`. Exits nonzero on any failure.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================================="
echo "1/2  Automated test suite (unittest)"
echo "=================================================================="
python3 -m unittest tests.test_loom -v

echo
echo "=================================================================="
echo "2/2  Full pipeline walkthrough: loom_cli demo"
echo "=================================================================="
./loom_cli demo --steps 500

echo
echo "=================================================================="
echo "ALL GREEN."
echo "=================================================================="
