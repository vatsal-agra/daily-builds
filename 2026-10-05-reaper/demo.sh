#!/usr/bin/env bash
# Exercises every Reaper feature end to end. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "build"
mkdir -p build
make -j8 reaper build/test >/dev/null
echo "built ./reaper and build/test"

step "feature 1+2+3: unit/integration suite (object model, verifier, 5 collectors, generational barrier, script language)"
./build/test | tail -3

step "feature 2+3: one workload on every collector, with the heap verifier running every 500 steps"
for gc in marksweep markcompact copying generational incremental; do
  ./reaper run "$gc" lru-cache --steps 20000 --verify-every 500 | sed -n '1p;2p;$p'
done

step "feature 4: differential fuzz vs. the never-collecting oracle (5 collectors x 6 workloads x 3 seeds)"
./reaper fuzz --gc all --workload all --seeds 3 --steps 8000 --heap 65536 | tail -8

step "feature 4b: the fuzzer fuzzes itself — 16 planted GC bugs must all be caught"
python3 tests/mutate.py | tail -3

step "feature 5: incremental collector — pause-time story on the barrier-torture workload"
./reaper run incremental pointer-shuffle --param 8 | sed -n '2,3p'
./reaper run marksweep pointer-shuffle | sed -n '2,3p'

step "feature 6: benchmark harness (all workloads x all collectors) -> build/bench.csv"
./reaper bench --scale 0.3 --csv build/bench.csv > build/bench.txt
head -24 build/bench.txt
echo "csv rows: $(($(wc -l < build/bench.csv) - 1))"

step "feature 7: mutator scripts on every collector (same program, same final graph hash)"
for f in list cycles barrier; do
  for gc in marksweep markcompact copying generational incremental; do
    ./reaper script examples/$f.rpr --gc "$gc" --heap 8192 >/dev/null
  done
  echo "examples/$f.rpr: ok on all 5 collectors"
done
hashes=$(for gc in marksweep markcompact copying generational incremental; do ./reaper script examples/barrier.rpr --gc $gc | grep 'graph hash'; done | sort -u | wc -l)
[ "$hashes" = "1" ] && echo "barrier.rpr: identical graph hash across collectors"
if ./reaper script examples/bad.rpr 2>build/bad.err; then echo "bad.rpr should have failed"; exit 1; fi
echo "bad script rejected cleanly: $(cat build/bad.err)"

step "feature 8: heap-map visualiser -> build/heapmap.html"
./reaper viz build/heapmap.html --workload fragmenter --steps 20000

step "error handling"
for bad in "run nope lru-cache" "run copying nope" "run copying lru-cache --stpes 3" "fuzz --seeds 0" "run copying lru-cache --heap 10" "script missing.rpr" "frobnicate"; do
  if ./reaper $bad >/dev/null 2>build/err.txt; then echo "expected failure: $bad"; exit 1; fi
  printf '  %-34s -> %s\n' "reaper $bad" "$(head -1 build/err.txt)"
done

printf '\n\033[1;32mdemo complete: every feature exercised, all checks green\033[0m\n'
