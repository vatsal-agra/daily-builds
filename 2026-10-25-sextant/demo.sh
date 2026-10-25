#!/usr/bin/env bash
# Guided tour of every feature. Writes pictures and interactive viewers into out/.
set -euo pipefail
cd "$(dirname "$0")"
make -s
S=build/sextant
mkdir -p out
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

echo "== 1. exact predicates: where naive floating point lies"
python3 tests/predicate_diff.py build/pred_cli 3000 2>/dev/null || { g++ -std=c++17 -O2 -ffp-contract=off -Isrc tests/pred_cli.cpp src/predicates.cpp -o build/pred_cli; python3 tests/predicate_diff.py build/pred_cli 3000; }

echo; echo "== 2. Delaunay: 300 random points, then 400 exactly-cocircular lattice points on a circle, then a 100x100 lattice"
$S gen uniform 300 --seed 2 > $T/u.txt
$S delaunay $T/u.txt --verify --svg out/delaunay.svg --html out/delaunay.html
$S gen circle 6 > $T/circle.txt
$S delaunay $T/circle.txt --verify --stats
$S gen grid 100 > $T/grid.txt
$S delaunay $T/grid.txt --stats

echo; echo "== 2b. everything that breaks naive code, at once (duplicates, collinear tail, 2^-40 slivers)"
$S gen degenerate 400 > $T/deg.txt
$S delaunay $T/deg.txt --verify --svg out/degenerate.svg

echo; echo "== 3. Voronoi + hull + nearest neighbour"
$S voronoi $T/u.txt --verify --svg out/voronoi.svg --html out/voronoi.html
$S hull $T/u.txt | head -3
$S nearest $T/u.txt 0.5 0.5 --verify

echo; echo "== 4. constrained Delaunay: gear with a hole, a pentagram (self-crossing), a comb"
$S gen gear 10 > $T/gear.poly
$S cdt $T/gear.poly --verify --svg out/cdt-gear.svg
$S gen pentagram > $T/pent.poly
$S cdt $T/pent.poly --verify --svg out/cdt-pentagram.svg
$S gen comb 8 > $T/comb.poly
$S cdt $T/comb.poly --verify --svg out/cdt-comb.svg

echo; echo "== 5. Ruppert refinement: minimum angle 30 degrees"
$S refine $T/gear.poly --angle 30 --area 0.002 --verify --svg out/refine-gear.svg --html out/refine-gear.html
$S refine $T/comb.poly --angle 28 --area 0.2 --verify --svg out/refine-comb.svg

echo; echo "== 7. Lloyd relaxation: random points -> blue-noise-like centroidal Voronoi"
$S gen uniform 150 --seed 5 > $T/l.txt
$S lloyd $T/l.txt --iters 40 --svg out/lloyd.svg --html out/lloyd.html

echo; echo "== 8. independent certificate on everything above"
for f in $T/u.txt $T/deg.txt $T/circle.txt $T/grid.txt $T/gear.poly $T/pent.poly $T/comb.poly; do printf "%-28s" "$(basename $f)"; $S check $f | head -1; done

echo; echo "pictures and viewers written to out/:"; ls out
