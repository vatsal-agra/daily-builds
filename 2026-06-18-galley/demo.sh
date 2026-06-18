#!/usr/bin/env bash
# Galley demo runner — exercises every feature and writes artifacts.
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
OUT=${1:-demo_out}

echo "############################################################"
echo "# Galley — optimal typesetting demo"
echo "############################################################"

echo
echo ">> Running the test suite"
$PY -m unittest discover -s tests -v

echo
echo ">> hyphenate"
$PY galley.py hyphenate typesetting algorithm beautiful representation knuth

echo
echo ">> break (Knuth-Plass, ASCII column)"
$PY galley.py break --width 56

echo
echo ">> compare (Knuth-Plass vs greedy)"
$PY galley.py compare --width 252

echo
echo ">> guided tour + artifacts -> $OUT/"
$PY galley.py demo --outdir "$OUT"

echo
echo "Done. Artifacts in $OUT/ :"
ls -1 "$OUT"
echo
echo "Open $OUT/compare.html and $OUT/playground.html in a browser,"
echo "or view $OUT/preview.png directly (no browser needed)."
