#!/usr/bin/env bash
# Ember end-to-end verification: unit/integration test suite, then the
# real CLI demo (differential harness across every example program,
# runtime error guards, a measured benchmark, the objdump oracle, and
# the constant-folding optimizer), then a few explicit CLI smoke checks.
set -euo pipefail
cd "$(dirname "$0")"

echo "=================================================================="
echo "1/3  Running the Python test suite (unittest discover)"
echo "=================================================================="
python3 -m unittest discover -s tests -v

echo
echo "=================================================================="
echo "2/3  Running 'ember demo' -- the full feature showcase"
echo "=================================================================="
python3 -m ember.cli demo

echo
echo "=================================================================="
echo "3/3  A few explicit CLI smoke checks"
echo "=================================================================="

check() {
    local desc="$1"; shift
    echo "--- $desc ---"
    "$@"
}

check "run: JIT-execute fib(20)" \
    python3 -m ember.cli run examples/fib.em fib 20

check "interp: same program via the interpreter" \
    python3 -m ember.cli interp examples/fib.em fib 20

check "compare: interpreter vs JIT vs gcc" \
    python3 -m ember.cli compare examples/ackermann.em ackermann 2 6

check "compare with --opt: constant-folded JIT vs interpreter vs gcc" \
    python3 -m ember.cli compare examples/gcd.em gcd 1071 462 --opt

check "ast: print the parsed AST" \
    python3 -m ember.cli ast examples/primes.em --fn is_prime

check "disasm: real objdump listing of the compiled machine code" \
    python3 -m ember.cli disasm examples/gcd.em --fn gcd

check "bench: measured interpreter-vs-JIT wall time" \
    python3 -m ember.cli bench examples/fib.em fib 26

check "viz: generate the interactive HTML report" \
    python3 -m ember.cli viz examples/fib.em --out /tmp/ember_demo_report.html --bench-fn fib --bench-args 24
test -s /tmp/ember_demo_report.html
rm -f /tmp/ember_demo_report.html

echo
echo "--- clean error handling (no raw tracebacks) ---"
set +e
python3 -m ember.cli run examples/fib.em fib not_a_number 2>/tmp/ember_err.txt
code=$?
set -e
if [ "$code" -ne 1 ] || ! grep -q "^error:" /tmp/ember_err.txt || grep -q "Traceback" /tmp/ember_err.txt; then
    echo "FAIL: bad-argument error handling did not behave as expected"
    cat /tmp/ember_err.txt
    exit 1
fi
echo "OK: bad argument produced a clean 'error: ...' message and exit code 1"
rm -f /tmp/ember_err.txt

echo
echo "=================================================================="
echo "ALL CHECKS PASSED"
echo "=================================================================="
