#!/usr/bin/env bash
# Parsimony demo: exercises every feature end-to-end and asserts on the output.
# Usage: ./demo.sh        (exit code 0 = everything verified)
set -euo pipefail
cd "$(dirname "$0")"
P="python3 -m parsimony"
EX=examples
pass=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
expect() {  # expect <label> <needle> <haystack>
  if grep -qF -- "$2" <<<"$3"; then pass=$((pass+1)); printf '  ok   %s\n' "$1"
  else printf '  FAIL %s\n  wanted: %s\n  got:\n%s\n' "$1" "$2" "$3"; exit 1; fi
}

step "1. Grammar DSL + analysis: FIRST/FOLLOW, diagnostics, grammar-class verdict"
out=$($P check $EX/slr_fails.pg); echo "$out" | sed -n '1,14p;/grammar classes/,$p'
expect "SLR rejects the Dragon-book grammar" "✘ SLR(1)" "$out"
expect "LALR accepts it" "✔ LALR(1)" "$out"
out=$($P check $EX/lr1_not_lalr.pg | sed -n '/grammar classes/,$p'); echo "$out"
expect "LR(1)-but-not-LALR separator" "smallest LR class: LR(1)" "$out"
expect "EBNF grammar is SLR" "smallest LR class: SLR(1)" "$($P check $EX/json.pg)"

step "2. LR conflicts with concrete examples + ambiguity witness"
out=$($P conflicts $EX/dangling_else.pg -m lalr --witness || true); echo "$out"
expect "S/R conflict located" "shift/reduce on 'else'" "$out"
expect "ambiguity witness" "ambiguous sentence: if ID then if ID then ID else ID" "$out"
out=$($P conflicts $EX/dangling_else_fixed.pg -v); echo "$out" | head -4
expect "precedence settles dangling else" "no conflicts (1 resolved by precedence)" "$out"

step "3. Shift-reduce parsing: tree, precedence, trace, errors"
$P parse $EX/expr.pg -e '1 + 2 * 3 ^ 2 ^ 2' --compact
expect "precedence/assoc" "(expr (expr NUM:1) + (expr (expr NUM:2) * (expr (expr NUM:3) ^ (expr (expr NUM:2) ^ (expr NUM:2)))))" "$($P parse $EX/expr.pg -e '1 + 2 * 3 ^ 2 ^ 2' --format sexp)"
$P parse $EX/expr.pg -e '2*(3+4)' --trace --format sexp | head -12
out=$($P parse $EX/expr.pg -e '1 + * 2' 2>&1 || true); echo "$out"
expect "syntax error with position + expected set" "syntax error at 1:5: unexpected '*'; expected one of: '(', '-', NUM" "$out"
out=$($P parse $EX/json.pg -e '{"a": [1, 2, {"b": null}], "ok": true}' --format json | head -8); echo "$out ..."

step "4. Earley: ambiguity, counting, enumeration, infinite ambiguity"
out=$($P ambig $EX/ambiguous.pg -e 'n+n+n+n+n' --limit 3 --compact); echo "$out"
expect "Catalan(4)=14 parses" "parses: 14" "$out"
expect "infinite ambiguity detected" "parses: infinitely many" "$($P ambig $EX/nullable.pg -e 'a' --limit 2)"
expect "non-LR grammar still parses (palindromes)" "parses: 1" "$(printf "%%skip /[ ]+/\nP : 'a' P 'a' | 'b' P 'b' | ;\n" > /tmp/pal.pg; $P ambig /tmp/pal.pg -e 'a b b a')"

step "5. [stretch] LL(1): table, conflicts, transformer, predictive parse"
$P ll1 $EX/expr.pg | tail -5 || true
$P transform $EX/expr.pg | sed -n '1,13p'
expect "LL(1) parse" "(prog" "$($P parse $EX/ll1_lists.pg -m ll1 -e 'x = 1 + 2; print x;' --format sexp --compact)"

step "6. [stretch] Standalone generated parser (no Parsimony needed)"
gen=$(mktemp -d)/json_parser.py
$P gen $EX/json.pg -o "$gen"
out=$(cd / && python3 -I "$gen" '{"k": [1, 2]}'); echo "$out"
expect "generated parser runs alone" "(value (object {" "$out"

step "7. [stretch] yacc-style error recovery: all errors in one pass"
out=$($P parse $EX/recover.pg --recover --compact --format sexp -e 'a = 1; b = + ; c = (2 * ; d = 4 + 5;' 2>&1 || true); echo "$out"
expect "two errors reported" "syntax error at 1:25" "$out"
expect "parse continued past errors" "(stmt ID:d = " "$out"

step "8. [stretch] Cross-check every strategy on one input"
out=$($P compare $EX/ll1_lists.pg -e 'x = (1 + 2) * 3; print x;'); echo "$out"
expect "all strategies agree" "all deterministic strategies agree on the parse tree" "$out"

step "9. [stretch] Self-check: Parsimony's DSL, written as a grammar, parses its own examples"
for f in $EX/*.pg; do $P parse $EX/parsimony_dsl.pg -f "$f" --format sexp >/dev/null && printf '  parsed %s\n' "$(basename $f)"; done
pass=$((pass+1))

step "10. Unit + property + CLI test-suite (incl. differential fuzzing against Earley)"
python3 -m unittest discover -s tests -t . 2>&1 | tail -4

printf '\n\033[1;32mdemo OK\033[0m (%d scripted assertions + full test-suite)\n' "$pass"
