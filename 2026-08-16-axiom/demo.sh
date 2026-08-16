#!/usr/bin/env bash
# Axiom end-to-end verification: unit suite + a real CLI walkthrough of
# every feature + a live HTML playground smoke test (best-effort, skipped
# cleanly if Node/Playwright aren't available in this environment).
set -euo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
check() {
    local desc="$1"; shift
    if "$@" > /tmp/axiom_demo_check.out 2>&1; then
        echo "  ok  - $desc"
        PASS=$((PASS+1))
    else
        echo "  FAIL - $desc"
        cat /tmp/axiom_demo_check.out | sed 's/^/         /'
        FAIL=$((FAIL+1))
    fi
}

echo "=== 1. Unit test suite ==="
python3 -m unittest discover -s tests -v

echo
echo "=== 2. CLI walkthrough (every required + stretch feature) ==="
check "simplify"        bash -c "test \"\$(python3 -m axiom.cli simplify '2*x+3*x-x')\" = '4*x'"
check "diff + steps"    bash -c "python3 -m axiom.cli diff 'x^2*sin(x)' --steps | grep -q 'product rule'"
check "solve linear"    bash -c "test \"\$(python3 -m axiom.cli solve '2*x-6')\" = '3'"
check "solve quadratic" bash -c "python3 -m axiom.cli solve 'x^2-5*x+6' | sort | tr '\n' ' ' | grep -q '2 3'"
check "solve complex"   bash -c "python3 -m axiom.cli solve 'x^2+1' | grep -q j"
check "factor cubic"    bash -c "python3 -m axiom.cli factor 'x^3-8' | grep -q 'x - 2'"
check "expand"          bash -c "test \"\$(python3 -m axiom.cli expand '(x+1)^3')\" = 'x^3 + 3*x^2 + 3*x + 1'"
check "integrate"       bash -c "python3 -m axiom.cli integrate 'x*exp(x)' | grep -q exp"
check "gcd/poly module" python3 -c "from axiom.polynomial import poly_gcd; from axiom import parse,sym; assert poly_gcd(parse('x^2-1'),parse('x^2-3*x+2'),sym('x'))==parse('x-1')"
check "matrix det/inv"  python3 -c "
from axiom.matrix import Matrix
A = Matrix([[2,1],[1,1]])
assert (A*A.inverse()).rows == Matrix.identity(2).rows
"
check "latex render"    bash -c "python3 -m axiom.cli latex 'x^2/(x-1)' | grep -q frac"
check "eval exact"      bash -c "test \"\$(python3 -m axiom.cli eval '0.1+0.2')\" = '0.3'"
check "viz report"      bash -c "python3 -m axiom.cli viz 'x^2*sin(x)' --out /tmp/axiom_demo_report.html && test -s /tmp/axiom_demo_report.html"
check "demo subcommand" python3 -m axiom.cli demo

echo
echo "=== 3. Error-handling sanity (no raw tracebacks) ==="
check "malformed expr clean error" bash -c "! python3 -m axiom.cli simplify 'x+' 2>&1 | grep -q Traceback"
check "unknown function clean error" bash -c "! python3 -m axiom.cli diff 'foo(x)' 2>&1 | grep -q Traceback"
check "deep nesting clean error" bash -c "! python3 -m axiom.cli simplify \"\$(python3 -c 'print(\"(\"*500+\"x\"+\")\"*500)')\" 2>&1 | grep -q Traceback"
check "bad --bind clean error" bash -c "! python3 -m axiom.cli eval 'x' --bind x=abc 2>&1 | grep -q Traceback"

echo
echo "=== 4. Live HTML playground (best-effort; needs Node+Playwright) ==="
if command -v node >/dev/null 2>&1 && [ -d /opt/pw-browsers ]; then
    (python3 -m axiom.cli serve --port 8799 > /tmp/axiom_demo_server.log 2>&1 &)
    sleep 1
    if NODE_PATH=/opt/node22/lib/node_modules node -e "
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({executablePath: '/opt/pw-browsers/chromium'});
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto('http://127.0.0.1:8799/');
  await page.waitForTimeout(600);
  await page.click('.chip[data-expr=\"x/(x^2+1)\"]');
  await page.waitForTimeout(500);
  const text = await page.textContent('#results');
  // the log-substitution result renders through the LaTeX-subset renderer
  // as ln(...) (axiom/latex.py maps log to \\ln), not the literal word log
  if (!text.includes('ln')) throw new Error('substitution result missing: ' + text.slice(0, 200));
  // XSS regression check
  let alertFired = false;
  page.on('dialog', async d => { alertFired = true; await d.dismiss(); });
  await page.fill('#expr', '<img src=x onerror=alert(1)>');
  await page.click('button[type=submit]');
  await page.waitForTimeout(500);
  if (alertFired) throw new Error('XSS REGRESSION: alert fired');
  if (errors.length) throw new Error('console errors: ' + errors.join(', '));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"; then
        echo "  ok  - live playground: substitution result + XSS regression check"
        PASS=$((PASS+1))
    else
        echo "  FAIL - live playground check"
        FAIL=$((FAIL+1))
    fi
    pkill -f "axiom.cli serve --port 8799" 2>/dev/null || true
else
    echo "  skip - Node/Playwright not available in this environment"
fi

echo
echo "================================================================"
echo "demo.sh: $PASS checks passed, $FAIL failed"
echo "================================================================"
[ "$FAIL" -eq 0 ]
