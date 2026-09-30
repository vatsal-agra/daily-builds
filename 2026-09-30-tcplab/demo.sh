#!/usr/bin/env bash
# Runnable demo: exercises every feature end-to-end, then the test suite. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")"
cargo build --release -q
T=./target/release/tcplab
mkdir -p out
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

step "1+2. wire codec + state machine: handshake, data, graceful close (packet trace)"
$T handshake

step "2. SYN retries with exponential backoff, then timeout (black-holed path)"
$T run --scenario clean --bytes 1KB --loss 100% --max-time 120s | tail -2 || true

step "3. reliability: scripted loss → fast retransmit; tail loss → RTO"
$T run --bytes 200KB --drop 30 | grep -E "transfer|sender"
$T run --bytes 50KB --drop 50 | grep -E "transfer|sender"

step "3. reliability: chaos (5% loss, reorder, duplication, corruption, jitter), wraparound ISS"
$T run --scenario chaos --iss 4294967000 | grep -E "transfer|receiver|network"

step "4. congestion control: Tahoe / Reno / NewReno / CUBIC on a drop-tail bottleneck (+ HTML)"
$T compare --scenario bottleneck --html out/bottleneck.html

step "4. flow control: slow reader, zero-window probing with lossy ACK path"
$T run --scenario slowreader | grep -E "transfer|receiver"
$T run --bytes 30KB --rcv-buf 4KB --reader-rate 32kbit --ack-loss 60% --seed 7 | grep -E "transfer|sender"

step "5-8. CUBIC vs Reno on a long fat pipe (+ HTML report)"
$T compare --scenario satellite --html out/satellite.html

step "test suite (debug build → overflow checks on)"
cargo test 2>&1 | grep -E "^test result"
echo; echo "demo OK — open out/bottleneck.html and out/satellite.html"
