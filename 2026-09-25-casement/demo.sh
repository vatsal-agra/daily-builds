#!/usr/bin/env bash
# Casement end-to-end demo / verification script.
# Exercises every required and stretch feature and fails loudly (non-zero
# exit) the moment anything doesn't behave as documented.
set -euo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

check() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  [ok] $desc"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "== 1/6: Unit test suite (parser, cascade, layout, flexbox, CLI, edge cases) =="
python3 -m unittest discover -s tests -v > "$TMP/unittest.log" 2>&1
if grep -q "^OK" "$TMP/unittest.log"; then
    n=$(grep -c "^test_" "$TMP/unittest.log" || true)
    echo "  [ok] full unit test suite ($(tail -3 "$TMP/unittest.log" | grep Ran))"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] unit test suite -- see $TMP/unittest.log"
    tail -40 "$TMP/unittest.log"
    FAIL=$((FAIL + 1))
fi

echo
echo "== 2/6: Render (required feature 1-4: HTML/CSS parsing, cascade, block/inline + flexbox layout, paint) =="
python3 -m casement.cli render examples/showcase.html -o "$TMP/showcase.png" --width 700 --json "$TMP/showcase.json"
check "showcase.png was written and non-trivial" test -s "$TMP/showcase.png"
check "showcase.png is at least 5KB (real rendered content, not a blank page)" \
    bash -c '[ "$(stat -c%s "'"$TMP"'/showcase.png")" -gt 5000 ]'
check "layout.json was exported and is valid JSON" python3 -c "import json; json.load(open('$TMP/showcase.json'))"

echo
echo "== 3/6: Interactive box-model inspector (stretch feature 5) =="
python3 -m casement.cli inspect examples/showcase.html -o "$TMP/inspector.html" --width 700
check "inspector.html was written" test -s "$TMP/inspector.html"
check "inspector.html embeds the boxes JSON and the rendered PNG" \
    bash -c "grep -q 'boxes-data' '$TMP/inspector.html' && grep -q 'data:image/png;base64,' '$TMP/inspector.html'"

if command -v node >/dev/null 2>&1 && NODE_PATH="$(npm root -g 2>/dev/null)" node -e "require('playwright')" >/dev/null 2>&1; then
    cat > "$TMP/inspector_check.js" << 'JSEOF'
const { chromium } = require('playwright');
(async () => {
  const errors = [];
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 1000, height: 900 } });
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => errors.push(String(err)));
  await page.goto('file://' + process.argv[2]);
  await page.waitForTimeout(200);
  await page.mouse.move(60, 340);
  await page.waitForTimeout(150);
  const panelText = await page.$eval('#panel', (el) => el.textContent);
  await browser.close();
  if (errors.length) { console.error('CONSOLE_ERRORS:' + JSON.stringify(errors)); process.exit(1); }
  if (!panelText || panelText.indexOf('box type') === -1) { console.error('PANEL_DID_NOT_UPDATE'); process.exit(1); }
  console.log('OK');
})().catch((e) => { console.error(String(e)); process.exit(1); });
JSEOF
    if NODE_PATH="$(npm root -g)" node "$TMP/inspector_check.js" "$TMP/inspector.html" > "$TMP/inspector_check.log" 2>&1; then
        echo "  [ok] headless-Chromium smoke test: zero console errors, hover panel updates"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] headless-Chromium inspector check -- $(cat "$TMP/inspector_check.log")"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  [skip] node/playwright not available in this environment"
fi

echo
echo "== 4/6: Chromium differential oracle (stretch feature 6) =="
if command -v node >/dev/null 2>&1 && NODE_PATH="$(npm root -g 2>/dev/null)" node -e "require('playwright')" >/dev/null 2>&1; then
    if python3 -m casement.cli compare examples/oracle_test.html --width 800 --tolerance 4 > "$TMP/compare.log" 2>&1; then
        echo "  [ok] compare examples/oracle_test.html --tolerance 4 -> PASS"
        PASS=$((PASS + 1))
        tail -3 "$TMP/compare.log" | sed 's/^/      /'
    else
        echo "  [FAIL] oracle comparison exceeded documented tolerance"
        cat "$TMP/compare.log"
        FAIL=$((FAIL + 1))
    fi
else
    echo "  [skip] node/playwright not available in this environment"
fi

echo
echo "== 5/6: CLI error handling (clean errors, not raw tracebacks) =="
set +e
python3 -m casement.cli render /no/such/file.html -o "$TMP/x.png" > "$TMP/err1.log" 2>&1
code1=$?
python3 -m casement.cli render examples/showcase.html --width 0 -o "$TMP/x.png" > "$TMP/err2.log" 2>&1
code2=$?
set -e
check "missing input file exits 1 with a clean message (no traceback)" \
    bash -c "[ $code1 -eq 1 ] && grep -q 'casement: error' '$TMP/err1.log' && ! grep -q Traceback '$TMP/err1.log'"
check "--width 0 exits 1 with a clean message" \
    bash -c "[ $code2 -eq 1 ] && grep -q 'casement: error' '$TMP/err2.log'"

echo
echo "== 6/6: Manual CLI walkthrough over a fresh page (independent of the test suite) =="
cat > "$TMP/manual.html" << 'HTMLEOF'
<html><head><style>
  body { font-family: monospace; margin: 0; }
  .hero { display: flex; justify-content: space-between; align-items: center; background: navy; color: white; padding: 20px; }
  .badge { background: gold; padding: 4px 10px; }
</style></head>
<body>
  <div class="hero"><span>Casement</span><span class="badge">v0.1</span></div>
  <p>A hand-rolled HTML/CSS engine, rendered by itself.</p>
</body></html>
HTMLEOF
python3 -m casement.cli render "$TMP/manual.html" -o "$TMP/manual.png" --width 500
check "manual walkthrough page rendered" test -s "$TMP/manual.png"

echo
echo "================================================================"
echo "Casement demo: $PASS checks passed, $FAIL failed"
echo "================================================================"
[ "$FAIL" -eq 0 ]
