#!/usr/bin/env bash
# Runs every test. UI tests are skipped (loudly) if Playwright is unavailable.
set -e
cd "$(dirname "$0")"
node test/run.js
if node -e "require('playwright')" 2>/dev/null; then node test/ui.js; else echo "SKIPPED: UI tests (playwright not installed)"; fi
echo "verify: done"
