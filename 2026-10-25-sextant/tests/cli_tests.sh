#!/usr/bin/env bash
# CLI contract: exit codes, messages, and end-to-end behaviour of every command.
set -u
cd "$(dirname "$0")/.."
S=build/sextant
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
pass=0; fail=0
expect() {  # expect <exit-code> <substring> -- <command...>
  local want=$1 sub=$2; shift 3
  local out; out=$("$@" 2>&1); local rc=$?
  if [[ $rc -eq $want && "$out" == *"$sub"* ]]; then pass=$((pass+1)); else
    fail=$((fail+1)); echo "FAIL: $* -> exit $rc (wanted $want), output: ${out:0:200} (wanted substring '$sub')"; fi
}
: > $T/empty.txt
echo "1 2" > $T/one.txt
printf "0 0\n1 0\n0 1\n1 1\n" > $T/sq.txt
printf "1 2\nfoo bar\n" > $T/bad.txt
printf "0 0\n1 0\n0 1\ns 0 7\n" > $T/badseg.txt
printf "0 0\n1 1\n2 2\n3 3\n" > $T/line.txt
printf "0 0\n1 0\n1 1\n0 1\ns 0 1\n" > $T/open.poly
printf "0 0\n1e200 0\n0 1\n" > $T/huge.txt

expect 0 "Usage" -- bash -c "$S --help | sed 's/usage/Usage/'"
expect 2 "unknown command" -- $S bogus
expect 2 "needs exactly one input file" -- $S delaunay
expect 2 "cannot open" -- $S delaunay $T/nope.txt
expect 2 "bad number" -- $S delaunay $T/bad.txt
expect 2 "does not exist" -- $S cdt $T/badseg.txt
expect 3 "magnitude exceeds" -- $S delaunay $T/huge.txt
expect 0 "no triangles" -- $S delaunay $T/empty.txt --verify
expect 0 "all collinear" -- $S delaunay $T/line.txt --verify
expect 0 "2 triangles" -- $S delaunay $T/sq.txt --verify
expect 0 "OK" -- $S voronoi $T/sq.txt --verify
expect 2 "--margin" -- $S voronoi $T/sq.txt --margin -3
expect 2 "needs a value" -- $S voronoi $T/sq.txt --margin
expect 0 "hull: 4 vertices" -- $S hull $T/sq.txt
expect 0 "identical" -- $S hull $T/sq.txt
expect 0 "OK" -- $S nearest $T/sq.txt 0.9 0.8 --verify
expect 2 "no points" -- $S nearest $T/empty.txt 0 0
expect 2 "finite" -- $S nearest $T/sq.txt abc 0
expect 0 "do not enclose a region" -- $S cdt $T/open.poly
expect 2 "needs a PSLG" -- $S refine $T/sq.txt
expect 2 "at least 3" -- $S lloyd $T/one.txt
expect 2 "count must be" -- $S gen uniform abc
expect 2 "unknown generator" -- $S gen nonsense 5
expect 0 "OK" -- bash -c "$S gen uniform 300 --seed 9 | $S check -"
expect 0 "OK" -- bash -c "$S gen gear 10 | $S check -"
expect 0 "OK" -- bash -c "$S gen degenerate 200 | $S check -"
expect 0 "OK" -- bash -c "$S gen circle 5 | $S check -"
expect 0 "OK" -- bash -c "$S gen pentagram | $S cdt - --verify"
expect 0 "segments encroached by a vertex: 0" -- bash -c "$S gen annulus | $S refine - --angle 30 --area 0.05 --verify"
expect 0 "quantisation energy" -- bash -c "$S gen uniform 80 | $S lloyd - --iters 5"
expect 0 "0 duplicates" -- bash -c "$S gen uniform 200 | $S delaunay -"
# outputs are produced and well-formed
$S gen uniform 120 --seed 3 > $T/p.txt
$S delaunay $T/p.txt --svg $T/d.svg --html $T/d.html --mesh $T/d.mesh > /dev/null
$S gen gear 8 | $S refine - --angle 28 --area 0.01 --svg $T/r.svg --html $T/r.html > /dev/null
for f in $T/d.svg $T/r.svg; do
  if head -c 4 $f | grep -q "<svg" && tail -c 8 $f | grep -q "</svg>"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $f is not a complete SVG"; fi
done
for f in $T/d.html $T/r.html; do
  if grep -q "<canvas" $f && grep -q "const D = {" $f && ! grep -q "src=\"http" $f; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $f is not a self-contained viewer"; fi
done
if python3 tests/verify_mesh.py $T/d.mesh --delaunay > /dev/null; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: verify_mesh.py rejected the Delaunay mesh"; fi
echo "cli tests: $pass passed, $fail failed"
[[ $fail -eq 0 ]]
