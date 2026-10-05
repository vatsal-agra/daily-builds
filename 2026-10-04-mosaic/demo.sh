#!/usr/bin/env bash
# Exercises every Mosaic feature end to end and fails loudly if anything is off.
set -euo pipefail
cd "$(dirname "$0")"
OUT=${1:-gallery}
mkdir -p "$OUT"

echo "== build + unit/integration tests"
cargo build --release --quiet
cargo test --release --quiet 2>&1 | grep -E "test result" | sed 's/^/   /'
M=target/release/mosaic

run() { # name args...   -> runs, requires "verify: OK"
  local name=$1; shift
  echo "== $name"
  "$M" "$@" | tee /dev/stderr | grep -q "verify: OK" || { echo "FAILED: $name"; exit 1; }
}

echo "== list"; $M list | sed 's/^/   /'

# Feature 2: overlapping model — every built-in sample
for s in flowers dungeon maze wires; do
  run "overlap/$s" overlap --sample $s --size 48x32 --seed 3 --out "$OUT/overlap-$s.png" 2>&1
done
run "overlap/waves (wrap in + out)" overlap --sample waves --wrap-in --wrap-out --size 48x48 --n 3 --out "$OUT/overlap-waves.png" 2>&1
run "overlap/city (ground)" overlap --sample city --ground --size 96x28 --seed 4 --out "$OUT/overlap-city-ground.png" 2>&1
run "overlap/dungeon (8-fold symmetry)" overlap --sample dungeon --symmetry 8 --size 64x40 --seed 8 --out "$OUT/overlap-dungeon-sym8.png" 2>&1
run "overlap/PNG sample" overlap --sample tests/fixtures/mixed_filters_rgba.png --n 2 --wrap-in --symmetry 8 --size 24x24 --out "$OUT/overlap-from-png.png" 2>&1

# Feature 3: tiled model
run "tiled/circuit" tiled --set circuit --size 40x24 --seed 5 --out "$OUT/tiled-circuit.png" 2>&1
run "tiled/terrain" tiled --set terrain --size 40x26 --seed 6 --out "$OUT/tiled-terrain.png" --scale 2 2>&1

# Stretch: pins
run "pins/overlap" overlap --sample flowers --size 40x30 --pin 8,8,'*' --pin 30,20,o --seed 2 --out "$OUT/pins-flowers.png" 2>&1
run "pins/tiled (island in the middle)" tiled --set terrain --size 40x26 --pin 20,13,t2222 --pin 0,0,t0000 --seed 7 --out "$OUT/pins-terrain.png" --scale 2 2>&1

# Stretch: animation
run "animation (terrain)" tiled --set terrain --size 24x16 --seed 9 --anim "$OUT/anim-terrain.html" --anim-frames 80 --out "$OUT/anim-terrain-final.png" 2>&1
run "animation (backtracking wires)" overlap --sample wires --n 4 --wrap-in --wrap-out --size 36x36 --seed 2 --anim "$OUT/anim-wires-backtrack.html" --anim-frames 80 --out "$OUT/anim-wires.png" 2>&1

# Feature 4: backtracking + stretch: benchmark
echo "== bench: backtracking vs restart-only (constrained torus)"
$M bench overlap --sample wires --n 4 --wrap-in --wrap-out --size 50x50 --trials 12 --restarts 100 | tee "$OUT/bench-wires.txt"
echo "== bench: easy tiled case"
$M bench tiled --set circuit --size 40x30 --trials 10 | tee "$OUT/bench-circuit.txt"

# Error handling
echo "== error handling"
for bad in "overlap --sample nope" "tiled --set circuit --pin 0,0,ghost" "overlap --sample wires --size 0x4"; do
  if $M $bad >/dev/null 2>"$OUT/err.txt"; then echo "expected failure: $bad"; exit 1; fi
  echo "   '$bad' -> $(head -1 "$OUT/err.txt" | cut -c1-90)"
done
rm -f "$OUT/err.txt"
echo "ALL FEATURES OK — artifacts in $OUT/"
