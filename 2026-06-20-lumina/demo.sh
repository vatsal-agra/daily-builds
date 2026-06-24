#!/usr/bin/env bash
# demo.sh — quick smoke demo of Lumina (fast settings, all render modes)
set -e
cd "$(dirname "$0")"

echo "=============================="
echo " Lumina — Demo Render Script"
echo "=============================="
echo

mkdir -p demo_out

echo "▶  Path trace: showcase scene (64×36, 16 spp)"
python lumina.py render scenes/showcase.json \
    --width 64 --height 36 --samples 16 --mode path --tonemap aces \
    -o demo_out/showcase_demo.png

echo
echo "▶  Path trace: Cornell box (64×64, 32 spp)"
python lumina.py render scenes/cornell.json \
    --width 64 --height 64 --samples 32 --mode path --tonemap aces \
    -o demo_out/cornell_demo.png

echo
echo "▶  Path trace: depth of field (80×45, 16 spp)"
python lumina.py render scenes/dof.json \
    --width 80 --height 45 --samples 16 --mode path --tonemap aces \
    -o demo_out/dof_demo.png

echo
echo "▶  Whitted ray tracer: classic scene (80×60, 4 spp)"
python lumina.py render scenes/whitted_demo.json \
    --width 80 --height 60 --samples 4 --mode whitted --tonemap aces \
    -o demo_out/whitted_demo.png

echo
echo "▶  Mesh BVH: sphere mesh (60×60, 8 spp)"
python lumina.py render scenes/mesh.json \
    --width 60 --height 60 --samples 8 --mode path --tonemap aces \
    -o demo_out/mesh_demo.png

echo
echo "▶  BVH benchmark: mesh scene"
python lumina.py bench scenes/mesh.json

echo
echo "▶  Unit tests"
python tests/test_lumina.py

echo
echo "=============================="
echo " All outputs → demo_out/"
ls -lh demo_out/*.png
echo "=============================="
