#!/usr/bin/env bash
# Atlasforge demo: runs the test suite, then generates three showcase worlds.
# Usage: ./demo.sh [output-dir]   (default: ./demo-out)
set -euo pipefail
cd "$(dirname "$0")"
OUT="${1:-demo-out}"
mkdir -p "$OUT"

echo "== 1/4 test suite =="
python3 -m unittest discover -s tests

echo
echo "== 2/4 default world (seed 42) + JSON export =="
python3 -m atlasforge.cli --seed 42 -o "$OUT/realm-42.html" --json "$OUT/realm-42.json"

echo
echo "== 3/4 archipelago (low land fraction) =="
python3 -m atlasforge.cli --seed 1337 --land 0.22 -o "$OUT/archipelago.html"

echo
echo "== 4/4 wide continent (rectangular, land-heavy) =="
python3 -m atlasforge.cli --seed 7 --width 240 --height 120 --land 0.55 \
  -o "$OUT/continent.html" --title "The Sundered Reach"

echo
echo "Demo complete. Open these in a browser:"
ls -la "$OUT"/*.html
