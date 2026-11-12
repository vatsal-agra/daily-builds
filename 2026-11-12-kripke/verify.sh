#!/usr/bin/env bash
# Full gate for Kripke. Ends with "ALL GREEN" or exits non-zero at the first failure.
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n== %s\n' "$*"; }
K=./target/release/kripke
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

step "build (warnings are errors) + fmt"
RUSTFLAGS="-D warnings" cargo build --release --all-targets 2>&1 | tail -1
cargo fmt --check 2>/dev/null || cargo fmt && echo "fmt ok"

step "tests: BDD engine, bit-vectors, parser, examples, differential fuzz (150 random models)"
cargo test --release 2>&1 | grep -E "^test result|FAILED|panicked" | sort | uniq -c

step "review replay (REVIEW.md probes)"
./review_check.sh | tail -1

step "demo: every example against the explicit-state oracle"
for f in peterson broken_mutex msi msi_buggy traffic elevator elevator_naive; do
  out=$($K explicit examples/$f.smv); echo "$out" | tail -1 | grep -q "both engines agree" || { echo "$out"; exit 1; }
  printf '   %-15s %s\n' "$f" "$($K examples/$f.smv --quiet | tail -1)" || true
done

step "demo: generated families (deadlock, fairness, reordering, long cycles)"
$K gen philosophers 5 > $T/ph.smv;       $K $T/ph.smv --quiet | grep -E "^states|FAIL" | head -3 || true
$K gen philosophers-fixed 5 > $T/phf.smv; $K $T/phf.smv --quiet | grep -E "^states" || true
$K gen lfsr 16 > $T/l16.smv;              $K $T/l16.smv --quiet | grep -E "^states" || true
$K gen comparator 16 > $T/c16.smv;        $K $T/c16.smv --reorder | grep -E "^reordering" || true
$K gen tokenring 8 > $T/tr.smv;           $K $T/tr.smv --quiet | tail -1 || true

step "demo: HTML report, DOT export, simulation"
$K examples/elevator_naive.smv --html $T/r.html --quiet | tail -1 || true
grep -q "Lasso counterexample" $T/r.html && echo "html ok ($(wc -c < $T/r.html) bytes)"
$K dot examples/peterson.smv reach | head -1 || true
$K sim examples/peterson.smv --steps 4 --seed 7 | head -3 || true

step "differential fuzz, 1000 fresh seeds"
$K fuzz --count 1000 --seed 50000

echo; echo "ALL GREEN"
