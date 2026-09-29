#!/usr/bin/env bash
# Runnable demo/verification: builds Tarski and exercises every feature end-to-end.
set -u
cd "$(dirname "$0")"
pass=0; fail=0
check() { # name, command...
  local name=$1; shift
  if "$@" >/tmp/tarski_demo.out 2>&1; then echo "  ok   $name"; pass=$((pass+1));
  else echo "  FAIL $name"; sed 's/^/       /' /tmp/tarski_demo.out | head -20; fail=$((fail+1)); fi
}
contains() { grep -q -- "$1" /tmp/tarski_demo_cmd.out; }
run_expect() { # name, expected-substring, command...
  local name=$1 want=$2; shift 2
  "$@" >/tmp/tarski_demo_cmd.out 2>&1
  if grep -qF -- "$want" /tmp/tarski_demo_cmd.out; then echo "  ok   $name"; pass=$((pass+1));
  else echo "  FAIL $name (missing: $want)"; sed 's/^/       /' /tmp/tarski_demo_cmd.out | head -15; fail=$((fail+1)); fi
}

echo "== build"
check "go build" go build -o tarski .
echo "== unit + fuzz suite (parser, semi-naive, negation, arithmetic, aggregates, provenance, REPL, CLI, oracle fuzz)"
check "go test" go test ./...
echo "== 1. parser: errors carry line:col and a source snippet"
printf 'p(X) :- q(X,\n' > /tmp/tarski_bad.dl
run_expect "parse error snippet" "expected a term" ./tarski run /tmp/tarski_bad.dl
echo "== 2. semi-naive recursion"
run_expect "family ancestors" "X = gina" ./tarski run examples/family.dl
run_expect "graph cycle nodes" "X = c" ./tarski run examples/graph.dl
run_expect "points-to analysis" "O = o2" ./tarski run examples/pointsto.dl
echo "== 3. stratified negation / rejection"
run_expect "negation stratum" "stratum 1" ./tarski check examples/graph.dl
printf 'win(X) :- move(X,Y), not win(Y).\n' > /tmp/tarski_unstrat.dl
run_expect "unstratifiable rejected" "not stratifiable" ./tarski check /tmp/tarski_unstrat.dl
printf 'p(X) :- not q(X).\n' > /tmp/tarski_unsafe.dl
run_expect "unsafe rule rejected" "unsafe rule" ./tarski check /tmp/tarski_unsafe.dl
echo "== 4. arithmetic, queries, provenance"
run_expect "arithmetic generation" "N = 3" ./tarski run examples/family.dl
run_expect "why proof tree" "[fact]" ./tarski why examples/family.dl 'ancestor(alice, gina)'
run_expect "why on false fact" "not derivable" ./tarski why examples/family.dl 'ancestor(gina, alice)'
printf 'n(0). n(X) :- n(Y), X = Y + 1.\n' > /tmp/tarski_inf.dl
run_expect "runaway recursion is cut off" "derivation limit" ./tarski run -limit 20000 /tmp/tarski_inf.dl
echo "== stretch: aggregates, naive vs semi-naive bench, REPL"
run_expect "aggregates" "U = ann, N = 4" ./tarski run examples/access.dl
run_expect "bench equal models" "identical models" ./tarski bench -n 80
run_expect "stats flag" "semi-naive" ./tarski run -stats examples/graph.dl
run_expect "naive flag" "naive:" ./tarski run -naive -stats examples/graph.dl
printf 'e(a,b).\ne(b,c).\nr(X,Y):-e(X,Y).\nr(X,Z):-r(X,Y),e(Y,Z).\n?- r(a,Z).\n:why r(a,c)\n:quit\n' | ./tarski repl >/tmp/tarski_demo_cmd.out 2>&1
if grep -q "Z = c" /tmp/tarski_demo_cmd.out && grep -q "e(b, c)" /tmp/tarski_demo_cmd.out; then echo "  ok   repl session"; pass=$((pass+1)); else echo "  FAIL repl"; fail=$((fail+1)); fi
echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
