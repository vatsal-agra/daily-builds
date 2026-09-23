#!/usr/bin/env bash
# Runs the full Gossamer test suite plus the flagship multi-process demo.
set -euo pipefail
cd "$(dirname "$0")"

echo "=== 1/3 unit + integration test suite ==="
python3 -m unittest discover -s tests -v

echo
echo "=== 2/3 CLI smoke test (separate process per command, real cluster) ==="
rm -f .gossamer-cluster.json
python3 -m gossamer.cli cluster start --nodes A,B,C --base-port 9950
sleep 0.5
python3 -m gossamer.cli put demo-key '"demo-value"' >/tmp/gossamer-cli-put.json
python3 -m gossamer.cli get demo-key >/tmp/gossamer-cli-get.json
grep -q "demo-value" /tmp/gossamer-cli-get.json
python3 -m gossamer.cli status
python3 -m gossamer.cli cluster stop
echo "CLI smoke test OK"

echo
echo "=== 3/3 flagship demo (real 5-node cluster, all features) ==="
python3 -m gossamer.demo

echo
echo "ALL GREEN"
