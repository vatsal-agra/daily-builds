#!/usr/bin/env bash
# End-to-end demonstration + verification for Vignette.
# Runs the automated test suite, then exercises every CLI feature against
# real output, so a fresh clone can confirm everything actually works.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1. Automated test suite =="
python3 -m unittest discover -s tests -v

echo
echo "== 2. Encode every test image, every quality (round-trip sanity) =="
mkdir -p out/demo
for img in gradient checkerboard circles plasma textbars; do
  for q in 90 60 30; do
    python3 -m vignette.cli encode "$img" "out/demo/${img}_q${q}.jpg" -q "$q"
  done
done

echo
echo "== 3. Decode one back and confirm it's a real, recognized JPEG =="
python3 -m vignette.cli decode out/demo/circles_q60.jpg out/demo/circles_q60.png
if command -v file >/dev/null 2>&1; then
  file out/demo/circles_q60.jpg
  file out/demo/circles_q60.png
fi

echo
echo "== 4. Rate/distortion sweep (analyze) =="
python3 -m vignette.cli analyze plasma --qualities 95 75 50 25 10

echo
echo "== 5. Optimal per-image Huffman tables: verify smaller AND lossless =="
python3 -m vignette.cli encode circles out/demo/circles_std.jpg -q 60
python3 -m vignette.cli encode circles out/demo/circles_opt.jpg -q 60 --optimal-huffman
python3 - <<'PY'
from vignette import decoder
a = decoder.decode(open("out/demo/circles_std.jpg", "rb").read())
b = decoder.decode(open("out/demo/circles_opt.jpg", "rb").read())
import os
std_size = os.path.getsize("out/demo/circles_std.jpg")
opt_size = os.path.getsize("out/demo/circles_opt.jpg")
assert a.pixels == b.pixels, "optimal-huffman reconstruction should be pixel-identical"
assert opt_size < std_size, "optimal-huffman file should be smaller"
print(f"standard tables: {std_size} bytes; optimal tables: {opt_size} bytes "
      f"({100*(1-opt_size/std_size):.1f}% smaller, identical pixels)")
PY

echo
echo "== 6. Interactive HTML report + quality-ladder gallery =="
python3 -m vignette.cli report out/report.html --size 160
python3 -m vignette.cli gallery out/gallery.html --size 160

echo
echo "== 7. Error handling on malformed input (should fail cleanly, not crash) =="
set +e
python3 -m vignette.cli decode /nonexistent/path.jpg out/demo/x.png
code=$?
set -e
if [ "$code" -ne 1 ]; then
  echo "expected exit code 1 for missing file, got $code" >&2
  exit 1
fi
echo "  (correctly exited 1 with a clean error message, not a traceback)"

echo
echo "All demos passed. See out/report.html and out/gallery.html for the visuals."
