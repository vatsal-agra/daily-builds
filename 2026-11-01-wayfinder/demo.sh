#!/usr/bin/env bash
# Exercises every Wayfinder feature end to end. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
go build -o "$OUT/wf" ./cmd/wayfinder
wf="$OUT/wf"
step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

step "1. Maps: every generator, ASCII format round-trip"
for k in random maze rooms caves open; do
  "$wf" gen -kind "$k" -w 40 -h 16 -seed 7 -terrain 0 -o "$OUT/$k.txt"
  printf '%-7s %s walls\n' "$k" "$(tr -cd '#' < "$OUT/$k.txt" | wc -c)"
done
"$wf" gen -kind caves -w 70 -h 40 -seed 5 -terrain 0.25 -o "$OUT/terrain.txt"
"$wf" gen -kind rooms -w 60 -h 22 -seed 11 -o "$OUT/rooms.txt"
cat "$OUT/rooms.txt"

step "2. Optimal planners (Dijkstra, A*, JPS) agree on cost; JPS expands far fewer nodes"
"$wf" compare -map "$OUT/rooms.txt" 2>&1
"$wf" solve -map "$OUT/rooms.txt" -algo jps -draw

step "2b. Weighted terrain: A* routes around mud/swamp, JPS refuses (needs uniform cost)"
"$wf" solve -map "$OUT/terrain.txt" -algo astar
if "$wf" solve -map "$OUT/terrain.txt" -algo jps 2>/dev/null; then echo "jps should have refused"; exit 1; else echo "jps correctly refused mixed terrain"; fi

step "3. Theta* any-angle (cost < grid optimum) and HPA* (hierarchical, near-optimal)"
"$wf" solve -map "$OUT/rooms.txt" -algo theta -draw
"$wf" solve -map "$OUT/rooms.txt" -algo hpa

step "4. D* Lite: agent explores an unknown maze (every replan cross-checked vs A*)"
"$wf" gen -kind maze -w 81 -h 41 -seed 3 -o "$OUT/maze.txt"
"$wf" explore -map "$OUT/maze.txt" -radius 2 -draw | tail -n 46

step "5. Unreachable goal handled cleanly"
printf 'S.#..\n..#.G\n' | "$wf" solve -map - -algo astar || test $? -eq 3
printf 'S.#..\n..#.G\n' | "$wf" explore -map - -radius 2

step "6. HTML replay viewer"
"$wf" html -map "$OUT/rooms.txt" -o "$OUT/replay.html" -radius 3 2>/dev/null
test -s "$OUT/replay.html" && echo "replay.html: $(wc -c < "$OUT/replay.html") bytes"
mkdir -p examples && cp "$OUT/replay.html" examples/rooms-replay.html

step "7. Fuzz cross-validation (all planners + D* Lite self-check)"
"$wf" fuzz -n 400 -seed 20000

step "8. Benchmark"
"$wf" bench -size 100 -seeds 3

step "9. Go test suite"
go test ./... 2>&1

printf '\n\033[1;32mdemo OK — all features exercised\033[0m\n'
