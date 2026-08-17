#!/usr/bin/env bash
# Folio Phase 5 verification script: runs the full test suite, the bundled
# end-to-end demo, and a handful of direct CLI smoke checks, then reports a
# single pass/fail summary. Exits non-zero on any failure.
set -u
cd "$(dirname "$0")"

PASS=0
FAIL=0
FAILED_NAMES=()

check() {
    local name="$1"
    shift
    if "$@" >/tmp/folio_demo_check.log 2>&1; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        sed 's/^/         /' /tmp/folio_demo_check.log | tail -20
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
    fi
}

echo "=== Folio verification ==="
echo

echo "-- Unit test suite --"
check "unittest discover (125+ tests, incl. Chromium oracle if available)" \
    python3 -m unittest discover -s tests

echo
echo "-- Bundled end-to-end demo (folio/demo.py) --"
rm -rf /tmp/folio_demo_out
check "folio demo" python3 cli.py demo --outdir /tmp/folio_demo_out
check "demo gallery index.html was written" test -f /tmp/folio_demo_out/index.html
check "demo produced at least 3 SVG renders" \
    bash -c '[ "$(ls /tmp/folio_demo_out/*.svg 2>/dev/null | wc -l)" -ge 3 ]'

echo
echo "-- CLI smoke checks --"
check "parse: fixtures/sample1.html" python3 cli.py parse fixtures/sample1.html
check "cascade: fixtures/sample1.html" python3 cli.py cascade fixtures/sample1.html
check "layout: fixtures/sample1.html" python3 cli.py layout fixtures/sample1.html
check "render: fixtures/sample1.html -> svg" \
    python3 cli.py render fixtures/sample1.html -o /tmp/folio_smoke.svg --width 600
check "render output is well-formed SVG" \
    bash -c "head -c 200 /tmp/folio_smoke.svg | grep -q '<svg xmlns='"
check "inspect: fixtures/sample1.html -> interactive html" \
    python3 cli.py inspect fixtures/sample1.html -o /tmp/folio_smoke_inspect.html --width 600 --no-oracle
check "inspect output embeds hit-rects and box data" \
    bash -c "grep -q 'folio-hit' /tmp/folio_smoke_inspect.html && grep -q 'BOXES =' /tmp/folio_smoke_inspect.html"

echo
echo "-- Adversarial-input CLI checks (Phase 3 regressions) --"
check "missing file exits cleanly (no traceback)" \
    bash -c '! python3 cli.py render /tmp/definitely_missing_xyz.html 2>/tmp/e.log; ! grep -q Traceback /tmp/e.log'
check "empty document exits cleanly (no traceback)" \
    bash -c 'F=$(mktemp --suffix=.html); : > "$F"; ! python3 cli.py render "$F" 2>/tmp/e.log; ! grep -q Traceback /tmp/e.log; rm -f "$F"'

echo
echo "=== Summary: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -ne 0 ]; then
    echo "Failed checks:"
    for n in "${FAILED_NAMES[@]}"; do echo "  - $n"; done
    exit 1
fi
exit 0
