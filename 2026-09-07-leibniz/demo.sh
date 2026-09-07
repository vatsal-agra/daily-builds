#!/usr/bin/env bash
# Leibniz demo/verification script -- exercises every feature end-to-end and
# exits 0 only if every check passes. Run from this directory.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
CHECK=0

check() {
    CHECK=$((CHECK + 1))
    local desc="$1"; local expected="$2"; local actual="$3"
    if [ "$actual" = "$expected" ]; then
        PASS=$((PASS + 1))
        printf '  [%2d] OK   %s\n' "$CHECK" "$desc"
    else
        FAIL=$((FAIL + 1))
        printf '  [%2d] FAIL %s\n       expected: %s\n       actual:   %s\n' "$CHECK" "$desc" "$expected" "$actual"
    fi
}

check_ok() {
    CHECK=$((CHECK + 1))
    local desc="$1"
    if [ "$2" -eq 0 ]; then
        PASS=$((PASS + 1))
        printf '  [%2d] OK   %s\n' "$CHECK" "$desc"
    else
        FAIL=$((FAIL + 1))
        printf '  [%2d] FAIL %s (exit code %s)\n' "$CHECK" "$desc" "$2"
    fi
}

check_fails() {
    CHECK=$((CHECK + 1))
    local desc="$1"
    if [ "$2" -ne 0 ]; then
        PASS=$((PASS + 1))
        printf '  [%2d] OK   %s (correctly errored)\n' "$CHECK" "$desc"
    else
        FAIL=$((FAIL + 1))
        printf '  [%2d] FAIL %s (should have errored but exited 0)\n' "$CHECK" "$desc"
    fi
}

echo "== Leibniz demo/verification =="
echo
echo "-- 1. unit test suite (parser/simplify/diff/integrate/solve/polynomial/CLI/viz, incl. fuzz) --"
python3 -m unittest discover tests -v 2>&1 | tail -12
UNITTEST_STATUS=${PIPESTATUS[0]}
check_ok "full unittest suite" "$UNITTEST_STATUS"
echo

echo "-- 2. required feature 1: parser + canonical simplifier --"
check "simplify combines like terms" "5*x - 1" "$(./leibniz_cli simplify '2*x + 3*x - 1')"
check "simplify folds exact fractions" "1/2" "$(./leibniz_cli simplify '1/3 + 1/6')"
check "mul is as eager as add (regression)" "x*y + x + y + 1" "$(./leibniz_cli simplify '(x+1)*(y+1)')"
echo

echo "-- 3. required feature 2: symbolic differentiation --"
check "product + chain rule" "cos(x)*x^2 + 2*x*sin(x)" "$(./leibniz_cli diff 'x^2*sin(x)' --var x)"
check "generalized power rule x^x" "ln(x)*x^x + x^x" "$(./leibniz_cli diff 'x^x' --var x)"
check "exponential rule 2^x" "ln(2)*2^x" "$(./leibniz_cli diff '2^x' --var x)"
echo

echo "-- 4. required feature 3: exact equation solving --"
check "quadratic, two rational roots" "x = 3
x = 2" "$(./leibniz_cli solve 'x^2-5*x+6=0' --var x)"
check "quadratic, exact irrational root" "x = sqrt(2)
x = -sqrt(2)" "$(./leibniz_cli solve 'x^2-2=0' --var x)"
check "quadratic, exact complex root" "x = i
x = -i" "$(./leibniz_cli solve 'x^2+1=0' --var x)"
check "linear system" "x = 2
y = 1" "$(./leibniz_cli solve-system '2*x+y=5' 'x-y=1' --vars x,y)"
echo

echo "-- 5. required feature 4: polynomial expand/factor --"
check "expand binomial" "x^2 - x - 2" "$(./leibniz_cli expand '(x+1)*(x-2)')"
check "factor simple quadratic" "(x - 2)*(x - 3)" "$(./leibniz_cli factor 'x^2 - 5*x + 6')"
check "factor clears root denominators" "(x + 1)*(2*x + 1)" "$(./leibniz_cli factor '2*x^2+3*x+1')"
check "factor pulls out common variable power" "x*(x - 1)*(x + 1)" "$(./leibniz_cli factor 'x^3-x')"
echo

echo "-- 6. stretch feature 1: symbolic integration --"
check "power rule" "1/4*x^4 + C" "$(./leibniz_cli integrate 'x^3' --var x)"
check "1/x is ln|x|" "ln(abs(x)) + C" "$(./leibniz_cli integrate '1/x' --var x)"
check "tabular integration by parts" "exp(x)*x^2 - 2*x*exp(x) + 2*exp(x) + C" "$(./leibniz_cli integrate 'x^2*exp(x)' --var x)"
./leibniz_cli integrate 'exp(x^2)' --var x >/tmp/leibniz_demo_out.txt 2>&1
check_fails "integrate correctly refuses exp(x^2) (no matching rule)" $?
echo

echo "-- 7. stretch feature 2: HTML step visualizer --"
./leibniz_cli diff 'x^2*sin(x)' --var x --viz /tmp/leibniz_demo_viz.html >/dev/null
check_ok "viz file generation" $?
if command -v node >/dev/null 2>&1 && [ -d /opt/pw-browsers ]; then
    NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}" node -e "
      const { chromium } = require('playwright');
      (async () => {
        const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
        const page = await browser.newPage();
        const errors = [];
        page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
        page.on('pageerror', e => errors.push(String(e)));
        await page.goto('file:///tmp/leibniz_demo_viz.html');
        await page.waitForTimeout(300);
        await page.click('#next'); await page.waitForTimeout(100);
        await page.click('#play'); await page.waitForTimeout(200);
        await page.click('#play'); await page.waitForTimeout(100);
        const svgNodes = await page.\$\$eval('svg .node', els => els.length);
        if (errors.length > 0) { console.error('CONSOLE ERRORS:', errors); process.exit(1); }
        if (svgNodes < 1) { console.error('no tree nodes rendered'); process.exit(1); }
        await browser.close();
      })().catch(e => { console.error(e); process.exit(1); });
    "
    check_ok "headless-Chromium: zero console errors, tree renders" $?
else
    echo "  (skipping headless-browser check -- node/playwright not available)"
fi
echo

echo "-- 8. bonus feature: rational-function simplification --"
check "full cancellation" "x + 1" "$(./leibniz_cli ratsimp '(x^2-1)/(x-1)')"
check "common denominator + combine" "(2*x + 1)/(x^2 + x)" "$(./leibniz_cli ratsimp '1/x + 1/(x+1)')"
echo

echo "-- 9. error handling / invalid input (must fail cleanly, no traceback) --"
for bad_case in \
    "simplify:2+*3" \
    "solve:sin(x)=0 --var x" \
    "factor:x*y+1" \
    "integrate:exp(x^2) --var x" \
    "eval:x+1" \
    "simplify:1/0" \
    "simplify:"; do
    cmd="${bad_case%%:*}"; rest="${bad_case#*:}"
    out=$(./leibniz_cli $cmd $rest 2>&1)
    rc=$?
    check_fails "leibniz $cmd $rest" "$rc"
    case "$out" in
        *Traceback*) echo "       !! saw a Python traceback in output: $out"; FAIL=$((FAIL+1)) ;;
    esac
done
echo

echo "-- 10. REPL smoke test --"
repl_out=$(printf "3*x + x\ndiff x^3, x\nsolve x^2-4, x\nquit\n" | ./leibniz_cli repl)
echo "$repl_out" | grep -q "4\*x" && echo "  [ok] repl simplify" || { echo "  [FAIL] repl simplify"; FAIL=$((FAIL+1)); }
echo "$repl_out" | grep -q "3\*x\^2" && echo "  [ok] repl diff" || { echo "  [FAIL] repl diff"; FAIL=$((FAIL+1)); }
echo "$repl_out" | grep -q "x = 2" && echo "  [ok] repl solve" || { echo "  [FAIL] repl solve"; FAIL=$((FAIL+1)); }
echo

echo "== Summary: $PASS/$CHECK checks passed =="
if [ "$FAIL" -eq 0 ]; then
    echo "ALL GREEN"
    exit 0
else
    echo "$FAIL check(s) FAILED"
    exit 1
fi
