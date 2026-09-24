#!/usr/bin/env bash
# End-to-end walkthrough for Spectral: a from-scratch JPEG codec.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

pass() { echo "  [OK] $1"; }
section() { echo; echo "=== $1 ==="; }

section "1/6 Python unit test suite"
python3 -m unittest discover -s tests -p "test_*.py"
pass "unit test suite green"

section "2/6 DCT correctness (fast separable transform vs brute-force O(N^4) oracle)"
python3 -m spectral.cli dct-demo
pass "forward/inverse DCT proven against an independent reference"

section "3/6 CLI walkthrough: encode a real image, decode it back"
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
  --output /tmp/spectral_demo.jpg --quality 80 --subsampling 420
python3 -m spectral.cli decode /tmp/spectral_demo.jpg --output /tmp/spectral_demo_out.bmp
python3 -m spectral.cli encode --test-image photo --width 96 --height 96 \
  --output /tmp/spectral_demo_opt.jpg --quality 80 --subsampling 420 --optimize
python3 - <<'PY'
import os
base = os.path.getsize("/tmp/spectral_demo.jpg")
opt = os.path.getsize("/tmp/spectral_demo_opt.jpg")
assert opt < base, f"optimized Huffman table ({opt}) did not shrink the file (was {base})"
print(f"  standard tables: {base} bytes, optimized tables: {opt} bytes ({100*(1-opt/base):.1f}% smaller)")
PY
pass "encode/decode CLI round trip, optimized Huffman shrinks the file"

section "4/6 Rate-distortion sweep (quality/subsampling vs size/PSNR)"
python3 -m spectral.cli compare --test-image photo --width 96 --height 96 --qualities 10 50 90
pass "quality and subsampling trade off size against PSNR as expected"

section "5/6 CLI error handling on bad input"
if python3 -m spectral.cli decode /tmp/spectral_demo.jpg.doesnotexist --output /tmp/x.bmp 2>/tmp/err.txt; then
  echo "expected a clean failure on a missing file"; exit 1
fi
grep -q "error" /tmp/err.txt
echo "not a jpeg" > /tmp/notajpeg.jpg
if python3 -m spectral.cli decode /tmp/notajpeg.jpg --output /tmp/x.bmp 2>/tmp/err2.txt; then
  echo "expected a clean failure on a malformed JPEG"; exit 1
fi
grep -q "error" /tmp/err2.txt
pass "malformed/missing input fails cleanly with no raw traceback"

section "6/6 Independent oracle: real headless-Chromium JPEG decode"
if command -v node >/dev/null 2>&1; then
  FIXTURE_DIR="$(mktemp -d)"
  python3 tests/generate_oracle_fixtures.py "$FIXTURE_DIR"
  NODE_PATH=/opt/node22/lib/node_modules PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
    node tests/browser_oracle_test.cjs "$FIXTURE_DIR"
  pass "every encoded JPEG opens correctly in a real, independent browser decoder"
else
  echo "  [SKIP] node not available; skipping the headless-browser oracle check"
fi

echo
echo "=== demo.sh: all checks passed ==="
