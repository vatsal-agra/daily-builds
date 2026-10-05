#!/usr/bin/env bash
# Guided tour: exercises every Kepler feature. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")"
go build -o kepler ./cmd/kepler
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
need() { grep -qF -- "$1" <<<"$2" || { echo "DEMO FAILED: expected '$1' in output:"; echo "$2"; exit 1; }; }

say "1. Expression engine: parse, evaluate, simplify"
out=$(./kepler eval "x^3 - x - x + 2*x - 3 + 5" x=2); echo "$out"; need "x^3 + 2" "$out"

say "2. Symbolic differentiation (stretch)"
out=$(./kepler diff "x^2*sin(x)" x); echo "$out"; need "2 * x * sin(x) + x^2 * cos(x)" "$out"

say "3. Rediscover Kepler's third law from orbit data (GP + constant fitting + Pareto)"
./kepler gen kepler > "$T/kepler.csv"; head -3 "$T/kepler.csv"
out=$(./kepler fit -q "$T/kepler.csv"); echo "$out"; need "T = a^1.5" "$out"

say "4. Multi-variable law with noise-free constants: kinetic energy"
./kepler gen kinetic > "$T/k.csv"
out=$(./kepler fit -q -report "$T/k.html" "$T/k.csv"); echo "$out" | tail -4; need "0.5 * m * v^2" "$out"; test -s "$T/k.html"

say "5. Your own CSV, target column chosen by name, Ctrl-C-safe time budget"
printf 'speed,mass,drag\n' > "$T/own.csv"
python3 - >> "$T/own.csv" <<'PY'
import random; random.seed(3)
for _ in range(60):
    v=random.uniform(1,9); m=random.uniform(1,4); print(f"{v},{m},{0.5*1.2*v*v/m}")
PY
out=$(./kepler fit -q -time 20s -target drag "$T/own.csv"); echo "$out" | tail -3; need "drag = " "$out"

say "6. Benchmark suite: all 7 physical laws, with HTML report (stretch)"
out=$(./kepler bench -report "$T/bench.html"); echo "$out" | grep -E "found|laws"; need "7/7 laws rediscovered" "$out"; test -s "$T/bench.html"

say "7. Bad input is rejected with a useful message"
printf 'x,y\n1,2\n2,oops\n3,6\n4,8\n5,10\n' > "$T/bad.csv"
if ./kepler fit -q "$T/bad.csv" 2>"$T/err"; then echo "DEMO FAILED: bad csv accepted"; exit 1; fi
cat "$T/err"; need "row 3" "$(cat "$T/err")"

say "8. Unit tests (race detector on the fast ones)"
go test -short -race ./expr ./opt ./data ./report
echo; echo "DEMO PASSED"
