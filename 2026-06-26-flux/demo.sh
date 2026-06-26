#!/usr/bin/env bash
# demo.sh — render all built-in scenes to demo_output/ and run the test suite
set -e
cd "$(dirname "$0")"

echo "=== Flux Demo ==="
echo ""

echo "--- Running test suite ---"
python3 tests.py
echo ""

echo "--- Rendering all scenes (N=64, 30 frames each) ---"
python3 cli.py demo --N 64 --frames 30 --mode composite --output demo_output
echo ""

echo "--- Rendering example_scene.json (channel flow, 40 frames) ---"
python3 cli.py anim --scene example_scene.json --N 64 --frames 40 \
    --mode composite --output demo_output/channel_flow.html
echo ""

echo "--- Info for each built-in scene ---"
for scene in smoke ink wind vortex fire; do
    python3 cli.py info --scene "$scene" --N 64
    echo ""
done

echo "=== Done! Open demo_output/index.html in a browser. ==="
