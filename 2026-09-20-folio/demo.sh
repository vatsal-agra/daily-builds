#!/usr/bin/env bash
# Folio demo/verification script: exercises every shipped feature through
# the real CLI (not just the test suite in isolation) and checks the
# results, the same way this repo's other builds' demo.sh scripts do.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
OUT_DIR="$(mktemp -d)"
trap 'rm -rf "$OUT_DIR"' EXIT

check() {
  local desc="$1"
  shift
  if "$@" >/tmp/folio_demo_check.log 2>&1; then
    echo "  [PASS] $desc"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $desc"
    cat /tmp/folio_demo_check.log | sed 's/^/         /'
    FAIL=$((FAIL + 1))
  fi
}

echo "=== 1. Unit + integration test suite (103 tests) ==="
check "full test suite (unittest discover)" python3 -m unittest discover -s tests

echo
echo "=== 2. Feature 1 -- HTML parser -> DOM (via 'folio info') ==="
check "parses basic.html and reports real DOM element count" bash -c \
  "python3 -m folio.cli info examples/basic.html | grep -q 'DOM elements: 17'"

echo
echo "=== 3. Feature 2 -- CSS parser + cascade (via 'folio info') ==="
check "parses basic.html's <style> block into 6 author rules" bash -c \
  "python3 -m folio.cli info examples/basic.html | grep -q 'CSS rules (author): 6'"

echo
echo "=== 4. Feature 3 -- block/inline box-model layout + Feature 4 -- PNG paint ==="
check "renders basic.html to a real PNG" \
  python3 -m folio.cli render examples/basic.html -o "$OUT_DIR/basic.png" -w 500
check "output is a real, independently-decodable PNG (system 'file' utility)" bash -c \
  "file '$OUT_DIR/basic.png' | grep -q 'PNG image data'"
check "renders floats.html (box model + text wrap) to a real PNG" \
  python3 -m folio.cli render examples/floats.html -o "$OUT_DIR/floats.png" -w 500
check "floats.html output is a real PNG" bash -c \
  "file '$OUT_DIR/floats.png' | grep -q 'PNG image data'"

echo
echo "=== 5. Stretch feature -- float layout + clearance ==="
check "float layout produces correctly narrowed + full-width lines" python3 -c "
from folio.engine import render_html
from folio.layout import Box
html = '''<html><body style=\"margin:10px\">
<div style=\"float:left; width:80px; height:60px;\">L</div>
<div style=\"float:right; width:80px; height:60px;\">R</div>
<p>''' + ('word ' * 30) + '''</p>
</body></html>'''
page = render_html(html, viewport_width=300)
def find_p(b):
    if isinstance(b, Box) and b.node is not None and getattr(b.node, 'tag', None) == 'p':
        return b
    for c in b.children:
        if isinstance(c, Box):
            r = find_p(c)
            if r: return r
p = find_p(page.root_box)
lines = p.children[0].children
narrow = [l for l in lines if l.width < 280]
full = [l for l in lines if l.width == 280]
assert narrow, 'expected at least one float-narrowed line'
assert full, 'expected at least one full-width line below the floats'
"

echo
echo "=== 6. Stretch feature -- interactive DOM/box-model inspector ==="
check "generates the inspector HTML page" \
  python3 -m folio.cli inspect examples/basic.html -o "$OUT_DIR/inspector.html" -w 500
check "inspector embeds valid JSON with real regions + paint commands" python3 -c "
import json, re
html = open('$OUT_DIR/inspector.html').read()
m = re.search(r'const DATA = (.*?);\n\nconst canvas', html, re.DOTALL)
data = json.loads(m.group(1))
assert data['width'] == 500
assert len(data['regions']) > 0
assert len(data['paint']) > 0
"
if command -v node >/dev/null 2>&1; then
  check "inspector's embedded JS has no syntax errors (node --check)" bash -c \
    "python3 -c \"
import re
html = open('$OUT_DIR/inspector.html').read()
m = re.search(r'<script>(.*)</script>', html, re.DOTALL)
open('$OUT_DIR/inspector.js', 'w').write(m.group(1))
\" && node --check '$OUT_DIR/inspector.js'"
else
  echo "  [SKIP] node not available -- skipping inspector JS syntax check"
fi

echo
echo "=== 7. Headless-Chromium click-through smoke test (real browser, zero console errors) ==="
if python3 -c "import playwright" >/dev/null 2>&1; then
  check "inspector loads and responds to a click with zero console errors" python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    page = browser.new_page(viewport={'width': 900, 'height': 700})
    errors = []
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('file://$OUT_DIR/inspector.html')
    page.wait_for_timeout(200)
    canvas = page.locator('#canvas')
    box = canvas.bounding_box()
    page.mouse.click(box['x'] + 50, box['y'] + 50)
    page.wait_for_timeout(150)
    dom_path = page.locator('#domPath').inner_text()
    browser.close()
    assert not errors, f'console errors: {errors}'
    assert 'Nothing selected' not in dom_path, 'click did not select an element'
"
else
  echo "  [SKIP] playwright not installed -- skipping real-browser smoke test"
fi

echo
echo "=== 8. Differential verification against real headless Chromium ==="
if python3 -c "import playwright" >/dev/null 2>&1; then
  check "Folio's box-model geometry matches Chromium's (8 layout scenarios)" \
    python3 -m unittest tests.test_oracle -v
else
  echo "  [SKIP] playwright not installed -- skipping Chromium oracle tests"
fi

echo
echo "=== 9. CLI error handling (no raw tracebacks) ==="
check "missing file gives a clean error, not a traceback" bash -c \
  "! python3 -m folio.cli render /no/such/file.html 2>&1 | grep -q Traceback"
check "invalid --width gives a clean error, not a traceback" bash -c \
  "! python3 -m folio.cli render examples/basic.html -w 0 2>&1 | grep -q Traceback"
check "empty HTML file renders a minimal valid PNG instead of crashing" bash -c \
  "touch '$OUT_DIR/empty.html' && python3 -m folio.cli render '$OUT_DIR/empty.html' -o '$OUT_DIR/empty.png'"

echo
echo "=================================================="
echo "  $PASS passed, $FAIL failed"
echo "=================================================="
[ "$FAIL" -eq 0 ]
