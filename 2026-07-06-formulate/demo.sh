#!/usr/bin/env bash
# Runs the full verification suite for Formulate:
#   1. Python unit/fuzz/server tests
#   2. An end-to-end API walkthrough of every required + stretch feature
#   3. A terminal demo of a real workbook
#   4. A headless-browser UI smoke test (skipped gracefully if no browser
#      runtime is available in this environment)
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/4  Python test suite (unit + fuzz oracle + HTTP server)"
python3 -m unittest discover -s tests -t . -v

echo
echo "==> 2/4  End-to-end API walkthrough (D1-D9: every feature, over real HTTP)"
python3 tests/demo_walkthrough.py

echo
echo "==> 3/4  CLI demo (builds + prints a real budget workbook)"
python3 cli.py demo

echo
echo "==> 4/4  Headless-browser UI smoke test"
CHROME_CANDIDATES=(
  "${CHROME_PATH:-}"
  "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
  "$(command -v chromium 2>/dev/null || true)"
  "$(command -v google-chrome 2>/dev/null || true)"
)
FOUND_CHROME=""
for c in "${CHROME_CANDIDATES[@]}"; do
  if [ -n "$c" ] && [ -x "$c" ]; then FOUND_CHROME="$c"; break; fi
done

PLAYWRIGHT_CANDIDATES=(
  "${PLAYWRIGHT_MODULE:-}"
  "/opt/node22/lib/node_modules/playwright/index.js"
)
FOUND_PLAYWRIGHT=""
for p in "${PLAYWRIGHT_CANDIDATES[@]}"; do
  if [ -n "$p" ] && [ -f "$p" ]; then FOUND_PLAYWRIGHT="$p"; break; fi
done

if [ -n "$FOUND_CHROME" ] && [ -n "$FOUND_PLAYWRIGHT" ] && command -v node >/dev/null 2>&1; then
  CHROME_PATH="$FOUND_CHROME" PLAYWRIGHT_MODULE="$FOUND_PLAYWRIGHT" node tests/ui_smoke.mjs
else
  echo "SKIPPED: no headless Chromium + Playwright module found in this environment."
  echo "         (set CHROME_PATH and PLAYWRIGHT_MODULE to run it manually)"
fi

echo
echo "All checks complete."
