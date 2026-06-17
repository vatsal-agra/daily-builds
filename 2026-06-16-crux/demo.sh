#!/usr/bin/env bash
# Crux end-to-end demo: exercises every feature, then runs the test suite.
# Usage: ./demo.sh        (from the project root)
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

hr "1. Solve a random 3-SAT instance"
$PY -m crux gen --vars 40 --clauses 160 --seed 1 | $PY -m crux solve
echo "(exit codes: 10=SAT 20=UNSAT 0=UNKNOWN)"

hr "2. Solve & decode a real 9x9 Sudoku"
$PY -m crux decode sudoku examples/sudoku_hard.txt

hr "3. 8-Queens"
$PY -m crux decode queens -n 8

hr "4. Graph 3-colouring of C5"
$PY -m crux decode coloring examples/graph_c5.txt -k 3

hr "5. Pigeonhole 6->5 is UNSAT"
$PY -m crux encode pigeonhole -m 6 -n 5 | $PY -m crux solve

hr "6. Differential fuzz vs brute force (2000 formulas)"
$PY -m crux fuzz --trials 2000 --vars 7

hr "7. Exact model count, cross-checked vs brute force"
$PY -m crux gen --vars 8 --clauses 18 --seed 5 | $PY -m crux count --verify

hr "8. UNSAT proof, independently verified (DRUP/RUP)"
$PY -m crux encode pigeonhole -m 5 -n 4 | $PY -m crux proof

hr "9. Generate the interactive conflict-analysis visualizer"
$PY -m crux viz --problem pigeonhole -m 5 -n 4 --out web/crux-viz.html

hr "10. Guided feature tour"
$PY -m crux demo >/dev/null && echo "crux demo: ALL CHECKS PASSED"

hr "11. Unit test suite"
$PY -m unittest discover -s tests 2>&1 | tail -4

echo
echo "Done. Open web/crux-viz.html in a browser to explore conflict analysis."
