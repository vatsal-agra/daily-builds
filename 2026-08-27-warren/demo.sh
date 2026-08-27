#!/usr/bin/env bash
# End-to-end demo/verification script for Warren.
# Runs the full unit test suite, then exercises every required and
# stretch feature through the real CLI, checking real output against
# expected answers (no mocking, no stubs). Exits non-zero on any
# failure.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0

section() { echo; echo "=== $1 ==="; }

check() {
    # check "description" "expected substring" -- command...
    local desc="$1" expected="$2"; shift 2
    local out
    out="$("$@" 2>&1)"
    if echo "$out" | grep -qF "$expected"; then
        echo "  OK   $desc"
        PASS=$((PASS+1))
    else
        echo "  FAIL $desc"
        echo "       expected to find: $expected"
        echo "       got:"
        echo "$out" | sed 's/^/         /'
        FAIL=$((FAIL+1))
    fi
}

section "1. Unit + differential test suite (pytest)"
if python3 -m pytest -q tests/; then
    echo "  OK   full pytest suite green"
    PASS=$((PASS+1))
else
    echo "  FAIL pytest suite had failures"
    FAIL=$((FAIL+1))
fi

section "2. Parser: operator precedence, lists, DCG arrow, quoted atoms (via family.pl load + query)"
check "family tree ancestor/2 (recursive rules over facts)" "true." \
    python3 -m warren run examples/family.pl "ancestor(tom, jim)."

section "3. WAM compiler + machine: backtracking, indexing, cut"
check "append/3 generate-mode backtracking (4 solutions via findall)" "L = [[],[1],[1,2],[1,2,3]]" \
    python3 -m warren run examples/family.pl "findall(X, append(X,_,[1,2,3]), L)."
check "cut commits to first matching clause" "L = [1]" \
    python3 -m warren run examples/cut_demo.pl "findall(X, q(X), L)."
check "N-Queens matches the published solution count for N=6 (4)" "C = 4" \
    python3 -m warren run examples/queens.pl "count_solutions(6, C)."
check "N-Queens matches the published solution count for N=8 (92)" "C = 92" \
    python3 -m warren run examples/queens.pl "count_solutions(8, C)."

section "4. Built-in predicate library: arithmetic, findall, catch/throw, assert/retract"
check "arithmetic + comparisons" "F = 120" \
    python3 -m warren run examples/family.pl "N is 5, F is N*(N-1)*(N-2)*(N-3)*(N-4)+0, F2 is 120, F=F2."
check "catch/3 traps a real evaluation_error" "X = caught" \
    python3 -m warren run examples/family.pl "catch(X is 1/0, error(evaluation_error(zero_divisor),_), X=caught)."
check "assert/retract: mutable counter reaches 3 after 3 increments" "X = 3" \
    python3 -m warren run examples/counter_demo.pl "incr3, counter(X)."

section "5. Golden-model differential oracle: the Zebra puzzle, checked against the published answer"
check "Zebra puzzle: the Japanese owns the zebra" "Owner = japanese" \
    python3 -m warren run examples/zebra.pl "zebra(Owner, Water, S)."
check "Zebra puzzle: the Norwegian drinks water" "Water = norwegian" \
    python3 -m warren run examples/zebra.pl "zebra(Owner, Water, S)."

section "6. Stretch: DCG grammar (arithmetic expression parser)"
check "DCG respects * before + precedence" "V = 11" \
    python3 -m warren run examples/expr_dcg.pl "calc([3,+,4,*,2],V)."
check "DCG parenthesization overrides precedence" "V = 14" \
    python3 -m warren run examples/expr_dcg.pl "calc(['(',3,+,4,')',*,2],V)."

section "7. Stretch: interactive HTML WAM execution visualizer"
python3 -m warren viz examples/family.pl "ancestor(tom, X)." --out /tmp/warren_demo_trace.html >/tmp/warren_viz_stdout.txt 2>&1
if grep -q "wrote" /tmp/warren_viz_stdout.txt && python3 -c "
import re
html = open('/tmp/warren_demo_trace.html').read()
m = re.search(r'const TRACE = (\{.*\});', html)
import json
d = json.loads(m.group(1))
assert d['solved'] and d['solution'] == 'X = bob' and len(d['steps']) > 5
"; then
    echo "  OK   visualizer HTML generated with a real captured trace"
    PASS=$((PASS+1))
else
    echo "  FAIL visualizer did not produce a valid trace"
    FAIL=$((FAIL+1))
fi

section "8. Polish: clean CLI error handling (no raw tracebacks)"
OUT="$(python3 -m warren run /nonexistent/file.pl "true." 2>&1)"
if echo "$OUT" | grep -q "no such file" && ! echo "$OUT" | grep -q "Traceback"; then
    echo "  OK   missing-file error is clean, no traceback"
    PASS=$((PASS+1))
else
    echo "  FAIL missing-file error handling regressed"
    echo "$OUT" | sed 's/^/       /'
    FAIL=$((FAIL+1))
fi

section "Summary"
echo "  $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
echo "All checks green."
