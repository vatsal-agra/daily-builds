#!/usr/bin/env bash
# Cotangent end-to-end demo. Exercises every feature; pure stdlib Python 3.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
OUT="${OUT_DIR:-./demo_out}"
mkdir -p "$OUT"

echo "==================================================================="
echo " COTANGENT — reverse-mode autodiff engine + neural-net trainer"
echo "==================================================================="

echo
echo ">> 1. Gradient check: analytic gradients vs central finite differences"
$PY cotangent.py gradcheck

echo
echo ">> 2. Computation-graph HTML for  out = tanh(a*b + c)"
$PY cotangent.py graph --a 1.5 --b -2.0 --c 3.0 --out "$OUT/graph.html"

echo
echo ">> 3. Train an MLP on each easy dataset (xor / moons / circles)"
for ds in xor moons circles; do
  echo "   --- $ds ---"
  $PY cotangent.py train --dataset "$ds" --hidden 16,16 --epochs 60 \
      --n 140 --optimizer adam
done

echo
echo ">> 4. Adam vs SGD on the same net (moons)"
$PY cotangent.py compare --dataset moons --hidden 12,12 --epochs 40 --n 120

echo
echo ">> 5. Interactive training-playground HTML"
echo "      (moons = fast; spiral = the hard two-arm case, ~4 min, reaches ~95%)"
$PY cotangent.py viz --dataset moons --hidden 16,16 --epochs 60 \
    --n 140 --frames 20 --out "$OUT/playground_moons.html"
$PY cotangent.py viz --dataset spiral --hidden 24,24 --epochs 120 \
    --lr 0.05 --frames 24 --out "$OUT/playground_spiral.html"

echo
echo ">> 6. Full test suite"
$PY tests/test_cotangent.py

echo
echo "Done. Open the HTML files in $OUT/ :"
ls -1 "$OUT"
