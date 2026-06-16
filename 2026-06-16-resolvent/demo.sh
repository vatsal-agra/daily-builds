#!/usr/bin/env bash
# Resolvent — end-to-end demo. Exercises every feature from the CLI.
# Usage: ./demo.sh
set -euo pipefail
cd "$(dirname "$0")"
PY="python3 -m resolvent"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

hr() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }

# The solver uses DIMACS competition exit codes (10=SAT, 20=UNSAT). Treat those
# as success under `set -e`; anything else is a real error.
sat() { "$@" || { rc=$?; [ "$rc" -eq 10 ] || [ "$rc" -eq 20 ] || return "$rc"; }; }

hr "0. Self-test suite (brute-force differential + every feature)"
python3 -m unittest discover -s tests -q

hr "1. Generate a random 3-SAT instance at the phase transition"
$PY gen --vars 60 --clauses 256 --seed 1 --out "$TMP/rand.cnf"
head -1 "$TMP/rand.cnf"

hr "2. Solve it (CDCL) and verify the model"
sat $PY solve "$TMP/rand.cnf" | tee "$TMP/out.txt"
grep '^v' "$TMP/out.txt" > "$TMP/model.txt" || true
$PY check "$TMP/rand.cnf" "$TMP/model.txt"

hr "3. N-Queens (N=12): encode -> solve -> decode"
sat $PY solve-puzzle queens --n 12

hr "4. Sudoku (a hard grid): encode -> solve -> decode"
sat $PY solve-puzzle sudoku

hr "5. Graph coloring: 3-color a 5-cycle (SAT)"
printf '5\n0 1\n1 2\n2 3\n3 4\n4 0\n' > "$TMP/c5.txt"
sat $PY solve-puzzle color --graph "$TMP/c5.txt" --colors 3

hr "6. Pigeonhole PHP(6,5) is UNSAT -> emit + independently check a DRUP proof"
$PY encode pigeonhole --holes 5 --out "$TMP/php.cnf"
sat $PY solve-puzzle pigeonhole --holes 5 --proof "$TMP/php.drup"
$PY proofcheck "$TMP/php.cnf" "$TMP/php.drup"

hr "7. Differential fuzz: 1000 random instances vs the brute-force oracle"
$PY fuzz -n 1000 --max-vars 13 --seed 7 2>/dev/null

hr "8. Phase-transition sweep (P(SAT) collapses around ratio 4.26)"
$PY bench --vars 70 --lo 3.5 --hi 5.5 --step 0.5 --trials 15

hr "9. Implication-graph visualizer -> self-contained HTML"
$PY viz "$TMP/rand.cnf" --out "$TMP/impl.html"
echo "wrote $(wc -c < "$TMP/impl.html") bytes of dependency-free HTML"

hr "ALL FEATURES EXERCISED — demo complete"
