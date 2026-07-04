#!/usr/bin/env bash
# Morphica — end-to-end demo
set -e
cd "$(dirname "$0")"

echo "══════════════════════════════════════════════════════════════"
echo "  Morphica — Generative Algorithmic Art Engine — Demo"
echo "══════════════════════════════════════════════════════════════"
echo

# ── L-system ──────────────────────────────────────────────────────────────────
echo "── L-Systems ─────────────────────────────────────────────────"

echo "[LS-1] Koch snowflake (SVG)"
python3 morphica.py lsystem koch --format svg -o output/ls_koch.svg
test -f output/ls_koch.svg && echo "  PASS: ls_koch.svg exists"

echo "[LS-2] Hilbert curve (PNG)"
python3 morphica.py lsystem hilbert --width 600 --height 600 \
        --color '#44ffaa' -o output/ls_hilbert.png
test -f output/ls_hilbert.png && echo "  PASS: ls_hilbert.png exists"

echo "[LS-3] Barnsley fern"
python3 morphica.py lsystem barnsley --seed 12 -o output/ls_barnsley.png
test -f output/ls_barnsley.png && echo "  PASS: ls_barnsley.png exists"

echo "[LS-4] Stochastic plant (seeded)"
python3 morphica.py lsystem stochastic_plant --seed 77 -o output/ls_stochastic.png
test -f output/ls_stochastic.png && echo "  PASS: ls_stochastic.png exists"

echo "[LS-5] Seed reproducibility check"
python3 morphica.py lsystem stochastic_plant --seed 77 -o output/ls_stoch_check.png
python3 -c "
import hashlib, sys
a = open('output/ls_stochastic.png','rb').read()
b = open('output/ls_stoch_check.png','rb').read()
assert a == b, 'FAIL: same seed produced different output!'
print('  PASS: identical output for same seed')
"

echo
# ── Reaction-diffusion ────────────────────────────────────────────────────────
echo "── Reaction-Diffusion ────────────────────────────────────────"

for PRESET in coral worms maze spots fingerprint; do
  echo "[RD] $PRESET"
  python3 morphica.py rd "$PRESET" --size 150 --steps 2000 --seed 42 \
          -o "output/rd_${PRESET}.png"
  test -f "output/rd_${PRESET}.png" && echo "  PASS: rd_${PRESET}.png exists"
done

echo
# ── Attractors ────────────────────────────────────────────────────────────────
echo "── Strange Attractors ────────────────────────────────────────"

for ATT in lorenz rossler clifford dejong pickover duffing; do
  echo "[ATT] $ATT"
  python3 morphica.py attractor "$ATT" --width 400 --height 400 \
          --seed 0 --palette viridis -o "output/att_${ATT}.png"
  test -f "output/att_${ATT}.png" && echo "  PASS: att_${ATT}.png exists"
done

echo
# ── Voronoi ───────────────────────────────────────────────────────────────────
echo "── Voronoi + Stippling ───────────────────────────────────────"

echo "[VOR-1] Voronoi SVG (50 points, 5 Lloyd iters)"
python3 morphica.py voronoi --points 50 --lloyd 5 --seed 1 \
        --format svg -o output/vor_50.svg
test -f output/vor_50.svg && echo "  PASS: vor_50.svg exists"

echo "[VOR-2] Voronoi PNG (80 points)"
python3 morphica.py voronoi --points 80 --format png --seed 9 \
        -o output/vor_80.png
test -f output/vor_80.png && echo "  PASS: vor_80.png exists"

echo "[VOR-3] Stipple art (200 dots)"
python3 morphica.py stipple --points 200 --lloyd 3 --seed 5 \
        -o output/stipple_200.png
test -f output/stipple_200.png && echo "  PASS: stipple_200.png exists"

echo
# ── Animation ─────────────────────────────────────────────────────────────────
echo "── Animation Frame Export ────────────────────────────────────"

echo "[ANIM-1] L-system dragon growth (6 frames)"
python3 morphica.py animate lsystem dragon --frames 6 --seed 0 \
        -o output/anim_dragon
NFRAMES=$(ls output/anim_dragon/frame_*.png 2>/dev/null | wc -l)
echo "  Frames written: $NFRAMES"
test "$NFRAMES" -eq 6 && echo "  PASS: 6 frames produced"

echo "[ANIM-2] Clifford attractor buildup (8 frames)"
python3 morphica.py animate attractor clifford --frames 8 --seed 42 \
        -o output/anim_clifford
NFRAMES=$(ls output/anim_clifford/frame_*.png 2>/dev/null | wc -l)
test "$NFRAMES" -eq 8 && echo "  PASS: 8 frames produced"

echo "[ANIM-3] RD worms time-lapse (5 frames)"
python3 morphica.py animate rd worms --frames 5 --seed 7 \
        -o output/anim_rd_worms
NFRAMES=$(ls output/anim_rd_worms/frame_*.png 2>/dev/null | wc -l)
test "$NFRAMES" -eq 5 && echo "  PASS: 5 frames produced"

echo
# ── Viewer HTML ───────────────────────────────────────────────────────────────
echo "── Interactive Viewer ────────────────────────────────────────"
python3 morphica.py viewer --seed 42 -o output/viewer.html
test -f output/viewer.html && echo "  PASS: viewer.html exists"
SIZE=$(wc -c < output/viewer.html)
echo "  Viewer size: ${SIZE} bytes"

echo
# ── Tests ─────────────────────────────────────────────────────────────────────
echo "── Test Suite ────────────────────────────────────────────────"
python3 tests/test_morphica.py 2>&1 | tail -3

echo
echo "══════════════════════════════════════════════════════════════"
echo "  All demo steps complete."
echo "  Output files are in: output/"
echo "  Open output/viewer.html in a browser to explore interactively."
echo "══════════════════════════════════════════════════════════════"
