#!/usr/bin/env bash
# Full verification: build, unit tests (ASan+UBSan), predicate differential vs a Fraction oracle,
# fuzzing, CLI contract, independent Python mesh verifier, demo tour, headless-browser check.
set -euo pipefail
cd "$(dirname "$0")"
make -s
mkdir -p build
SRC="src/predicates.cpp src/triangulation.cpp src/voronoi.cpp src/check.cpp src/io.cpp src/refine.cpp"
FLAGS="-std=c++17 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=undefined -ffp-contract=off -Isrc"

echo "== unit tests (ASan + UBSan)"
g++ $FLAGS tests/unit.cpp $SRC -o build/unit_asan
build/unit_asan | tail -4

echo; echo "== predicates vs Python Fraction oracle (20000 adversarial cases)"
g++ -std=c++17 -O2 -ffp-contract=off -Isrc tests/pred_cli.cpp src/predicates.cpp -o build/pred_cli
python3 tests/predicate_diff.py build/pred_cli 10000

echo; echo "== fuzz: lattices / segment soups / refinement / Lloyd (ASan + UBSan), 3 seeds"
g++ $FLAGS tests/fuzz.cpp $SRC -o build/fuzz_asan
for seed in 1 2 3; do build/fuzz_asan 1500 $seed | grep -E "^(fuzz|refine|note|FAIL)"; done

echo; echo "== CLI contract"
tests/cli_tests.sh

echo; echo "== independent Python verifier (exact rationals, shares no code with C++)"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
for k in "uniform 200" "grid 12" "circle 4" "cluster 200" "degenerate 100" "spiral 120"; do
  set -- $k
  build/sextant gen $1 $2 --seed 4 > $T/p.txt
  build/sextant delaunay $T/p.txt --mesh $T/m.mesh > /dev/null
  printf "%-12s" "$1"; python3 tests/verify_mesh.py $T/m.mesh --delaunay
done
for k in "annulus 1" "gear 8" "comb 5" "pentagram 1"; do
  set -- $k
  build/sextant gen $1 $2 > $T/p.poly
  build/sextant refine $T/p.poly --angle 25 --area 0.05 --mesh $T/m.mesh > /dev/null
  printf "%-12s" "refine $1"; python3 tests/verify_mesh.py $T/m.mesh
done

echo; echo "== demo tour (must run clean)"
./demo.sh > $T/demo.log
tail -3 $T/demo.log
echo "demo OK"

if command -v node >/dev/null 2>&1 && node -e "require('playwright')" 2>/dev/null; then
  echo; echo "== viewers in headless Chromium (light, dark, phone; no console errors, hover, toggles)"
  node tests/browser_check.js out
else
  echo "(skipping browser check: node + playwright not available)"
fi
echo; echo "ALL GREEN"
