#!/usr/bin/env bash
# Tumble end-to-end demo: exercises the CLI, renders an SVG gallery, runs the
# JS<->Python parity check, and runs the full test suite.
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo " TUMBLE — demo"
echo "============================================================"

echo; echo "## preset scenes"
python3 -m tumble scenes

echo; echo "## headless sim (cloth, 300 steps)"
python3 -m tumble sim --scene cloth --steps 300 -v

echo; echo "## physics invariants across all scenes"
python3 -m tumble check

echo; echo "## rendering SVG gallery -> gallery/"
mkdir -p gallery
python3 -m tumble render --scene rope      --steps 120 --out gallery/rope.svg
python3 -m tumble render --scene cloth     --steps 140 --out gallery/cloth.svg
python3 -m tumble render --scene curtain   --steps 200 --out gallery/curtain.svg
python3 -m tumble render --scene ballpit   --steps 220 --out gallery/ballpit.svg
python3 -m tumble render --scene blobs     --steps 160 --out gallery/blobs.svg
python3 -m tumble render --scene obstacles --steps 220 --out gallery/obstacles.svg
ls -1 gallery/

echo; echo "## JS <-> Python parity (Node), ballpit, 300 steps"
if command -v node >/dev/null 2>&1; then
  python3 - <<'PY'
import json, subprocess
from tumble import scenes
w = scenes.build("ballpit")
payload = json.dumps(w.to_dict())
r = subprocess.run(["node", "web/node_parity.js", "stepjson", "300"],
                   input=payload, capture_output=True, text=True)
pos = json.loads(r.stdout)["positions"]
for _ in range(300):
    w.step()
worst = max(max(abs(x-p.x), abs(y-p.y)) for (x,y,_,_), p in zip(pos, w.particles))
print("max |JS - Python| after 300 steps: %.3e  (expect 0.0 / bit-identical)" % worst)
PY
else
  echo "node not found — skipping parity demo"
fi

echo; echo "## test suite"
python3 -m unittest discover -s tests

echo; echo "Demo complete. Open web/index.html in a browser for the playground."
