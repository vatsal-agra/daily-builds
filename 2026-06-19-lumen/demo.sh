#!/usr/bin/env bash
# Lumen quick demo — renders all three scenes at low-res + opens gallery
set -e
cd "$(dirname "$0")"

echo "=== Lumen Path Tracer Demo ==="
echo "Rendering Cornell box, metallic spheres, and glass caustics..."
echo "(96×96 / 128×72 @ 8 spp — expect ~60s on a 4-core machine)"
echo ""

python3 lumen.py demo

echo ""
echo "Done! Open gallery.html in your browser:"
if command -v xdg-open &>/dev/null; then
    xdg-open gallery.html
elif command -v open &>/dev/null; then
    open gallery.html
else
    echo "  file://$(pwd)/gallery.html"
fi
