#!/usr/bin/env bash
# Skein end-to-end verification demo: exercises every feature (required
# 1-4, stretch 5-6, extra 7) against real processes and real sockets,
# not mocks. Prints PASS/FAIL for each check and exits nonzero if any
# check failed.
set -uo pipefail
cd "$(dirname "$0")"

WORK=$(mktemp -d)
BG_PIDS=()
cleanup() {
    for pid in "${BG_PIDS[@]:-}"; do
        kill "$pid" >/dev/null 2>&1 || true
    done
    wait >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

pass=0
fail=0
check() {
    # usage: check <exit_code> <description>
    if [ "$1" -eq 0 ]; then
        echo "  PASS: $2"
        pass=$((pass + 1))
    else
        echo "  FAIL: $2 (exit $1)"
        fail=$((fail + 1))
    fi
}
section() { echo; echo "=== $1 ==="; }

wait_for_tracker_url() {
    # $1 = log file path; echoes the tracker URL once it appears, or
    # nothing after ~5s.
    local log="$1"
    for _ in $(seq 1 50); do
        if grep -q "tracker listening on" "$log" 2>/dev/null; then
            grep -o 'http://[^ ]*' "$log" | head -1
            return 0
        fi
        sleep 0.1
    done
    return 1
}

# ---------------------------------------------------------------------
section "1. Unit + integration test suite"
python3 -m unittest discover -s tests 2>&1 | tail -20
check $? "97-test suite (bencode, torrent, tracker, wire, piecemanager, choke, resume, swarm integration, review regressions)"

# ---------------------------------------------------------------------
section "2. Feature 1+2: bencode + real .torrent creation, no live tracker required"
head -c 500000 /dev/urandom > "$WORK/demo-source.bin"
python3 -m skein.cli create-torrent "$WORK/demo-source.bin" --tracker http://127.0.0.1:1 \
    -o "$WORK/standalone.torrent" --piece-length 16384 > "$WORK/create.log" 2>&1
check $? "create-torrent produces a valid bencoded .torrent"
grep -q "info hash:" "$WORK/create.log" && echo "  $(grep 'info hash:' "$WORK/create.log")"

# ---------------------------------------------------------------------
section "3. Feature 3+4: standalone tracker + seed + leech via the CLI subcommands"
python3 -m skein.cli tracker --host 127.0.0.1 --port 0 > "$WORK/tracker1.log" 2>&1 &
BG_PIDS+=($!)
TRACKER_URL=$(wait_for_tracker_url "$WORK/tracker1.log")
if [ -z "${TRACKER_URL:-}" ]; then
    echo "  FAIL: tracker never came up"
    fail=$((fail + 1))
else
    echo "  tracker up at $TRACKER_URL"
    python3 -m skein.cli create-torrent "$WORK/demo-source.bin" --tracker "$TRACKER_URL" \
        -o "$WORK/live.torrent" --piece-length 16384 > /dev/null 2>&1
    python3 -m skein.cli seed "$WORK/live.torrent" "$WORK/demo-source.bin" --tracker "$TRACKER_URL" \
        > "$WORK/seed1.log" 2>&1 &
    BG_PIDS+=($!)
    sleep 0.5
    python3 -m skein.cli leech "$WORK/live.torrent" "$WORK/leech-standalone.out" --tracker "$TRACKER_URL" \
        --timeout 30 > "$WORK/leech1.log" 2>&1
    check $? "standalone \`skein leech\` completes"
    cmp -s "$WORK/demo-source.bin" "$WORK/leech-standalone.out"
    check $? "standalone leech output is byte-identical to source"
fi

# ---------------------------------------------------------------------
section "4. Features 1-6 together: full multi-process swarm (tracker + seed + 4 leechers, real OS processes)"
python3 -m skein.cli swarm "$WORK/demo-source.bin" --leechers 4 --piece-length 16384 \
    --out-dir "$WORK/swarm-run" --timeout 30 --choke-interval 1 --announce-interval 0.5 \
    > "$WORK/swarm.log" 2>&1
SWARM_RC=$?
tail -15 "$WORK/swarm.log"
check $SWARM_RC "swarm command: every leecher reconstructs the file byte-for-byte"

section "5. Feature 6: HTML visualizer renders from the real event log"
python3 -m skein.cli viz "$WORK/swarm-run/events.json" -o "$WORK/swarm-run/viz.html" > /dev/null 2>&1
check $? "viz render produces HTML"
if python3 -c "import playwright" 2>/dev/null && [ -x /opt/pw-browsers/chromium ]; then
    python3 - "$WORK/swarm-run/viz.html" <<'PYEOF'
import sys
from playwright.sync_api import sync_playwright
path = sys.argv[1]
errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/opt/pw-browsers/chromium')
    page = browser.new_page()
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(f'file://{path}')
    page.wait_for_timeout(400)
    page.click('#playbtn')
    page.wait_for_timeout(400)
    page.click('#playbtn')
    browser.close()
sys.exit(1 if errors else 0)
PYEOF
    check $? "viz page has zero console errors in headless Chromium (play/pause exercised)"
else
    echo "  SKIP: playwright/chromium not available in this environment"
fi

# ---------------------------------------------------------------------
section "6. Feature 7: resume support — kill a leecher mid-download, restart, verify it resumes"
head -c 20000000 /dev/urandom > "$WORK/big-source.bin"
python3 -m skein.cli tracker --host 127.0.0.1 --port 0 > "$WORK/tracker2.log" 2>&1 &
BG_PIDS+=($!)
TRACKER_URL2=$(wait_for_tracker_url "$WORK/tracker2.log")
if [ -z "${TRACKER_URL2:-}" ]; then
    echo "  FAIL: second tracker never came up"
    fail=$((fail + 1))
else
    python3 -m skein.cli create-torrent "$WORK/big-source.bin" --tracker "$TRACKER_URL2" \
        --piece-length 16384 -o "$WORK/big.torrent" > /dev/null 2>&1
    python3 -m skein.cli seed "$WORK/big.torrent" "$WORK/big-source.bin" --tracker "$TRACKER_URL2" \
        --choke-interval 1 --announce-interval 0.5 > "$WORK/seed2.log" 2>&1 &
    BG_PIDS+=($!)
    sleep 0.5

    # First run: forcibly killed after 3s, guaranteed mid-transfer for a
    # 20MB/16384-byte-piece torrent (>1200 pieces).
    timeout 3 python3 -m skein.cli leech "$WORK/big.torrent" "$WORK/big-dest.bin" \
        --tracker "$TRACKER_URL2" --timeout 60 --choke-interval 1 --announce-interval 0.5 \
        > "$WORK/leech-run1.log" 2>&1 || true

    # Second run: same dest file, must resume and finish.
    timeout 60 python3 -m skein.cli leech "$WORK/big.torrent" "$WORK/big-dest.bin" \
        --tracker "$TRACKER_URL2" --timeout 55 --choke-interval 1 --announce-interval 0.5 \
        > "$WORK/leech-run2.log" 2>&1
    check $? "resumed leech completes on the second run"
    grep -q "resumed from disk" "$WORK/leech-run2.log"
    check $? "leech actually reported resuming from disk"
    cat "$WORK/leech-run2.log" | grep "resumed from disk" | sed 's/^/  /'
    cmp -s "$WORK/big-source.bin" "$WORK/big-dest.bin"
    check $? "resumed download is byte-identical to source"
fi

# ---------------------------------------------------------------------
section "7. Adversarial-review regressions stay fixed (spot check outside the test suite)"
python3 -m skein.cli create-torrent "$WORK/does-not-exist.bin" --tracker http://x/announce \
    > "$WORK/err1.log" 2>&1
rc=$?
grep -q "Traceback" "$WORK/err1.log" && has_tb=1 || has_tb=0
[ "$rc" -eq 1 ] && [ "$has_tb" -eq 0 ]
check $? "create-torrent on a missing file: exit 1, no raw traceback"

python3 -m skein.cli swarm "$WORK/demo-source.bin" --leechers 0 --out-dir "$WORK/zero-run" \
    > "$WORK/err2.log" 2>&1
rc=$?
grep -q "RESULT: OK" "$WORK/err2.log" && vacuous=1 || vacuous=0
[ "$rc" -eq 1 ] && [ "$vacuous" -eq 0 ]
check $? "swarm --leechers 0 fails clearly instead of claiming vacuous success"

# ---------------------------------------------------------------------
echo
echo "=== SUMMARY: $pass passed, $fail failed ==="
if [ "$fail" -eq 0 ]; then
    echo "ALL CHECKS GREEN"
else
    echo "SOME CHECKS FAILED"
fi
exit $fail
