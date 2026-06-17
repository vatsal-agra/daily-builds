#!/usr/bin/env bash
# Conflux end-to-end demo — exercises every feature.
set -e
cd "$(dirname "$0")"
PY="python3 -m conflux"

hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

hr "1. Sudoku (the classic) — encode → solve → validate"
$PY sudoku "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"

hr "2. AI escargot (one of the hardest 9x9 sudokus)"
$PY sudoku "1....7.9..3..2...8..96..5....53..9...1..8...26....4...3......1..4......7..7...3.."

hr "3. 12-Queens"
$PY queens 12

hr "4. Graph coloring — Petersen graph with 3 colors"
$PY color petersen 3

hr "5. Pigeonhole PHP(7,6) — provably UNSAT, with a verified DRAT proof"
$PY php 7 6

hr "6. Solve a DIMACS file with model verification"
$PY gen --vars 60 --ratio 4.0 --seed 11 > /tmp/conflux_demo.cnf
$PY solve /tmp/conflux_demo.cnf --check

hr "7. explain — the anatomy of a conflict (implication graph + 1-UIP)"
$PY gen --vars 14 --ratio 4.6 --seed 3 > /tmp/conflux_explain.cnf
$PY explain /tmp/conflux_explain.cnf

hr "8. Random 3-SAT phase transition (the α≈4.26 threshold)"
$PY phase --vars 50 --steps 18 --samples 25 --seed 7

hr "9. Generate the interactive HTML visualizer"
$PY viz web/conflux.html
echo "open web/conflux.html in a browser to watch CDCL run step-by-step"

hr "10. Full test suite"
python3 -m unittest tests.run_tests 2>&1 | tail -4

printf '\n\033[1;32mAll demos complete.\033[0m\n'
