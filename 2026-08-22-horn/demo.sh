#!/usr/bin/env bash
# Phase 5 verification: exercises every feature end-to-end through the real
# `horn` CLI (not the Python API directly), and fails loudly (set -e) the
# moment anything doesn't behave as expected. Run from the project root:
#   ./demo.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

pass() { echo "  ok: $1"; }
step() { echo; echo "=== $1 ==="; }

step "1/8 unit test suite (pytest)"
python3 -m pytest -q tests
pass "all unit tests green"

step "2/8 built-in assertion-checked walkthrough (horn demo)"
python3 -m horn demo
pass "horn demo: all checks green"

step "3/8 family tree (facts, rules, recursion)"
out=$(python3 -m horn query examples/family.horn "ancestor(tom, jim).")
[ "$out" = "true." ]
pass "ancestor(tom, jim) -- $out"
out=$(python3 -m horn query examples/family.horn "grandparent(marge, X)." --all)
[ "$out" = "$(printf 'X = ann.\nX = pat.')" ]
pass "grandparent(marge, X), all solutions correct"

step "4/8 N-Queens (generate-and-test CSP search)"
out=$(python3 -m horn query examples/queens.horn "findall(Qs, queens(6, Qs), All), length(All, N).")
echo "  $out"
echo "$out" | grep -q "N = 4"
pass "6-Queens: exactly 4 solutions (published count)"

step "5/8 Australia map coloring (CSP)"
out=$(python3 -m horn query examples/map_coloring.horn "findall(c(WA,NT,SA,Q,NSW,V,T), australia(WA,NT,SA,Q,NSW,V,T), L), length(L, N).")
echo "$out" | grep -q "N = 18"
pass "Australia map coloring: exactly 18 solutions"

step "6/8 Zebra puzzle (unique-answer constraint satisfaction)"
out=$(python3 -m horn query examples/zebra.horn "water_drinker(X).")
[ "$out" = "X = norwegian." ]
pass "water_drinker(X) -- $out"
out=$(python3 -m horn query examples/zebra.horn "zebra_owner(X).")
[ "$out" = "X = japanese." ]
pass "zebra_owner(X) -- $out"

step "7/8 REPL (consult, multi-solution stepping, halt)"
out=$(printf "member(X,[a,b,c]).\n;\n;\n.\nhalt.\n" | python3 -m horn repl examples/family.horn)
echo "$out" | grep -q "X = a."
echo "$out" | grep -q "X = b."
echo "$out" | grep -q "X = c."
echo "$out" | grep -q "halt(0)"
pass "REPL: consult + 3-solution stepping + halt all correct"

step "8/8 HTML SLD-resolution-tree visualizer"
tmp_html="$(mktemp -d)/trace.html"
python3 -m horn viz examples/family.horn -q "ancestor(tom, X)." --out "$tmp_html"
[ -s "$tmp_html" ]
grep -q "<script>" "$tmp_html"
grep -q "Solutions found (5)" "$tmp_html"
pass "wrote a non-empty, self-contained trace HTML with 5 solutions"

echo
echo "======================================"
echo " ALL DEMO CHECKS PASSED"
echo "======================================"
