#!/usr/bin/env bash
# Runs the full verification suite for Waveforge:
#   1. The Node test suite (DSP engine, sequencer, WAV encoding, validation, CLI)
#   2. A CLI render of the full demo song to a real WAV file
#   3. A headless-browser UI smoke test (skipped gracefully if no browser
#      runtime is available in this environment)
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/3  Node test suite"
node test/run.js

echo
echo "==> 2/3  CLI demo render (builds a real playable WAV from demo-pattern.json)"
node render.js demo-pattern.json /tmp/waveforge-demo-output.wav
ls -la /tmp/waveforge-demo-output.wav

echo
echo "==> 3/3  Headless-browser UI smoke test"
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
  CHROME_PATH="$FOUND_CHROME" PLAYWRIGHT_MODULE="$FOUND_PLAYWRIGHT" node test/ui_smoke.mjs
else
  echo "SKIPPED: no headless Chromium + Playwright module found in this environment."
  echo "         (set CHROME_PATH and PLAYWRIGHT_MODULE to run it manually)"
fi

echo
echo "All checks complete."
