#!/usr/bin/env bash
# Runnable demo + verification: exercises every feature through the CLI and asserts on the results.
set -u
cd "$(dirname "$0")"
OUT=$(mktemp -d); fail=0
check() { # name, expected-rc, pattern, command...
  local name=$1 rc=$2 pat=$3; shift 3
  local out; out=$("$@" 2>&1); local got=$?
  if [ "$got" -eq "$rc" ] && grep -qE -- "$pat" <<<"$out"; then echo "PASS  $name"; else echo "FAIL  $name (rc=$got, wanted $rc / /$pat/)"; echo "$out" | head -12; fail=1; fi
}
D="python3 -m delve"
echo "== F1 language + concrete interpreter"
check "run returns value"       0 "returned 3"          $D run examples/safe_sum.dl --width 16 -i n=2
check "run traps"               1 "TRAP: signed overflow at line 2" $D run examples/abs.dl -i n=-128
check "run rejects bad literal" 64 "does not fit"       $D run examples/safe_sum.dl --width 4
echo "== F2 SMT / SAT solver"
check "solve sat"               0 "x=0, y=42"           $D solve 'x*3 + y == 42 && x < y'
check "solve unsat"             1 "UNSAT"               $D solve 'x*x == 2'
check "solve proves identity"   0 "VALID"               $D solve '(x ^ y) + 2*(x & y) == x + y' --prove --width 12
check "solve finds overflow"    1 "x=127"               $D solve 'x + 1 > x' --prove
echo "== F3 path exploration + test generation"
check "clean program exhaustive" 0 "Exploration was exhaustive" $D analyze examples/safe_sum.dl --width 16 --loop-bound 12 -q
check "tests file written"      1 "wrote 12 tests"      $D analyze examples/triage.dl -q --tests $OUT/t.json
check "replay generated tests"  0 "12/12 passed"        $D replay examples/triage.dl $OUT/t.json
echo "== F4 bug finding with confirmed counterexamples"
check "div by zero witness"     1 "age=5.*replay-confirmed" $D analyze examples/triage.dl -q
check "int-min overflow"        1 "n=-128.*replay-confirmed" $D analyze examples/abs.dl -q
check "assert violation"        1 "assertion failure"   $D analyze examples/sorted3.dl -q
echo "== F5 equivalence checking"
check "equivalent"              0 "^EQUIVALENT"        $D equiv examples/equiv/abs_branch.dl examples/equiv/abs_trick.dl
check "not equivalent"          1 "x=101"               $D equiv examples/equiv/clamp_a.dl examples/equiv/clamp_buggy.dl
echo "== F6 HTML report"
check "html written"            1 "wrote HTML"          $D analyze examples/triage.dl -q --html $OUT/r.html
check "html content"            0 "replay-confirmed"    grep -o "replay-confirmed" $OUT/r.html
echo "== F7 solver stats / cache"
check "stats line"              1 "solver: [0-9]+ queries \([0-9]+ cached" $D analyze examples/triage.dl -q
echo "== unit + differential + fuzz tests"
check "test suite"              0 "OK"                  python3 tests/run_all.py
rm -rf "$OUT"
[ $fail -eq 0 ] && echo "ALL GREEN" || { echo "FAILURES"; exit 1; }
