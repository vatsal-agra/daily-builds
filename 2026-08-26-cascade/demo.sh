#!/usr/bin/env bash
# Cascade end-to-end demo/verification script — exercises every feature
# from PLAN.md and reports a clear pass/fail summary. Exits non-zero if
# anything fails.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0
OUT_DIR="$(mktemp -d)"

pass() { echo "  ✓ $1"; PASS=$((PASS+1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL+1)); }

section() { echo; echo "== $1 =="; }

# ---------------------------------------------------------------- 1. unit tests
section "1. Unit test suite (feature 1: HTML parser, 2: CSS cascade, 3: layout, 4: paint)"
if python3 -m unittest discover -s tests > "$OUT_DIR/unittest.log" 2>&1; then
    N=$(grep -oE "Ran [0-9]+ test" "$OUT_DIR/unittest.log" | grep -oE "[0-9]+")
    pass "unittest suite: $N tests, all green"
else
    fail "unittest suite (see $OUT_DIR/unittest.log)"
    tail -30 "$OUT_DIR/unittest.log"
fi

# ---------------------------------------------------------- 2. CLI render (1-4)
section "2. CLI render every test page (features 1-4 end-to-end)"
CLI_OK=1
for f in testpages/*.html; do
    name=$(basename "$f" .html)
    if python3 cli.py render "$f" -o "$OUT_DIR/$name.svg" > /dev/null 2>"$OUT_DIR/$name.err"; then
        if [ -s "$OUT_DIR/$name.svg" ] && head -c 4 "$OUT_DIR/$name.svg" | grep -q "<svg"; then
            :
        else
            fail "render $name: output not a valid SVG"; CLI_OK=0
        fi
    else
        fail "render $name (see $OUT_DIR/$name.err)"; CLI_OK=0
    fi
done
[ "$CLI_OK" = 1 ] && pass "rendered all $(ls testpages/*.html | wc -l | tr -d ' ') test pages to valid SVG via the CLI"

# ------------------------------------------------------- 3. Chromium oracle
section "3. Differential verification against real Chromium (feature 6)"
if python3 oracle/run_diff.py testpages > "$OUT_DIR/oracle.log" 2>&1; then
    pass "$(tail -1 "$OUT_DIR/oracle.log")"
else
    fail "oracle differential test — see $OUT_DIR/oracle.log"
    tail -40 "$OUT_DIR/oracle.log"
fi

# --------------------------------------------------------- 4. float layout
section "4. Float layout (feature 5): direct check that text narrows around a float"
python3 - "$OUT_DIR" <<'PYEOF'
import sys
sys.path.insert(0, ".")
from cascade.engine import render_html
from cascade.dom import Element

html = ('<div style="width:400px">'
        '<div style="width:100px;height:50px;float:left"></div>'
        '<p style="font-family:monospace">' + "x " * 60 + "</p></div>")
r = render_html(html, viewport_width=800)
p = next(b for b in r.box.walk() if isinstance(b.node, Element) and b.node.tag == "p")
anon = [c for c in p.children if c.box_type == "anon-inline"][0]
narrow_x = anon.lines[0].words[0].x
wide_x = anon.lines[-1].words[0].x
ok = narrow_x > wide_x  # first line (next to float) starts further right than a later line
print("PASS" if ok else "FAIL", f"first_line_x={narrow_x:.1f} later_line_x={wide_x:.1f}")
sys.exit(0 if ok else 1)
PYEOF
if [ $? -eq 0 ]; then pass "float narrows the line boxes of following text, later lines return to full width"; else fail "float line-narrowing check"; fi

# ------------------------------------------------------- 5. playground server
section "5. Interactive server-backed playground (feature 7)"
PORT=8531
python3 server.py "$PORT" > "$OUT_DIR/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
sleep 1
RENDER_JSON=$(curl -s -X POST "http://127.0.0.1:$PORT/render" \
    -H 'Content-Type: application/json' \
    -d '{"html":"<div style=\"width:100px;height:50px;background:red\"></div>","css":"","width":300}')
DEFAULT_JSON=$(curl -s "http://127.0.0.1:$PORT/default")
kill "$SERVER_PID" 2>/dev/null
trap - EXIT

if echo "$RENDER_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); assert '<svg' in d['svg']; assert len(d['boxes'])>=2" 2>/dev/null; then
    pass "server /render returns real SVG + box-model data"
else
    fail "server /render endpoint"
fi
if echo "$DEFAULT_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['html']" 2>/dev/null; then
    pass "server /default endpoint serves the playground's starter page"
else
    fail "server /default endpoint"
fi

# --------------------------------------------------------------- 6. robustness
section "6. Robustness: malformed/extreme inputs never crash (adversarial review, REVIEW.md)"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, ".")
from cascade.engine import render_html
cases = [
    "", "hello world", '<div style="color:#zzz;background:#12345">x</div>',
    "<div>" * 300 + "x" + "</div>" * 300,
    '<div style="width:20px;padding:80px">x</div>',
    "<p>one</p><p>two</p>",  # no body wrapper
]
for h in cases:
    r = render_html(h, viewport_width=800)
    assert r.svg.startswith("<svg")
print("PASS")
PYEOF
if [ $? -eq 0 ]; then pass "6 adversarial edge cases (malformed color, deep nesting, negative content width, no-body doc, ...) all render without crashing"; else fail "robustness check"; fi

# ---------------------------------------------------------------- summary
echo
echo "===================================="
echo " $PASS passed, $FAIL failed"
echo "===================================="
rm -rf "$OUT_DIR"
[ "$FAIL" -eq 0 ]
