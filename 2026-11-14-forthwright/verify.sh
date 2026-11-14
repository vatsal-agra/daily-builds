#!/usr/bin/env bash
# Runs every check. Exit code is non-zero if anything fails.
set -e
cd "$(dirname "$0")"
echo "== engine / analyzer / optimizer / tracer / CLI =="; node test/run.js
echo "== regression checks for REVIEW.md =="; node test/review.js | tail -1
echo "== Forth conformance suite (written in Forth) =="; node cli.js test
echo "== analyzer soundness + optimizer differential fuzz =="
for s in 12345 7 8; do SEED=$s N=3000 node test/fuzz.js | tail -2; done
if node -e "require('playwright')" 2>/dev/null; then echo "== web IDE (headless Chromium) =="; node test/ui.js
else echo "SKIPPED: UI tests (playwright not installed)"; fi
echo "verify: ALL GREEN"
