#!/bin/bash
# Full verification gate for Quire. Exits non-zero on the first failing stage.
#   ./verify.sh            everything
#   ./verify.sh --quick    skip fuzzing and the headless-browser check
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$PWD"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
pass=0; fail=0
stage() { printf '\n== %s\n' "$1"; }
ok()    { printf '   ok   %s\n' "$1"; pass=$((pass+1)); }
bad()   { printf '   FAIL %s\n' "$1"; fail=$((fail+1)); }
run()   { local name="$1"; shift; if "$@" >/tmp/quire-verify.out 2>&1; then ok "$name"; else bad "$name"; tail -25 /tmp/quire-verify.out; fi; }

stage "1. unit + integration tests (parser, filters, crypto, text, render, gallery, CLI, report)"
run "python -m unittest discover tests" python3 -W ignore -m unittest discover tests

stage "2. feature demo through the CLI (every command, every required feature)"
T=$(mktemp -d)
run "info: plain"                 bash -c "./quire.sh info tests/fixtures/chrome.pdf | grep -q 'Pages:       2'"
run "info: encrypted w/o password refuses" bash -c "! ./quire.sh info tests/fixtures/enc_aes256.pdf 2>/dev/null"
run "info: AES-256 with password" bash -c "./quire.sh info tests/fixtures/enc_aes256.pdf -p userpw | grep -q 'AES-256'"
run "info: RC4-40 owner password" bash -c "./quire.sh info tests/fixtures/enc_rc4_40.pdf -p ownerpw | grep -q 'opened as owner'"
run "repair: truncated file is rebuilt" bash -c "head -c 46000 tests/fixtures/chrome.pdf > $T/trunc.pdf; ./quire.sh info $T/trunc.pdf | grep -q 'Repaired:    yes'"
run "text: reading order (2 columns)" bash -c "./quire.sh text tests/fixtures/chrome.pdf | tr '\n' ' ' | grep -q 'consectetur adipiscing .* fugiat nulla'"
run "text: encrypted"             bash -c "./quire.sh text tests/fixtures/enc_rc4_128.pdf -p userpw | grep -q 'quick brown fox'"
run "search: finds with bbox"     bash -c "./quire.sh search tests/fixtures/chrome.pdf 'lazy dog' | grep -q 'page 1'"
run "render: PNG + highlight"     bash -c "./quire.sh render tests/fixtures/chrome.pdf -o $T/p.png --dpi 80 --highlight 'lazy dog' >/dev/null && [ \$(head -c 4 $T/p.png | tail -c 3) = PNG ]"
run "decrypt -> plain copy opens in poppler" bash -c "./quire.sh decrypt tests/fixtures/enc_aes128.pdf $T/dec.pdf -p userpw >/dev/null && pdftotext $T/dec.pdf - | grep -q 'quick brown fox'"
run "decrypt --compress (objstm+xref stream) opens in poppler" bash -c "./quire.sh decrypt tests/fixtures/chrome.pdf $T/c.pdf --compress >/dev/null && pdftotext $T/c.pdf - | grep -q 'quick brown fox'"
run "report: HTML written"        bash -c "./quire.sh report tests/fixtures/chrome.pdf -o $T/r.html >/dev/null && grep -q 'Quire' $T/r.html"

stage "3. pixel comparison against poppler (pdftoppm) on real-world PDFs"
for f in chrome libreoffice libreoffice_cff chrome_cff; do
  run "render $f.pdf p1 @100dpi" python3 - <<PY
import sys; sys.path.insert(0,'.')
from quire import Document
from quire.render import render_page
from quire.compare import diff_stats, load
from quire.raster import read_png_rgb
import subprocess, tempfile, os
d = Document('tests/fixtures/$f.pdf'); cv = render_page(d, d.pages()[0], 100)
t = tempfile.mkdtemp(); subprocess.check_call(['pdftoppm','-cropbox','-r','100','-png','-singlefile','tests/fixtures/$f.pdf',t+'/r'], stderr=subprocess.DEVNULL)
s = diff_stats(read_png_rgb(cv.to_png()), load(t+'/r.png')); print(s)
sys.exit(0 if s['bad_frac'] < 0.012 else 1)
PY
done

if [ $QUICK -eq 0 ]; then
  stage "4. mutation fuzzing (never crash, never hang)"
  for s in 1 2 3; do run "fuzz seed $s (60 mutants)" python3 tools/fuzz.py 60 $s; done
  stage "5. HTML inspector in headless Chromium"
  if command -v node >/dev/null && NODE_PATH=$(npm root -g 2>/dev/null) node -e "require('playwright')" 2>/dev/null; then
    ./quire.sh report tests/fixtures/chrome.pdf -o $T/r2.html >/dev/null
    run "inspector loads, tabs/search/objects work, no overflow @1280 and @390" env NODE_PATH=$(npm root -g) node tools/check_report.js $T/r2.html
  else
    printf '   skip (node + playwright not available)\n'
  fi
fi

printf '\n== %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ] && echo "ALL GREEN" || { echo "FAILURES"; exit 1; }
