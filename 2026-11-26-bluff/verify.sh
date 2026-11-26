#!/usr/bin/env bash
# Exercises every Bluff feature end-to-end and asserts on the output. Exit 0 = all green.
set -u
cd "$(dirname "$0")"
go build -o ./bluff . || exit 1
B=./bluff; T=$(mktemp -d); pass=0; fail=0
check() { # name, haystack, needle
  if grep -q -- "$3" <<<"$2"; then echo "  ok   $1"; pass=$((pass+1)); else echo "  FAIL $1  (wanted: $3)"; echo "$2" | head -5; fail=$((fail+1)); fi
}
echo "== F1 CFR+ solver"
o=$($B solve kuhn -iters 3000 -out $T/kuhn.json);  check "kuhn value -1/18" "$o" "\-0.0555"
o=$($B solve leduc -iters 2000 -out $T/leduc.json); check "leduc value -0.0856" "$o" "\-0.085[56]"
echo "== F2 exploitability / best response"
o=$($B exploit leduc nit);     check "nit loses exactly 1.0" "$o" "exploitability        1.000000"
o=$($B exploit leduc $T/leduc.json); check "solved ~0 exploitability" "$o" "exploitability        0.0000"
echo "== F3 hold'em equity"
o=$($B equity AhAs KdKc);       check "AA vs KK exact" "$o" "exact"
check "AA vs KK ≈81%" "$o" "81.2"
o=$($B equity -board Ah7d2c "KK" "AKs,QQ+"); check "range vs range on flop" "$o" "exact"
o=$($B equity "QQ+,AKs" random "TT-77");  check "3-way monte carlo" "$o" "Monte Carlo"
o=$($B equity AA KK 2>&1);     check "seeded MC reproducible" "$o" "$($B equity AA KK 2>&1 | sed -n 4p | cut -c1-30)"
echo "== F4 play + match"
o=$(printf 'hint\ncheck\nbet\ncall\nfold\nquit\n' | $B play kuhn -seat 0 -hands 1 -seed 9); check "interactive hint" "$o" "equilibrium play here"
check "interactive result" "$o" "Result:"
o=$($B match leduc -vs maniac -hands 50000); check "match exact EV shown" "$o" "exact EV"
echo "== F5 push/fold"
o=$($B pushfold -stack 10 -hand A5s); check "10bb SB shove%" "$o" "SB shoves 5"
check "A5s shoves" "$o" "A5s: SB shoves 100%"
echo "== F6 HTML report"
$B report -out $T/r.html -iters 500 -stacks 10 >/dev/null; check "report written" "$(head -c 40 $T/r.html)" "doctype"
echo "== F7 strategy save/load"
o=$($B show kuhn -strategy $T/kuhn.json); check "show from file" "$o" "1Q:b"
o=$($B match kuhn -vs $T/kuhn.json -hands 5000); check "match vs file" "$o" "exact EV"
echo "== error handling"
$B solve poker >/dev/null 2>&1; [ $? -ne 0 ] && { echo "  ok   bad game rejected"; pass=$((pass+1)); } || { echo "  FAIL bad game"; fail=$((fail+1)); }
$B equity AhAs AhKd >/dev/null 2>&1; [ $? -ne 0 ] && { echo "  ok   conflicting hands rejected"; pass=$((pass+1)); } || { echo "  FAIL conflict"; fail=$((fail+1)); }
echo "== go test"
go test ./... >/dev/null 2>&1 && { echo "  ok   go test"; pass=$((pass+1)); } || { echo "  FAIL go test"; fail=$((fail+1)); }
rm -rf $T ./bluff
echo; echo "passed $pass, failed $fail"; [ $fail -eq 0 ]
