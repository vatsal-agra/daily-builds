#!/usr/bin/env bash
# Runs every feature of Bellman end to end and prints a final PASS/FAIL
# summary. Exits 0 only if everything is green.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
TOTAL=0
FAILED_STEPS=()

step() {
    local name="$1"
    shift
    TOTAL=$((TOTAL + 1))
    echo ""
    echo "=== $name ==="
    if "$@"; then
        echo "--- PASS: $name ---"
        PASS=$((PASS + 1))
    else
        echo "--- FAIL: $name ---"
        FAILED_STEPS+=("$name")
    fi
}

step "Unit tests (bellman/dp, td, minimax, selfplay, reinforce, envs)" \
    python3 -m unittest discover -s tests -v

step "Gradient check (REINFORCE policy network backward pass)" \
    python3 -m bellman.gradcheck

step "Full pipeline: viz_export.py (production episode counts)" \
    python3 -m bellman.viz_export

step "Browser: visualizer/index.html end to end (Playwright, headless Chromium)" \
    python3 browser_checks.py

echo ""
echo "================================================================"
echo "demo.sh: $PASS/$TOTAL steps green"
if [ "$PASS" -ne "$TOTAL" ]; then
    echo "FAILED: ${FAILED_STEPS[*]}"
    echo "================================================================"
    exit 1
fi
echo "================================================================"
exit 0
