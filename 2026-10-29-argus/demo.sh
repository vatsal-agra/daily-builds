#!/usr/bin/env bash
# Runnable end-to-end demo / verification: exercises every Argus feature and asserts on the outcome.
# Usage: ./demo.sh          (exits non-zero on the first surprise)
set -u
cd "$(dirname "$0")"
A="python3 -m argus"
TMP=$(mktemp -d)
pass=0; fail=0

ok()   { pass=$((pass+1)); printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31m✗\033[0m %s\n' "$1"; }
# expect <exit-code> <grep-pattern> <description> -- command...
expect() {
  local code=$1 pat=$2 desc=$3; shift 4
  local out; out=$("$@" 2>&1); local rc=$?
  if [ "$rc" -eq "$code" ] && printf '%s' "$out" | grep -qE -- "$pat"; then ok "$desc"; else
    bad "$desc (exit $rc, wanted $code; pattern: $pat)"; printf '%s\n' "$out" | head -15; fi
}

echo "== 1. language & compiler"
expect 0 "3 locations|2 locations|process P0" "info summarises processes, labels, properties" -- $A info models/peterson.arg
expect 0 "holds" "-D overrides a const (bakery with 3 processes)" -- $A check models/bakery.arg -D N=3
expect 2 "not declared as const" "-D on an unknown name is a clean error" -- $A check models/peterson.arg -D NOPE=1
printf 'var x = 0;\nproc P() { x = ; }\nrun P();\n' > "$TMP/bad.arg"
expect 2 "line 2.*\n?.*\^|\^" "syntax errors show line and caret" -- $A check "$TMP/bad.arg"

echo "== 2. safety checking (BFS, shortest counterexamples)"
expect 0 "✓ safety.*holds" "Peterson: mutual exclusion + no deadlock" -- $A check models/peterson.arg --no-ltl
expect 1 "invariant 'mutex' violated" "check-then-act race breaks mutual exclusion" -- $A check models/mutex_race.arg
expect 1 "assertion violated: lost update" "lost update found as assertion failure" -- $A check models/lost_update.arg
expect 1 "counterexample: 3 steps" "dining philosophers deadlock in exactly 3 steps" -- $A check models/philosophers.arg
expect 1 "runtime error: index 3 out of bounds" "array overrun is a reportable violation" -- $A check models/errors.arg
expect 1 "invariant 'in_range'|VIOLATED" "--all collects every distinct violation" -- $A check models/lost_update.arg --all
expect 3 "INCONCLUSIVE" "state limit is inconclusive, never a silent pass" -- $A check models/bakery.arg -D N=3 --max-states 1000

echo "== 3. LTL liveness with fairness"
expect 0 "ltl live0: holds" "Peterson starvation-freedom holds" -- $A check models/peterson.arg --prop live0
expect 1 "ltl done2: VIOLATED" "no fairness: scheduler may ignore an always-enabled process" -- $A check models/fairness_ladder.arg --prop done2 --fair none
expect 0 "ltl done2: holds" "weak fairness fixes it" -- $A check models/fairness_ladder.arg --prop done2 --fair weak
expect 1 "ltl done1: VIOLATED" "weak fairness is not enough for an intermittently-enabled waiter" -- $A check models/fairness_ladder.arg --prop done1 --fair weak
expect 0 "ltl done1: holds" "strong fairness is" -- $A check models/fairness_ladder.arg --prop done1 --fair strong
expect 1 "ltl all_delivered: VIOLATED" "ABP: message loss forever breaks delivery under process fairness" -- $A check models/abp.arg --prop all_delivered --fair weak
expect 0 "ltl all_delivered: holds" "ABP delivers under per-statement strong fairness" -- $A check models/abp.arg --prop all_delivered --fair strong --fair-by edge
expect 0 "ltl elected: holds" "ring leader election terminates" -- $A check models/leader_ring.arg --prop elected
expect 1 "invariant 'one_leader' violated" "buggy election elects several leaders" -- $A check models/leader_broken.arg

echo "== 4. traces: render, replay-validate, JSON, HTML"
expect 1 "independent replay ✓.*\n?.*" "every counterexample is independently replayed" -- $A check models/philosophers.arg
expect 1 "evaluated the formula directly on the lasso word.*FALSE" "lasso verdicts are re-evaluated by a second LTL evaluator" -- $A check models/fairness_ladder.arg --prop done1 --fair weak
$A check models/lost_update.arg --save-trace "$TMP/t.json" >/dev/null 2>&1
expect 0 "replayed .* steps" "saved counterexample replays" -- $A replay models/lost_update.arg "$TMP/t.json"
python3 - "$TMP/t.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["steps"][2]["state"][0] += 5; json.dump(d, open(sys.argv[1], "w"))
PY
expect 1 "NOT valid" "a tampered trace is rejected" -- $A replay models/lost_update.arg "$TMP/t.json"
expect 1 '"ok": false' "--json output" -- $A check models/flag_deadlock.arg --json
expect 1 "wrote interactive report" "--html report" -- $A check models/abp.arg --html "$TMP/r.html"
[ -s "$TMP/r.html" ] && grep -q 'id="data"' "$TMP/r.html" && ok "report is a self-contained page ($(wc -c < "$TMP/r.html") bytes)" || bad "report missing"

echo "== 5. partial-order reduction"
full=$($A check models/por_demo.arg | grep -oE '[0-9,]+ states' | head -1 | tr -d ', states')
red=$($A check models/por_demo.arg --por | grep -oE '[0-9,]+ states' | head -1 | tr -d ', states')
[ "$red" -lt "$full" ] && ok "POR cuts por_demo from $full to $red states, same verdict" || bad "POR did not reduce ($full -> $red)"
expect 1 "deadlock" "POR still finds the philosophers' deadlock" -- $A check models/philosophers.arg --por

echo "== 6. simulator"
expect 0 "simulation seed=7" "random simulation" -- $A sim models/peterson.arg --steps 10 --seed 7 --save "$TMP/s.json"
expect 0 "replayed 10 steps" "simulated trace replays" -- $A replay models/peterson.arg "$TMP/s.json"
expect 1 "DEADLOCK" "simulation reports deadlock" -- $A sim models/flag_deadlock.arg --steps 50 --seed 1

echo "== 7. Graphviz + Büchi export"
expect 0 "digraph states" "state graph as DOT" -- $A graph models/peterson.arg --max 50
expect 0 "digraph buchi" "Büchi automaton as DOT" -- $A buchi '[](p -> <>q)' --negate --dot
expect 0 "acceptance set" "Büchi automaton as text" -- $A buchi 'p U q'

echo "== 8. regression runner & unit/fuzz tests"
expect 0 "expectations met" "verify: all // expect: annotations in models/" -- $A verify models
if [ "${SKIP_TESTS:-0}" != 1 ]; then
  out=$(python3 -m unittest discover -s tests -t . 2>&1 | tail -3)
  printf '%s' "$out" | grep -q '^OK' && ok "unit + fuzz test suite ($(printf '%s' "$out" | grep -oE 'Ran [0-9]+ tests'))" || { bad "unit tests"; echo "$out"; }
fi

rm -rf "$TMP"
echo
echo "demo: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
