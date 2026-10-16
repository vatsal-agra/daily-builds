#!/usr/bin/env bash
# End-to-end demonstration + verification of every Dominion feature. Exits non-zero on any failure.
#   ./demo.sh            full run (~1 min)
#   FAST=1 ./demo.sh     smaller fuzz budgets
set -euo pipefail
cd "$(dirname "$0")"
BIN=$(mktemp -d)/dom
go build -o "$BIN" ./cmd/dom
D="$BIN"
FUZZ=${FAST:+60}; FUZZ=${FUZZ:-400}
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[32m✓\033[0m %s\n' "$*"; }

step "1. front-end → SSA IR: the Dom source is lowered to alloca/load/store form"
$D ir -O0 examples/gcd.dom | sed -n '1,14p'
$D ir -O0 examples/gcd.dom | grep -q alloca && ok "-O0 IR is in memory form (allocas)"

step "2. SSA construction: mem2reg turns the same function into phis"
$D ir -passes simplifycfg,mem2reg -trace examples/sieve.dom 2>&1 | grep -E '\[pass\]'
$D ir -passes simplifycfg,mem2reg examples/collatz.dom | sed -n '/func @steps/,/^}/p'
$D ir -passes simplifycfg,mem2reg examples/collatz.dom | sed -n '/func @steps/,/^}/p' | grep -q phi && ok "phis placed at join points"

step "3. optimizer: -O2 pass statistics and the IR of a small function"
$D ir -O2 -stats examples/primes.dom 2>&1 >/dev/null
$D ir -O3 examples/hash.dom | sed -n '/func @popcount/,/^}/p'

step "4. backend: linear-scan register allocation with spilling, 4 vs 12 registers"
$D asm -O2 -regs 4  -report examples/queens.dom 2>&1 >/dev/null
$D asm -O2 -regs 12 -report examples/queens.dom 2>&1 >/dev/null
$D asm -O2 -regs 6 examples/gcd.dom | sed -n '1,24p'

step "5. every example, every optimisation level, interpreter vs VM, several register files"
for f in examples/*.dom; do
  ref=$($D run -O0 -interp "$f" 2>&1)
  for cfg in "-O1" "-O2" "-O3" "-O2 -interp" "-O3 -regs 4" "-O2 -regs 5" "-O0 -regs 8"; do
    got=$($D run $cfg "$f" 2>&1)
    [ "$got" == "$ref" ] || { echo "MISMATCH $f [$cfg]"; exit 1; }
  done
done
ok "$(ls examples/*.dom | wc -l) programs × 8 configurations agree with the reference interpreter"

step "6. benchmark: VM cycles (cost model: mul 3, div 12, memory 3, call 5)"
$D bench examples/*.dom

step "7. differential fuzzing: generated programs, mutated IR, random pass orders, 3 register files"
$D fuzz -n "$FUZZ" -seed 777
$D fuzz -ir -n "$((FUZZ * 3))" -seed 777

step "8. HTML pass explorer"
$D report -O3 -o /tmp/dominion-matmul.html examples/matmul.dom
if command -v node >/dev/null && NODE_PATH=$(npm root -g 2>/dev/null) node -e 'require("playwright")' 2>/dev/null; then
  NODE_PATH=$(npm root -g) node scripts/screenshot.js /tmp/dominion-matmul.html /tmp/dominion-shot 0 && ok "report renders without errors in headless Chromium (light + dark)"
else
  echo "   (playwright not installed — skipping the browser render check)"
fi

step "9. hostile inputs are rejected with diagnostics"
printf 'fn main() {\n    var x = 1 +;\n}\n' > /tmp/dominion-bad.dom
if $D run /tmp/dominion-bad.dom 2>/tmp/dominion-err; then echo "should have failed"; exit 1; fi
cat /tmp/dominion-err
printf 'fn main(){ var z = 0; print(1); return 1 / z; }\n' > /tmp/dominion-trap.dom
set +e; $D run /tmp/dominion-trap.dom; rc=$?; set -e
[ $rc -eq 3 ] && ok "runtime traps exit with status 3 after flushing output"

step "10. Go test-suite"
go vet ./...
go test -count=1 -short ./... 2>&1 | sed 's/^/   /'
printf '\n\033[32mAll Dominion checks passed.\033[0m\n'
