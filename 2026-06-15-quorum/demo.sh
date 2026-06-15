#!/usr/bin/env bash
# Quorum demo: exercises every feature end-to-end. No dependencies beyond
# Python 3 standard library.
set -euo pipefail
cd "$(dirname "$0")"

line() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$1"; }

line "1. Feature tour (election, partition survival, chaos, determinism)"
python3 -m quorum.cli demo

line "2. Healthy cluster: elect a leader and replicate writes"
python3 -m quorum.cli run --nodes 5 --seed 5 --writes 6

line "3. Scripted Raft hard cases"
for s in split_brain leader_crash rolling_restart flapping_partition; do
  python3 -m quorum.cli scenario "$s" | tail -1
done

line "4. Randomized chaos torture test (20 seeds: crashes, partitions, loss, dup)"
python3 -m quorum.cli chaos --runs 20 --ticks 1000

line "5. Full verification suite"
python3 -m unittest discover -s tests

line "Done. To watch a cluster live, run:  python3 -m quorum.cli dashboard"
