#!/usr/bin/env bash
# Guided tour of Coil. Run from the project directory: ./demo.sh
set -e
cd "$(dirname "$0")"
COIL="python3 coil.py"

hr() { printf '\n\033[1;36m== %s ==\033[0m\n' "$1"; }

hr "1. Closures & per-iteration capture (examples/closures.coil)"
$COIL examples/closures.coil

hr "2. Recursion — Fibonacci (examples/fib.coil)"
$COIL examples/fib.coil

hr "3. FizzBuzz (examples/fizzbuzz.coil)"
$COIL examples/fizzbuzz.coil

hr "4. Sorting — quicksort + in-place insertion sort (examples/sort.coil)"
$COIL examples/sort.coil

hr "5. Data munging — word-frequency map (examples/wordcount.coil)"
$COIL examples/wordcount.coil

hr "6. Bytecode disassembly of a function (--disasm)"
cat > /tmp/coil_demo_fn.coil <<'EOF'
fn add(a, b) { return a + b; }
print add(2, 3);
EOF
$COIL --disasm /tmp/coil_demo_fn.coil

hr "7. Garbage collector — reclaiming garbage (--trace-gc)"
cat > /tmp/coil_demo_gc.coil <<'EOF'
fn churn() { for (let i = 0; i < 400; i = i + 1) { let tmp = [i, i, i]; } }
print "heap before: " + str(heap_size());
churn();
print "freed by gc(): " + str(gc());
print "heap after:  " + str(heap_size());
EOF
$COIL --trace-gc /tmp/coil_demo_gc.coil

hr "8. Runtime error with a multi-frame traceback"
cat > /tmp/coil_demo_err.coil <<'EOF'
fn a() { return b(); }
fn b() { return 1 + "boom"; }
print a();
EOF
$COIL /tmp/coil_demo_err.coil || true

hr "9. Syntax error with a source caret"
printf 'let x = ;\n' > /tmp/coil_demo_syn.coil
$COIL /tmp/coil_demo_syn.coil || true

hr "10. Full test suite"
python3 -m unittest tests.test_coil 2>&1 | tail -4

printf '\n\033[1;32mDemo complete.\033[0m\n'
