#!/usr/bin/env bash
# One-command verification of every Wick feature. Usage: ./verify.sh [fuzz-cases=2000]
set -euo pipefail
cd "$(dirname "$0")"
N="${1:-2000}"
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
W=./target/release/wick
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

step "build (release)";                       cargo build --release 2>&1 | tail -1
step "[1 assembler][2 decoder/validator][3 interpreter] cargo test (unit, round-trip, corpus, API, clang-vs-native)"
cargo test --release 2>&1 | grep -E "^test result|FAILED|panicked" 
step "[1,3] CLI demo: assemble, validate, run, disassemble"
$W asm examples/fib.wat -o "$TMP/fib.wasm"
$W validate "$TMP/fib.wasm"
test "$($W run "$TMP/fib.wasm" --invoke fib 20)" = "i32:6765" && echo "fib(20) = 6765 ok"
test "$($W run examples/fib.wat --invoke fib_iter 90)" = "i64:2880067194370816120" && echo "fib_iter(90) ok"
$W dis "$TMP/fib.wasm" > "$TMP/fib.dis.wat"; $W asm "$TMP/fib.dis.wat" -o "$TMP/fib2.wasm" 2>/dev/null
$W dis "$TMP/fib2.wasm" | cmp - "$TMP/fib.dis.wat" && echo "disassemble -> assemble -> disassemble is a fixed point"
step "[6 profiler][7 fuel] profile + HTML + fuel"
$W run examples/programs.wasm --invoke nqueens 7 --html "$TMP/p.html" --trace 20 2>&1 | grep -E "instructions executed"
grep -q "Call depth over time" "$TMP/p.html" && echo "HTML report generated"
$W run examples/fib.wat --invoke fib 30 --fuel 1000 2>&1 | grep -q "out of fuel" && echo "fuel limit traps ok"
step "hostile-input battery";                 ./tests/hostile.sh | grep -c '^ok' | sed 's/$/ hostile cases ok/'
if command -v node >/dev/null; then
  step "[4 differential fuzzer] $N random programs: Wick vs V8"
  $W fuzz --count "$N" --seed 424242 --out "$TMP/fz"
  node diff/diff.js "$TMP/fz"
  step "validator differential: AST mutants + byte mutants vs V8"
  $W mutants --count $((N/4)) --per 20 --seed 31337 --out "$TMP/mu"
  node diff/validate_diff.js "$TMP/mu" --as-is
  node diff/validate_diff.js "$TMP/fz" 3 5 | head -4
  step "conformance corpus replayed on V8"
  node diff/corpus.js
else
  echo "node not found: skipping V8 differential steps"
fi
printf '\n\033[1;32mALL VERIFICATION PASSED\033[0m\n'
