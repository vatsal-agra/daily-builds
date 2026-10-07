#!/usr/bin/env bash
# End-to-end demo: exercises every Dantzig feature and asserts on the results.
set -u
cd "$(dirname "$0")"
BIN=$(mktemp -d)/dantzig
go build -o "$BIN" ./cmd/dantzig || exit 1
W=$(mktemp -d)
pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  FAIL %s\n' "$1"; }
has()  { if grep -qF -- "$2" <<<"$1"; then ok "$3"; else bad "$3 (missing: $2)"; echo "$1" | head -20; fi; }

echo "== 1. language: parse, canonical format, positioned errors"
out=$("$BIN" fmt examples/production.lp); has "$out" "Maximize" "fmt prints canonical model"
printf 'Minimize\n o: x\nSubject To\n c: x + y @ 3 <= 4\nEnd\n' > $W/bad.lp
out=$("$BIN" solve $W/bad.lp 2>&1); has "$out" "line 4, col 11" "syntax error position"

echo "== 2/3. LP: optimal, infeasible, unbounded - each with an exact certificate"
for spec in "diet:OPTIMAL:1268/9" "infeasible:INFEASIBLE:" "unbounded:UNBOUNDED:"; do
  IFS=: read f st extra <<<"$spec"
  out=$("$BIN" solve examples/$f.lp --proof $W/$f.json); has "$out" "status: $st (exact certificate verified)" "$f status"
  [ -n "$extra" ] && has "$out" "$extra" "$f exact objective $extra"
  out=$("$BIN" check examples/$f.lp $W/$f.json); has "$out" "VERIFIED" "$f proof re-verified by independent checker"
done

echo "== 4. MIP: branch & bound with certified proof tree"
out=$("$BIN" solve examples/knapsack.lp --proof $W/k.json); has "$out" "objective (max): 29" "knapsack optimum 29"
out=$("$BIN" check examples/knapsack.lp $W/k.json); has "$out" "VERIFIED" "knapsack proof verifies"
out=$("$BIN" solve examples/parity.lp --proof $W/p.json); has "$out" "INFEASIBLE (exact certificate verified)" "integer-infeasible parity model"
"$BIN" gen tsp 9 2 > $W/tsp.lp
out=$("$BIN" solve $W/tsp.lp --proof $W/tsp.json --quiet); has "$out" "OPTIMAL (exact certificate verified)" "TSP-9 solved and certified"
out=$("$BIN" check $W/tsp.lp $W/tsp.json); has "$out" "VERIFIED" "TSP proof tree verified"
sed 's/"objective": "253"/"objective": "250"/' $W/tsp.json > $W/tsp_bad.json
out=$("$BIN" check $W/tsp.lp $W/tsp_bad.json); has "$out" "REJECTED" "tampered proof rejected"
out=$("$BIN" check examples/knapsack.lp $W/tsp.json); has "$out" "REJECTED" "proof for another model rejected"

echo "== 5. sensitivity analysis"
out=$("$BIN" sens examples/diet.lp); has "$out" "SHADOW PRICE" "sens table"; has "$out" "34/315" "exact shadow price of calories"

echo "== 6. generators (+ solve each)"
for spec in "knapsack 30 1" "setcover 25 30 1" "assignment 12 1" "facility 5 10 1" "transport 5 8 1" "sudoku hard"; do
  "$BIN" gen $spec > $W/g.lp
  out=$("$BIN" solve $W/g.lp --quiet --proof $W/g.json); has "$out" "(exact certificate verified)" "gen $spec certified"
  out=$("$BIN" check $W/g.lp $W/g.json); has "$out" "VERIFIED" "gen $spec re-verified"
done

echo "== 7. search controls"
"$BIN" gen knapsack 45 3 3 > $W/kn.lp
out=$("$BIN" solve $W/kn.lp --nodes 5 --quiet --proof $W/lim.json); has "$out" "status: LIMIT" "node limit stops the search"
has "$out" "proven bound" "limit run reports a proven bound"
out=$("$BIN" check $W/kn.lp $W/lim.json); has "$out" "proven bound" "partial proof verifies its bound"
out=$("$BIN" solve $W/kn.lp --branch mostfrac --quiet); has "$out" "OPTIMAL" "most-fractional branching"
out=$("$BIN" solve $W/kn.lp --log --quiet 2>&1); has "$out" "gap" "progress log shows gap"

echo "== 8. HTML report"
"$BIN" report $W/tsp.lp $W/r.html >/dev/null; has "$(cat $W/r.html)" "Proof tree" "report has proof tree"
has "$(cat $W/r.html)" "Search convergence" "report has convergence chart"

echo
echo "demo: $pass passed, $fail failed"
[ $fail -eq 0 ]
