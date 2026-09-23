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
echo "=== 3/4 flagship demo (real 5-node cluster, all features) ==="
python3 -m gossamer.demo

echo
echo "=== 4/4 live dashboard smoke test (real cluster, headless Chromium) ==="
if python3 -c "import playwright" >/dev/null 2>&1; then
    rm -f .gossamer-cluster.json
    python3 -m gossamer.cli cluster start --nodes A,B,C,D,E --base-port 9995
    sleep 0.5
    python3 - <<'PYEOF'
from gossamer import client

class Stub:
    def __init__(self, peers): self.peers = peers
    def address_of(self, n): return tuple(self.peers[n])

peers = {n: ("127.0.0.1", 9995 + i) for i, n in enumerate(["A", "B", "C", "D", "E"])}
c = Stub(peers)
client.put(c, "A", "k1", "v1", context=None)
client.put(c, "C", "cart", ["milk"], context=None)
client.put(c, "D", "cart", ["eggs"], context=None)
client.get(c, "B", "cart")
PYEOF
    python3 tests/browser_smoke.py http://127.0.0.1:9995/dashboard
    python3 -m gossamer.cli cluster stop
else
    echo "playwright not installed in this environment -- skipping browser smoke test"
    echo "(the dashboard's own server-side route and data are still covered by the unit suite)"
fi

echo
echo "ALL GREEN"
