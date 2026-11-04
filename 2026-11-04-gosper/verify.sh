#!/usr/bin/env bash
# Full verification gate for Gosper. Ends with ALL GREEN or exits non-zero.
set -euo pipefail
cd "$(dirname "$0")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
eq() { [[ "$2" == *"$3"* ]] || fail "$1: expected output to contain [$3], got:
$2"; echo "  ok  $1"; }

echo "== build / format / vet"
[[ -z "$(gofmt -l .)" ]] || fail "gofmt"
go vet ./...
go build -o "$T/gosper" .
G="$T/gosper"

echo "== unit + property tests"
go test ./... 2>&1 | tail -3

echo "== differential: Hashlife vs naive oracle (400 random soups, 8 named + random rules)"
$G verify -n 400 -seed 7 | tee "$T/v.txt"; eq "verify zero failures" "$(cat $T/v.txt)" "0 failures"

echo "== CLI feature walk-through"
eq "patterns list" "$($G patterns)" "gosper-gun"
eq "info" "$($G info rpentomino)" "population: 5"
out=$($G run gosper-gun -gens 2^40 -o $T/gun.mc); eq "2^40 jump pop" "$out" "population: 183,251,938,004"
eq "macrocell reload" "$($G info $T/gun.mc)" "population: 183,251,938,004"
out=$($G run rpentomino -gens 1103 -o $T/r.rle); eq "rpent @1103" "$out" "population: 116"
eq "rle reload+analyze" "$($G analyze $T/r.rle --horizon 0 --growth 4)" "population settles"
out=$($G run glider -gens 4 -show); eq "glider shifts" "$out" "bounding:   3 x 3  (x 0..2, y 0..2)"
out=$($G analyze glider); eq "glider ship" "$out" "spaceship, period 4"; eq "glider speed" "$out" "1c/4 diagonal"
out=$($G analyze lwss); eq "lwss speed" "$out" "2c/4 orthogonal"
eq "pentadecathlon" "$($G analyze pentadecathlon)" "oscillator, period 15"
eq "block still" "$($G analyze block)" "still life"
eq "diehard dies" "$($G analyze diehard)" "dies out at generation 130"
out=$($G analyze rpentomino); eq "rpent settle" "$out" "settles into period 1 from generation 1,103"; eq "rpent lookahead" "$out" "CONFIRMED"
eq "acorn settle" "$($G analyze acorn)" "from generation 5,206"
eq "gun linear" "$($G analyze gosper-gun --growth 28)" "linear growth"
eq "highlife rule from lib" "$($G run highlife-replicator -gens 64)" "rule B36/S23"
printf '!Name: t\n.O.\n..O\nOOO\n' > $T/g.cells
eq "plaintext in" "$($G analyze $T/g.cells)" "spaceship"
eq "stdin in" "$(printf 'bob$2bo$3o!' | $G analyze -)" "spaceship"
eq "rule override" "$($G run glider -rule B36/S23 -gens 8)" "rule B36/S23"
eq "bad rule rejected" "$($G run glider -rule B0/S23 2>&1 || true)" "B0 rules are not supported"
eq "bad gens rejected" "$($G run glider -gens -4 2>&1 || true)" "bad generation count"
eq "missing file rejected" "$($G info nope.rle 2>&1 || true)" "neither a built-in pattern"
eq "budget error graceful" "$(printf 'x=1,y=1,rule=B2/S\n' > $T/s.rle; python3 - >> $T/s.rle <<'PY'
import random; random.seed(3)
print('$'.join(''.join('o' if random.random()<.5 else 'b' for _ in range(150)) for _ in range(150))+'!')
PY
$G run $T/s.rle -gens 5000 2>&1 || true)" "node budget exceeded"

echo "== census (stretch)"
out=$($G census -soups 300 -gens 800 -seed 3 -top 6); echo "$out" | head -8; eq "census block first" "$(echo "$out" | sed -n 5p)" "block"
a=$($G census -soups 60 -gens 400 -seed 9 -top 3); b=$($G census -soups 60 -gens 400 -seed 9 -top 3)
[[ "${a#*(}" == "${b#*(}" || "$(echo "$a" | tail -n +2)" == "$(echo "$b" | tail -n +2)" ]] || fail "census nondeterministic"; echo "  ok  census deterministic"

echo "== render + report (stretch)"
$G render gosper-gun -gens 2^36 -o $T/g.png -size 400 >/dev/null
[[ "$(head -c 4 $T/g.png | tail -c 3)" == "PNG" ]] || fail "png header"; echo "  ok  png written"
$G report acorn -o $T/acorn.html >/dev/null
$G report gosper-gun -o $T/gun.html >/dev/null
$G report glider -o $T/glider.html >/dev/null
if node -e "require('playwright')" 2>/dev/null; then
  for f in acorn gun glider; do echo " $f:"; node check_report.js $T/$f.html; done
else echo "  (skipped headless check: playwright not installed)"; fi

echo
echo "ALL GREEN"
