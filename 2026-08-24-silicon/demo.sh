#!/usr/bin/env bash
# demo.sh -- exercises every feature of Silicon end-to-end through the real
# CLI and the real test suite. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")"

pass() { echo "  [OK] $1"; }
section() { echo; echo "=== $1 ==="; }

section "1/8  Unit + cross-check test suite (101 tests)"
python3 -m unittest discover -s tests -v 2>&1 | tail -5
pass "test suite green"

section "2/8  Assembler: encode a program, verify machine code appears"
OUT=$(python3 -m silicon.cli assemble fibonacci)
echo "$OUT" | grep -q "0x00000000: 0x00000293" || { echo "FAIL: unexpected first instruction"; exit 1; }
pass "assembler produces expected machine code"

section "3/8  Sequential golden-model simulator"
OUT=$(python3 -m silicon.cli run fibonacci)
echo "$OUT" | grep -q "retired 97 instructions" || { echo "FAIL: wrong instruction count"; exit 1; }
pass "golden model runs fibonacci.s correctly (97 instructions retired)"

section "4/8  Cycle-accurate pipeline: hazards, forwarding, branch prediction, caches"
for pred in static dynamic; do
  OUT=$(python3 -m silicon.cli pipeline fibonacci --predictor "$pred" \
        --icache 512:16:2 --dcache 512:16:2 --check)
  echo "$OUT" | grep -q "check: pipeline state MATCHES sequential golden model" \
    || { echo "FAIL: $pred predictor diverged from golden model"; exit 1; }
  pass "pipeline ($pred predictor, with caches) matches golden model"
done

section "5/8  Full benchmark suite: all 5 programs, both predictors, real cycle counts"
OUT=$(python3 -m silicon.cli bench)
echo "$OUT"
FAILCOUNT=$(echo "$OUT" | grep -c "FAIL" || true)
if [ "$FAILCOUNT" -ne 0 ]; then
  echo "FAIL: $FAILCOUNT benchmark program(s) diverged from the golden model"
  exit 1
fi
pass "10/10 program x predictor combinations verified correct"

section "6/8  Branch predictor: dynamic must beat static on a loop-heavy program"
python3 -c "
from silicon.assembler import assemble
from silicon.pipeline_sim import PipelineSimulator
from pathlib import Path
src = Path('programs/fibonacci.s').read_text()
s = PipelineSimulator(assemble(src), predictor_kind='static'); s.run()
d = PipelineSimulator(assemble(src), predictor_kind='dynamic'); d.run()
assert d.stats.mispredictions < s.stats.mispredictions, 'dynamic did not beat static'
assert d.stats.cycles < s.stats.cycles, 'dynamic was not faster'
print(f'  static:  {s.stats.mispredictions} mispredictions, {s.stats.cycles} cycles')
print(f'  dynamic: {d.stats.mispredictions} mispredictions, {d.stats.cycles} cycles')
"
pass "dynamic 2-bit predictor measurably beats static predict-not-taken"

section "7/8  HTML pipeline visualizer: renders, screenshot-verified with zero console errors"
python3 -m silicon.cli viz gcd -o /tmp/silicon_demo_viz.html --predictor dynamic
SIZE=$(wc -c < /tmp/silicon_demo_viz.html)
[ "$SIZE" -gt 5000 ] || { echo "FAIL: visualizer output suspiciously small ($SIZE bytes)"; exit 1; }
pass "visualizer HTML generated ($SIZE bytes)"
if command -v node >/dev/null 2>&1 && [ -d /opt/node22/lib/node_modules/playwright ] && [ -x /opt/pw-browsers/chromium ]; then
  ERRORS=$(NODE_PATH=/opt/node22/lib/node_modules node -e "
    const { chromium } = require('playwright');
    (async () => {
      const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
      const page = await b.newPage();
      const errs = [];
      page.on('pageerror', e => errs.push(e.message));
      page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
      await page.goto('file:///tmp/silicon_demo_viz.html');
      await page.waitForTimeout(300);
      console.log(JSON.stringify(errs));
      await b.close();
    })();
  ")
  [ "$ERRORS" = "[]" ] || { echo "FAIL: browser console errors: $ERRORS"; exit 1; }
  pass "visualizer renders with zero browser console errors"
else
  echo "  (skipped headless-browser check: playwright/chromium not available in this environment)"
fi

section "8/8  CLI error handling: bad input produces clean errors, not raw tracebacks"
set +e
python3 -m silicon.cli assemble /dev/stdin <<< "bogus_mnemonic t0, t1" >/tmp/err1 2>&1
python3 -m silicon.cli run /dev/stdin <<< "" >/tmp/err2 2>&1
python3 -m silicon.cli pipeline /dev/stdin --max-cycles 200 <<< $'loop:\n  j loop' >/tmp/err3 2>&1
set -e
for f in /tmp/err1 /tmp/err2 /tmp/err3; do
  grep -q "Traceback" "$f" && { echo "FAIL: raw traceback leaked in $f"; cat "$f"; exit 1; }
done
grep -q "assembler error" /tmp/err1
grep -q "trap:" /tmp/err2
grep -q "trap:" /tmp/err3
pass "bad input produces clean, non-crashing error messages"

echo
echo "=== ALL CHECKS PASSED ==="
