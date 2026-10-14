#!/usr/bin/env bash
# Full verification of Plinth. Exits non-zero on the first failure.
#   1. cargo test (unit/feature/hostile/repair/CLI/model-differential/crash-fuzz/mutants)
#   2. extra crash-fuzz and differential-fuzz seeds through the CLI
#   3. every journal mutant must be killed
#   4. demo tour, then the HTML block map is loaded in headless Chromium
set -euo pipefail
cd "$(dirname "$0")"
export PLINTH_NOSYNC=1
step() { printf '\n\033[1;35m### %s\033[0m\n' "$*"; }

step "build"
cargo build --release 2>&1 | tail -1
P=$PWD/target/release/plinth

step "cargo test --release"
cargo test --release 2>&1 | grep -E "^test result|^running|FAILED|panicked" 

step "more crash-fuzz seeds (correct journal must never fail)"
for seed in 11 12 13 14 15; do $P crashtest --seed $seed --ops 60 | sed -n '1,3p'; done

step "differential fuzz vs reference model (more seeds, longer)"
for seed in 21 22 23 24 25 26; do $P difftest --seed $seed --ops 2500; done

step "mutants: every broken journal must be caught"
for bug in $($P bugs); do
  out=$($P crashtest --seed 1 --ops 40 --bug $bug)
  echo "$out" | grep -q "killed" || { echo "MUTANT $bug SURVIVED"; echo "$out"; exit 1; }
  printf '  %-18s killed\n' "$bug"
done

step "demo tour"
MAP_OUT=$PWD/target/demo-map.html ./demo.sh > target/demo.log 2>&1 || { tail -30 target/demo.log; exit 1; }
tail -3 target/demo.log

step "HTML block map in headless Chromium"
if command -v node >/dev/null 2>&1; then
  export NODE_PATH=${NODE_PATH:-}:$(npm root -g 2>/dev/null || true):/node-tools/node_modules
  node check_map.js target/demo-map.html target/map.png
else
  echo "node not available; skipping browser check"
fi

printf '\n\033[1;32mALL VERIFICATION PASSED\033[0m\n'
