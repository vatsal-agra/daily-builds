#!/usr/bin/env bash
# Bellman demo: installs deps, runs the full test suite, trains every
# agent on every environment (real training, real numbers — nothing
# canned), builds the interactive HTML report, and does a handful of
# scripted CLI-robustness checks (bad input, invalid flags). Exits
# non-zero on the first failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

pass=0
fail=0
check() {
    local desc="$1"; shift
    if "$@" > /tmp/bellman_demo_check.log 2>&1; then
        echo "  OK  $desc"
        pass=$((pass + 1))
    else
        echo "FAIL  $desc"
        cat /tmp/bellman_demo_check.log
        fail=$((fail + 1))
    fi
}
expect_fail() {
    local desc="$1"; shift
    if "$@" > /tmp/bellman_demo_check.log 2>&1; then
        echo "FAIL  $desc (expected nonzero exit, got 0)"
        cat /tmp/bellman_demo_check.log
        fail=$((fail + 1))
    else
        echo "  OK  $desc"
        pass=$((pass + 1))
    fi
}

echo "=== [0/4] Install dependencies ==="
pip install -q -r requirements.txt

echo
echo "=== [1/4] Unit + integration test suite ==="
python3 -m unittest discover -s tests -v

echo
echo "=== [2/4] Full training run (every required + stretch feature, real numbers) ==="
python3 -m bellman.train demo --episodes 800 --cartpole-episodes 150 --ablation-episodes 200 --ablation-seeds 3 --seed 0

echo
echo "=== [3/4] Interactive HTML report ==="
python3 -m bellman.viz
test -f report.html
echo "  report.html: $(du -h report.html | cut -f1)"

echo
echo "=== [4/4] CLI robustness checks (empty/invalid input) ==="
expect_fail "no subcommand -> usage error"                python3 -m bellman.train
expect_fail "unknown subcommand -> clean error"            python3 -m bellman.train frobnicate
expect_fail "negative --episodes -> validation error"      python3 -m bellman.train qlearning --episodes -5
expect_fail "negative --n-seeds -> validation error"       python3 -m bellman.train ablation --n-seeds -1
expect_fail "path-separator --name -> validation error"    python3 -m bellman.train dqn --episodes 5 --name ../escape
check       "--help does not crash"                        python3 -m bellman.train --help
check       "single qlearning run still works after checks" python3 -m bellman.train qlearning --episodes 50

echo
echo "=== Summary ==="
echo "checks passed: $pass, failed: $fail"
if [ "$fail" -ne 0 ]; then
    echo "DEMO FAILED"
    exit 1
fi
echo "DEMO PASSED"
