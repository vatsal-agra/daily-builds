#!/usr/bin/env bash
# demo.sh -- runs the full verification suite for Torque:
#   1. the headless Node physics test suite (engine ground-truth checks)
#   2. a headless-Chromium smoke test of the live interactive playground
#
# Exits non-zero if either fails. (2) is skipped with a warning, not a
# failure, if Playwright/Chromium isn't available in this environment --
# the engine itself has zero dependencies and (1) always runs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Torque verification ==="
echo
echo "--- 1/2: physics test suite (tests/run-all.js) ---"
node tests/run-all.js
echo

echo "--- 2/2: live playground smoke test (headless Chromium) ---"
GLOBAL_NODE_MODULES="$(npm root -g 2>/dev/null || true)"
CHROMIUM_BIN="${CHROMIUM_PATH:-/opt/pw-browsers/chromium}"

if [ -d "$GLOBAL_NODE_MODULES/playwright" ] && [ -x "$CHROMIUM_BIN" ]; then
  NODE_PATH="$GLOBAL_NODE_MODULES" CHROMIUM_PATH="$CHROMIUM_BIN" node tests/smoke-demo.js
else
  echo "Playwright/Chromium not found in this environment -- skipping the"
  echo "browser smoke test. The engine test suite above already passed;"
  echo "open demo/index.html directly in a browser to check the UI."
fi

echo
echo "=== all checks passed ==="
