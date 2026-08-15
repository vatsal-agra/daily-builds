#!/usr/bin/env bash
# Bellman end-to-end verification: exercises every required and stretch
# feature through the real CLI (not internal function calls), asserts on
# the actual printed output, and builds the final interactive HTML report.
# Exit code is 0 iff every check passes.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
FAILED_CHECKS=()

check() {
    local description="$1"
    local condition="$2"
    if eval "$condition"; then
        echo "  [PASS] $description"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $description"
        FAIL=$((FAIL + 1))
        FAILED_CHECKS+=("$description")
    fi
}

echo "=== Bellman verification ==="
echo

echo "--- 1/6: unit test suite ---"
TEST_OUTPUT=$(python3 -m unittest discover -s tests 2>&1)
TEST_EXIT=$?
echo "$TEST_OUTPUT" | tail -5
check "unit test suite exits 0" "[ $TEST_EXIT -eq 0 ]"
check "unit test suite reports OK" "echo \"\$TEST_OUTPUT\" | grep -q '^OK$'"
echo

echo "--- 2/6: DP oracle (Value Iteration + Policy Iteration ground truth) ---"
ORACLE_OUT=$(python3 -m bellman.cli oracle 2>&1)
echo "$ORACLE_OUT"
check "VI and PI agree on V*" "echo \"\$ORACLE_OUT\" | grep -q 'agree on V\*: True'"
check "optimal rollout return is exactly -13 (classic Cliff Walking result)" \
    "echo \"\$ORACLE_OUT\" | grep -q 'Optimal rollout return = -13.0'"
echo

echo "--- 3/6: GridWorld TD control (Q-Learning / SARSA / SARSA(lambda)) ---"
GW_OUT=$(python3 -m bellman.cli gridworld --episodes 500 --seed 0 2>&1)
echo "$GW_OUT"
check "Q-Learning matches DP-optimal exactly" "echo \"\$GW_OUT\" | grep -q 'matches optimal'"
check "SARSA reaches the goal (prints a finite, non-crashing return)" \
    "echo \"\$GW_OUT\" | grep -q 'SARSA greedy return:'"
echo

echo "--- 4/6: CartPole REINFORCE (from-scratch autodiff + MLP policy) ---"
CP_OUT=$(python3 -m bellman.cli cartpole --episodes 400 --seed 1 2>&1)
echo "$CP_OUT"
EVAL_MEAN=$(echo "$CP_OUT" | grep 'Trained policy eval mean' | grep -oE '[0-9]+\.[0-9]+' | head -1)
check "trained policy sustains well over 100 steps (mean=${EVAL_MEAN:-?})" \
    "python3 -c \"import sys; sys.exit(0 if float('${EVAL_MEAN:-0}') > 100 else 1)\""
check "training beats random baseline by a wide margin" "echo \"\$CP_OUT\" | grep -qE 'Improvement: *x[1-9][0-9]*\\.'"
echo

echo "--- 5/6: Blackjack Monte Carlo Exploring Starts ---"
BJ_OUT=$(python3 -m bellman.cli blackjack --episodes 500000 --seed 0 2>&1)
echo "$BJ_OUT"
AGREEMENT=$(echo "$BJ_OUT" | grep -oE '[0-9]+\.[0-9]+%' | head -1 | tr -d '%')
check "agreement with independently-computed optimal policy >= 95% (got ${AGREEMENT:-?}%)" \
    "python3 -c \"import sys; sys.exit(0 if float('${AGREEMENT:-0}') >= 95.0 else 1)\""
echo

echo "--- 6/6: interactive HTML report ---"
rm -f viz/report.html
VIZ_OUT=$(python3 -m bellman.cli viz --out viz/report.html --gridworld-episodes 500 --cartpole-episodes 400 --blackjack-episodes 500000 --seed 0 2>&1)
echo "$VIZ_OUT"
check "report file was written" "[ -f viz/report.html ]"
check "report is a substantial, non-empty HTML file (>50KB)" \
    "[ \$(wc -c < viz/report.html) -gt 51200 ]"
check "report has no unresolved template placeholders" \
    "! grep -q '__DATA_JSON__\|__APP_JS__' viz/report.html"
check "report embeds real gridworld/cartpole/blackjack data" \
    "grep -q '\"gridworld\"' viz/report.html && grep -q '\"cartpole\"' viz/report.html && grep -q '\"blackjack\"' viz/report.html"

# Headless-browser check: page loads with zero console/page errors, all 3
# tabs render, and the CartPole animation runs a frame -- catches JS bugs
# no Python-side check ever could.
if python3 -c "import playwright" 2>/dev/null; then
    BROWSER_CHECK=$(python3 tests/browser_check.py "$(pwd)/viz/report.html" 2>&1)
    echo "$BROWSER_CHECK"
    check "headless browser reports zero console/page errors" \
        "echo \"\$BROWSER_CHECK\" | grep -q 'NO_ERRORS'"
else
    echo "  (playwright not installed -- skipping headless browser check)"
fi
echo

echo "=== Summary: $PASS passed, $FAIL failed ==="
if [ $FAIL -gt 0 ]; then
    echo "Failed checks:"
    for c in "${FAILED_CHECKS[@]}"; do
        echo "  - $c"
    done
    exit 1
fi
echo "All checks green."
exit 0
