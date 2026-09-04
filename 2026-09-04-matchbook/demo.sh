#!/usr/bin/env bash
# Matchbook end-to-end verification script.
#
# Exercises every required feature (R1-R4) and every stretch feature
# (S1-S2), plus the full unit/property test suite, and prints a final
# PASS/FAIL tally. Exits non-zero if anything fails.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

check() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  [PASS] $desc"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "=================================================================="
echo "Matchbook verification"
echo "=================================================================="

echo
echo "--- Unit / property test suite ---"
if python3 -m unittest discover -s tests -v > "$WORKDIR/tests.log" 2>&1; then
    N=$(grep -oE "Ran [0-9]+ test" "$WORKDIR/tests.log" | grep -oE "[0-9]+")
    echo "  [PASS] full test suite ($N tests green)"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] test suite -- see below"
    tail -40 "$WORKDIR/tests.log"
    FAIL=$((FAIL + 1))
fi

echo
echo "--- R1: matching engine (limit/market/IOC/FOK, partial fills) ---"
python3 -m matchbook.cli demo --journal "$WORKDIR/demo.journal" --out "$WORKDIR/demo.html" > "$WORKDIR/demo.log" 2>&1
DEMO_RC=$?
check "demo subcommand exits 0" test "$DEMO_RC" = "0"
check "demo output shows a partial-fill sweep" grep -q "2 trades: 50@10.05, 70@10.0" "$WORKDIR/demo.log"
check "demo output shows an oversized FOK order rejected atomically" grep -q "status=REJECTED (no partial fill, book untouched)" "$WORKDIR/demo.log"
check "demo output shows an unfillable IOC order cancelled, not resting" grep -q "status=CANCELLED (does not rest)" "$WORKDIR/demo.log"

echo
echo "--- R2: event-sourced journal + crash recovery ---"
check "crash-demo reports matching fingerprints" bash -c "python3 -m matchbook.cli crash-demo --journal '$WORKDIR/crash.journal' --ticks 300 --seed 11 | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"fingerprints_match\"] else 1)'"
python3 -m matchbook.cli run --ticks 200 --seed 5 --journal "$WORKDIR/run.journal" > "$WORKDIR/run_summary.json" 2>"$WORKDIR/run.err"
check "run --journal exits 0" test -s "$WORKDIR/run_summary.json"
python3 -m matchbook.cli replay "$WORKDIR/run.journal" > "$WORKDIR/replay_summary.json" 2>"$WORKDIR/replay.err"
check "replay-only reconstruction matches the live run's summary byte-for-byte" diff -q "$WORKDIR/run_summary.json" "$WORKDIR/replay_summary.json"

echo
echo "--- R3: multi-agent market simulation (determinism + real emergent trades) ---"
python3 -m matchbook.cli run --ticks 300 --seed 77 > "$WORKDIR/run_a.json" 2>&1
python3 -m matchbook.cli run --ticks 300 --seed 77 > "$WORKDIR/run_b.json" 2>&1
check "same seed reproduces an identical session" diff -q "$WORKDIR/run_a.json" "$WORKDIR/run_b.json"
check "the session actually traded (not a stub)" bash -c "python3 -c \"import json; d=json.load(open('$WORKDIR/run_a.json')); exit(0 if d['trade_count'] > 50 else 1)\""

echo
echo "--- R4: interactive HTML visualizer ---"
python3 -m matchbook.cli viz --ticks 300 --seed 21 --symbols ACME,GLOBEX --out "$WORKDIR/viz.html" --position-limit 80 --max-order-qty 50 > "$WORKDIR/viz.log" 2>&1
check "viz writes a substantial self-contained HTML file" bash -c "[ -s '$WORKDIR/viz.html' ] && [ \$(stat -c%s '$WORKDIR/viz.html' 2>/dev/null || stat -f%z '$WORKDIR/viz.html') -gt 50000 ]"
check "viz HTML embeds the session data inline (no server needed)" grep -q "const DATA = " "$WORKDIR/viz.html"

if command -v node >/dev/null 2>&1 && [ -d /opt/node22/lib/node_modules/playwright ]; then
    cat > "$WORKDIR/headless_check.js" << 'EOF'
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file://' + process.argv[2]);
  await page.waitForTimeout(300);
  await page.fill('#scrubber', '150');
  await page.dispatchEvent('#scrubber', 'input');
  await page.waitForTimeout(200);
  await browser.close();
  process.exit(errors.length === 0 ? 0 : 1);
})();
EOF
    check "viz HTML runs error-free in a real headless browser" env NODE_PATH=/opt/node22/lib/node_modules node "$WORKDIR/headless_check.js" "$WORKDIR/viz.html"
else
    echo "  [SKIP] headless browser check (node/playwright not available in this environment)"
fi

echo
echo "--- S1: risk engine (position limits, self-trade prevention, fat-finger collar) ---"
check "tight risk limits produce real pre-trade rejections" bash -c "python3 -m matchbook.cli run --ticks 300 --seed 99 --symbols ACME,GLOBEX --position-limit 80 --max-order-qty 50 | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"rejections\"] > 0 else 1)'"
check "self-trade prevention fires within a normal session" bash -c "python3 -m matchbook.cli run --ticks 300 --seed 99 | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d[\"stp_cancels\"] > 0 else 1)'"

echo
echo "--- S2: multi-symbol exchange with cross-symbol portfolios ---"
check "a multi-symbol session trades independently on both books" bash -c "python3 -m matchbook.cli run --ticks 300 --seed 3 --symbols A,B | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if set(d[\"last_price\"]) == {\"A\",\"B\"} else 1)'"

echo
echo "=================================================================="
echo "RESULT: $PASS passed, $FAIL failed"
echo "=================================================================="
[ "$FAIL" -eq 0 ]
