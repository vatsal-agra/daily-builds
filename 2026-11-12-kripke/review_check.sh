#!/usr/bin/env bash
# Replays the probes from REVIEW.md. Exits non-zero on the first regression.
set -uo pipefail
cd "$(dirname "$0")"
K=./target/release/kripke
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail() { echo "REVIEW CHECK FAILED: $*"; exit 1; }
expect_exit() { local want=$1; shift; "$@" >"$T/out" 2>&1; local got=$?; [[ $got == "$want" ]] || { cat "$T/out" | head -5; fail "$* exited $got, wanted $want"; }; }
expect_text() { grep -q -- "$1" "$T/out" || { head -8 "$T/out"; fail "output lacks '$1'"; }; }

# 1 deep nesting -> clean error, no crash
python3 -c "print('VAR x : boolean;\nSPEC ' + '('*100000 + 'x' + ')'*100000)" > $T/deep.smv
expect_exit 2 $K $T/deep.smv; expect_text "nested too deeply"
# 2/3 big ranges: 16-bit counter, shortest counterexample, abbreviated trace
printf 'VAR n : 0..65535;\nASSIGN init(n):=0; next(n):=(n+1) mod 65536;\nINVARSPEC n != 65535\nSPEC AG AF n = 0\n' > $T/ctr.smv
expect_exit 1 $K $T/ctr.smv; expect_text "counterexample (65536 states)"; expect_text "states omitted"
[[ $(wc -l < $T/out) -lt 120 ]] || fail "trace was not abbreviated"
expect_exit 1 $K $T/ctr.smv --full-traces; [[ $(wc -l < $T/out) -gt 65000 ]] || fail "--full-traces did not print everything"
printf 'VAR m : 0..5000;\nASSIGN init(m):=0; next(m):=case m < 4998 : m + 2; TRUE : m; esac;\nSPEC AG m <= 5000\nINVARSPEC m != 4998\n' > $T/big.smv
expect_exit 1 $K $T/big.smv; expect_text "FAIL\] INVAR"; expect_text "PASS\] CTL"
printf 'VAR m : 0..5000;\nASSIGN next(m) := m + 1;\n' > $T/ovf.smv
expect_exit 2 $K $T/ovf.smv; expect_text "can leave its type"
expect_exit 0 $K $T/ovf.smv --lax
# 4 deadlock semantics
printf 'VAR n : 0..3;\nASSIGN init(n):=0;\nTRANS n < 3 & next(n) = n + 1\nSPEC AG n < 3\nINVARSPEC n < 3\n' > $T/dl.smv
expect_exit 1 $K $T/dl.smv; expect_text "WARNING: 1 reachable deadlock"; expect_text "PASS\] CTL"
expect_exit 1 $K $T/dl.smv --stutter; expect_text "FAIL\] CTL"
# 5 division by zero
printf 'VAR n : 0..3; m : 0..3;\nASSIGN init(n):=1; init(m):=0; next(n):= n / m; next(m):=m;\n' > $T/dz.smv
expect_exit 2 $K $T/dz.smv; expect_text "divisor can be zero"
# 6 bad input files / flags
printf 'VAR x : boolean;\nSPEC \xff\xfe\n' > $T/bin.smv
expect_exit 2 $K $T/bin.smv; expect_text "not valid UTF-8"
expect_exit 2 $K $T/nonexistent.smv; expect_exit 2 $K examples/peterson.smv --bogus; expect_text "unknown option"
# 11/12
printf 'VAR x : boolean; y : boolean;\nASSIGN init(x):=TRUE; next(x):=y; next(y):={TRUE,FALSE};\nFAIRNESS FALSE\nSPEC AF x\n' > $T/vac.smv
expect_exit 0 $K $T/vac.smv; expect_text "vacuous"
printf 'VAR x : boolean;\nSPEC NAME a := x\nSPEC NAME a := !x\n' > $T/dup.smv
expect_exit 2 $K $T/dup.smv; expect_text "duplicate specification name"
printf 'VAR x : boolean;\n' > $T/nospec.smv
expect_exit 0 $K $T/nospec.smv; expect_text "nothing to check"
# 14 precedence
printf 'VAR x : boolean;\nASSIGN init(x):=TRUE; next(x):=x;\nSPEC EF x = TRUE\n' > $T/prec.smv
expect_exit 0 $K $T/prec.smv
# 15 elevator: fixed passes, naive starves
expect_exit 0 $K examples/elevator.smv --quiet
expect_exit 1 $K examples/elevator_naive.smv; expect_text "lasso counterexample"
# 8: gc-stress + reorder must not change any verdict on any example
for f in examples/*.smv; do
  a=$($K $f --stutter 2>&1 | grep -E '^\[|^states' | sed 's/([0-9.]* ms)//')
  b=$($K $f --stutter --gc-stress --reorder 2>&1 | grep -E '^\[|^states' | sed 's/([0-9.]* ms)//')
  [[ "$a" == "$b" ]] || fail "gc-stress/reorder changed the verdicts of $f"
done
# 7: LTL vs CTL vs explicit on random models
expect_exit 0 $K fuzz --count 300 --seed 9000
echo "REVIEW CHECK PASSED"
