#!/usr/bin/env bash
# Runs the full verification suite for Ashenkeep:
#   1. The node:test unit/integration suite (dungeon, fov, astar, entities,
#      items, combat, game — 87 checks)
#   2. A narrated, assertion-backed playthrough exercising every shipped
#      feature end-to-end, including a real autonomous win against the
#      floor-10 boss
#   3. A headless-browser UI smoke test in light + dark mode (skipped
#      gracefully if no browser runtime is available in this environment)
set -euo pipefail
cd "$(dirname "$0")"

echo "==> 1/3  node:test unit/integration suite"
node --test "tests/test_*.js"

echo
echo "==> 2/3  Narrated feature-by-feature + autonomous-win playthrough"
node tests/demo_playthrough.js

echo
echo "==> 3/3  Headless-browser UI smoke test (light + dark)"
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
