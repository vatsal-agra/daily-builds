#!/usr/bin/env bash
# Acceptance demo: exercises every feature through the CLI. Exits non-zero on any failure.
set -u
cd "$(dirname "$0")"
go build -o /tmp/spillway-demo ./cmd/spillway || exit 1
S=/tmp/spillway-demo
pass=0; fail=0
check() { # name, expected-substring, command...
  local name=$1 want=$2; shift 2
  local out; out=$("$@" 2>&1); local rc=$?
  if [[ $out == *"$want"* ]]; then pass=$((pass+1)); echo "ok   $name"
  else fail=$((fail+1)); echo "FAIL $name (rc=$rc) wanted [$want]"; echo "$out" | head -5; fi
}
T=$(mktemp -d); trap 'rm -rf $T' EXIT

check "interp sumsq(10)=285"        "ret=285"            $S interp examples/sumsq.ir -args 10
check "live: pressure + loop depth" "max register pressure" $S live examples/pressure.ir
check "live: loop depth 1"          "depth=1"            $S live examples/sumsq.ir
for ex in sumsq pressure collatz bubble moves poly; do
  for al in color linear naive; do
    check "run $ex/$al K=4 verified" "machine == reference" $S run examples/$ex.ir -k 4 -alloc $al -args "7;20"
  done
done
check "compare verifies all three"  "yes"                $S compare examples/pressure.ir -k 5 -args 12
check "coalescing removes moves"    "move(s) eliminated" $S run examples/moves.ir -k 6 -args 5
check "nocoalesce flag"             "machine == reference" $S run examples/moves.ir -k 6 -args 5 -nocoalesce
check "nopost flag"                 "machine == reference" $S run examples/pressure.ir -k 4 -args 5 -nopost
check "post-pass reports"           "post-pass:"         $S run examples/pressure.ir -k 4 -args 5
check "sweep table"                 "color (cycles"      $S sweep examples/poly.ir -kmax 10 -args 3
check "gen is deterministic"        "$($S gen -seed 7 | md5sum | cut -c1-8)" bash -c "$S gen -seed 7 | md5sum"
$S gen -seed 11 -vars 16 -shuffle > $T/g.ir
check "generated program runs"      "ret="               $S interp $T/g.ir -args "3,4"
check "generated program allocates" "machine == reference" $S run $T/g.ir -k 3 -args "3,4"
check "fuzz finds no divergence"    "no divergence"      $S fuzz -n 80 -seed 5
check "report written"              "wrote"              $S report examples/bubble.ir -k 5 -args 16 -o $T/r.html
check "report has graph"            "Interference graph" grep -o "Interference graph" $T/r.html
# error handling
printf 'func f(0) {\ne:\n  x = add y, 1\n  ret x\n}\n' > $T/u.ir
check "undefined register rejected" "possibly-undefined" $S interp $T/u.ir
printf 'func f(0) {\ne:\n  jmp e\n}\n' > $T/i.ir
check "no-ret loop rejected"        "can never return"   $S interp $T/i.ir
printf 'func f(0) {\ne:\n  x = const 1\n  br x, e, r\nr:\n  ret x\n}\n' > $T/inf.ir
check "infinite loop reported"      "infinite loop?"     $S compare $T/inf.ir -k 4
check "K too small"                 "K must be at least" $S run examples/sumsq.ir -k 2
check "K too large"                 "K must be at most"  $S run examples/sumsq.ir -k 99999
check "bad allocator"               "unknown allocator"  $S run examples/sumsq.ir -alloc zzz
check "bad -args"                   "bad -args"          $S run examples/sumsq.ir -args q
check "missing file"                "no such file"       $S run $T/none.ir
check "parse error has line"        "line 3"             bash -c "printf 'func f(0) {\ne:\n  x = foo 1\n  ret x\n}\n' > $T/b.ir; $S interp $T/b.ir"
check "unknown command"             "unknown command"    $S frobnicate

echo; echo "demo: $pass passed, $fail failed"
[[ $fail -eq 0 ]]
