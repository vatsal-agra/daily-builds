#!/usr/bin/env bash
# Shannon — end-to-end demonstration of every feature.
# Usage: ./demo.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "=============================================================="
echo " Shannon demo — pure-Python compression toolkit"
echo "=============================================================="

echo
echo ">> 1. Self-checking demo (round-trips + property + integrity checks)"
$PY cli.py demo

echo
echo ">> 2. Compress a real file with every codec and round-trip it"
SRC=PLAN.md
for m in store huffman arith0 arith1 lz77 bwt; do
  $PY cli.py compress "$SRC" -m "$m" -o "$TMP/p.$m.shz" | sed 's/^/   /'
  $PY cli.py decompress "$TMP/p.$m.shz" -o "$TMP/out.$m" >/dev/null
  cmp -s "$SRC" "$TMP/out.$m" && echo "   verified: $m decompresses byte-identical"
done

echo
echo ">> 3. Auto-pick the best codec"
$PY cli.py compress "$SRC" --best -o "$TMP/best.shz" | sed 's/^/   /'
$PY cli.py info "$TMP/best.shz" | sed 's/^/   /'

echo
echo ">> 4. Entropy + codec comparison report"
$PY cli.py analyze "$SRC"

echo
echo ">> 5. Generate the interactive HTML report"
$PY cli.py viz "$SRC" -o "$TMP/report.html" | sed 's/^/   /'

echo
echo ">> 6. Full test suite"
$PY -m unittest discover -s tests 2>&1 | tail -3

echo
echo "All demo steps completed successfully."
