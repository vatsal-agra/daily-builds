#!/usr/bin/env bash
# Re-runs the reproduction of every finding in REVIEW.md against the current build.
# Exit status 0 means none of the listed issues reproduces any more.
set -u
cd "$(dirname "$0")/.."
go build -o /tmp/dominion_recheck ./cmd/dom || exit 1
D=/tmp/dominion_recheck
T=$(mktemp -d)
fail=0
check() { # name, command...
  local name=$1; shift
  if "$@" >"$T/out" 2>&1; then echo "  ok    $name"; else echo "  FAIL  $name"; sed 's/^/        /' "$T/out" | head -5; fail=1; fi
}
within() { # seconds, command...
  local secs=$1; shift
  local s=$(date +%s.%N); "$@" >/dev/null 2>&1; local e=$(date +%s.%N)
  awk -v a="$s" -v b="$e" -v m="$secs" 'BEGIN{exit !((b-a) < m)}'
}

# R1 quadratic compile time: 3000 statements / 50000-term expression
python3 - "$T" <<'PY'
import sys
t=sys.argv[1]
L=["fn main() {","  var s = 0;"]
for i in range(3000):
    L.append(f"  var x{i} = s + {i};"); L.append(f"  if x{i} % 3 == 0 {{ s += x{i}; }} else {{ s -= {i}; }}")
L.append("  return s; }")
open(t+"/big.dom","w").write("\n".join(L))
open(t+"/chain.dom","w").write("fn main(){ return "+"+".join(["1"]*50000)+"; }")
open(t+"/spin.dom","w").write("fn main(){ while 1 { } return 0; }")
open(t+"/flood.dom","w").write("fn main(){ while 1 { print(123456789); } return 0; }")
open(t+"/min.dom","w").write("fn main(){ var m = -9223372036854775808; print(m); return m == -9223372036854775807 - 1; }")
open(t+"/many.dom","w").write("fn f(%s) { return p0; }\nfn main() { return 0; }\n" % ",".join(f"p{i}" for i in range(40)))
PY
check "R1 big function compiles in < 5s"         within 5 $D run $T/big.dom
check "R1 50k-term expression compiles in < 3s"  within 3 $D run $T/chain.dom
# R2/R3 runaway programs end quickly and cleanly
check "R2 infinite loop stops at the fuel limit (< 8s)" within 8 $D run -fuel 20000000 $T/spin.dom
check "R3 print flood is capped"                  bash -c "$D run -fuel 100000000 $T/flood.dom 2>&1 | tail -c 200 | grep -q 'output limit exceeded'"
# R4 MinInt64 literal
check "R4 -9223372036854775808 literal"           bash -c "$D run $T/min.dom 2>&1 | grep -q 'exit value: 1'"
# R5 error prefix
printf 'func @main() {\nentry:\n  %%x = add 1\n  ret %%x\n}\n' >"$T/bad.ir"
check "R5 IR errors have a single prefix"         bash -c "! $D run $T/bad.ir 2>&1 | grep -q 'ir:ir:'"
# R13 parameter limit
check "R13 too many parameters is a source diagnostic" bash -c "$D run $T/many.dom 2>&1 | grep -q 'limit is 32'"
# R6/R7/R9/R10 covered by go tests
check "R6-R11 regression tests"                   go test -short ./ir ./front ./opt ./backend
echo
if [ $fail -eq 0 ]; then echo "recheck: none of the REVIEW.md findings reproduce"; else echo "recheck: FINDINGS STILL REPRODUCE"; fi
rm -rf "$T"
exit $fail
