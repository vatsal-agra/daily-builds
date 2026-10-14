#!/usr/bin/env bash
# End-to-end tour of Plinth through its CLI. Safe to run repeatedly; works in a temp dir.
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release -q
P=$PWD/target/release/plinth
export PLINTH_NOSYNC=1          # demo only: skip fsync so 300 KB writes don't take seconds
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
IMG=$T/demo.img
say() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

say "1. make a 4 MiB image, copy files in, build a small tree"
$P mkfs $IMG --size-mb 4 --inodes 256
$P mkdir $IMG /src; $P mkdir $IMG /src/lib; $P mkdir $IMG /var
head -c 200000 /dev/urandom > $T/blob.bin
printf 'fn main() { println!("hi"); }\n' > $T/main.rs
$P put $IMG $T/main.rs /src/main.rs
$P put $IMG $T/blob.bin /var/blob.bin
$P ln-s $IMG /var/blob.bin /src/lib/blob-link
$P ln $IMG /src/main.rs /src/main.rs.bak
$P tree $IMG
$P ls $IMG /src

say "2. round-trip is byte-exact; sparse truncate-extend reads zeros"
$P get $IMG /var/blob.bin $T/blob.out; cmp $T/blob.bin $T/blob.out && echo "blob.bin identical (200000 bytes)"
$P truncate $IMG /var/blob.bin 1000000
$P df $IMG | head -2
$P fsck $IMG

say "3. rename a directory, remove a file, check again"
$P mv $IMG /src/lib /var/lib; $P rm $IMG /src/main.rs; $P cat $IMG /src/main.rs.bak
$P fsck $IMG

say "4. what does the journal look like right now?"
$P journal $IMG

say "5. crash-consistency fuzzer: crash a 40-op workload at every device event"
$P crashtest --seed 7 --ops 40

say "6. prove the fuzzer has teeth: each broken journal must be caught"
for bug in $($P bugs); do
  printf '%-18s ' "$bug"; $P crashtest --seed 1 --ops 40 --bug $bug | grep -E 'FAILURE' | head -1 || echo SURVIVED
done

say "7. vandalise the image, then repair it"
$P corrupt $IMG 5 --seed 2
$P fsck $IMG || true
$P fsck $IMG --repair
$P fsck $IMG
$P ls $IMG /lost+found

say "8. differential fuzz against the in-memory model"
$P difftest --seed 3 --ops 1500

say "9. HTML block map"
$P map $IMG ${MAP_OUT:-$T/map.html}
echo "ok"
