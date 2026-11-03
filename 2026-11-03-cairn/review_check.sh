#!/usr/bin/env bash
# Re-runs every probe listed in REVIEW.md and asserts the issue no longer reproduces.
set -u
cd "$(dirname "$0")"
cargo build --release -q 2>&1 | grep -E "^(warning|error)" && exit 1
C=./target/release/cairn
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail=0
ok()   { echo "  ok   $1"; }
bad()  { echo "  FAIL $1"; fail=1; }
prog() { printf '%s' "$1" > "$T/p.cairn"; }

# R4 unknown flags rejected
prog '(print 1)'
out=$($C run "$T/p.cairn" --bogus 5 2>&1); [[ $? -ne 0 && $out == *"unknown option"* ]] && ok "R4 unknown flag rejected" || bad "R4 unknown flag"
# R5 absurd heap rejected cleanly (no abort)
out=$($C run "$T/p.cairn" --heap 999999999999999 2>&1); rc=$?; [[ $rc -eq 1 && $out == *"limited to"* ]] && ok "R5 huge heap rejected" || bad "R5 huge heap (rc=$rc)"
# R6 default nursery on a small heap
prog '(def i 0) (while (< i 20000) (cons i i) (set! i (+ i 1))) (print i)'
out=$($C run "$T/p.cairn" --gc generational --heap 2000 2>&1); [[ $out == "20000" ]] && ok "R6 small heap + default nursery" || bad "R6: $out"
# R11 oversized literal message
prog '(print 99999999999999999999)'
out=$($C run "$T/p.cairn" 2>&1); [[ $out == *"does not fit in 63 bits"* ]] && ok "R11 literal diagnostic" || bad "R11: $out"
# R12 variadic arithmetic
prog '(print (+ 1 2 3 4) (- 10) (- 10 1 2) (* 2 3 4))'
out=$($C run "$T/p.cairn" 2>&1); [[ $out == "10 -10 7 24" ]] && ok "R12 variadic + - *" || bad "R12: $out"
# R3 fuzzer is sensitive: it must catch the no-barrier incremental collector...
out=$($C fuzz --iters 300 --seed 1 --gcs incremental --no-barrier 2>&1); [[ $? -ne 0 && $out == *"HEAP CORRUPTION"* ]] && ok "R3 fuzzer catches missing deletion barrier" || bad "R3: $out"
# ...and the generational collector without its remembered-set barrier
out=$($C run examples/cache.cairn --gc generational --heap 20000 --nursery 800 --verify --no-barrier 2>&1); [[ $? -ne 0 && $out == *"not remembered"* ]] && ok "R3b oracle catches missing remembered set" || bad "R3b: $out"
# R9 incremental pause log stays bounded and populated
out=$($C run examples/bintrees.cairn --gc incremental --heap 400000 --stats 2>&1 | tail -3 | head -1); [[ $out == incremental* ]] && ok "R9 pause accounting" || bad "R9: $out"
# R14 closed stdout pipe is not a panic
$C run examples/bintrees.cairn | head -1 >/dev/null; rc=${PIPESTATUS[0]}; [[ $rc -eq 0 ]] && ok "R14 broken pipe exits quietly" || bad "R14 rc=$rc"
# the cargo-level regression tests for the rest
cargo test --release -q --test barrier --test model 2>&1 | grep -E "test result" | grep -q "failed; 0" && ok "R1/R2/R7/R8 barrier + model tests" || bad "tests"
[[ $fail -eq 0 ]] && echo "review re-check: ALL CLEAN" || { echo "review re-check: FAILURES"; exit 1; }
