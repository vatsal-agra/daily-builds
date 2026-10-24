#!/usr/bin/env bash
# Full verification: unit/integration tests, large differential fuzz, demo tour, optional browser check.
set -euo pipefail
cd "$(dirname "$0")"

echo "== tests"
ruby -Itest test/all.rb

echo
echo "== differential fuzz (CLI)"
bin/pinion fuzz --count 400
bin/pinion fuzz --count 150 --packages 8 --versions 6 --density 0.25 --start 5000

echo
echo "== demo tour (must run clean)"
./demo.sh > /dev/null
echo "demo OK"

if command -v node >/dev/null 2>&1 && node -e "require('playwright')" 2>/dev/null; then
  echo
  echo "== HTML report in headless Chromium (light + dark, click-to-trace, no console errors)"
  node test/browser_check.js
else
  echo "(skipping browser check: node + playwright not available)"
fi
echo
echo "ALL GREEN"
