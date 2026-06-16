#!/usr/bin/env bash
# Resolvent end-to-end demo: exercises every command and feature.
set -e
cd "$(dirname "$0")"
PY="python3 -m resolvent.cli"
hr(){ printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

hr "1. Built-in demo (sudoku + queens + UNSAT proof)"
$PY demo

hr "2. Solve the 'world's hardest' Sudoku"
$PY sudoku examples/sudoku_hard.txt || true

hr "3. 16-Queens"
$PY queens 16 || true

hr "4. 3-color the Petersen graph (SAT) then try 2 colors (UNSAT)"
$PY color examples/petersen.graph -k 3 | head -4 || true
$PY color examples/petersen.graph -k 2 | head -1 || true

hr "5. Pigeonhole PHP(7,6): UNSAT, certified by the independent proof checker"
$PY php 7 6 --check-proof || true

hr "6. Generate a random 3-SAT instance at the phase transition and solve it"
$PY gen --vars 60 --ratio 4.26 --seed 7 --out /tmp/resolvent_demo.cnf
$PY solve /tmp/resolvent_demo.cnf | head -1 || true

hr "7. Exact #SAT model count of a small formula"
$PY gen --vars 12 --ratio 2.0 --seed 3 --out /tmp/resolvent_small.cnf
$PY verify /tmp/resolvent_small.cnf --count

hr "8. Emit a DRAT proof for an UNSAT instance and verify it independently"
python3 - <<'PYEOF'
from resolvent.puzzles.pigeonhole import Pigeonhole
open('/tmp/php54.cnf','w').write(Pigeonhole(5,4).model.cnf.to_dimacs('PHP(5,4)'))
PYEOF
$PY solve /tmp/php54.cnf --proof /tmp/php54.drat || true
$PY verify /tmp/php54.cnf --proof /tmp/php54.drat

hr "9. Generate the interactive HTML implication-graph visualizer"
$PY viz php -a 5 -b 4 --out /tmp/resolvent_php.html
$PY viz queens -a 8 --out /tmp/resolvent_queens.html
echo "open /tmp/resolvent_php.html and /tmp/resolvent_queens.html in a browser"

hr "10. Run the test suite"
python3 -m unittest tests.test_resolvent 2>&1 | tail -3

printf '\n\033[1;32mAll demo steps completed.\033[0m\n'
