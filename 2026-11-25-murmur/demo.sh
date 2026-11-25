#!/usr/bin/env bash
# End-to-end verification: unit tests, every CLI command, browser UI check.
set -u
cd "$(dirname "$0")"
OUT=$(mktemp -d); pass=0; fail=0
ok()  { echo "  ✔ $1"; pass=$((pass+1)); }
bad() { echo "  ✘ $1"; fail=$((fail+1)); }
check() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }

echo "== unit + integration tests"
check "node --test (engine, tools, cli)" node --test test/engine.test.js test/tools.test.js test/cli.test.js

echo "== feature 1: engine / spatial hash"
check "bench: grid==brute, 0 kNN mismatches" bash -c "node murmur.js bench --n 1500 | grep -q 'kNN mismatches vs brute: 0'"
check "deterministic run (same hash twice)" bash -c "[ \"\$(node murmur.js run --n 90 --steps 80 --seed 5 | tail -1)\" = \"\$(node murmur.js run --n 90 --steps 80 --seed 5 | tail -1)\" ]"
echo "== feature 2: neighbourhood modes"
check "metric run" node murmur.js run --n 80 --steps 40 --mode metric
check "topological run" node murmur.js run --n 80 --steps 40 --mode topological --boundary wall
echo "== feature 3: instruments + sweeps"
check "noise sweep: ordered→disordered" bash -c "node murmur.js sweep --out $OUT --reps 2 --n 150 --noises 0,1.0 | awk '/^0 /{a=\$2} /^1 /{b=\$2} END{exit !(a>0.5 && b<0.2)}'"
check "sweep.svg + csv written" bash -c "test -s $OUT/sweep.svg && test -s $OUT/sweep.csv"
check "compare metric vs topological" node murmur.js compare --out $OUT --ns 60,120 --reps 2
echo "== feature 4: predators"
check "hunt catches prey" bash -c "node murmur.js hunt --n 150 | grep -Eq 'catches=[1-9]'"
echo "== stretch: tuner, replay, UI"
check "tuner runs and reports fitness (improvement asserted in unit test)" bash -c "node murmur.js tune --gens 3 --pop 6 --n 50 --out $OUT | grep -q 'best fitness'"
check "snapshot → replay hash matches direct run" bash -c "
  node murmur.js run --n 70 --steps 30 --seed 4 --predators 1 --snapshot $OUT/s.json >/dev/null
  want=\$(node murmur.js run --n 70 --steps 90 --seed 4 --predators 1 | tail -1 | awk '{print \$3}')
  node murmur.js replay --snapshot $OUT/s.json --steps 60 --expect \$want | grep -q 'hash matches'"
check "browser UI end-to-end" node test/ui.check.js
echo "== hostile input"
check "typo flag rejected" bash -c "! node murmur.js run --nosie 1"
check "corrupt snapshot rejected" bash -c "echo '{\"v\":1}' > $OUT/bad.json; ! node murmur.js replay --snapshot $OUT/bad.json"

echo; echo "passed $pass, failed $fail"; rm -rf "$OUT"
[ $fail -eq 0 ] && echo "ALL GREEN" || { echo "FAILURES"; exit 1; }
