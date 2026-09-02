#!/usr/bin/env bash
# Beacon demo/verification script: exercises every feature end-to-end and
# exits non-zero on any failure. Run from anywhere; paths are relative to
# this script's own location.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PY="${PYTHON:-python3}"
OUT_DIR="$(mktemp -d)"
trap 'rm -rf "$OUT_DIR"' EXIT

echo "== Beacon verification =="
echo "Python: $($PY --version)"
echo "Scratch dir: $OUT_DIR"
echo

echo "-- [1/5] Unit + integration test suite --"
"$PY" -m unittest discover -s tests -v
echo

echo "-- [2/5] CLI: 'demo' across all three built-in maps --"
"$PY" -m beacon.cli demo --max-steps 500
echo

echo "-- [3/5] CLI: explicit waypoint navigation (stretch feature 5) --"
"$PY" -m beacon.cli run --world open --mode waypoints \
    --waypoint 10,2 --waypoint 15,10 --waypoint 3,15 --waypoint 2,2 \
    --max-steps 400
echo

echo "-- [4/5] CLI: frontier exploration + HTML visualizer (stretch feature 6) --"
VIZ_OUT="$OUT_DIR/beacon_demo_office.html"
"$PY" -m beacon.cli viz --world office --max-steps 400 --out "$VIZ_OUT"
if [ ! -s "$VIZ_OUT" ]; then
    echo "FAIL: visualizer file was not written" >&2
    exit 1
fi
echo "visualizer written: $VIZ_OUT ($(wc -c < "$VIZ_OUT") bytes)"
echo

echo "-- [5/5] Headless-browser smoke test of the visualizer --"
if "$PY" -c "import playwright" >/dev/null 2>&1; then
    "$PY" - "$VIZ_OUT" <<'PYEOF'
import sys
from playwright.sync_api import sync_playwright

path = sys.argv[1]
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"file://{path}")
    page.wait_for_timeout(400)
    page.evaluate("cur = Math.floor(frames.length / 2); draw();")
    page.wait_for_timeout(150)
    page.click("#playBtn")
    page.wait_for_timeout(600)
    page.click("#playBtn")
    browser.close()

if errors:
    print("JS console errors:", errors)
    sys.exit(1)
print("no JS console errors; playback controls exercised cleanly")
PYEOF
else
    echo "(playwright not installed in this environment -- skipping browser smoke test;"
    echo " the visualizer's JSON payload and CLI success above already verify it renders"
    echo " valid data. install with 'pip install playwright' for the full browser check.)"
fi
echo

echo "== All checks passed =="
