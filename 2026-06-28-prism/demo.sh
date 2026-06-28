#!/usr/bin/env bash
# Prism — full feature verification script
# Runs every CLI subcommand and checks outputs exist.
set -e

PRISM="python prism.py"
OUT="output"
PASS=0; FAIL=0

check() {
    local desc="$1"; shift
    if [ -f "$1" ]; then
        echo "  [PASS] $desc → $1"
        PASS=$((PASS+1))
    else
        echo "  [FAIL] $desc — expected file: $1"
        FAIL=$((FAIL+1))
    fi
}

cd "$(dirname "$0")"

echo "=== Prism Feature Verification ==="
echo

# --- info ---
echo "[1] info subcommand"
$PRISM info
echo

# --- render (all scenes) ---
echo "[2] render — all scenes"
$PRISM --width 160 --height 160 render torus
check "torus render"              $OUT/torus.png

$PRISM --width 160 --height 160 render sphere
check "sphere render"             $OUT/sphere.png

$PRISM --width 160 --height 160 render cornell
check "cornell render"            $OUT/cornell.png

$PRISM --width 160 --height 160 render shadow_demo
check "shadow_demo render"        $OUT/shadow_demo.png

$PRISM --width 160 --height 160 render showcase
check "showcase render"           $OUT/showcase.png
echo

# --- shadow rendering ---
echo "[3] shadow mapping"
$PRISM --width 160 --height 160 render shadow_demo --shadow
check "shadow_demo with shadows"  $OUT/shadow_demo_shadow.png
echo

# --- normal visualization ---
echo "[4] normal visualization mode"
$PRISM --width 160 --height 160 render sphere --mode normals
check "sphere normals mode"       $OUT/sphere_normals.png
echo

# --- animate ---
echo "[5] animate — torus (8 frames)"
$PRISM --width 128 --height 128 animate torus --frames 8 --fps 15
check "torus animation HTML"      $OUT/torus_anim.html
echo

# --- shadows comparison ---
echo "[6] shadows subcommand"
$PRISM --width 128 --height 128 shadows
check "shadow compare HTML"       $OUT/shadow_compare.html
check "shadow off PNG"            $OUT/shadow_off.png
check "shadow on PNG"             $OUT/shadow_on.png
echo

# --- compare ---
echo "[7] compare (5 panels)"
$PRISM --width 128 --height 128 compare torus
check "torus compare HTML"        $OUT/torus_compare.html
echo

# --- MSAA ---
echo "[8] MSAA 2x render"
$PRISM --width 128 --height 128 --msaa 2 render torus
check "torus MSAA"                $OUT/torus.png
echo

# --- unit tests ---
echo "[9] Unit test suite"
python -m unittest tests.test_prism -v 2>&1 | tail -4
echo

# --- summary ---
echo "==================================="
echo "PASS: $PASS   FAIL: $FAIL"
if [ "$FAIL" -gt 0 ]; then
    echo "Some checks failed."
    exit 1
else
    echo "All checks passed."
fi
