#!/usr/bin/env bash
# Full gate for Cairn. Ends with "ALL GREEN" or exits non-zero at the first failure.
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n== %s\n' "$*"; }
C=./target/release/cairn
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

step "build (warnings are errors)"
RUSTFLAGS="-D warnings" cargo build --release --all-targets 2>&1 | tail -2
cargo fmt --check

step "tests (unit-ish, model-based, features, barrier hazards, fuzz, CLI)"
cargo test --release 2>&1 | grep -E "^test result|FAILED|panicked" | sort | uniq -c

step "review re-check (REVIEW.md probes)"
./review_check.sh | tail -3

step "demo 1: every example under every collector, with the oracle checking the heap (every allocation for hello, every 61st for the heavy ones)"
for f in hello cycles churn cache frag strings queue; do
  every=61; [[ $f == hello ]] && every=1
  out=$($C compare examples/$f.cairn --heap 40000 --nursery 3000 --verify --verify-every $every)
  echo "$out" | tail -1 | grep -q "all collectors agree" || { echo "$out"; echo "FAIL: $f"; exit 1; }
  printf '   %-9s %s\n' "$f" "$(echo "$out" | head -1 | awk '{print $3, $4, $5, $6, $7, $8}')"
done

step "demo 2: torture mode (collect at every allocation) on a cyclic workload"
$C compare examples/cycles.cairn --heap 20000 --torture --verify | tail -1
$C run examples/hello.cairn --gc generational --torture --verify | head -1

step "demo 3: barriers on => safe, off => oracle catches corruption"
$C barrier-demo | grep -E "^==|oracle:" 

step "demo 4: bench on binary trees"
$C bench examples/bintrees.cairn --heap 400000 --nursery 20000 | tee "$T/bench.txt"
grep -q "outputs identical across 5" "$T/bench.txt"

step "demo 5: tight heap + big vectors — some collectors die of exhaustion/fragmentation, compaction survives"
$C bench examples/bigvecs.cairn --heap 12000 --nursery 1000 | tee "$T/frag.txt"
grep -q "^compact .*[0-9]%" "$T/frag.txt" && grep -q "FAILED" "$T/frag.txt"

step "demo 6: HTML report"
$C report examples/bintrees.cairn -o "$T/r.html" --heap 400000 --nursery 20000
[[ $(grep -o "<svg" "$T/r.html" | wc -l) -ge 11 ]] && echo "   report has $(wc -c < "$T/r.html") bytes, $(grep -o '<svg' "$T/r.html" | wc -l) charts"

step "demo 7: differential fuzz, 120 random programs x 5 collectors (+ 40 under torture)"
$C fuzz --iters 120 --seed 20261103 | tail -1
$C fuzz --iters 40 --seed 777 --torture | tail -1

step "demo 8: the fuzzer must catch a collector with its barrier removed"
if $C fuzz --iters 300 --seed 1 --gcs incremental --no-barrier >"$T/nb.txt" 2>&1; then echo "FAIL: not caught"; exit 1; fi
grep -o "seed [0-9]* FAILED[^:]*: HEAP CORRUPTION[^(]*" "$T/nb.txt" | head -1

printf '\nALL GREEN\n'
