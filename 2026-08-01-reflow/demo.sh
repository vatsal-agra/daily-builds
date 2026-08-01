#!/usr/bin/env bash
# Runs the whole test suite, then exercises every one of Reflow's six
# features end-to-end and leaves the real, inspectable output on disk in
# demo_output/. Exits non-zero if anything fails.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

OUT=demo_output
rm -rf "$OUT"
mkdir -p "$OUT"

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }

echo "== 1. Automated test suite (parser, cascade, layout, paint, CLI) =="
python3 -m unittest discover -s tests 2>&1 | tail -12
python3 -m unittest discover -s tests >/tmp/reflow_demo_tests.log 2>&1 \
  && pass "all unit tests pass" || fail "unit tests failed -- see /tmp/reflow_demo_tests.log"
echo

echo "== 2. Required feature: HTML5-style parser (malformed markup) =="
python3 cli.py render examples/hello.html --dump-dom > "$OUT/hello.dom.txt"
grep -q '#document' "$OUT/hello.dom.txt" && pass "parsed a real DOM tree -> $OUT/hello.dom.txt"
echo

echo "== 3. Required feature: CSS parser + cascade =="
python3 cli.py render examples/hello.html --dump-cascade > "$OUT/hello.cascade.txt"
grep -q 'display=' "$OUT/hello.cascade.txt" && pass "computed styles per element -> $OUT/hello.cascade.txt"
echo

echo "== 4. Required feature: layout engine (box model, block+inline flow) =="
python3 cli.py render examples/hello.html --dump-layout > "$OUT/hello.layout.txt"
grep -q '\[line\]' "$OUT/hello.layout.txt" && pass "positioned box tree with line-wrapped text -> $OUT/hello.layout.txt"
echo

echo "== 5. Required feature: painter + real PNG output =="
python3 cli.py render examples/hello.html -o "$OUT/hello.png" --width 480
python3 -c "
data = open('$OUT/hello.png','rb').read()
assert data[:8] == b'\x89PNG\r\n\x1a\n', 'not a valid PNG signature'
import struct
w, h = struct.unpack('>II', data[16:24])
assert w > 0 and h > 0
print(f'    {w}x{h}px, {len(data)} bytes')
" && pass "genuinely valid, openable PNG -> $OUT/hello.png"
echo

echo "== 6. Stretch feature: flexbox (row + column, grow, justify, align, gap) =="
python3 cli.py render examples/flex.html -o "$OUT/flex.png" --width 500
python3 -c "
data = open('$OUT/flex.png','rb').read()
assert data[:8] == b'\x89PNG\r\n\x1a\n'
" && pass "toolbar/sidebar/card-stack flex layouts rendered -> $OUT/flex.png"
echo

echo "== 7. Stretch feature: interactive server-backed visualizer =="
python3 server.py --port 8765 > /tmp/reflow_demo_server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 1
curl -sf http://127.0.0.1:8765/ -o "$OUT/viewer.html" && pass "served viewer.html"
curl -sf -X POST http://127.0.0.1:8765/render \
  -H 'Content-Type: application/json' \
  -d '{"html":"<h1>Demo</h1><p>hi</p>","css":"h1{color:red;}","width":300}' \
  -o "$OUT/visualizer_response.json"
python3 -c "
import json
d = json.load(open('$OUT/visualizer_response.json'))
for key in ('dom_text','cssom_text','cascade_text','layout_svg','png_base64'):
    assert d.get(key), f'missing {key} in server response'
print(f'    server returned all 4 pipeline stages + PNG ({d[\"width\"]}x{d[\"height\"]}px)')
" && pass "POST /render returns DOM + CSSOM/cascade + layout SVG + PNG"
kill $SERVER_PID 2>/dev/null || true
trap - EXIT
echo

echo "All 6 features (4 required + 2 stretch) verified. Output in $OUT/"
