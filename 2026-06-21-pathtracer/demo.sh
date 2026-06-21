#!/usr/bin/env bash
# demo.sh — exercise all CLI subcommands of the pathtracer
set -e
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
PT="$PYTHON -m pathtracer"

echo "=== Pathtracer demo ==="
echo

# 1. info — print scene metadata
echo "--- [1/5] info: scene metadata ---"
$PT info scenes/spheres_classic.json
$PT info scenes/cornell_box.json
$PT info scenes/dof_demo.json
echo

# 2. render — classic scene at small size
echo "--- [2/5] render: spheres_classic at 160×90 @ 16 SPP ---"
$PT render scenes/spheres_classic.json \
    --width 160 --height 90 --spp 16 \
    --output /tmp/demo_classic.png
echo "  Output: /tmp/demo_classic.png"
echo

# 3. render — Cornell box (tests color bleeding + area light)
echo "--- [3/5] render: cornell_box at 120×120 @ 32 SPP ---"
$PT render scenes/cornell_box.json \
    --width 120 --height 120 --spp 32 \
    --output /tmp/demo_cornell.png
echo "  Output: /tmp/demo_cornell.png"
echo

# 4. bench — BVH vs brute-force benchmark
echo "--- [4/5] bench: BVH vs brute-force (100 spheres) ---"
$PT bench --count 100
echo

# 5. demo — all three built-in scenes at minimum size
echo "--- [5/5] demo: all built-in scenes ---"
$PT demo --width 100 --height 75 --spp 8 --outdir /tmp/demo_renders/
echo

echo "=== All subcommands passed ==="
