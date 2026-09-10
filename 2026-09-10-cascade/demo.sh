#!/usr/bin/env bash
# Cascade end-to-end verification: exercises every feature from PLAN.md
# (HTML parsing, CSS parsing + cascade, layout, PNG rendering, flexbox,
# the Chromium differential oracle, the interactive inspector, and CLI
# error handling) and reports a clear pass/fail count. Exits 0 only if
# every check passed.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0
FAILED_NAMES=()

check() {
  local name="$1"
  shift
  if "$@" > /tmp/cascade_demo_out.$$ 2>&1; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name"
    sed 's/^/         /' /tmp/cascade_demo_out.$$ | tail -20
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
  rm -f /tmp/cascade_demo_out.$$
}

check_output_contains() {
  local name="$1" needle="$2"
  shift 2
  local out
  out="$("$@" 2>&1)"
  if echo "$out" | grep -qF "$needle"; then
    echo "  [PASS] $name"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $name (expected to see: $needle)"
    echo "$out" | sed 's/^/         /' | tail -10
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "=== 1. Full unit test suite ==="
check "unittest discover (all suites)" bash -c "cd tests && python3 -m unittest discover -s . -p 'test_*.py' -v"

echo ""
echo "=== 2. HTML parsing end-to-end ==="
cat > "$WORK/parse.html" <<'EOF'
<div><p>one<p>two<ul><li>a<li>b</ul></div>
EOF
check_output_contains "malformed markup recovers (auto-close p/li)" "block:p" \
  python3 src/cli.py layout "$WORK/parse.html" --width 400

echo ""
echo "=== 3. CSS parsing + cascade end-to-end ==="
cat > "$WORK/cascade.html" <<'EOF'
<html><head><style>
#x { color: red; } .y { color: blue !important; }
</style></head><body><p id="x" class="y">text</p></body></html>
EOF
check "cascade.html renders without error" python3 src/cli.py render "$WORK/cascade.html" --out "$WORK/cascade.png"
python3 src/cli.py viz "$WORK/cascade.html" --width 400 --out "$WORK/cascade_viz.html" > /dev/null
check_output_contains "!important beats id specificity in the computed cascade" "rgba(0,0,255" \
  cat "$WORK/cascade_viz.html"

echo ""
echo "=== 4. Layout engine (box model, margin collapsing, inline wrap, flexbox) ==="
check "renders every example page" python3 src/cli.py demo
for f in renders/*.png; do
  check "'$f' is a real PNG (file utility cross-check)" bash -c "file '$f' | grep -q 'PNG image data'"
done

echo ""
echo "=== 5. PNG renderer produces genuine, spec-valid files ==="
check "rendered PNG round-trips through our own decoder" python3 -c "
import sys; sys.path.insert(0, 'src')
from png_encoder import decode_png
w, h, data = decode_png(open('renders/cards.png', 'rb').read())
assert w == 900 and h > 0 and len(data) == w * h * 4
print('ok', w, h)
"

echo ""
echo "=== 6. Interactive box inspector (stretch #7) ==="
check "cascade viz produces a self-contained HTML file" python3 src/cli.py viz examples/boxmodel.html --width 900 --out "$WORK/inspector.html"
check_output_contains "inspector HTML has the expected structure" "CASCADE INSPECTOR" cat "$WORK/inspector.html"

echo ""
echo "=== 7. CLI error handling (clean errors, no raw tracebacks) ==="
check "missing file -> clean error, exit 1" bash -c "
  python3 src/cli.py render /no/such/file.html --out /tmp/x.png 2>&1 1>/dev/null | grep -q 'no such file' && \
  ! python3 src/cli.py render /no/such/file.html --out /tmp/x.png 2>&1 | grep -q Traceback
"
check "zero width -> clean error, exit 1" bash -c "
  ! python3 src/cli.py render examples/cards.html --width 0 --out /tmp/x.png > /dev/null 2>&1
"

echo ""
echo "=== 8. Chromium differential oracle + headless UI smoke test (stretch #6, #7) ==="
if [ -d tools/oracle/node_modules ]; then
  check "layout is pixel-identical to real Chromium (12 fixtures)" bash -c "cd tests && python3 -m unittest test_diff_oracle -v"
  check "inspector has zero console errors in real Chromium" bash -c "cd tests && python3 -m unittest test_viz_ui -v"
else
  echo "  [SKIP] tools/oracle/node_modules not installed in this environment"
  echo "         (run: cd tools/oracle && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install)"
  echo "         test_diff_oracle.py / test_viz_ui.py already skip themselves cleanly"
fi

echo ""
echo "========================================"
echo "  $PASS passed, $FAIL failed"
echo "========================================"
if [ "$FAIL" -gt 0 ]; then
  echo "Failed checks:"
  for n in "${FAILED_NAMES[@]}"; do echo "  - $n"; done
  exit 1
fi
exit 0
